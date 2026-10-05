enum KernelSnapshotStoragePolicy {
    static let brokerDirectoryName = "khaos-snapshot-broker"
    static let leaseDirectoryPrefix = "khaos-snapshot-broker-"
    static let maximumWorkspaceBytes: UInt64 = 1024 * 1024 * 1024
    static let storageOverheadBytes: UInt64 = 256 * 1024 * 1024
    static let storageBytes = 2 * maximumWorkspaceBytes + storageOverheadBytes
}
