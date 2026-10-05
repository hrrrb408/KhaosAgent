import Foundation

@objc protocol KernelSnapshotBrokerBootstrapEndpoint {
    func snapshotBrokerEndpoint(
        withReply reply: @escaping (NSXPCListenerEndpoint) -> Void
    )
}
