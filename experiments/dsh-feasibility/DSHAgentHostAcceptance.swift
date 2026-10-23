import Darwin
import CoreFoundation
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

private final class DSHBoundedResponseDelegate: NSObject, URLSessionDataDelegate {
    private let maximumResponseBytes: Int
    private let semaphore = DispatchSemaphore(value: 0)
    private let lock = NSLock()
    private var responseData = Data()
    private var response: URLResponse?
    private var responseError: Error?
    private var task: URLSessionDataTask?

    init(maximumResponseBytes: Int) {
        self.maximumResponseBytes = maximumResponseBytes
    }

    func attach(_ task: URLSessionDataTask) {
        lock.lock()
        self.task = task
        lock.unlock()
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        completionHandler(nil)
    }

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive response: URLResponse,
        completionHandler: @escaping (URLSession.ResponseDisposition) -> Void
    ) {
        lock.lock()
        self.response = response
        if response.expectedContentLength > Int64(maximumResponseBytes) {
            responseError = URLError(.dataLengthExceedsMaximum)
        }
        lock.unlock()
        if response.expectedContentLength > Int64(maximumResponseBytes) {
            completionHandler(.cancel)
        } else {
            completionHandler(.allow)
        }
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        lock.lock()
        if responseData.count + data.count > maximumResponseBytes {
            responseError = URLError(.dataLengthExceedsMaximum)
            lock.unlock()
            dataTask.cancel()
            return
        }
        responseData.append(data)
        lock.unlock()
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        lock.lock()
        if responseError == nil { responseError = error }
        lock.unlock()
        semaphore.signal()
    }

    func wait(timeoutSeconds: Int) -> (data: Data, response: URLResponse?, error: Error?)? {
        guard semaphore.wait(timeout: .now() + .seconds(max(1, timeoutSeconds))) == .success else {
            lock.lock()
            let task = self.task
            lock.unlock()
            task?.cancel()
            return nil
        }
        lock.lock()
        defer { lock.unlock() }
        return (responseData, response, responseError)
    }
}

private enum DSHModelBridge {
    private static let maximumRequestBytes = 56 * 1_024
    private static let maximumResponseBytes = 56 * 1_024
    private static let maximumCompletionTokens = 2_048
    fileprivate static let maximumModelCallsPerTask = 16
    fileprivate static let maximumTaskSeconds = 600
    private static let userAgent = "deepseek-harness/0.2.1-rc.2 (+https://github.com/deepseek-ai/deepseek-harness)"

