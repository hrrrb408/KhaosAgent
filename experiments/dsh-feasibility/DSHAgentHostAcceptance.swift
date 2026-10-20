import Darwin
import Foundation

private struct DSHProposal: Decodable {
    let argv: [String]
    let readScope: [String]
    let writeScope: [String]
}

private enum DSHAgentHostError: Error {
    case childUnavailable
    case frameTooLarge
    case invalidFrame
    case timedOut
    case childExited
}

private final class DSHRuntimeProcess {
    private let processID: pid_t
    private let processGroupID: pid_t
    private let input: FileHandle
    private let output: FileHandle
    private let lock = NSLock()
    private var processReaped = false
    private var processStopped = false

    init() throws {
        let resources = Bundle.main.bundleURL.appendingPathComponent(
            "Contents/Resources", isDirectory: true
        )
        let node = resources.appendingPathComponent("node", isDirectory: false)
        let script = resources.appendingPathComponent(
            "dsh/agenthost-runtime.mjs", isDirectory: false
        )
        guard FileManager.default.isExecutableFile(atPath: node.path),
              script.isFileURL,
              FileManager.default.fileExists(atPath: script.path) else {
            throw DSHAgentHostError.childUnavailable
        }

        let inputPipe = Pipe()
        let outputPipe = Pipe()
        var environment = [
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": NSHomeDirectory(),
            "TMPDIR": NSTemporaryDirectory(),
        ]
        environment["KHAOS_DSH_AGENTHOST_PID"] = String(getpid())
        for (infoKey, environmentKey) in [
            ("KhaosDSHProbeWorkspaceReadPath", "KHAOS_DSH_WORKSPACE_READ_PATH"),
            ("KhaosDSHProbeWorkspaceWritePath", "KHAOS_DSH_WORKSPACE_WRITE_PATH"),
            ("KhaosDSHProbeCredentialPath", "KHAOS_DSH_CREDENTIAL_PATH"),
            ("KhaosDSHProbeKernelPath", "KHAOS_DSH_KERNEL_PATH"),
            ("KhaosDSHProbeLocalPort", "KHAOS_DSH_LOCAL_PORT"),
            ("KhaosDSHCandidateBFixedScriptArgument", "KHAOS_DSH_CANDIDATE_B_FIXED_SCRIPT"),
        ] {
            if let value = Bundle.main.object(forInfoDictionaryKey: infoKey) as? String {
                environment[environmentKey] = value
            }
        }

        var actions: posix_spawn_file_actions_t? = nil
        guard posix_spawn_file_actions_init(&actions) == 0 else {
            throw DSHAgentHostError.childUnavailable
        }
        defer { posix_spawn_file_actions_destroy(&actions) }
        let nullDescriptor = Darwin.open("/dev/null", O_WRONLY | O_CLOEXEC)
        guard nullDescriptor >= 0 else { throw DSHAgentHostError.childUnavailable }
        defer { Darwin.close(nullDescriptor) }
        let inputRead = inputPipe.fileHandleForReading.fileDescriptor
        let inputWrite = inputPipe.fileHandleForWriting.fileDescriptor
        let outputRead = outputPipe.fileHandleForReading.fileDescriptor
        let outputWrite = outputPipe.fileHandleForWriting.fileDescriptor
        let setup = [
            posix_spawn_file_actions_adddup2(&actions, inputRead, STDIN_FILENO),
            posix_spawn_file_actions_adddup2(&actions, outputWrite, STDOUT_FILENO),
            posix_spawn_file_actions_adddup2(&actions, nullDescriptor, STDERR_FILENO),
            posix_spawn_file_actions_addclose(&actions, inputRead),
            posix_spawn_file_actions_addclose(&actions, inputWrite),
            posix_spawn_file_actions_addclose(&actions, outputRead),
            posix_spawn_file_actions_addclose(&actions, outputWrite),
            posix_spawn_file_actions_addclose(&actions, nullDescriptor),
        ]
        guard setup.allSatisfy({ $0 == 0 }) else { throw DSHAgentHostError.childUnavailable }

        var attributes: posix_spawnattr_t? = nil
        guard posix_spawnattr_init(&attributes) == 0 else {
            throw DSHAgentHostError.childUnavailable
        }
        defer { posix_spawnattr_destroy(&attributes) }
        // The JavaScript runtime receives only its explicit stdio pipes, never
        // unrelated descriptors owned by this untrusted XPC Host.
        guard posix_spawnattr_setflags(
            &attributes,
            Int16(POSIX_SPAWN_SETPGROUP | POSIX_SPAWN_CLOEXEC_DEFAULT)
        ) == 0,
              posix_spawnattr_setpgroup(&attributes, 0) == 0 else {
            throw DSHAgentHostError.childUnavailable
        }

        let argumentValues = [node.path, script.path]
        let environmentValues = environment.map { "\($0.key)=\($0.value)" }
        var argumentPointers = argumentValues.map { strdup($0) } + [nil]
        var environmentPointers = environmentValues.map { strdup($0) } + [nil]
        defer {
            argumentPointers.forEach { free($0) }
            environmentPointers.forEach { free($0) }
        }
        var spawnedID: pid_t = 0
        let spawnStatus = argumentPointers.withUnsafeMutableBufferPointer { arguments in
            environmentPointers.withUnsafeMutableBufferPointer { environment in
                node.path.withCString { executable in
                    posix_spawn(
                        &spawnedID,
                        executable,
                        &actions,
                        &attributes,
                        arguments.baseAddress,
                        environment.baseAddress
                    )
                }
            }
        }
        guard spawnStatus == 0 else { throw DSHAgentHostError.childUnavailable }
        try? inputPipe.fileHandleForReading.close()
        try? outputPipe.fileHandleForWriting.close()
        processID = spawnedID
        processGroupID = spawnedID
        input = inputPipe.fileHandleForWriting
        output = outputPipe.fileHandleForReading
        fputs("dsh-runtime=spawned pid=\(processID) process_group=\(processGroupID)\n", stderr)
        fflush(stderr)
    }

