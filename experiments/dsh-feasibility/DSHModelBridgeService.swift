import CoreFoundation
import Foundation

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
        completionHandler(
            response.expectedContentLength > Int64(maximumResponseBytes) ? .cancel : .allow
        )
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

private enum DSHModelCompletion {
    private static let userAgent = "deepseek-harness/0.2.1-rc.2 (+https://github.com/deepseek-ai/deepseek-harness)"

    static func complete(
        body: Any,
        headers: Any,
        provider: AgentModelProvider,
        apiKey: String,
        timeoutSeconds: Int
    ) -> (completion: [String: Any]?, error: String?, elapsedMilliseconds: Int) {
        let started = ProcessInfo.processInfo.systemUptime
        guard provider.isRemote, let endpoint = provider.endpoint,
              endpoint.scheme == "https", endpoint.host == "open.bigmodel.cn",
              validAPIKey(apiKey),
              let headerValues = headers as? [String: String],
              headerValues == ["user-agent": userAgent],
              let requestBody = body as? [String: Any],
              validRequest(requestBody),
              JSONSerialization.isValidJSONObject(requestBody),
              let bodyData = try? JSONSerialization.data(
                withJSONObject: requestBody,
                options: [.sortedKeys, .withoutEscapingSlashes]
              ), bodyData.count <= DSHModelBridgeLimits.maximumRequestBytes else {
            return (
                nil,
                apiKey.isEmpty ? "model_credentials_unavailable" : "invalid_model_request",
                0
            )
        }

        let configuration = URLSessionConfiguration.ephemeral
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        configuration.timeoutIntervalForRequest = TimeInterval(timeoutSeconds)
        configuration.timeoutIntervalForResource = TimeInterval(timeoutSeconds)
        let delegate = DSHBoundedResponseDelegate(
            maximumResponseBytes: DSHModelBridgeLimits.maximumResponseBytes
        )
        let session = URLSession(configuration: configuration, delegate: delegate, delegateQueue: nil)
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
        delegate.attach(task)
        task.resume()
        guard let received = delegate.wait(timeoutSeconds: timeoutSeconds) else {
            return (nil, "model_provider_timed_out", elapsedMilliseconds(since: started))
        }
        if let urlError = received.error as? URLError, urlError.code == .timedOut {
            return (nil, "model_provider_timed_out", elapsedMilliseconds(since: started))
        }
        if let urlError = received.error as? URLError, urlError.code == .dataLengthExceedsMaximum {
            return (nil, "model_output_too_large", elapsedMilliseconds(since: started))
        }
        guard received.error == nil,
              let http = received.response as? HTTPURLResponse,
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
        guard let completion = try? JSONSerialization.jsonObject(with: received.data)
                as? [String: Any] else {
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
              maxTokens.intValue <= DSHModelBridgeLimits.maximumCompletionTokens,
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
                guard let calls = rawCalls as? [[String: Any]],
                      role == "assistant", calls.count <= 1 else { return false }
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

private final class DSHModelBridgeBootstrapService: NSObject, DSHModelBridgeBootstrapEndpoint {
    private let endpoint: NSXPCListenerEndpoint

    init(endpoint: NSXPCListenerEndpoint) {
        self.endpoint = endpoint
    }

    func modelEndpoint(withReply reply: @escaping (NSXPCListenerEndpoint?) -> Void) {
        reply(endpoint)
    }
}

private final class DSHModelBridgeService: NSObject, DSHModelBridgeEndpoint {
    func complete(
        _ body: NSData,
        headers: NSData,
        apiKey: NSString,
        timeoutSeconds: NSNumber,
        withReply reply: @escaping (NSData?, NSString?, NSNumber) -> Void
    ) {
        DispatchQueue.global(qos: .userInitiated).async {
            guard body.length <= DSHModelBridgeLimits.maximumRequestBytes,
                  headers.length <= 1_024,
                  (1...120).contains(timeoutSeconds.intValue),
                  let bodyValue = try? JSONSerialization.jsonObject(with: body as Data),
                  let headerValue = try? JSONSerialization.jsonObject(with: headers as Data) else {
                reply(nil, "invalid_model_request" as NSString, 0)
                return
            }
            let result = DSHModelCompletion.complete(
                body: bodyValue,
                headers: headerValue,
                provider: AgentModelProvider.from(bundle: .main),
                apiKey: String(apiKey),
                timeoutSeconds: timeoutSeconds.intValue
            )
            guard let completion = result.completion,
                  let encoded = try? JSONSerialization.data(
                    withJSONObject: completion,
                    options: [.sortedKeys, .withoutEscapingSlashes]
                  ), encoded.count <= DSHModelBridgeLimits.maximumResponseBytes else {
                reply(
                    nil,
                    (result.error ?? "model_output_too_large") as NSString,
                    NSNumber(value: result.elapsedMilliseconds)
                )
                return
            }
            reply(
                encoded as NSData,
                nil,
                NSNumber(value: result.elapsedMilliseconds)
            )
        }
    }
}

private final class DSHModelBridgeListener: NSObject, NSXPCListenerDelegate {
    private let bootstrapListener = NSXPCListener.service()
    private let modelListener = NSXPCListener.anonymous()
    private let hostRequirement: String
    private let launcherRequirement: String

    init(hostRequirement: String, launcherRequirement: String) {
        self.hostRequirement = hostRequirement
        self.launcherRequirement = launcherRequirement
    }

    func run() {
        modelListener.delegate = self
        modelListener.resume()
        bootstrapListener.delegate = self
        bootstrapListener.resume()
        RunLoop.main.run()
    }

    func listener(
        _ listener: NSXPCListener,
        shouldAcceptNewConnection connection: NSXPCConnection
    ) -> Bool {
        if listener === bootstrapListener {
            connection.setCodeSigningRequirement(launcherRequirement)
            connection.exportedInterface = NSXPCInterface(
                with: DSHModelBridgeBootstrapEndpoint.self
            )
            connection.exportedObject = DSHModelBridgeBootstrapService(
                endpoint: modelListener.endpoint
            )
        } else {
            connection.setCodeSigningRequirement(hostRequirement)
            connection.exportedInterface = NSXPCInterface(with: DSHModelBridgeEndpoint.self)
            connection.exportedObject = DSHModelBridgeService()
        }
        connection.resume()
        return true
    }
}

@main
enum DSHModelBridgeMain {
    static func main() {
        guard let requirement = Bundle.main.object(
            forInfoDictionaryKey: DSHModelBridgeLimits.hostRequirementInfoKey
        ) as? String,
        !requirement.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
        let launcherRequirement = Bundle.main.object(
            forInfoDictionaryKey: DSHModelBridgeLimits.launcherRequirementInfoKey
        ) as? String,
        !launcherRequirement.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
        AgentModelProvider.from(bundle: .main).isRemote else {
            exit(EXIT_FAILURE)
        }
        DSHModelBridgeListener(
            hostRequirement: requirement,
            launcherRequirement: launcherRequirement
        ).run()
    }
}
