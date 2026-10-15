import Foundation

final class AgentHostClient {
    private let connection: NSXPCConnection
    private let modelAPIKey: String?

    init() {
        let provider = AgentModelProvider.from(bundle: .main)
        modelAPIKey = provider.isRemote
            ? ProcessInfo.processInfo.environment["KHAOS_BIGMODEL_API_KEY"]
            : nil
        connection = NSXPCConnection(serviceName: "org.khaos.Seed.AgentHost")
        connection.remoteObjectInterface = NSXPCInterface(
            with: AgentHostSessionEndpoint.self
        )
        connection.resume()
    }

    func sendUserTurn(
        _ text: String,
        activePlugin: AgentHostPluginMetadata?
    ) throws -> AgentHostReply {
        try request(AgentHostProtocol.userTurn(
            text,
            activePlugin: activePlugin,
            modelAPIKey: modelAPIKey
        ))
    }

    func sendToolResult(
        ok: Bool,
        canContinue: Bool,
        text: String,
        activePlugin: AgentHostPluginMetadata?
    ) throws -> AgentHostReply {
        try request(AgentHostProtocol.toolResult(
            ok: ok,
            canContinue: canContinue,
            text: text,
            activePlugin: activePlugin,
            modelAPIKey: modelAPIKey
        ))
    }

    func generateCandidate(
        proposal: Data,
        evidence: String,
        baselineManifest: Data,
        baselineSource: Data
    ) throws -> AgentCandidateFiles {
        let frame = try AgentHostProtocol.candidateGenerationRequest(
            proposal: proposal,
            evidence: evidence,
            baselineManifest: baselineManifest,
            baselineSource: baselineSource,
            modelAPIKey: modelAPIKey
        )
        guard case let .candidate(files) = try request(
            frame,
            timeoutSeconds: TimeInterval(
                AgentHostProtocol.modelRequestTimeoutSeconds
            )
        ) else {
            throw AgentHostClientError.invalidResponse(.unexpectedReplyType)
        }
        return files
    }

    func evaluateMemory(
        proposalDigest: String,
        baselineCandidateDigest: String,
        candidateDigest: String,
        manifestDigest: String,
        scopeDigest: String,
        datasetDigest: String,
        dataset: Data,
        results: [[String: Any]]
    ) throws -> Data {
        let frame = try AgentHostProtocol.memoryEvaluationRequest(
            proposalDigest: proposalDigest,
            baselineCandidateDigest: baselineCandidateDigest,
            candidateDigest: candidateDigest,
            manifestDigest: manifestDigest,
            scopeDigest: scopeDigest,
            datasetDigest: datasetDigest,
            dataset: dataset,
            results: results
        )
        guard case let .evaluation(record) = try request(frame) else {
            throw AgentHostClientError.invalidResponse(.unexpectedReplyType)
        }
        return record
    }

    func stop() {
        connection.invalidate()
    }

    deinit {
        stop()
    }

    private func request(
        _ frame: Data,
        timeoutSeconds: TimeInterval = TimeInterval(
            AgentHostProtocol.modelRequestTimeoutSeconds
        )
    ) throws -> AgentHostReply {
        let semaphore = DispatchSemaphore(value: 0)
        let lock = NSLock()
        var response: Data?
        var failed = false
        let finishWithFailure: (Error) -> Void = { _ in
            lock.lock()
            failed = true
            lock.unlock()
            semaphore.signal()
        }
        guard let endpoint = connection.remoteObjectProxyWithErrorHandler(
            finishWithFailure
        ) as? AgentHostSessionEndpoint else {
            throw AgentHostClientError.unavailable
        }
        endpoint.handle(NSData(data: frame)) { value in
            lock.lock()
            response = value.map(Data.init(referencing:))
            lock.unlock()
            semaphore.signal()
        }
        guard semaphore.wait(timeout: .now() + timeoutSeconds) == .success else {
            connection.invalidate()
            throw AgentHostClientError.timedOut
        }
        lock.lock()
        let data = response
        let didFail = failed
        lock.unlock()
        guard !didFail else {
            throw AgentHostClientError.invalidResponse(.xpcTransportFailure)
        }
        guard let data else {
            throw AgentHostClientError.invalidResponse(.hostReturnedNil)
        }
        guard let reply = AgentHostProtocol.decodeReply(data) else {
            throw AgentHostClientError.invalidResponse(.launcherReplyDecodeFailure)
        }
        return reply
    }
}

enum AgentHostClientError: Error {
    case unavailable
    case timedOut
    case invalidResponse(AgentHostResponseStage)

    var diagnosticStage: String? {
        guard case let .invalidResponse(stage) = self else { return nil }
        return stage.rawValue
    }
}

enum AgentHostResponseStage: String {
    case xpcTransportFailure = "xpc_transport_failure"
    case hostReturnedNil = "host_returned_nil"
    case launcherReplyDecodeFailure = "launcher_reply_decode_failure"
    case unexpectedReplyType = "unexpected_reply_type"
}
