import Darwin
import Foundation

private func spawnWorkspaceProbe(
    executable: URL,
    pythonHome: URL,
    probe: URL,
    arguments probeArguments: [String],
    workspaceDescriptor: Int32?,
    requestFrame: Data? = nil,
    cancellation: WorkspaceCancellationSignal,
    temporaryDirectory: String
) throws -> (exitStatus: Int32, output: String) {
    let output = Pipe()
    let input = Pipe()
    let inputRead = input.fileHandleForReading.fileDescriptor
    let inputWrite = input.fileHandleForWriting.fileDescriptor
    let outputRead = output.fileHandleForReading.fileDescriptor
    let outputWrite = output.fileHandleForWriting.fileDescriptor
    var actions: posix_spawn_file_actions_t? = nil
    var actionStatus = posix_spawn_file_actions_init(&actions)
    guard actionStatus == 0 else {
        throw NSError(domain: NSPOSIXErrorDomain, code: Int(actionStatus))
    }
    defer { posix_spawn_file_actions_destroy(&actions) }

    func checkAction(_ status: Int32) throws {
        guard status == 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(status))
        }
    }
    if let workspaceDescriptor {
        try checkAction(
            posix_spawn_file_actions_adddup2(&actions, workspaceDescriptor, 198)
        )
    }
    try checkAction(posix_spawn_file_actions_adddup2(&actions, inputRead, STDIN_FILENO))
    try checkAction(posix_spawn_file_actions_addclose(&actions, inputRead))
    try checkAction(posix_spawn_file_actions_addclose(&actions, inputWrite))
    try checkAction(
        posix_spawn_file_actions_adddup2(
            &actions,
            cancellation.readDescriptor,
            WorkspaceCancellationSignal.childDescriptor
        )
    )
    try checkAction(
        posix_spawn_file_actions_addclose(&actions, cancellation.writeDescriptor)
    )
    if cancellation.readDescriptor != WorkspaceCancellationSignal.childDescriptor {
        try checkAction(
            posix_spawn_file_actions_addclose(&actions, cancellation.readDescriptor)
        )
    }
    try checkAction(posix_spawn_file_actions_adddup2(&actions, outputWrite, STDOUT_FILENO))
    try checkAction(posix_spawn_file_actions_adddup2(&actions, outputWrite, STDERR_FILENO))
    try checkAction(posix_spawn_file_actions_addclose(&actions, outputRead))
    try checkAction(posix_spawn_file_actions_addclose(&actions, outputWrite))

    let argumentValues = [executable.path, "-S", probe.path]
        + probeArguments
        + [String(WorkspaceCancellationSignal.childDescriptor)]
    var arguments: [UnsafeMutablePointer<CChar>?] = []
    for value in argumentValues {
        guard let pointer = value.withCString({ strdup($0) }) else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(ENOMEM))
        }
        arguments.append(pointer)
    }
    arguments.append(nil)
    defer {
        for pointer in arguments {
            if let pointer { free(pointer) }
        }
    }

    let environmentValues = [
        "PATH=/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONHOME=\(pythonHome.path)",
        "PYTHONDONTWRITEBYTECODE=1",
        "TMPDIR=\(temporaryDirectory)",
    ]
    var environment: [UnsafeMutablePointer<CChar>?] = []
    for value in environmentValues {
        guard let pointer = value.withCString({ strdup($0) }) else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(ENOMEM))
        }
        environment.append(pointer)
    }
    environment.append(nil)
    defer {
        for pointer in environment {
            if let pointer { free(pointer) }
        }
    }

    var processID: pid_t = 0
    actionStatus = executable.path.withCString { path in
        arguments.withUnsafeMutableBufferPointer { argv in
            environment.withUnsafeMutableBufferPointer { envp in
                posix_spawn(
                    &processID,
                    path,
                    &actions,
                    nil,
                    argv.baseAddress!,
                    envp.baseAddress!
                )
            }
        }
    }
    guard actionStatus == 0 else {
        input.fileHandleForReading.closeFile()
        input.fileHandleForWriting.closeFile()
        throw NSError(domain: NSPOSIXErrorDomain, code: Int(actionStatus))
    }

    input.fileHandleForReading.closeFile()
    if let requestFrame {
        input.fileHandleForWriting.write(requestFrame)
    }
    input.fileHandleForWriting.closeFile()
    output.fileHandleForWriting.closeFile()
    let text = String(
        data: output.fileHandleForReading.readDataToEndOfFile(),
        encoding: .utf8
    ) ?? ""
    output.fileHandleForReading.closeFile()
    var waitStatus: Int32 = 0
    var waited: pid_t
    repeat {
        waited = waitpid(processID, &waitStatus, 0)
    } while waited < 0 && errno == EINTR
    guard waited == processID else {
        throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
    }
    return (waitStatus == 0 ? 0 : 1, text)
}