    func exchange(_ frame: [String: Any]) throws -> [String: Any] {
        lock.lock()
        defer { lock.unlock() }
        guard isRunning() else { throw DSHAgentHostError.childExited }
        let encoded = try JSONSerialization.data(withJSONObject: frame, options: [.sortedKeys])
        guard encoded.count <= AgentHostProtocol.maximumFrameBytes else {
            throw DSHAgentHostError.frameTooLarge
        }
        input.write(encoded)
        input.write(Data([0x0a]))
        let line = try readLine(timeoutSeconds: 60)
        guard let value = try JSONSerialization.jsonObject(with: line) as? [String: Any] else {
            throw DSHAgentHostError.invalidFrame
        }
        return value
    }

    func stop() {
        lock.lock()
        defer { lock.unlock() }
        guard !processStopped else { return }
        processStopped = true
        _ = Darwin.kill(-processGroupID, SIGTERM)
        let deadline = Date().addingTimeInterval(2)
        while Date() < deadline {
            _ = reapIfExited()
            if !processGroupExists() { break }
            usleep(10_000)
        }
        if processGroupExists() { _ = Darwin.kill(-processGroupID, SIGKILL) }
        if !processReaped {
            var status: Int32 = 0
            while waitpid(processID, &status, 0) < 0 && errno == EINTR {}
            processReaped = true
        }
        fputs("dsh-runtime=stopped pid=\(processID) process_group=\(processGroupID)\n", stderr)
        fflush(stderr)
    }

    deinit { stop() }

    private func readLine(timeoutSeconds: Int) throws -> Data {
        let descriptor = output.fileDescriptor
        let deadline = Date().addingTimeInterval(TimeInterval(timeoutSeconds))
        var data = Data()
        while Date() < deadline {
            var pollDescriptor = pollfd(fd: descriptor, events: Int16(POLLIN), revents: 0)
            let remaining = max(1, Int(deadline.timeIntervalSinceNow * 1_000))
            let ready = Darwin.poll(&pollDescriptor, 1, Int32(min(remaining, Int(Int32.max))))
            if ready < 0 {
                if errno == EINTR { continue }
                throw DSHAgentHostError.childExited
            }
            if ready == 0 { throw DSHAgentHostError.timedOut }
            var byte: UInt8 = 0
            let count = Darwin.read(descriptor, &byte, 1)
            if count == 0 { throw DSHAgentHostError.childExited }
            if count < 0 {
                if errno == EINTR { continue }
                throw DSHAgentHostError.childExited
            }
            if byte == 0x0a { return data }
            data.append(byte)
            guard data.count <= AgentHostProtocol.maximumFrameBytes else {
                throw DSHAgentHostError.frameTooLarge
            }
        }
        throw DSHAgentHostError.timedOut
    }

    private func isRunning() -> Bool {
        !reapIfExited()
    }

    private func reapIfExited() -> Bool {
        if processReaped { return true }
        var status: Int32 = 0
        let result = waitpid(processID, &status, WNOHANG)
        if result == processID || (result < 0 && errno == ECHILD) {
            processReaped = true
            return true
        }
        return false
    }

    private func processGroupExists() -> Bool {
        if Darwin.kill(-processGroupID, 0) == 0 { return true }
        return errno == EPERM
    }
}

private final class DSHAgentHostSession: NSObject, AgentHostSessionEndpoint {
    private let lock = NSLock()
    private var runtime: DSHRuntimeProcess?
    private var handlingRequest = false
    private var awaitingToolResult = false

    override init() {
        runtime = try? DSHRuntimeProcess()
        super.init()
    }

