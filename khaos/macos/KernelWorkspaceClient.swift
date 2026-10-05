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

    private static func setSnapshotBrokerEndpoint(
        _ endpoint: NSXPCListenerEndpoint,
        on connection: NSXPCConnection
    ) throws {
        let accepted: Bool = try Self.awaitReply(
            timeout: 15,
            timeoutError: KernelWorkspaceClientError.timedOut
        ) { finish in
            guard let proxy = connection.remoteObjectProxyWithErrorHandler({ _ in
                finish(.failure(.requestFailed))
            }) as? KernelWorkspaceEndpoint else {
                throw KernelWorkspaceClientError.invalidWorkspaceProxy
            }
            proxy.setSnapshotBrokerEndpoint(
                KernelWorkspaceXPC.version,
                endpoint: endpoint
            ) { value in
                finish(.success(value))
            }
        }
        guard accepted else {
            throw KernelWorkspaceClientError.snapshotBrokerEndpointRejected
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
