import Foundation

final class AgentHostClient {
    private let connection: NSXPCConnection
    private let modelAPIKey: String?
    private let lock = NSLock()
    private var stopped = false
    private var activeRequest: (id: UUID, pending: AgentHostPendingRequest)?

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

    func sendUserTurnAsync(
        _ text: String,
        activePlugin: AgentHostPluginMetadata?,
        completion: @escaping (Result<AgentHostReply, Error>) -> Void
    ) throws {
        let frame = try AgentHostProtocol.userTurn(
            text,
            activePlugin: activePlugin,
            modelAPIKey: modelAPIKey
        )
        requestAsync(frame, completion: completion)
    }

    func sendToolResultAsync(
        ok: Bool,
        canContinue: Bool,
        text: String,
        activePlugin: AgentHostPluginMetadata?,
        completion: @escaping (Result<AgentHostReply, Error>) -> Void
    ) throws {
        let frame = try AgentHostProtocol.toolResult(
            ok: ok,
            canContinue: canContinue,
            text: text,
            activePlugin: activePlugin,
            modelAPIKey: modelAPIKey
        )
        requestAsync(frame, completion: completion)
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
        lock.lock()
        guard !stopped else {
            lock.unlock()
            return
        }
        stopped = true
        let pending = activeRequest?.pending
        activeRequest = nil
        lock.unlock()
        pending?.finish(.failure(AgentHostClientError.cancelled))
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

    private func requestAsync(
        _ frame: Data,
        completion: @escaping (Result<AgentHostReply, Error>) -> Void
    ) {
        let requestID = UUID()
        let pending = AgentHostPendingRequest { [weak self] result in
            self?.clearActiveRequest(requestID)
            completion(result)
        }
        lock.lock()
        guard !stopped, activeRequest == nil else {
            lock.unlock()
            pending.finish(.failure(AgentHostClientError.unavailable))
            return
        }
        activeRequest = (requestID, pending)
        lock.unlock()

        guard let endpoint = connection.remoteObjectProxyWithErrorHandler({ [weak self] _ in
            self?.finishActiveRequest(
                requestID,
                result: .failure(AgentHostClientError.invalidResponse(.xpcTransportFailure))
            )
        }) as? AgentHostSessionEndpoint else {
            finishActiveRequest(
                requestID,
                result: .failure(AgentHostClientError.unavailable)
            )
            return
        }
        endpoint.handle(NSData(data: frame)) { [weak self] value in
            guard let data = value.map(Data.init(referencing:)) else {
                self?.finishActiveRequest(
                    requestID,
                    result: .failure(AgentHostClientError.invalidResponse(.hostReturnedNil))
                )
                return
            }
            guard let reply = AgentHostProtocol.decodeReply(data) else {
                self?.finishActiveRequest(
                    requestID,
                    result: .failure(AgentHostClientError.invalidResponse(.launcherReplyDecodeFailure))
                )
                return
            }
            self?.finishActiveRequest(requestID, result: .success(reply))
        }
        DispatchQueue.global(qos: .utility).asyncAfter(
            deadline: .now() + .seconds(
                AgentHostProtocol.modelRequestTimeoutSeconds + 10
            )
        ) { [weak self] in
            self?.finishActiveRequest(
                requestID,
                result: .failure(AgentHostClientError.timedOut)
            )
        }
    }

    private func finishActiveRequest(
        _ requestID: UUID,
        result: Result<AgentHostReply, Error>
    ) {
        lock.lock()
        guard let active = activeRequest, active.id == requestID else {
            lock.unlock()
            return
        }
        activeRequest = nil
        lock.unlock()
        active.pending.finish(result)
    }

    private func clearActiveRequest(_ requestID: UUID) {
        lock.lock()
        if activeRequest?.id == requestID {
            activeRequest = nil
        }
        lock.unlock()
    }
}

private final class AgentHostPendingRequest {
    private let lock = NSLock()
    private var completed = false
    private let completion: (Result<AgentHostReply, Error>) -> Void

    init(completion: @escaping (Result<AgentHostReply, Error>) -> Void) {
        self.completion = completion
    }

    func finish(_ result: Result<AgentHostReply, Error>) {
        lock.lock()
        guard !completed else {
            lock.unlock()
            return
        }
        completed = true
        lock.unlock()
        completion(result)
    }
}

enum AgentHostClientError: Error {
    case unavailable
    case timedOut
    case cancelled
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
