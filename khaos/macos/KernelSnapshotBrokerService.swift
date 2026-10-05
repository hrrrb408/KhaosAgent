import Darwin
import Foundation
import OSLog

private struct SnapshotLease {
    let id: String
    let owner: ObjectIdentifier
    let directory: URL
    let image: URL
    let mountPoint: URL
    let storageRoot: URL
    let lockDescriptor: Int32
    var device: String?
    var cancelled = false
}

private struct AttachedSnapshotImage {
    let device: String?
}

private enum SnapshotBrokerFailure: Error {
    case invalidRequest
    case busy
    case cancelled
    case operationFailed
    case cleanupFailed
}

final class KernelSnapshotBrokerService: NSObject,
    KernelSnapshotBrokerEndpoint,
    KernelSnapshotBrokerBootstrapEndpoint,
    NSXPCListenerDelegate
{
    private static let sectorBytes: UInt64 = 512
    private static let imageOperationMarker = ".khaos-image-operation-pending"
    private static let directoryPrefix = KernelSnapshotStoragePolicy.leaseDirectoryPrefix
    private static let maximumToolOutputBytes = 1_048_576
    private static let logger = Logger(
        subsystem: "org.khaos.Seed.KernelSnapshotBroker",
        category: "startup"
    )

    private let bootstrapListener = NSXPCListener.service()
    private let operationListener = NSXPCListener.anonymous()
    private let serviceQueue = DispatchQueue(label: "org.khaos.snapshot-broker")
    private let processLock = NSLock()
    private let cancelledLock = NSLock()
    private let launcherRequirement: String
    private let kernelIdentifier: String
    private let expectedKernelTemporaryRoot: URL
    private var activeLease: SnapshotLease?
    private var activeProcess: KernelSnapshotBrokerToolProcess?
    private var activeOwner: ObjectIdentifier?
    private var leaseHoldReply: ((Bool) -> Void)?
    private var cancelledConnections = Set<ObjectIdentifier>()

    init(
        launcherRequirement: String,
        kernelRequirement: String,
        kernelIdentifier: String
    ) throws {
        guard !kernelRequirement.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !launcherRequirement.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              kernelIdentifier == "org.khaos.Seed.KernelProduction" else {
            throw SnapshotBrokerFailure.invalidRequest
        }
        self.launcherRequirement = launcherRequirement
        self.kernelIdentifier = kernelIdentifier
        Self.logger.info("startup=begin")
        expectedKernelTemporaryRoot = try KernelSnapshotBrokerSandbox.kernelTemporaryRoot(
            identifier: kernelIdentifier
        )
        super.init()
        operationListener.setConnectionCodeSigningRequirement(kernelRequirement)
        bootstrapListener.delegate = self
        operationListener.delegate = self
    }

    func run() throws {
        try KernelSnapshotBrokerSandbox.apply(kernelIdentifier: kernelIdentifier)
        Self.logger.notice("sandbox=active")
        operationListener.resume()
        bootstrapListener.resume()
        Self.logger.info("listeners=ready")
        RunLoop.main.run()
    }

    func snapshotBrokerEndpoint(
        withReply reply: @escaping (NSXPCListenerEndpoint) -> Void
    ) {
        guard NSXPCConnection.current() != nil else { return }
        reply(operationListener.endpoint)
    }

    func listener(
        _ listener: NSXPCListener,
        shouldAcceptNewConnection connection: NSXPCConnection
    ) -> Bool {
        if listener === bootstrapListener {
            connection.setCodeSigningRequirement(launcherRequirement)
            connection.exportedInterface = NSXPCInterface(
                with: KernelSnapshotBrokerBootstrapEndpoint.self
            )
            connection.exportedObject = self
        } else if listener === operationListener {
            let disconnected = { [weak self, weak connection] in
                guard let self, let connection else { return }
                self.cancel(owner: ObjectIdentifier(connection))
            }
            connection.interruptionHandler = disconnected
            connection.invalidationHandler = disconnected
            connection.exportedInterface = NSXPCInterface(
                with: KernelSnapshotBrokerEndpoint.self
            )
            connection.exportedObject = self
        } else {
            return false
        }
        connection.resume()
        return true
    }

    func createSnapshot(
        _ version: Int,
        storageRoot: URL,
        caseSensitive: Bool,
        withReply reply: @escaping (String?, String?, String?) -> Void
    ) {
        guard version == KernelSnapshotBrokerXPC.version,
              let connection = NSXPCConnection.current() else {
            reply(nil, nil, "invalid_request")
            return
        }
        let owner = ObjectIdentifier(connection)
        processLock.lock()
        guard activeOwner == nil else {
            processLock.unlock()
            reply(nil, nil, "operation_busy")
            return
        }
        activeOwner = owner
        processLock.unlock()
        serviceQueue.async {
            guard self.owns(owner: owner) else {
                reply(nil, nil, "cancelled")
                return
            }
            guard !self.isCancelled(owner) else {
                self.finish(owner: owner)
                reply(nil, nil, "cancelled")
                return
            }
            guard self.activeLease == nil else {
                self.finish(owner: owner)
                reply(nil, nil, "operation_busy")
                return
            }
            var lockDescriptor: Int32 = -1
            var lease: SnapshotLease?
            do {
                let root: URL
                do {
                    root = try self.resolveStorageRoot(storageRoot)
                } catch {
                    Self.logger.error("snapshot-create-stage=storage-root")
                    throw error
                }
                lockDescriptor = try Self.acquireServiceLock(in: root)
                do {
                    try self.recoverAbandonedLeases(in: root)
                } catch {
                    Self.logger.error("snapshot-create-stage=recovery")
                    throw error
                }
                guard !self.isCancelled(owner) else {
                    throw SnapshotBrokerFailure.cancelled
                }
                let id = UUID().uuidString.lowercased()
                let directory = root.appendingPathComponent(
                    Self.directoryPrefix + id,
                    isDirectory: true
                )
                let newLease = SnapshotLease(
                    id: id,
                    owner: owner,
                    directory: directory,
                    image: directory.appendingPathComponent("workspace.sparsebundle"),
                    mountPoint: directory.appendingPathComponent("volume", isDirectory: true),
                    storageRoot: root,
                    lockDescriptor: lockDescriptor
                )
                lease = newLease
                self.activeLease = newLease
                try self.create(newLease, caseSensitive: caseSensitive)
                guard !self.isCancelled(owner) else {
                    throw SnapshotBrokerFailure.cancelled
                }
                reply(id, newLease.mountPoint.path, nil)
            } catch {
                let errorCode: String
                if self.isCancelled(owner) {
                    errorCode = "cancelled"
                } else if let failure = error as? SnapshotBrokerFailure {
                    switch failure {
                    case .invalidRequest: errorCode = "invalid_request"
                    case .busy: errorCode = "operation_busy"
                    case .cancelled: errorCode = "cancelled"
                    case .operationFailed, .cleanupFailed: errorCode = "broker_failed"
                    }
                } else {
                    errorCode = "broker_failed"
                }
                Self.logger.error("snapshot-create-failed code=\(errorCode, privacy: .public)")
                if let lease {
                    if self.cleanup(lease) {
                        self.activeLease = nil
                        Self.releaseLeaseLock(lease)
                        self.finish(owner: owner)
                    }
                } else {
                    if lockDescriptor >= 0 { _ = Darwin.close(lockDescriptor) }
                    self.finish(owner: owner)
                }
                reply(nil, nil, errorCode)
            }
        }
    }

    func releaseSnapshot(
        _ version: Int,
        leaseID: String,
        withReply reply: @escaping (Bool) -> Void
    ) {
        guard version == KernelSnapshotBrokerXPC.version,
              UUID(uuidString: leaseID) != nil,
              let connection = NSXPCConnection.current() else {
            reply(false)
            return
        }
        let owner = ObjectIdentifier(connection)
        serviceQueue.async {
            guard let lease = self.activeLease,
                  lease.id == leaseID,
                  lease.owner == owner else {
                reply(false)
                return
            }
            if self.cleanup(lease) {
                self.activeLease = nil
                Self.releaseLeaseLock(lease)
                self.finish(owner: owner)
                let holdReply = self.leaseHoldReply
                self.leaseHoldReply = nil
                holdReply?(true)
                reply(true)
            } else {
                reply(false)
            }
        }
    }

    func holdSnapshot(
        _ version: Int,
        leaseID: String,
        withReply reply: @escaping (Bool) -> Void
    ) {
        guard version == KernelSnapshotBrokerXPC.version,
              UUID(uuidString: leaseID) != nil,
              let connection = NSXPCConnection.current() else {
            reply(false)
            return
        }
        let owner = ObjectIdentifier(connection)
        serviceQueue.async {
            guard let lease = self.activeLease,
                  lease.id == leaseID,
                  lease.owner == owner,
                  self.leaseHoldReply == nil else {
                reply(false)
                return
            }
            self.leaseHoldReply = reply
        }
    }

    private func create(
        _ lease: SnapshotLease,
        caseSensitive: Bool
    ) throws {
        guard !isCancelled(lease.owner) else { throw SnapshotBrokerFailure.cancelled }
        try FileManager.default.createDirectory(
            at: lease.directory,
            withIntermediateDirectories: false,
            attributes: [.posixPermissions: 0o700]
        )
        try FileManager.default.createDirectory(
            at: lease.mountPoint,
            withIntermediateDirectories: false,
            attributes: [.posixPermissions: 0o700]
        )
        let marker = lease.directory.appendingPathComponent(Self.imageOperationMarker)
        let markerDescriptor = Darwin.open(
            marker.path,
            O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW,
            0o600
        )
        guard markerDescriptor >= 0 else {
            throw SnapshotBrokerFailure.operationFailed
        }
        _ = Darwin.close(markerDescriptor)
        let sectors = KernelSnapshotStoragePolicy.storageBytes / Self.sectorBytes
        let filesystem = caseSensitive ? "Case-sensitive APFS" : "APFS"
        _ = try runTool(
            "/usr/bin/hdiutil",
            [
                "create", "-type", "SPARSEBUNDLE", "-sectors", String(sectors),
                "-layout", "NONE", "-fs", filesystem, "-volname", "KhaosWork",
                "-nospotlight", lease.image.path,
            ],
            timeout: 60,
            owner: lease.owner,
            currentDirectory: lease.storageRoot
        )
        guard !isCancelled(lease.owner) else { throw SnapshotBrokerFailure.cancelled }
        let attachOutput = try runTool(
            "/usr/bin/hdiutil",
            [
                "attach", "-plist", "-nobrowse", "-mountpoint",
                lease.mountPoint.path, lease.image.path,
            ],
            timeout: 60,
            owner: lease.owner,
            currentDirectory: lease.storageRoot
        )
        guard let volume = Self.attachedVolume(
            in: attachOutput,
            mountPoint: lease.mountPoint
        ) else {
            throw SnapshotBrokerFailure.operationFailed
        }
        var attachedLease = lease
        attachedLease.device = volume.device
        activeLease = attachedLease
        try validateAttachedVolume(
            attachedLease,
            storageBytes: KernelSnapshotStoragePolicy.storageBytes,
            caseSensitive: caseSensitive,
            device: volume.device,
            volumeDevice: volume.volumeDevice,
            owner: lease.owner
        )
        guard !isCancelled(lease.owner) else { throw SnapshotBrokerFailure.cancelled }
    }

    private func validateAttachedVolume(
        _ lease: SnapshotLease,
        storageBytes: UInt64,
        caseSensitive: Bool,
        device: String,
        volumeDevice: String,
        owner: ObjectIdentifier
    ) throws {
        guard Self.isDiskDevice(device, whole: true),
              Self.isDiskDevice(volumeDevice, whole: false),
              Self.isMountedRoot(lease.mountPoint) else {
            throw SnapshotBrokerFailure.operationFailed
        }
        let inventory = try runTool(
            "/usr/bin/hdiutil", ["info", "-plist"], timeout: 15,
            owner: owner,
            currentDirectory: lease.storageRoot
        )
        guard Self.imageCapacity(in: inventory, image: lease.image) == storageBytes else {
            throw SnapshotBrokerFailure.operationFailed
        }
        let info = try runTool(
            "/usr/sbin/diskutil", ["info", "-plist", lease.mountPoint.path],
            timeout: 15,
            owner: owner,
            currentDirectory: lease.storageRoot
        )
        guard let properties = try? PropertyListSerialization.propertyList(
            from: info,
            options: [],
            format: nil
        ) as? [String: Any] else {
            throw SnapshotBrokerFailure.operationFailed
        }
        let expectedFilesystem = caseSensitive ? "Case-sensitive APFS" : "APFS"
        let expectedVisibleName = caseSensitive ? "APFS (Case-sensitive)" : "APFS"
        guard (properties["MountPoint"] as? String).map({
                  Self.sameDirectoryIdentity($0, lease.mountPoint)
              }) == true,
              properties["FilesystemName"] as? String == expectedFilesystem,
              properties["FilesystemUserVisibleName"] as? String == expectedVisibleName,
              properties["DeviceIdentifier"] as? String == String(volumeDevice.dropFirst(5)),
              let totalSize = (properties["TotalSize"] as? NSNumber)?.uint64Value,
              totalSize > 0,
              totalSize <= storageBytes else {
            throw SnapshotBrokerFailure.operationFailed
        }
    }

    private func cleanup(_ lease: SnapshotLease) -> Bool {
        var stage = "lease-directory"
        do {
            var directoryInfo = stat()
            guard Darwin.lstat(lease.directory.path, &directoryInfo) == 0 else {
                return errno == ENOENT
            }
            stage = "image-inventory"
            let image = try attachedImage(
                in: lease.directory,
                storageRoot: lease.storageRoot
            )
            if let image {
                if let device = image.device {
                    stage = "image-detach"
                    _ = try runTool(
                        "/usr/bin/hdiutil", ["detach", device],
                        timeout: 15,
                        owner: lease.owner,
                        currentDirectory: lease.storageRoot,
                        allowCancelledOwner: true
                    )
                } else if Self.isMountedRoot(lease.mountPoint) {
                    stage = "mount-detach"
                    _ = try runTool(
                        "/usr/bin/hdiutil", ["detach", lease.mountPoint.path],
                        timeout: 15,
                        owner: lease.owner,
                        currentDirectory: lease.storageRoot,
                        allowCancelledOwner: true
                    )
                }
            } else if Self.isMountedRoot(lease.mountPoint) {
                stage = "mount-detach"
                _ = try runTool(
                    "/usr/bin/hdiutil", ["detach", lease.mountPoint.path],
                    timeout: 15,
                    owner: lease.owner,
                    currentDirectory: lease.storageRoot,
                    allowCancelledOwner: true
                )
            }
            stage = "detach-verification"
            guard !Self.isMountedRoot(lease.mountPoint) else {
                Self.logger.error("snapshot-cleanup=failed stage=mount-remains")
                return false
            }
            guard try attachedImage(
                in: lease.directory,
                storageRoot: lease.storageRoot
            ) == nil else {
                Self.logger.error("snapshot-cleanup=failed stage=image-remains")
                return false
            }
            stage = "lease-directory-remove"
            try removeLeaseDirectory(lease.directory, under: lease.storageRoot)
            return true
        } catch {
            Self.logger.error("snapshot-cleanup=failed stage=\(stage, privacy: .public)")
            return false
        }
    }

    private static func releaseLeaseLock(_ lease: SnapshotLease) {
        if lease.lockDescriptor >= 0 {
            _ = Darwin.close(lease.lockDescriptor)
        }
    }

    private func recoverAbandonedLeases(in storageRoot: URL) throws {
        let children = try FileManager.default.contentsOfDirectory(
            at: storageRoot,
            includingPropertiesForKeys: [.isDirectoryKey, .isSymbolicLinkKey],
            options: [.skipsHiddenFiles]
        )
        for directory in children where directory.lastPathComponent.hasPrefix(Self.directoryPrefix) {
            let id = String(directory.lastPathComponent.dropFirst(Self.directoryPrefix.count))
            guard UUID(uuidString: id) != nil else {
                throw SnapshotBrokerFailure.cleanupFailed
            }
            try Self.validatePrivateDirectory(directory, under: storageRoot)
            let lease = SnapshotLease(
                id: id,
                owner: ObjectIdentifier(self),
                directory: directory,
                image: directory.appendingPathComponent("workspace.sparsebundle"),
                mountPoint: directory.appendingPathComponent("volume", isDirectory: true),
                storageRoot: storageRoot,
                lockDescriptor: -1
            )
            guard cleanup(lease) else { throw SnapshotBrokerFailure.cleanupFailed }
        }
    }

    private func resolveStorageRoot(_ root: URL) throws -> URL {
        let expected = expectedKernelTemporaryRoot.appendingPathComponent(
            KernelSnapshotStoragePolicy.brokerDirectoryName,
            isDirectory: true
        )
        guard root.isFileURL,
              root.standardizedFileURL == expected,
              root.resolvingSymlinksInPath().standardizedFileURL == expected else {
            Self.logger.error("storage-root-url=path-rejected")
            throw SnapshotBrokerFailure.invalidRequest
        }
        try Self.validatePrivateDirectory(root, under: expected)
        return root
    }

    private func removeLeaseDirectory(_ directory: URL, under storageRoot: URL) throws {
        try Self.validatePrivateDirectory(directory, under: storageRoot)
        try FileManager.default.removeItem(at: directory)
    }

    private func attachedImage(
        in directory: URL,
        storageRoot: URL
    ) throws -> AttachedSnapshotImage? {
        let inventory = try runTool(
            "/usr/bin/hdiutil", ["info", "-plist"], timeout: 15,
            owner: ObjectIdentifier(self),
            currentDirectory: storageRoot,
            allowCancelledOwner: true
        )
        guard let plist = try? PropertyListSerialization.propertyList(
            from: inventory,
            options: [],
            format: nil
        ) as? [String: Any],
        let images = plist["images"] as? [[String: Any]] else {
            throw SnapshotBrokerFailure.operationFailed
        }
        let imagePath = directory.appendingPathComponent("workspace.sparsebundle")
            .standardizedFileURL.resolvingSymlinksInPath().path
        let matches = images.filter { entry in
            guard let path = entry["image-path"] as? String else { return false }
            return URL(fileURLWithPath: path).standardizedFileURL
                .resolvingSymlinksInPath().path == imagePath
        }
        guard matches.count <= 1 else { throw SnapshotBrokerFailure.operationFailed }
        guard let match = matches.first else { return nil }
        let entities = match["system-entities"] as? [[String: Any]] ?? []
        let devices = Set(entities.compactMap { entity -> String? in
            guard let path = entity["dev-entry"] as? String,
                  Self.isDiskDevice(path, whole: true),
                  (entity["content-hint"] as? String ?? "").isEmpty else {
                return nil
            }
            return path
        })
        guard devices.count <= 1 else { throw SnapshotBrokerFailure.operationFailed }
        return AttachedSnapshotImage(device: devices.first)
    }

    private func cancel(owner: ObjectIdentifier) {
        processLock.lock()
        let ownsLease = activeOwner == owner
        let process = ownsLease ? activeProcess : nil
        processLock.unlock()
        guard ownsLease else { return }
        cancelledLock.lock()
        cancelledConnections.insert(owner)
        cancelledLock.unlock()
        process?.requestTermination()
        serviceQueue.async {
            if let lease = self.activeLease, lease.owner == owner {
                guard self.cleanup(lease) else { return }
                self.activeLease = nil
                Self.releaseLeaseLock(lease)
            }
            let holdReply = self.leaseHoldReply
            self.leaseHoldReply = nil
            self.finish(owner: owner)
            holdReply?(false)
        }
    }

    private func finish(owner: ObjectIdentifier) {
        processLock.lock()
        if activeOwner == owner { activeOwner = nil }
        processLock.unlock()
        cancelledLock.lock()
        cancelledConnections.remove(owner)
        cancelledLock.unlock()
    }

    private func owns(owner: ObjectIdentifier) -> Bool {
        processLock.lock()
        defer { processLock.unlock() }
        return activeOwner == owner
    }

    private func isCancelled(_ owner: ObjectIdentifier) -> Bool {
        cancelledLock.lock()
        defer { cancelledLock.unlock() }
        return cancelledConnections.contains(owner)
    }

    private func runTool(
        _ executable: String,
        _ arguments: [String],
        timeout: TimeInterval,
        owner: ObjectIdentifier,
        currentDirectory: URL,
        allowCancelledOwner: Bool = false
    ) throws -> Data {
        if !allowCancelledOwner && isCancelled(owner) {
            throw SnapshotBrokerFailure.cancelled
        }
        do {
            return try KernelSnapshotBrokerToolRunner.run(
                executable: executable,
                arguments: arguments,
                environment: [
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                    "LC_ALL": "C",
                    "TMPDIR": currentDirectory.path,
                ],
                currentDirectory: currentDirectory,
                timeout: timeout,
                outputLimit: Self.maximumToolOutputBytes,
                isCancelled: { !allowCancelledOwner && self.isCancelled(owner) },
                processStarted: { process in
                    self.processLock.lock()
                    let ownerIsActive = self.activeOwner == owner
                    if ownerIsActive { self.activeProcess = process }
                    self.processLock.unlock()
                    if !allowCancelledOwner
                        && (!ownerIsActive || self.isCancelled(owner)) {
                        process.requestTermination()
                    }
                },
                processFinished: { process in
                    self.processLock.lock()
                    if self.activeProcess === process { self.activeProcess = nil }
                    self.processLock.unlock()
                }
            )
        } catch KernelSnapshotBrokerToolFailure.cancelled {
            throw SnapshotBrokerFailure.cancelled
        } catch let failure as KernelSnapshotBrokerToolFailure {
            let reason: String
            switch failure {
            case .cancelled:
                reason = "cancelled"
            case .timedOut:
                reason = "timeout"
            case .operationFailed:
                reason = "operation"
            case .spawnFailed(let status):
                reason = "spawn_status_\(status)"
            case .waitFailed(let code):
                reason = "wait_errno_\(code)"
            case .toolExited(let status):
                reason = "tool_wait_status_\(status)"
            }
            Self.logger.error("snapshot-tool=failed reason=\(reason, privacy: .public)")
            throw SnapshotBrokerFailure.operationFailed
        } catch {
            throw SnapshotBrokerFailure.operationFailed
        }
    }

    private static func acquireServiceLock(in root: URL) throws -> Int32 {
        let path = root.appendingPathComponent(".khaos-snapshot-broker.lock").path
        let descriptor = Darwin.open(
            path,
            O_RDWR | O_CREAT | O_CLOEXEC | O_NOFOLLOW,
            0o600
        )
        guard descriptor >= 0 else {
            logger.error("service-lock-failure=open errno=\(errno)")
            throw SnapshotBrokerFailure.busy
        }
        var lock = flock()
        lock.l_type = Int16(F_WRLCK)
        lock.l_whence = Int16(SEEK_SET)
        guard Darwin.fcntl(descriptor, F_SETLK, &lock) == 0 else {
            logger.error("service-lock-failure=fcntl errno=\(errno)")
            _ = Darwin.close(descriptor)
            throw SnapshotBrokerFailure.busy
        }
        guard Darwin.fchmod(descriptor, 0o600) == 0 else {
            logger.error("service-lock-failure=chmod errno=\(errno)")
            _ = Darwin.close(descriptor)
            throw SnapshotBrokerFailure.busy
        }
        return descriptor
    }

    private static func validatePrivateDirectory(_ directory: URL, under root: URL) throws {
        let path = directory.standardizedFileURL.path
        let rootPath = root.standardizedFileURL.path
        var info = stat()
        guard path.withCString({ Darwin.lstat($0, &info) }) == 0,
              (info.st_mode & S_IFMT) == S_IFDIR,
              info.st_uid == geteuid(),
              path == rootPath || path.hasPrefix(rootPath + "/"),
              directory.resolvingSymlinksInPath().standardizedFileURL.path == path
        else {
            throw SnapshotBrokerFailure.invalidRequest
        }
    }

    private static func attachedVolume(
        in data: Data,
        mountPoint: URL
    ) -> (device: String, volumeDevice: String)? {
        guard let plist = try? PropertyListSerialization.propertyList(
            from: data,
            options: [],
            format: nil
        ) as? [String: Any],
        let entities = plist["system-entities"] as? [[String: Any]] else {
            return nil
        }
        let volumes = entities.compactMap { entity -> String? in
            guard entity["volume-kind"] as? String == "apfs",
                  (entity["mount-point"] as? String).map({
                      sameDirectoryIdentity($0, mountPoint)
                  }) == true,
                  let device = entity["dev-entry"] as? String,
                  isDiskDevice(device, whole: false) else {
                return nil
            }
            return device
        }
        let imageDevices = Set(entities.compactMap { entity -> String? in
            guard let device = entity["dev-entry"] as? String,
                  isDiskDevice(device, whole: true),
                  (entity["content-hint"] as? String ?? "").isEmpty else {
                return nil
            }
            return device
        })
        guard volumes.count == 1, imageDevices.count == 1 else { return nil }
        return (imageDevices.first!, volumes[0])
    }

    private static func imageCapacity(in data: Data, image: URL) -> UInt64? {
        guard let plist = try? PropertyListSerialization.propertyList(
            from: data,
            options: [],
            format: nil
        ) as? [String: Any],
        let images = plist["images"] as? [[String: Any]] else {
            return nil
        }
        let matches = images.filter { entry in
            guard let path = entry["image-path"] as? String else { return false }
            return sameDirectoryIdentity(path, image)
        }
        guard matches.count == 1,
              let entry = matches.first,
              entry["image-type"] as? String == "sparse bundle disk image",
              entry["writeable"] as? Bool == true,
              let blockCount = (entry["blockcount"] as? NSNumber)?.uint64Value,
              let blockSize = (entry["blocksize"] as? NSNumber)?.uint64Value,
              blockSize == sectorBytes else {
            return nil
        }
        return blockCount.multipliedReportingOverflow(by: blockSize).overflow
            ? nil
            : blockCount * blockSize
    }

    private static func isDiskDevice(_ value: String, whole: Bool) -> Bool {
        let pattern: String
        if whole {
            pattern = #"^/dev/disk[0-9]+$"#
        } else {
            pattern = #"^/dev/disk[0-9]+(?:s[0-9]+)?$"#
        }
        return value.range(of: pattern, options: .regularExpression) != nil
    }

    private static func sameDirectoryIdentity(_ observed: String, _ expected: URL) -> Bool {
        guard observed.hasPrefix("/"),
              !observed.utf8.contains(0),
              observed.utf8.count <= 4096 else { return false }
        var observedInfo = stat()
        var expectedInfo = stat()
        guard observed.withCString({ Darwin.lstat($0, &observedInfo) }) == 0,
              expected.path.withCString({ Darwin.lstat($0, &expectedInfo) }) == 0,
              (observedInfo.st_mode & S_IFMT) == S_IFDIR,
              (expectedInfo.st_mode & S_IFMT) == S_IFDIR else { return false }
        return observedInfo.st_dev == expectedInfo.st_dev
            && observedInfo.st_ino == expectedInfo.st_ino
    }

    private static func isMountedRoot(_ url: URL) -> Bool {
        var info = statfs()
        guard statfs(url.path, &info) == 0 else { return false }
        let mountName = withUnsafePointer(to: &info.f_mntonname) {
            $0.withMemoryRebound(to: CChar.self, capacity: Int(MNAMELEN)) {
                String(cString: $0)
            }
        }
        return sameDirectoryIdentity(mountName, url)
    }
}
