import Foundation

enum KernelSnapshotBrokerBootstrapError: Error {
    case notConfigured
    case connectionFailed
    case invalidProxy
    case timedOut
}

enum KernelSnapshotBrokerBootstrapClient {
    private static let serviceName = "org.khaos.Seed.KernelSnapshotBroker"

    static func endpoint() throws -> NSXPCListenerEndpoint {
        guard Bundle.main.object(
            forInfoDictionaryKey: "KhaosSnapshotBrokerServiceName"
        ) as? String == serviceName,
        let requirement = XPCPeerIdentity.codeSigningRequirement(
            forInfoKey: "KhaosKernelSnapshotBrokerRequirement"
        ) else {
            throw KernelSnapshotBrokerBootstrapError.notConfigured
        }

        let connection = NSXPCConnection(serviceName: serviceName)
        connection.setCodeSigningRequirement(requirement)
        connection.remoteObjectInterface = NSXPCInterface(
            with: KernelSnapshotBrokerBootstrapEndpoint.self
        )
        connection.resume()
        defer { connection.invalidate() }

        do {
            return try KernelWorkspaceClient.awaitReply(
                timeout: 15,
                timeoutError: KernelSnapshotBrokerBootstrapError.timedOut
            ) { finish in
                guard let proxy = connection.remoteObjectProxyWithErrorHandler({ _ in
                    finish(.failure(.connectionFailed))
                }) as? KernelSnapshotBrokerBootstrapEndpoint else {
                    throw KernelSnapshotBrokerBootstrapError.invalidProxy
                }
                proxy.snapshotBrokerEndpoint { endpoint in
                    finish(.success(endpoint))
                }
            }
        } catch let error as KernelSnapshotBrokerBootstrapError {
            throw error
        } catch {
            throw KernelSnapshotBrokerBootstrapError.connectionFailed
        }
    }
}
