import Foundation

@objc protocol SnapshotBrokerSandboxProbeEndpoint {
    func probe(
        _ version: Int,
        readPath: String,
        aliasReadPath: String,
        writePath: String,
        directoryPath: String,
        temporaryWritePath: String,
        temporaryExecutablePath: String,
        privateTemporaryWritePath: String,
        tmpAliasWritePath: String,
        sharedExecutablePath: String,
        packageExecutablePath: String,
        packageAliasExecutablePath: String,
        packageWritePath: String,
        packageAliasWritePath: String,
        kernelExecutablePath: String,
        targetProcessID: Int32,
        loopbackPort: Int32,
        withReply reply: @escaping (Data) -> Void
    )
}