    static func complete(
        body: Any,
        headers: Any,
        provider: AgentModelProvider,
        apiKey: String?,
        timeoutSeconds: Int
    ) -> (completion: [String: Any]?, error: String?, elapsedMilliseconds: Int) {
        let started = ProcessInfo.processInfo.systemUptime
        guard provider.isRemote, let endpoint = provider.endpoint,
              endpoint.scheme == "https", endpoint.host == "open.bigmodel.cn",
              let apiKey, validAPIKey(apiKey),
              let headerValues = headers as? [String: String],
              headerValues == ["user-agent": userAgent],
              let requestBody = body as? [String: Any],
              validRequest(requestBody),
              JSONSerialization.isValidJSONObject(requestBody),
              let bodyData = try? JSONSerialization.data(
                withJSONObject: requestBody,
                options: [.sortedKeys, .withoutEscapingSlashes]
              ), bodyData.count <= maximumRequestBytes else {
            return (nil, apiKey == nil ? "model_credentials_unavailable" : "invalid_model_request", 0)
        }

        let configuration = URLSessionConfiguration.ephemeral
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        configuration.timeoutIntervalForRequest = TimeInterval(timeoutSeconds)
        configuration.timeoutIntervalForResource = TimeInterval(timeoutSeconds)
        let responseDelegate = DSHBoundedResponseDelegate(maximumResponseBytes: maximumResponseBytes)
        let session = URLSession(configuration: configuration, delegate: responseDelegate, delegateQueue: nil)
        defer { session.invalidateAndCancel() }

        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = TimeInterval(timeoutSeconds)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("no-store", forHTTPHeaderField: "Cache-Control")
        request.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        request.httpBody = bodyData

        let task = session.dataTask(with: request)
        responseDelegate.attach(task)
        task.resume()
        guard let received = responseDelegate.wait(timeoutSeconds: timeoutSeconds) else {
            return (nil, "model_provider_timed_out", elapsedMilliseconds(since: started))
        }
        let data = received.data
        let urlResponse = received.response
        let error = received.error

        if let urlError = error as? URLError, urlError.code == .timedOut {
            return (nil, "model_provider_timed_out", elapsedMilliseconds(since: started))
        }
        if let urlError = error as? URLError, urlError.code == .dataLengthExceedsMaximum {
            return (nil, "model_output_too_large", elapsedMilliseconds(since: started))
        }
        guard error == nil, let http = urlResponse as? HTTPURLResponse,
              http.url == endpoint else {
            return (nil, "model_provider_failed", elapsedMilliseconds(since: started))
        }
        if http.statusCode == 401 || http.statusCode == 403 {
            return (nil, "model_provider_auth_failed", elapsedMilliseconds(since: started))
        }
        if http.statusCode == 429 {
            return (nil, "model_provider_rate_limited", elapsedMilliseconds(since: started))
        }
        guard (200..<300).contains(http.statusCode) else {
            return (
                nil,
                "model_provider_http_\(http.statusCode)",
                elapsedMilliseconds(since: started)
            )
        }
        guard let completion = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return (nil, "invalid_model_response", elapsedMilliseconds(since: started))
        }
        return (completion, nil, elapsedMilliseconds(since: started))
    }

    private static func validAPIKey(_ key: String) -> Bool {
        let bytes = Array(key.utf8)
        return !bytes.isEmpty
            && bytes.count <= AgentHostProtocol.maximumModelAPIKeyBytes
            && bytes.allSatisfy { (0x21...0x7e).contains($0) }
    }

    private static func validRequest(_ body: [String: Any]) -> Bool {
        let allowedKeys: Set<String> = [
            "model", "messages", "tools", "tool_choice", "max_tokens", "temperature",
            "reasoning_effort", "thinking", "stream", "stop",
        ]
        guard Set(body.keys).isSubset(of: allowedKeys),
              body["model"] as? String == "glm-5.3",
              let stream = body["stream"] as? NSNumber,
              CFGetTypeID(stream) == CFBooleanGetTypeID(), !stream.boolValue,
              let maxTokens = body["max_tokens"] as? NSNumber,
              CFGetTypeID(maxTokens) != CFBooleanGetTypeID(),
              maxTokens.intValue >= 1,
              maxTokens.intValue <= maximumCompletionTokens,
              maxTokens.doubleValue == Double(maxTokens.intValue),
              let temperature = body["temperature"] as? NSNumber,
              CFGetTypeID(temperature) != CFBooleanGetTypeID(),
              temperature.doubleValue.isFinite,
              (0...2).contains(temperature.doubleValue),
              let thinking = body["thinking"] as? [String: Any],
              Set(thinking.keys) == ["type", "clear_thinking"],
              thinking["type"] as? String == "enabled",
              let clearThinking = thinking["clear_thinking"] as? NSNumber,
              CFGetTypeID(clearThinking) == CFBooleanGetTypeID(), !clearThinking.boolValue,
              let messages = body["messages"] as? [[String: Any]],
              (1...64).contains(messages.count) else {
            return false
        }

        if let effort = body["reasoning_effort"] as? String,
           !["low", "medium", "high", "max"].contains(effort) {
            return false
        }
        if let rawStop = body["stop"] {
            guard let stop = rawStop as? [String], stop.count <= 4,
                  !stop.contains(where: { $0.utf8.count > 256 }) else {
                return false
            }
        }

        for message in messages {
            guard let role = message["role"] as? String,
                  ["system", "user", "assistant", "tool"].contains(role),
                  message["content"] is String || message["content"] is NSNull else {
                return false
            }
            let allowedMessageKeys: Set<String> = role == "assistant"
                ? ["role", "content", "tool_calls"]
                : role == "tool" ? ["role", "content", "tool_call_id"] : ["role", "content"]
            guard Set(message.keys).isSubset(of: allowedMessageKeys) else { return false }
            if role == "tool" {
                guard let callID = message["tool_call_id"] as? String,
                      !callID.isEmpty, callID.utf8.count <= 128 else { return false }
            }
            if let rawCalls = message["tool_calls"] {
                guard let calls = rawCalls as? [[String: Any]] else { return false }
                guard role == "assistant", calls.count <= 1 else { return false }
                for call in calls {
                    guard Set(call.keys) == ["id", "type", "function"],
                          let callID = call["id"] as? String,
                          !callID.isEmpty, callID.utf8.count <= 128,
                          call["type"] as? String == "function",
                          let function = call["function"] as? [String: Any],
                          Set(function.keys) == ["name", "arguments"],
                          function["name"] as? String == "khaos_capability",
                          let arguments = function["arguments"] as? String,
                          arguments.utf8.count <= 32 * 1_024 else { return false }
                }
            }
        }

        if let tools = body["tools"] as? [[String: Any]] {
            guard tools.count == 1,
                  body["tool_choice"] as? String == "auto",
                  let tool = tools.first,
                  tool["type"] as? String == "function",
                  let function = tool["function"] as? [String: Any],
                  function["name"] as? String == "khaos_capability",
                  function["parameters"] is [String: Any] else {
                return false
            }
        } else if body["tools"] != nil || body["tool_choice"] != nil {
            return false
        }
        return true
    }

    private static func elapsedMilliseconds(since started: TimeInterval) -> Int {
        max(0, Int((ProcessInfo.processInfo.systemUptime - started) * 1_000))
    }
}