private struct WorkspaceProbeResult {
    let exitStatus: Int32
    let output: String
}

@objc protocol KernelProbe {
    func readUnscopedInput(_ path: String, withReply reply: @escaping (String) -> Void)
    func readInput(_ bookmark: Data, withReply reply: @escaping (String) -> Void)
}

extension KernelWorkspaceService: KernelProbe {
    @objc func readUnscopedInput(
        _ path: String,
        withReply reply: @escaping (String) -> Void
    ) {
        let descriptor = Darwin.open(path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
        guard descriptor >= 0 else {
            reply("kernel-unscoped=denied:\(errno)")
            return
        }
        _ = Darwin.close(descriptor)
        reply("kernel-unscoped=allowed")
    }

    @objc func readInput(
        _ bookmark: Data,
        withReply reply: @escaping (String) -> Void
    ) {
        do {
            let access = try KernelWorkspaceRoot.withScopedBookmark(bookmark) {
                _, directory, _ in
                let descriptor = Darwin.openat(
                    directory,
                    "input.txt",
                    O_RDONLY | O_NOFOLLOW | O_CLOEXEC
                )
                guard descriptor >= 0 else {
                    throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
                }
                defer { _ = Darwin.close(descriptor) }

                var before = stat()
                guard Darwin.fstat(descriptor, &before) == 0,
                      (before.st_mode & S_IFMT) == S_IFREG,
                      before.st_nlink == 1,
                      before.st_size > 0,
                      before.st_size <= 4096
                else {
                    throw NSError(domain: NSPOSIXErrorDomain, code: Int(EINVAL))
                }

                var bytes = [UInt8](repeating: 0, count: Int(before.st_size))
                let byteCount = bytes.count
                var offset = 0
                while offset < byteCount {
                    let result = bytes.withUnsafeMutableBytes { buffer in
                        Darwin.read(
                            descriptor,
                            buffer.baseAddress?.advanced(by: offset),
                            byteCount - offset
                        )
                    }
                    if result < 0 && errno == EINTR {
                        continue
                    }
                    guard result > 0 else {
                        throw NSError(domain: NSPOSIXErrorDomain, code: Int(EIO))
                    }
                    offset += result
                }

                var after = stat()
                guard Darwin.fstat(descriptor, &after) == 0,
                      before.st_dev == after.st_dev,
                      before.st_ino == after.st_ino,
                      before.st_size == after.st_size,
                      before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec,
                      before.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec,
                      let value = String(bytes: bytes, encoding: .utf8)
                else {
                    throw NSError(domain: NSPOSIXErrorDomain, code: Int(ESTALE))
                }
                return "kernel-read=\(value)"
            }
            reply(
                "\(access.value);bookmark-stale=\(access.stale);"
                    + "bookmark-refreshed=\(access.refreshed)"
            )
        } catch {
            reply("kernel-bookmark=invalid")
        }
    }
}

private func executeWorkspaceCommand(
    _ invocation: KernelWorkspaceXPC.WorkspaceInvocation,
    cancellation: WorkspaceCancellationSignal
) throws -> String {
    guard let pythonVersion = Bundle.main.object(
        forInfoDictionaryKey: "KhaosPythonVersion"
    ) as? String else {
        return "kernel-workspace-python=unavailable"
    }
    let contents = Bundle.main.bundleURL.appendingPathComponent("Contents")
    let pythonHome = contents
        .appendingPathComponent("Frameworks/Python.framework/Versions/\(pythonVersion)")
    let executable = pythonHome.appendingPathComponent("bin/python\(pythonVersion)")
    let descriptorProbe = contents.appendingPathComponent(
        "Resources/kernel_workspace_descriptor_probe.py"
    )
    let executionProbe = contents.appendingPathComponent(
        "Resources/kernel_workspace_probe.py"
    )
    let access = try KernelWorkspaceRoot.withScopedBookmark(invocation.bookmark) {
        workspace, workspaceDescriptor, _ in
        let descriptorWorkspace = workspace.appendingPathComponent(
            "kernel-descriptor-scope",
            isDirectory: true
        )
        let executionWorkspace = workspace.appendingPathComponent(
            "kernel-workspace",
            isDirectory: true
        )
        let descriptorRoot = try KernelWorkspaceRoot.openChildDirectory(
            "kernel-descriptor-scope",
            relativeTo: workspaceDescriptor
        )
        defer { _ = Darwin.close(descriptorRoot) }
        let executionRoot = try KernelWorkspaceRoot.openChildDirectory(
            "kernel-workspace",
            relativeTo: workspaceDescriptor
        )
        defer { _ = Darwin.close(executionRoot) }
        let descriptorResult = try runWorkspaceProbe(
            workspace: descriptorWorkspace,
            workspaceDescriptor: descriptorRoot,
            executable: executable,
            pythonHome: pythonHome,
            probe: descriptorProbe,
            additionalArguments: ["198"],
            requestFrame: nil,
            cancellation: cancellation
        )
        let executionResult = try runWorkspaceProbe(
            workspace: executionWorkspace,
            workspaceDescriptor: executionRoot,
            executable: executable,
            pythonHome: pythonHome,
            probe: executionProbe,
            additionalArguments: ["198"],
            requestFrame: try invocation.request.encodeFrame(
                requestID: invocation.requestID
            ),
            cancellation: cancellation
        )
        return (descriptorResult, executionResult)
    }
    let (descriptorResult, executionResult) = access.value
    if executionResult.output == "xpc-kernel-operation=process_cancelled\n" {
        throw KernelWorkspaceServiceError.processCancelled
    }
    return [
        "kernel-workspace-bookmark-stale=\(access.stale)",
        "kernel-workspace-bookmark-refreshed=\(access.refreshed)",
        "kernel-workspace-descriptor-exit=\(descriptorResult.exitStatus)",
        descriptorResult.output,
        "kernel-workspace-exit=\(executionResult.exitStatus)",
        executionResult.output,
    ].joined(separator: "\n")
}

private func runWorkspaceProbe(
    workspace: URL,
    workspaceDescriptor: Int32,
    executable: URL,
    pythonHome: URL,
    probe: URL,
    additionalArguments: [String],
    requestFrame: Data?,
    cancellation: WorkspaceCancellationSignal
) throws -> WorkspaceProbeResult {
    let result = try spawnWorkspaceProbe(
        executable: executable,
        pythonHome: pythonHome,
        probe: probe,
        arguments: [workspace.path] + additionalArguments,
        workspaceDescriptor: workspaceDescriptor,
        requestFrame: requestFrame,
        cancellation: cancellation,
        temporaryDirectory: NSTemporaryDirectory()
    )
    return WorkspaceProbeResult(
        exitStatus: result.exitStatus,
        output: result.output
    )
}

final class KernelDelegate: NSObject, NSXPCListenerDelegate {
    private let service = KernelWorkspaceService(executor: executeWorkspaceCommand)

