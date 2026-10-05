import Darwin
import Foundation

@main
enum SnapshotBrokerProbeServiceMain {
    static func main() {
        do {
            guard let workspaceRequirement = XPCPeerIdentity.codeSigningRequirement(
                forInfoKey: "KhaosWorkspaceCallerRequirement"
            ),
            let bootstrapRequirement = XPCPeerIdentity.codeSigningRequirement(
                forInfoKey: "KhaosBootstrapRequirement"
            ) else {
                throw SnapshotBrokerProbeFailure.missingConfiguration
            }
            let service = SnapshotBrokerProbeService(
                workspaceRequirement: workspaceRequirement,
                bootstrapRequirement: bootstrapRequirement
            )
            withExtendedLifetime(service) { service.run() }
        } catch {
            fputs("snapshot-broker-probe=unavailable\n", stderr)
            exit(EXIT_FAILURE)
        }
    }
}

private final class SnapshotBrokerProbeService: NSObject,
    KernelWorkspaceBootstrapEndpoint,
    NSXPCListenerDelegate
{
    private let bootstrapListener = NSXPCListener.service()
    private let workspaceListener = NSXPCListener.anonymous()
    private let bootstrapRequirement: String
    private let endpoint = SnapshotBrokerProbeWorkspaceEndpoint()

    init(workspaceRequirement: String, bootstrapRequirement: String) {
        self.bootstrapRequirement = bootstrapRequirement
        super.init()
        workspaceListener.setConnectionCodeSigningRequirement(workspaceRequirement)
        workspaceListener.delegate = self
        workspaceListener.resume()
    }

    func run() {
        bootstrapListener.delegate = self
        bootstrapListener.resume()
        RunLoop.main.run()
    }

    func kernelEndpoint(withReply reply: @escaping (NSXPCListenerEndpoint) -> Void) {
        reply(workspaceListener.endpoint)
    }

    func listener(
        _ listener: NSXPCListener,
        shouldAcceptNewConnection connection: NSXPCConnection
    ) -> Bool {
        if listener === bootstrapListener {
            connection.setCodeSigningRequirement(bootstrapRequirement)
            connection.exportedInterface = NSXPCInterface(
                with: KernelWorkspaceBootstrapEndpoint.self
            )
            connection.exportedObject = self
        } else if listener === workspaceListener {
            connection.exportedInterface = NSXPCInterface(
                with: KernelWorkspaceEndpoint.self
            )
            connection.exportedObject = endpoint
        } else {
            return false
        }
        connection.resume()
        return true
    }

}

private final class SnapshotBrokerProbeWorkspaceEndpoint: NSObject,
    KernelWorkspaceEndpoint
{
    func setSnapshotBrokerEndpoint(
        _ version: Int,
        endpoint: NSXPCListenerEndpoint,
        withReply reply: @escaping (Bool) -> Void
    ) {
        guard version == KernelWorkspaceXPC.version else {
            reply(false)
            return
        }
        DispatchQueue.global(qos: .utility).async {
            do {
                try self.verifyBrokerLease(endpoint: endpoint)
                reply(true)
            } catch {
                reply(false)
            }
        }
    }

    func runWorkspaceCommand(
        _ version: Int,
        requestIDHigh: UInt64,
        requestIDLow: UInt64,
        invocationStream: FileHandle,
        withReply reply: @escaping (Data) -> Void
    ) {
        reply(failure(requestIDHigh, requestIDLow))
    }

    func cancelWorkspaceCommand(
        _ version: Int,
        requestIDHigh: UInt64,
        requestIDLow: UInt64,
        withReply reply: @escaping (Data) -> Void
    ) {
        reply(failure(requestIDHigh, requestIDLow))
    }

    private func failure(_ high: UInt64, _ low: UInt64) -> Data {
        KernelWorkspaceXPC.failure(
            requestID: KernelWorkspaceXPC.RequestID(high: high, low: low),
            code: "invalid_request"
        )
    }

    private func verifyBrokerLease(endpoint: NSXPCListenerEndpoint) throws {
        let cancellation = try WorkspaceCancellationSignal()
        defer { cancellation.finish() }
        let lease = try KernelSnapshotBrokerClient.createLease(
            snapshotBrokerEndpoint: endpoint,
            caseSensitive: false,
            cancellation: cancellation
        )
        let leaseRoot = lease.mountPath.deletingLastPathComponent()
        try lease.release()
        var info = stat()
        guard Darwin.lstat(leaseRoot.path, &info) != 0,
              errno == ENOENT else {
            throw SnapshotBrokerProbeFailure.leaseCleanupFailed
        }
    }

}

private enum SnapshotBrokerProbeFailure: Error {
    case missingConfiguration
    case leaseCleanupFailed
}
