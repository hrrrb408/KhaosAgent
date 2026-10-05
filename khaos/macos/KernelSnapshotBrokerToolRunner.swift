import Darwin
import Foundation

enum KernelSnapshotBrokerToolFailure: Error {
    case cancelled
    case timedOut
    case operationFailed
    case spawnFailed(Int32)
    case waitFailed(Int32)
    case toolExited(Int32)
}

final class KernelSnapshotBrokerToolProcess {
    let processGroupID: pid_t

    init(processGroupID: pid_t) {
        self.processGroupID = processGroupID
    }

    func requestTermination() {
        _ = Darwin.kill(-processGroupID, SIGTERM)
    }
}

enum KernelSnapshotBrokerToolRunner {
    static func run(
        executable: String,
        arguments: [String],
        environment: [String: String],
        currentDirectory: URL,
        timeout: TimeInterval,
        outputLimit: Int,
        isCancelled: () -> Bool,
        processStarted: (KernelSnapshotBrokerToolProcess) -> Void,
        processFinished: (KernelSnapshotBrokerToolProcess) -> Void
    ) throws -> Data {
        guard !isCancelled() else { throw KernelSnapshotBrokerToolFailure.cancelled }

        let output = Pipe()
        let errorOutput = Pipe()
        let nullDescriptor = Darwin.open("/dev/null", O_RDONLY | O_CLOEXEC)
        guard nullDescriptor >= 0 else {
            throw KernelSnapshotBrokerToolFailure.operationFailed
        }
        defer { _ = Darwin.close(nullDescriptor) }

        let sourceDescriptors = [
            nullDescriptor,
            Int32(output.fileHandleForReading.fileDescriptor),
            Int32(output.fileHandleForWriting.fileDescriptor),
            Int32(errorOutput.fileHandleForReading.fileDescriptor),
            Int32(errorOutput.fileHandleForWriting.fileDescriptor),
        ]
        guard sourceDescriptors.allSatisfy({ $0 > STDERR_FILENO }),
              Set(sourceDescriptors).count == sourceDescriptors.count else {
            throw KernelSnapshotBrokerToolFailure.operationFailed
        }

        var actions: posix_spawn_file_actions_t? = nil
        guard posix_spawn_file_actions_init(&actions) == 0 else {
            throw KernelSnapshotBrokerToolFailure.operationFailed
        }
        defer { posix_spawn_file_actions_destroy(&actions) }
        func add(_ result: Int32) throws {
            guard result == 0 else {
                throw KernelSnapshotBrokerToolFailure.operationFailed
            }
        }

        try add(posix_spawn_file_actions_adddup2(
            &actions,
            nullDescriptor,
            STDIN_FILENO
        ))
        try add(posix_spawn_file_actions_adddup2(
            &actions,
            sourceDescriptors[2],
            STDOUT_FILENO
        ))
        try add(posix_spawn_file_actions_adddup2(
            &actions,
            sourceDescriptors[4],
            STDERR_FILENO
        ))
        // Keep hdiutil's working directory in its private Broker storage root.
        let workingDirectoryStatus = currentDirectory.path.withCString { path in
            if #available(macOS 26, *) {
                posix_spawn_file_actions_addchdir(&actions, path)
            } else {
                posix_spawn_file_actions_addchdir_np(&actions, path)
            }
        }
        try add(workingDirectoryStatus)
        for descriptor in sourceDescriptors {
            try add(posix_spawn_file_actions_addclose(&actions, descriptor))
        }

        var attributes: posix_spawnattr_t? = nil
        guard posix_spawnattr_init(&attributes) == 0 else {
            throw KernelSnapshotBrokerToolFailure.operationFailed
        }
        defer { posix_spawnattr_destroy(&attributes) }
        var signalDefaults = sigset_t()
        var signalMask = sigset_t()
        guard sigemptyset(&signalDefaults) == 0,
              sigaddset(&signalDefaults, SIGTERM) == 0,
              sigemptyset(&signalMask) == 0 else {
            throw KernelSnapshotBrokerToolFailure.operationFailed
        }
        try add(posix_spawnattr_setpgroup(&attributes, 0))
        try add(posix_spawnattr_setsigdefault(&attributes, &signalDefaults))
        try add(posix_spawnattr_setsigmask(&attributes, &signalMask))
        try add(posix_spawnattr_setflags(
            &attributes,
            Int16(
                POSIX_SPAWN_SETPGROUP
                    | POSIX_SPAWN_CLOEXEC_DEFAULT
                    | POSIX_SPAWN_SETSIGDEF
                    | POSIX_SPAWN_SETSIGMASK
            )
        ))

        var argumentPointers = try KernelCStringArray.create([executable] + arguments)
        defer { KernelCStringArray.release(argumentPointers) }
        var environmentPointers = try KernelCStringArray.create(
            environment.map { "\($0.key)=\($0.value)" }.sorted()
        )
        defer { KernelCStringArray.release(environmentPointers) }

