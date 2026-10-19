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
    private let process: Process
    private let input: FileHandle
    private let output: FileHandle
    private let lock = NSLock()

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
        let child = Process()
        child.executableURL = node
        child.arguments = [script.path]
        child.environment = [
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": NSHomeDirectory(),
            "TMPDIR": NSTemporaryDirectory(),
        ]
        child.standardInput = inputPipe
        child.standardOutput = outputPipe
        child.standardError = FileHandle(forWritingAtPath: "/dev/null")
        try child.run()
        process = child
        input = inputPipe.fileHandleForWriting
        output = outputPipe.fileHandleForReading
    }

    func exchange(_ frame: [String: Any]) throws -> [String: Any] {
        lock.lock()
        defer { lock.unlock() }
        guard process.isRunning else { throw DSHAgentHostError.childExited }
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
        guard process.isRunning else { return }
        process.terminate()
        process.waitUntilExit()
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
}

private final class DSHAgentHostSession: NSObject, AgentHostSessionEndpoint {
    private let lock = NSLock()
    private let runtime: DSHRuntimeProcess?
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
            return nil
        }
        guard let runtime else { return response(.failure("dsh_runtime_unavailable")) }

        do {
            switch operation {
            case "user":
                guard !awaitingToolResult,
                      let text = frame["text"] as? String else {
                    return response(.failure("invalid_request"))
                }
                let event = try runtime.exchange(["operation": "user", "text": text])
                guard event["type"] as? String == "proposal",
                      let proposalObject = event["proposal"] as? [String: Any],
                      let proposalData = try? JSONSerialization.data(withJSONObject: proposalObject),
                      let proposal = try? JSONDecoder().decode(DSHProposal.self, from: proposalData) else {
                    return response(.failure("dsh_invalid_proposal"))
                }
                let action = AgentAction(
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
                let activePlugin = AgentHostProtocol.activePlugin(in: frame)
                let encoded = try AgentHostActionOutput.encodeAction(action, activePlugin: activePlugin)
                awaitingToolResult = true
                return encoded
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
                guard event["type"] as? String == "reply",
                      let responseText = event["text"] as? String else {
                    return response(.failure("dsh_invalid_result"))
                }
                awaitingToolResult = false
                let action = AgentAction(
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
                return try AgentHostActionOutput.encodeAction(
                    action,
                    activePlugin: AgentHostProtocol.activePlugin(in: frame)
                )
            default:
                return response(.failure("invalid_request"))
            }
        } catch {
            return response(.failure("dsh_runtime_failed"))
        }
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