private final class DSHRuntimeProcess {
    private let processID: pid_t
    private let processGroupID: pid_t
    private let input: FileHandle
    private let output: FileHandle
    private let lock = NSLock()
    private var processReaped = false
    private var processStopped = false
    private var modelCallsThisTask = 0

    init() throws {
        let resources = Bundle.main.bundleURL.appendingPathComponent(
            "Contents/Resources", isDirectory: true
        )
        let node = resources.appendingPathComponent("node", isDirectory: false)
        let nodeSandbox = URL(fileURLWithPath: "/usr/bin/sandbox-exec", isDirectory: false)
        let script = resources.appendingPathComponent(
            "dsh/agenthost-runtime.mjs", isDirectory: false
        )
        guard FileManager.default.isExecutableFile(atPath: node.path),
              FileManager.default.isExecutableFile(atPath: nodeSandbox.path),
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

        // The experimental XPC Host needs network.client for its fixed model
        // bridge. Keep that entitlement out of DSH and every Plugin descendant.
        let argumentValues = [
            nodeSandbox.path,
            "-p",
            "(version 1) (allow default) (deny network*)",
            node.path,
            script.path,
        ]
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
                nodeSandbox.path.withCString { executable in
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

    func beginTask() {
        lock.lock()
        modelCallsThisTask = 0
        lock.unlock()
    }

    func exchange(
        _ frame: [String: Any],
        modelAPIKey: String? = nil,
        taskDeadlineUptime: TimeInterval? = nil
    ) throws -> [String: Any] {
        lock.lock()
        defer { lock.unlock() }
        guard isRunning() else { throw DSHAgentHostError.childExited }
        try writeFrame(frame)
        while true {
            let readTimeout: Int
            if modelAPIKey != nil {
                let remaining = taskDeadlineUptime.map {
                    max(1, Int($0 - ProcessInfo.processInfo.systemUptime))
                } ?? 120
                readTimeout = min(120, remaining)
            } else {
                readTimeout = 60
            }
            let line = try readLine(timeoutSeconds: readTimeout)
            guard let value = try JSONSerialization.jsonObject(with: line) as? [String: Any] else {
                throw DSHAgentHostError.invalidFrame
            }
            guard value["type"] as? String == "model_request" else { return value }
            guard let requestID = value["request_id"] as? String,
                  !requestID.isEmpty, requestID.utf8.count <= 64 else {
                throw DSHAgentHostError.invalidFrame
            }

            let provider = AgentModelProvider.from(bundle: .main)
            let call: (completion: [String: Any]?, error: String?, elapsedMilliseconds: Int)
            if modelCallsThisTask >= DSHModelBridge.maximumModelCallsPerTask {
                call = (nil, "model_call_budget_exceeded", 0)
            } else if let deadline = taskDeadlineUptime,
                      deadline <= ProcessInfo.processInfo.systemUptime {
                call = (nil, "model_provider_timed_out", 0)
            } else {
                modelCallsThisTask += 1
                let remaining = taskDeadlineUptime.map {
                    max(1, Int($0 - ProcessInfo.processInfo.systemUptime))
                } ?? 120
                call = DSHModelBridge.complete(
                    body: value["body"] as Any,
                    headers: value["headers"] as Any,
                    provider: provider,
                    apiKey: modelAPIKey,
                    timeoutSeconds: min(120, remaining)
                )
            }
            let modelCallRecord: [String: Any] = [
                "status": call.error ?? "ok",
                "elapsed_ms": call.elapsedMilliseconds,
                "call_number": modelCallsThisTask,
            ]
            if let diagnostic = try? JSONSerialization.data(
                withJSONObject: modelCallRecord,
                options: [.sortedKeys]
            ) {
                fputs("dsh-model-call=\(String(decoding: diagnostic, as: UTF8.self))\n", stderr)
                fflush(stderr)
            }
            var response: [String: Any] = [
                "operation": "model_result",
                "request_id": requestID,
                "ok": call.error == nil,
                "elapsed_ms": call.elapsedMilliseconds,
            ]
            if let completion = call.completion {
                response["response"] = completion
            }
            if let error = call.error {
                response["error"] = ["code": error]
            }
            try writeFrame(response)
        }
    }

    private func writeFrame(_ frame: [String: Any]) throws {
        let encoded = try JSONSerialization.data(withJSONObject: frame, options: [.sortedKeys])
        guard encoded.count <= AgentHostProtocol.maximumFrameBytes else {
            throw DSHAgentHostError.frameTooLarge
        }
        input.write(encoded)
        input.write(Data([0x0a]))
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

    func interrupt() {
        _ = Darwin.kill(-processGroupID, SIGTERM)
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
    private var crashAfterToolResult = false
    private var cancelled = false
    private var realModelTask = false
    private var taskDeadlineUptime: TimeInterval?

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
        lock.lock()
        let isCancelled = cancelled
        lock.unlock()
        guard !isCancelled else { return response(.failure("dsh_runtime_unavailable")) }
        if operation == "stop" {
            let current = runtimeSnapshot()
            current?.stop()
            replaceRuntime(nil)
            return nil
        }
        if runtimeSnapshot() == nil {
            guard operation == "user" else {
                return response(.failure("dsh_runtime_unavailable"))
            }
            guard let created = try? DSHRuntimeProcess() else {
                return response(.failure("dsh_runtime_unavailable"))
            }
            replaceRuntime(created)
        }
        guard let runtime = runtimeSnapshot() else { return response(.failure("dsh_runtime_unavailable")) }

        do {
            switch operation {
            case "user":
                guard !awaitingToolResult,
                      let text = frame["text"] as? String else {
                    return response(.failure("invalid_request"))
                }
                crashAfterToolResult = text.contains("KHAOS_DSH_AGENTHOST_CRASH_ON_TOOL_RESULT")
                let realModelPrefix = "KHAOS_DSH_REAL_MODEL_CODING\n"
                realModelTask = text.hasPrefix(realModelPrefix)
                let taskText = realModelTask ? String(text.dropFirst(realModelPrefix.count)) : text
                guard !taskText.isEmpty else { return response(.failure("invalid_request")) }
                if realModelTask {
                    guard AgentModelProvider.from(bundle: .main).isRemote,
                          frame["model_api_key"] as? String != nil else {
                        return response(.failure("model_credentials_unavailable"))
                    }
                    taskDeadlineUptime = ProcessInfo.processInfo.systemUptime
                        + TimeInterval(DSHModelBridge.maximumTaskSeconds)
                    runtime.beginTask()
                } else {
                    taskDeadlineUptime = nil
                }
                let event = try runtime.exchange(
                    ["operation": "user", "text": taskText],
                    modelAPIKey: realModelTask ? frame["model_api_key"] as? String : nil,
                    taskDeadlineUptime: taskDeadlineUptime
                )
                return try encodeAgentAction(event, activePlugin: AgentHostProtocol.activePlugin(in: frame))
            case "tool_result":
                guard awaitingToolResult,
                      let ok = frame["ok"] as? Bool,
                      let canContinue = frame["can_continue"] as? Bool,
                      let text = frame["text"] as? String else {
                    return response(.failure("invalid_request"))
                }
                if crashAfterToolResult {
                    crashAfterToolResult = false
                    exit(86)
                }
                let event = try runtime.exchange(
                    [
                        "operation": "tool_result",
                        "ok": ok,
                        "can_continue": canContinue,
                        "text": text,
                    ],
                    modelAPIKey: realModelTask ? frame["model_api_key"] as? String : nil,
                    taskDeadlineUptime: taskDeadlineUptime
                )
                return try encodeAgentAction(event, activePlugin: AgentHostProtocol.activePlugin(in: frame))
            default:
                return response(.failure("invalid_request"))
            }
        } catch {
            runtime.stop()
            replaceRuntime(nil)
            awaitingToolResult = false
            realModelTask = false
            taskDeadlineUptime = nil
            return response(.failure("dsh_runtime_failed"))
        }
    }

    func cancel() {
        lock.lock()
        cancelled = true
        let current = runtime
        lock.unlock()
        current?.interrupt()
        if let current {
            DispatchQueue.global(qos: .utility).async { current.stop() }
        }
    }

    private func runtimeSnapshot() -> DSHRuntimeProcess? {
        lock.lock()
        defer { lock.unlock() }
        return runtime
    }

    private func replaceRuntime(_ value: DSHRuntimeProcess?) {
        lock.lock()
        runtime = value
        lock.unlock()
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
            let proposalRecord: [String: Any] = [
                "argv": proposal.argv,
                "read_scope": proposal.readScope,
                "write_scope": proposal.writeScope,
            ]
            if let diagnostic = try? JSONSerialization.data(
                withJSONObject: proposalRecord,
                options: [.sortedKeys, .withoutEscapingSlashes]
            ), diagnostic.count <= 16 * 1_024 {
                fputs("dsh-tool-proposal=\(String(decoding: diagnostic, as: UTF8.self))\n", stderr)
                fflush(stderr)
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
            if let toolResults = event["toolResults"],
               JSONSerialization.isValidJSONObject(toolResults),
               let data = try? JSONSerialization.data(
                withJSONObject: toolResults,
                options: [.sortedKeys, .withoutEscapingSlashes]
               ), data.count <= 48 * 1_024 {
                fputs("dsh-tool-results=\(String(decoding: data, as: UTF8.self))\n", stderr)
                fflush(stderr)
            }
            if let statistics = event["model_stats"] as? [String: Any],
               JSONSerialization.isValidJSONObject(statistics),
               let data = try? JSONSerialization.data(withJSONObject: statistics, options: [.sortedKeys]),
               data.count <= 1_024 {
                fputs("dsh-model-stats=\(String(decoding: data, as: UTF8.self))\n", stderr)
                fflush(stderr)
            }
            if let diagnostics = event["diagnostics"] as? [String: Any] {
                let safeDiagnostics: [String: Any] = [
                    "assistant_message_count": diagnostics["assistantMessageCount"] ?? NSNull(),
                    "tool_result_count": diagnostics["toolResultCount"] ?? NSNull(),
                    "last_message_role": diagnostics["lastMessageRole"] ?? NSNull(),
                    "last_message_block_types": diagnostics["lastMessageBlockTypes"] ?? NSNull(),
                    "adapter_rejected_proposal_count": diagnostics["adapterRejectedProposalCount"] ?? NSNull(),
                    "agent_error_count": (diagnostics["agentErrors"] as? [Any])?.count ?? 0,
                ]
                if let data = try? JSONSerialization.data(
                    withJSONObject: safeDiagnostics,
                    options: [.sortedKeys]
                ), data.count <= 1_024 {
                    fputs("dsh-agent-loop=\(String(decoding: data, as: UTF8.self))\n", stderr)
                    fflush(stderr)
                }
            }
            awaitingToolResult = false
            realModelTask = false
            taskDeadlineUptime = nil
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
        let session = DSHAgentHostSession()
        connection.exportedObject = session
        connection.invalidationHandler = { [weak session] in session?.cancel() }
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
