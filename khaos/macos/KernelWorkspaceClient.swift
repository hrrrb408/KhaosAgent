import Foundation

enum KernelWorkspaceClientError: Error {
    case missingPeerRequirement(String)
    case invalidBootstrapProxy
    case invalidWorkspaceProxy
    case bootstrapFailed
    case requestFailed
    case invalidResponse
    case snapshotBrokerEndpointRejected
    case timedOut
    case cancelledBeforeSubmission
}

struct KernelWorkspaceRequestIdentity: Equatable {
    let taskID: UUID
    let workspaceSessionID: UUID
    let requestID: KernelWorkspaceXPC.RequestID
    let connectionID: UUID
}

enum KernelWorkspaceCancellationResult: Equatable {
    case notRequested
    case notSubmitted
    case accepted
    case rejected(String)
    case unavailable
    case notActive
    case staleIdentity
    case alreadyRequested
}

struct KernelWorkspaceCommandObservation {
    let reply: Result<KernelWorkspaceXPC.Reply, KernelWorkspaceClientError>
    let cancellation: KernelWorkspaceCancellationResult
    let submitted: Bool
    let submittedAt: TimeInterval?
}

struct KernelWorkspaceTarget {
    let endpoint: NSXPCListenerEndpoint
    let peerRequirementKey: String
}

enum KernelWorkspaceClient {
    static func connect(
        serviceName: String,
        peerRequirementKey: String
    ) throws -> KernelWorkspaceTarget {
        let connection = try connectToService(
            serviceName: serviceName,
            peerRequirementKey: peerRequirementKey,
            remoteInterface: KernelWorkspaceBootstrapEndpoint.self
        )
        defer { connection.invalidate() }

        let timeoutError = KernelWorkspaceClientError.timedOut
        let endpoint: NSXPCListenerEndpoint = try Self.awaitReply(
            timeout: 15,
            timeoutError: timeoutError
        ) { finish in
            let proxy = connection.remoteObjectProxyWithErrorHandler { _ in
                finish(.failure(.bootstrapFailed))
            } as? KernelWorkspaceBootstrapEndpoint
            guard let proxy else {
                throw KernelWorkspaceClientError.invalidBootstrapProxy
            }
            proxy.kernelEndpoint { endpoint in
                finish(.success(endpoint))
            }
        }
        return KernelWorkspaceTarget(
            endpoint: endpoint,
            peerRequirementKey: peerRequirementKey
        )
    }

    static func connectToService(
        serviceName: String,
        peerRequirementKey: String,
        remoteInterface: Protocol
    ) throws -> NSXPCConnection {
        let connection = NSXPCConnection(serviceName: serviceName)
        try authenticateAndResume(
            connection,
            peerRequirementKey: peerRequirementKey,
            remoteInterface: remoteInterface
        )
        return connection
    }

    static func connectWorkspaceEndpoint(
        _ target: KernelWorkspaceTarget
    ) throws -> NSXPCConnection {
        let connection = NSXPCConnection(listenerEndpoint: target.endpoint)
        try authenticateAndResume(
            connection,
            peerRequirementKey: target.peerRequirementKey,
            remoteInterface: KernelWorkspaceEndpoint.self
        )
        return connection
    }

    static func registerSnapshotBrokerEndpoint(
        _ endpoint: NSXPCListenerEndpoint,
        with target: KernelWorkspaceTarget
    ) throws {
        let connection = try connectWorkspaceEndpoint(target)
        defer { connection.invalidate() }
        try setSnapshotBrokerEndpoint(endpoint, on: connection)
    }

    static func request(
        _ target: KernelWorkspaceTarget,
        requestID: KernelWorkspaceXPC.RequestID,
        snapshotBrokerEndpoint: NSXPCListenerEndpoint? = nil,
        submit: (
            KernelWorkspaceEndpoint,
            @escaping (Data) -> Void
        ) throws -> Void
    ) throws -> KernelWorkspaceXPC.Reply {
        let connection = try connectWorkspaceEndpoint(target)
        defer { connection.invalidate() }

        if let snapshotBrokerEndpoint {
            try setSnapshotBrokerEndpoint(snapshotBrokerEndpoint, on: connection)
        }

        let timeoutError = KernelWorkspaceClientError.timedOut
        let data: Data = try Self.awaitReply(
            timeout: 90,
            timeoutError: timeoutError
        ) { finish in
            let proxy = connection.remoteObjectProxyWithErrorHandler { _ in
                finish(.failure(.requestFailed))
            } as? KernelWorkspaceEndpoint
            guard let proxy else {
                throw KernelWorkspaceClientError.invalidWorkspaceProxy
            }
            try submit(proxy) { data in
                finish(.success(data))
            }
        }
        guard let reply = KernelWorkspaceXPC.decode(data, requestID: requestID) else {
            throw KernelWorkspaceClientError.invalidResponse
        }
        return reply
    }