        var processID: pid_t = 0
        let spawnStatus = executable.withCString { path in
            argumentPointers.withUnsafeMutableBufferPointer { argv in
                environmentPointers.withUnsafeMutableBufferPointer { envp in
                    posix_spawn(
                        &processID,
                        path,
                        &actions,
                        &attributes,
                        argv.baseAddress!,
                        envp.baseAddress!
                    )
                }
            }
        }
        guard spawnStatus == 0 else {
            output.fileHandleForReading.closeFile()
            output.fileHandleForWriting.closeFile()
            errorOutput.fileHandleForReading.closeFile()
            errorOutput.fileHandleForWriting.closeFile()
            throw KernelSnapshotBrokerToolFailure.spawnFailed(spawnStatus)
        }

        let tool = KernelSnapshotBrokerToolProcess(processGroupID: processID)
        processStarted(tool)
        output.fileHandleForWriting.closeFile()
        errorOutput.fileHandleForWriting.closeFile()

        let stdout = KernelLimitedPipeOutput(limit: outputLimit)
        let stderr = KernelLimitedPipeOutput(limit: 64 * 1024)
        let readers = DispatchGroup()
        readers.enter()
        DispatchQueue.global(qos: .utility).async {
            stdout.drain(output.fileHandleForReading)
            readers.leave()
        }
        readers.enter()
        DispatchQueue.global(qos: .utility).async {
            stderr.drain(errorOutput.fileHandleForReading)
            readers.leave()
        }

        var leaderReaped = false
        defer {
            if !leaderReaped {
                _ = try? terminateAndReap(
                    processID,
                    readers: readers,
                    leaderReaped: &leaderReaped
                )
            }
            if leaderReaped { processFinished(tool) }
            output.fileHandleForReading.closeFile()
            errorOutput.fileHandleForReading.closeFile()
        }

        let deadline = Date().addingTimeInterval(timeout)
        var status: Int32 = 0
        while true {
            if isCancelled() {
                _ = try terminateAndReap(
                    processID,
                    readers: readers,
                    leaderReaped: &leaderReaped
                )
                throw KernelSnapshotBrokerToolFailure.cancelled
            }
            if Date() >= deadline {
                _ = try terminateAndReap(
                    processID,
                    readers: readers,
                    leaderReaped: &leaderReaped
                )
                throw KernelSnapshotBrokerToolFailure.timedOut
            }
            if try childHasExitedWithoutReaping(processID) {
                status = try terminateAndReap(
                    processID,
                    readers: readers,
                    leaderReaped: &leaderReaped
                )
                break
            }
            Thread.sleep(forTimeInterval: 0.02)
        }

        guard status & 0x7f == 0, (status >> 8) & 0xff == 0 else {
            throw KernelSnapshotBrokerToolFailure.toolExited(status)
        }
        guard let capturedOutput = stdout.value, stderr.value != nil else {
            throw KernelSnapshotBrokerToolFailure.operationFailed
        }
        return capturedOutput
    }

    private static func childHasExitedWithoutReaping(_ processID: pid_t) throws -> Bool {
        var info = siginfo_t()
        let result = Darwin.waitid(
            P_PID,
            id_t(processID),
            &info,
            WEXITED | WNOHANG | WNOWAIT
        )
        if result == 0 { return info.si_pid == processID }
        if errno == EINTR { return false }
        throw KernelSnapshotBrokerToolFailure.waitFailed(errno)
    }

    private static func terminateAndReap(
        _ processID: pid_t,
        readers: DispatchGroup,
        leaderReaped: inout Bool
    ) throws -> Int32 {
        _ = Darwin.kill(-processID, SIGTERM)
        Thread.sleep(forTimeInterval: 0.1)
        // Signal the whole dedicated group before reaping its leader, so its PID
        // cannot be reused as an unrelated process-group ID during cleanup.
        _ = Darwin.kill(-processID, SIGKILL)
        var status: Int32 = 0
        let waited = Darwin.waitpid(processID, &status, 0)
        if waited == processID {
            leaderReaped = true
        } else {
            let code = errno
            if code == ECHILD {
                // SIGCHLD may have been configured to auto-reap this child.
                // The group has already been killed, so do not signal its ID again.
                leaderReaped = true
                guard readers.wait(timeout: .now() + 3) == .success else {
                    throw KernelSnapshotBrokerToolFailure.operationFailed
                }
            }
            throw KernelSnapshotBrokerToolFailure.waitFailed(code)
        }
        guard readers.wait(timeout: .now() + 3) == .success else {
            throw KernelSnapshotBrokerToolFailure.operationFailed
        }
        return status
    }
}

final class KernelLimitedPipeOutput {
    private let limit: Int
    private let lock = NSLock()
    private var captured = Data()
    private var exceeded = false

    init(limit: Int) {
        self.limit = limit
    }

    func drain(_ handle: FileHandle) {
        do {
            while let chunk = try handle.read(upToCount: 16 * 1024), !chunk.isEmpty {
                lock.lock()
                if captured.count + chunk.count <= limit {
                    captured.append(chunk)
                } else {
                    exceeded = true
                }
                lock.unlock()
            }
        } catch {
            lock.lock()
            exceeded = true
            lock.unlock()
        }
    }

    var value: Data? {
        lock.lock()
        defer { lock.unlock() }
        return exceeded ? nil : captured
    }
}