    func listener(
        _ listener: NSXPCListener,
        shouldAcceptNewConnection connection: NSXPCConnection
    ) -> Bool {
        connection.exportedInterface = NSXPCInterface(with: KernelProbe.self)
        connection.exportedObject = service
        connection.resume()
        return true
    }
}

final class KernelScopeBootstrapService: NSObject, KernelWorkspaceBootstrapEndpoint {
    private let listener: NSXPCListener
    private let delegate: KernelDelegate

    override init() {
        guard let requirement = Bundle.main.object(
            forInfoDictionaryKey: "KhaosHostRequirement"
        ) as? String, !requirement.isEmpty else {
            fatalError("missing Host code requirement")
        }
        listener = NSXPCListener.anonymous()
        delegate = KernelDelegate()
        super.init()
        listener.setConnectionCodeSigningRequirement(requirement)
        listener.delegate = delegate
        listener.resume()
    }

    func kernelEndpoint(withReply reply: @escaping (NSXPCListenerEndpoint) -> Void) {
        reply(listener.endpoint)
    }
}

final class KernelScopeBootstrapDelegate: NSObject, NSXPCListenerDelegate {
    private let service = KernelScopeBootstrapService()

    func listener(
        _ listener: NSXPCListener,
        shouldAcceptNewConnection connection: NSXPCConnection
    ) -> Bool {
        connection.exportedInterface = NSXPCInterface(
            with: KernelWorkspaceBootstrapEndpoint.self
        )
        connection.exportedObject = service
        connection.resume()
        return true
    }
}

@main
struct Kernel {
    static func main() {
        guard let mode = Bundle.main.object(
            forInfoDictionaryKey: "KhaosKernelServiceMode"
        ) as? String else {
            exit(EXIT_FAILURE)
        }
        if mode == "execution" {
            do {
                let service = try KernelWorkspaceBootstrapService(
                    executor: executeWorkspaceCommand
                )
                service.run()
            } catch {
                FileHandle.standardError.write(Data("kernel-bootstrap=unavailable\n".utf8))
                exit(EXIT_FAILURE)
            }
            return
        }
        guard mode == "scope" else { exit(EXIT_FAILURE) }
        let delegate = KernelScopeBootstrapDelegate()
        let listener = NSXPCListener.service()
        listener.delegate = delegate
        listener.resume()
        RunLoop.main.run()
    }
}