    static func workspaceCommand(
        _ target: KernelWorkspaceTarget,
        taskID: UUID,
        workspaceSessionID: UUID,
        requestID: KernelWorkspaceXPC.RequestID,
        invocationFrame: Data,
        snapshotBrokerEndpoint: NSXPCListenerEndpoint? = nil
    ) throws -> KernelWorkspaceCommandHandle {
        let connection = try connectWorkspaceEndpoint(target)
        return KernelWorkspaceCommandHandle(
            connection: connection,
            identity: KernelWorkspaceRequestIdentity(
                taskID: taskID,
                workspaceSessionID: workspaceSessionID,
                requestID: requestID,
                connectionID: UUID()
            ),
            invocationFrame: invocationFrame,
            snapshotBrokerEndpoint: snapshotBrokerEndpoint
        )
    }

    private static func setSnapshotBrokerEndpoint(
        _ endpoint: NSXPCListenerEndpoint,
        on connection: NSXPCConnection
    ) throws {
        try Self.awaitReply(
            timeout: 15,
            timeoutError: KernelWorkspaceClientError.timedOut
        ) { finish in
            Self.setSnapshotBrokerEndpoint(
                endpoint,
                on: connection,
                completion: finish
            )
        }
    }

    static func setSnapshotBrokerEndpoint(
        _ endpoint: NSXPCListenerEndpoint,
        on connection: NSXPCConnection,
        completion: @escaping (Result<Void, KernelWorkspaceClientError>) -> Void
    ) {
        guard let proxy = connection.remoteObjectProxyWithErrorHandler({ _ in
            completion(.failure(.requestFailed))
        }) as? KernelWorkspaceEndpoint else {
            completion(.failure(.invalidWorkspaceProxy))
            return
        }
        proxy.setSnapshotBrokerEndpoint(
            KernelWorkspaceXPC.version,
            endpoint: endpoint
        ) { accepted in
            completion(accepted
                ? .success(())
                : .failure(.snapshotBrokerEndpointRejected))
        }
    }

    static func awaitReply<Value, Failure: Error>(
        timeout: TimeInterval,
        timeoutError: Failure,
        start: (@escaping (Result<Value, Failure>) -> Void) throws -> Void
    ) throws -> Value {
        let completed = DispatchSemaphore(value: 0)
        let lock = NSLock()
        var result: Result<Value, Failure>?
        func finish(_ value: Result<Value, Failure>) {
            lock.lock()
            let shouldComplete = result == nil
            if shouldComplete {
                result = value
            }
            lock.unlock()
            if shouldComplete {
                completed.signal()
            }
        }

        try start(finish)
        guard completed.wait(timeout: .now() + timeout) == .success else {
            throw timeoutError
        }
        lock.lock()
        let resolution = result
        lock.unlock()
        guard let resolution else {
            throw timeoutError
        }
        return try resolution.get()
    }

    private static func authenticateAndResume(
        _ connection: NSXPCConnection,
        peerRequirementKey: String,
        remoteInterface: Protocol
    ) throws {
        guard XPCPeerIdentity.requirePeerIdentity(
            connection,
            requirementKey: peerRequirementKey
        ) else {
            connection.invalidate()
            throw KernelWorkspaceClientError.missingPeerRequirement(
                peerRequirementKey
            )
        }
        connection.remoteObjectInterface = NSXPCInterface(with: remoteInterface)
        connection.resume()
    }
}

final class KernelWorkspaceCommandHandle {
    let identity: KernelWorkspaceRequestIdentity