    func handle(_ frame: NSData, withReply reply: @escaping (NSData?) -> Void) {
        let data = Data(referencing: frame)
        guard data.count <= AgentHostProtocol.maximumFrameBytes else {
            reply(response(.failure("invalid_request")).map(NSData.init(data:)))
            return
        }
        lock.lock()
        guard !handlingRequest else {
            lock.unlock()
            reply(response(.failure("invalid_request")).map(NSData.init(data:)))
            return
        }
        handlingRequest = true
        lock.unlock()

        DispatchQueue.global(qos: .userInitiated).async {
            let result = self.process(data)
            self.lock.lock()
            self.handlingRequest = false
            self.lock.unlock()
            reply(result.map(NSData.init(data:)))
        }
    }

    private func process(_ data: Data) -> Data? {
        guard let frame = AgentHostProtocol.decodeInput(data),
              let operation = frame["operation"] as? String else {
            return response(.failure("invalid_request"))
        }
        if operation == "stop" {
            runtime?.stop()
            runtime = nil
            return nil
        }
        if self.runtime == nil {
            guard operation == "user" else {
                return response(.failure("dsh_runtime_unavailable"))
            }
            self.runtime = try? DSHRuntimeProcess()
        }
        guard let runtime = self.runtime else { return response(.failure("dsh_runtime_unavailable")) }

        do {
            switch operation {
            case "user":
                guard !awaitingToolResult,
                      let text = frame["text"] as? String else {
                    return response(.failure("invalid_request"))
                }
                let event = try runtime.exchange(["operation": "user", "text": text])
                return try encodeAgentAction(event, activePlugin: AgentHostProtocol.activePlugin(in: frame))
            case "tool_result":
                guard awaitingToolResult,
                      let ok = frame["ok"] as? Bool,
                      let canContinue = frame["can_continue"] as? Bool,
                      let text = frame["text"] as? String else {
                    return response(.failure("invalid_request"))
                }
                let event = try runtime.exchange([
                    "operation": "tool_result",
                    "ok": ok,
                    "can_continue": canContinue,
                    "text": text,
                ])
                return try encodeAgentAction(event, activePlugin: AgentHostProtocol.activePlugin(in: frame))
            default:
                return response(.failure("invalid_request"))
            }
        } catch {
            runtime.stop()
            self.runtime = nil
            awaitingToolResult = false
            return response(.failure("dsh_runtime_failed"))
        }
    }

    private func encodeAgentAction(
        _ event: [String: Any],
        activePlugin: AgentHostPluginMetadata?
    ) throws -> Data? {
        guard let type = event["type"] as? String else {
            return response(.failure("dsh_invalid_result"))
        }
        let action: AgentAction
        switch type {
        case "proposal":
            guard let proposalObject = event["proposal"] as? [String: Any],
                  let proposalData = try? JSONSerialization.data(withJSONObject: proposalObject),
                  let proposal = try? JSONDecoder().decode(DSHProposal.self, from: proposalData) else {
                return response(.failure("dsh_invalid_proposal"))
            }
            awaitingToolResult = true
            action = AgentAction(
                type: "shell",
                text: "",
                argv: proposal.argv,
                readScope: proposal.readScope,
                writeScope: proposal.writeScope,
                pluginID: "",
                candidateDigest: "",
                generation: 0,
                pluginInput: "",
                evolutionGoal: ""
            )
        case "reply":
            guard let responseText = event["text"] as? String else {
                return response(.failure("dsh_invalid_result"))
            }
            awaitingToolResult = false
            action = AgentAction(
                type: "text",
                text: responseText,
                argv: [],
                readScope: [],
                writeScope: [],
                pluginID: "",
                candidateDigest: "",
                generation: 0,
                pluginInput: "",
                evolutionGoal: ""
            )
        default:
            return response(.failure("dsh_invalid_result"))
        }
        return try AgentHostActionOutput.encodeAction(action, activePlugin: activePlugin)
    }

    private func response(_ reply: AgentHostReply) -> Data? {
        try? AgentHostProtocol.encodeReply(reply)
    }
}

private final class DSHAgentHostService: NSObject, NSXPCListenerDelegate {
    private let listener = NSXPCListener.service()
    private let launcherRequirement: String

    init(launcherRequirement: String) {
        self.launcherRequirement = launcherRequirement
    }

    func run() {
        listener.delegate = self
        listener.resume()
        RunLoop.main.run()
    }

    func listener(
        _ listener: NSXPCListener,
        shouldAcceptNewConnection connection: NSXPCConnection
    ) -> Bool {
        connection.setCodeSigningRequirement(launcherRequirement)
        connection.exportedInterface = NSXPCInterface(with: AgentHostSessionEndpoint.self)
        connection.exportedObject = DSHAgentHostSession()
        connection.resume()
        return true
    }
}

@main
enum DSHAgentHostMain {
    static func main() {
        guard let requirement = Bundle.main.object(
            forInfoDictionaryKey: "KhaosLauncherRequirement"
        ) as? String,
        !requirement.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            exit(EXIT_FAILURE)
        }
        let service = DSHAgentHostService(launcherRequirement: requirement)
        service.run()
    }
}
