import Foundation

final class AgentHostClient {
    private let connection: NSXPCConnection

    init() {
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
        try request(AgentHostProtocol.userTurn(text, activePlugin: activePlugin))
    }

    func sendToolResult(
        ok: Bool,
        text: String,
        activePlugin: AgentHostPluginMetadata?
    ) throws -> AgentHostReply {
        try request(AgentHostProtocol.toolResult(
            ok: ok,
            text: text,
            activePlugin: activePlugin
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
            baselineSource: baselineSource
        )
        guard case let .candidate(files) = try request(
            frame,
            timeoutSeconds: TimeInterval(
                AgentHostProtocol.candidateGenerationRequestTimeoutSeconds
            )
        ) else {
            throw AgentHostClientError.invalidResponse
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
            throw AgentHostClientError.invalidResponse
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
        timeoutSeconds: TimeInterval = 180
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
        guard !didFail, let data,
              let reply = AgentHostProtocol.decodeReply(data) else {
            throw AgentHostClientError.invalidResponse
        }
        return reply
    }
}

enum AgentHostClientError: Error {
    case unavailable
    case timedOut
    case invalidResponse
}