    private let connection: NSXPCConnection
    private let invocationFrame: Data
    private let snapshotBrokerEndpoint: NSXPCListenerEndpoint?
    private let requestQueue = DispatchQueue(
        label: "org.khaos.Seed.KernelWorkspaceCommand"
    )
    private let lock = NSLock()
    private var started = false
    private var completed = false
    private var submitted = false
    private var submittedAt: TimeInterval?
    private var cancelledBeforeSubmission = false
    private var brokerSetupAttemptID: UUID?
    private var originalReply: Result<KernelWorkspaceXPC.Reply, KernelWorkspaceClientError>?
    private var cancellationResult: KernelWorkspaceCancellationResult = .notRequested
    private var completion: ((KernelWorkspaceCommandObservation) -> Void)?
    private var cancellationAcknowledgement: ((KernelWorkspaceCancellationResult) -> Void)?

    init(
        connection: NSXPCConnection,
        identity: KernelWorkspaceRequestIdentity,
        invocationFrame: Data,
        snapshotBrokerEndpoint: NSXPCListenerEndpoint?
    ) {
        self.connection = connection
        self.identity = identity
        self.invocationFrame = invocationFrame
        self.snapshotBrokerEndpoint = snapshotBrokerEndpoint
    }

    func start(completion: @escaping (KernelWorkspaceCommandObservation) -> Void) {
        lock.lock()
        guard !started, !completed else {
            lock.unlock()
            completion(KernelWorkspaceCommandObservation(
                reply: .failure(.requestFailed),
                cancellation: .notRequested,
                submitted: false,
                submittedAt: nil
            ))
            return
        }
        started = true
        self.completion = completion
        let hasPendingCancellation = cancellationAcknowledgement != nil
        lock.unlock()

        requestQueue.async { [weak self] in
            self?.beginSubmission()
        }
        if hasPendingCancellation {
            scheduleCancellation()
        }
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 90) { [weak self] in
            self?.finishOriginal(.failure(.timedOut))
        }
    }

    func requestCancellation(
        matching requestedIdentity: KernelWorkspaceRequestIdentity,
        acknowledgement: @escaping (KernelWorkspaceCancellationResult) -> Void
    ) {
        lock.lock()
        guard requestedIdentity == identity else {
            lock.unlock()
            acknowledgement(.staleIdentity)
            return
        }
        guard !completed, originalReply == nil else {
            lock.unlock()
            acknowledgement(.notActive)
            return
        }
        guard cancellationResult == .notRequested else {
            lock.unlock()
            acknowledgement(.alreadyRequested)
            return
        }
        cancellationResult = .unavailable
        cancellationAcknowledgement = acknowledgement
        let shouldSchedule = started
        if !submitted {
            cancelledBeforeSubmission = true
        }
        lock.unlock()

        if shouldSchedule {
            scheduleCancellation()
        }
    }

    private func beginSubmission() {
        lock.lock()
        let shouldContinue = !completed && !cancelledBeforeSubmission
        lock.unlock()
        guard shouldContinue else { return }
        guard let snapshotBrokerEndpoint else {
            submitFrozenInvocation()
            return
        }
        let attemptID = UUID()
        lock.lock()
        guard !completed, !cancelledBeforeSubmission else {
            lock.unlock()
            return
        }
        brokerSetupAttemptID = attemptID
        lock.unlock()

        KernelWorkspaceClient.setSnapshotBrokerEndpoint(
            snapshotBrokerEndpoint,
            on: connection
        ) { [weak self] result in
            self?.requestQueue.async {
                self?.finishBrokerSetup(
                    attemptID: attemptID,
                    result: result
                )
            }
        }
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 15) { [weak self] in
            self?.requestQueue.async {
                self?.finishBrokerSetup(
                    attemptID: attemptID,
                    result: .failure(.timedOut)
                )
            }
        }
    }

    private func finishBrokerSetup(
        attemptID: UUID,
        result: Result<Void, KernelWorkspaceClientError>
    ) {
        lock.lock()
        guard !completed, brokerSetupAttemptID == attemptID else {
            lock.unlock()
            return
        }
        brokerSetupAttemptID = nil
        let wasCancelled = cancelledBeforeSubmission
        lock.unlock()
        if wasCancelled {
            finishCancellation(.notSubmitted)
            finishOriginal(.failure(.cancelledBeforeSubmission))
            return
        }
        switch result {
        case .success:
            submitFrozenInvocation()
        case let .failure(error):
            finishOriginal(.failure(error))
        }
    }

    private func submitFrozenInvocation() {
        lock.lock()
        guard !completed, !cancelledBeforeSubmission, !submitted else {
            lock.unlock()
            return
        }
        // The serial request queue orders this invocation before any cancellation
        // sent over the same authenticated connection.
        submitted = true
        submittedAt = ProcessInfo.processInfo.systemUptime
        lock.unlock()
        guard let proxy = connection.remoteObjectProxyWithErrorHandler({ [weak self] _ in
            self?.finishOriginal(.failure(.requestFailed))
        }) as? KernelWorkspaceEndpoint else {
            lock.lock()
            submitted = false
            submittedAt = nil
            lock.unlock()
            finishOriginal(.failure(.invalidWorkspaceProxy))
            return
        }
        do {
            try KernelWorkspaceXPC.submit(
                proxy,
                requestID: identity.requestID,
                invocationFrame: invocationFrame
            ) { [weak self] data in
                guard let self,
                      let reply = KernelWorkspaceXPC.decode(
                        data,
                        requestID: self.identity.requestID
                      ),
                      reply.cancellationAccepted == nil else {
                    self?.finishOriginal(.failure(.invalidResponse))
                    return
                }
                self.finishOriginal(.success(reply))
            }
        } catch {
            lock.lock()
            submitted = false
            submittedAt = nil
            lock.unlock()
            finishOriginal(.failure(.requestFailed))
        }
    }

    private func performCancellation() {
        lock.lock()
        guard !completed, cancellationAcknowledgement != nil else {
            lock.unlock()
            return
        }
        if originalReply != nil {
            lock.unlock()
            finishCancellation(.notActive)
            return
        }
        guard submitted else {
            cancelledBeforeSubmission = true
            lock.unlock()
            finishCancellation(.notSubmitted)
            finishOriginal(.failure(.cancelledBeforeSubmission))
            return
        }
        lock.unlock()

        // The cancellation shares the original authenticated connection and is
        // serialized after the original workspace.run invocation.
        guard let proxy = connection.remoteObjectProxyWithErrorHandler({ [weak self] _ in
            self?.finishCancellation(.unavailable)
        }) as? KernelWorkspaceEndpoint else {
            finishCancellation(.unavailable)
            return
        }
        proxy.cancelWorkspaceCommand(
            KernelWorkspaceXPC.version,
            requestIDHigh: identity.requestID.high,
            requestIDLow: identity.requestID.low
        ) { [weak self] data in
            guard let self,
                  let reply = KernelWorkspaceXPC.decode(
                    data,
                    requestID: self.identity.requestID
                  ) else {
                self?.finishCancellation(.unavailable)
                return
            }
            if reply.cancellationAccepted == true {
                self.finishCancellation(.accepted)
            } else if let code = reply.errorCode {
                self.finishCancellation(.rejected(code))
            } else {
                self.finishCancellation(.unavailable)
            }
        }
    }

    private func scheduleCancellation() {
        requestQueue.async { [weak self] in
            self?.performCancellation()
        }
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 5) { [weak self] in
            self?.finishCancellation(.unavailable)
        }
    }

    private func finishOriginal(
        _ result: Result<KernelWorkspaceXPC.Reply, KernelWorkspaceClientError>
    ) {
        lock.lock()
        guard originalReply == nil, !completed else {
            lock.unlock()
            return
        }
        originalReply = result
        lock.unlock()
        completeIfReady()
    }

    private func finishCancellation(_ result: KernelWorkspaceCancellationResult) {
        lock.lock()
        guard !completed,
              cancellationAcknowledgement != nil,
              cancellationResult == .unavailable else {
            lock.unlock()
            return
        }
        cancellationResult = result
        let acknowledgement = cancellationAcknowledgement
        cancellationAcknowledgement = nil
        lock.unlock()
        acknowledgement?(result)
        completeIfReady()
    }

    private func completeIfReady() {
        lock.lock()
        guard !completed,
              let originalReply,
              cancellationAcknowledgement == nil else {
            lock.unlock()
            return
        }
        completed = true
        let observation = KernelWorkspaceCommandObservation(
            reply: originalReply,
            cancellation: cancellationResult,
            submitted: submitted,
            submittedAt: submittedAt
        )
        let completion = self.completion
        self.completion = nil
        lock.unlock()
        connection.invalidate()
        completion?(observation)
    }
}
