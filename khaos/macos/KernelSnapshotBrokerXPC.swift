import Foundation

enum KernelSnapshotBrokerXPC {
    static let version = 2
}

@objc protocol KernelSnapshotBrokerEndpoint {
    func createSnapshot(
        _ version: Int,
        storageRoot: URL,
        caseSensitive: Bool,
        withReply reply: @escaping (_ leaseID: String?, _ mountPath: String?, _ error: String?) -> Void
    )

    func holdSnapshot(
        _ version: Int,
        leaseID: String,
        withReply reply: @escaping (_ released: Bool) -> Void
    )

    func releaseSnapshot(
        _ version: Int,
        leaseID: String,
        withReply reply: @escaping (_ released: Bool) -> Void
    )
}
