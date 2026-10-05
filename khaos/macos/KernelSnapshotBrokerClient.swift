import Darwin
import Foundation

enum KernelSnapshotBrokerClientError: Error {
    case missingServiceConfiguration
    case invalidPeerRequirement
    case connectionFailed
    case invalidProxy
    case brokerRejected(String)
    case invalidLease
    case releaseFailed
    case timedOut
}

final class KernelSnapshotBrokerLease {
    let mountPath: URL
    let temporaryDirectory: URL

    private let connection: NSXPCConnection
    private let leaseID: String
    private let cancellation: WorkspaceCancellationSignal
    private let stateLock = NSLock()
    private var released = false

    fileprivate init(
        connection: NSXPCConnection,
        leaseID: String,
        mountPath: URL,
        temporaryDirectory: URL,
        cancellation: WorkspaceCancellationSignal
    ) {
        self.connection = connection
        self.leaseID = leaseID
        self.mountPath = mountPath
        self.temporaryDirectory = temporaryDirectory
        self.cancellation = cancellation
        connection.interruptionHandler = { [weak self] in
            guard let self, !self.isReleased else { return }
            _ = self.cancellation.request()
        }
        connection.invalidationHandler = { [weak self] in
            guard let self, !self.isReleased else { return }
            _ = self.cancellation.request()
        }
    }

    fileprivate func holdUntilRelease() throws {
        guard let proxy = connection.remoteObjectProxyWithErrorHandler({ [weak self] _ in
            guard let self, !self.isReleased else { return }
            _ = self.cancellation.request()
        }) as? KernelSnapshotBrokerEndpoint else {
            throw KernelSnapshotBrokerClientError.invalidProxy
        }
        proxy.holdSnapshot(
            KernelSnapshotBrokerXPC.version,
            leaseID: leaseID
        ) { [weak self] released in
            guard let self, !released, !self.isReleased else { return }
            _ = self.cancellation.request()
        }
    }

    func release() throws {
        guard !isReleased else { return }
        let result: Bool = try KernelWorkspaceClient.awaitReply(
            timeout: 20,
            timeoutError: KernelSnapshotBrokerClientError.timedOut
        ) { finish in
            guard let proxy = connection.remoteObjectProxyWithErrorHandler({ _ in
                finish(.failure(.releaseFailed))
            }) as? KernelSnapshotBrokerEndpoint else {
                throw KernelSnapshotBrokerClientError.invalidProxy
            }
            proxy.releaseSnapshot(
                KernelSnapshotBrokerXPC.version,
                leaseID: leaseID
            ) { value in
                finish(.success(value))
            }
        }
        guard result else {
            throw KernelSnapshotBrokerClientError.releaseFailed
        }
        closeConnection()
    }

    func invalidate() {
        guard !isReleased else { return }
        closeConnection()
    }

    private func closeConnection() {
        stateLock.lock()
        released = true
        stateLock.unlock()
        connection.interruptionHandler = nil
        connection.invalidationHandler = nil
        connection.invalidate()
    }

    private var isReleased: Bool {
        stateLock.lock()
        defer { stateLock.unlock() }
        return released
    }
}

enum KernelSnapshotBrokerClient {
    static func createLease(
        snapshotBrokerEndpoint: NSXPCListenerEndpoint,
        caseSensitive: Bool,
        cancellation: WorkspaceCancellationSignal
    ) throws -> KernelSnapshotBrokerLease {
        guard XPCPeerIdentity.codeSigningRequirement(
            forInfoKey: "KhaosSnapshotBrokerRequirement"
        ) != nil else {
            throw KernelSnapshotBrokerClientError.missingServiceConfiguration
        }
        let storageRoot = try storageRootURL()

        let connection = NSXPCConnection(listenerEndpoint: snapshotBrokerEndpoint)
        guard XPCPeerIdentity.requirePeerIdentity(
            connection,
            requirementKey: "KhaosSnapshotBrokerRequirement"
        ) else {
            connection.invalidate()
            throw KernelSnapshotBrokerClientError.invalidPeerRequirement
        }
        connection.remoteObjectInterface = NSXPCInterface(
            with: KernelSnapshotBrokerEndpoint.self
        )
        connection.resume()

        let error: ErrorHandler = {
            _ = cancellation.request()
        }
        connection.interruptionHandler = error
        connection.invalidationHandler = error

        do {
            let result: (String?, String?, String?) = try KernelWorkspaceClient.awaitReply(
                timeout: 75,
                timeoutError: KernelSnapshotBrokerClientError.timedOut
            ) { finish in
                guard let proxy = connection.remoteObjectProxyWithErrorHandler({ _ in
                    finish(.failure(KernelSnapshotBrokerClientError.connectionFailed))
                }) as? KernelSnapshotBrokerEndpoint else {
                    throw KernelSnapshotBrokerClientError.invalidProxy
                }
                proxy.createSnapshot(
                    KernelSnapshotBrokerXPC.version,
                    storageRoot: storageRoot,
                    caseSensitive: caseSensitive
                ) { leaseID, mountPath, error in
                    finish(.success((leaseID, mountPath, error)))
                }
            }
            guard let leaseID = result.0,
                  let path = result.1,
                  result.2 == nil,
                  UUID(uuidString: leaseID) != nil else {
                connection.interruptionHandler = nil
                connection.invalidationHandler = nil
                throw KernelSnapshotBrokerClientError.brokerRejected(
                    Self.safeErrorCode(result.2) ?? "invalid_lease"
                )
        }
        let mountPath = try validateMountPath(path)
        // Python must stage inside the authenticated lease. App Sandbox may
        // deny file creation in the otherwise readable container temp root.
        let temporaryDirectory = mountPath.deletingLastPathComponent()
        connection.interruptionHandler = nil
        connection.invalidationHandler = nil
        let lease = KernelSnapshotBrokerLease(
            connection: connection,
            leaseID: leaseID,
            mountPath: mountPath,
            temporaryDirectory: temporaryDirectory,
            cancellation: cancellation
        )
            try lease.holdUntilRelease()
            return lease
        } catch {
            connection.interruptionHandler = nil
            connection.invalidationHandler = nil
            connection.invalidate()
            throw error
        }
    }

    private static func validateMountPath(_ path: String) throws -> URL {
        guard path.hasPrefix("/"),
              !path.utf8.contains(0),
              path.utf8.count <= 4096 else {
            throw KernelSnapshotBrokerClientError.invalidLease
        }
        let mount = URL(fileURLWithPath: path, isDirectory: true)
            .standardizedFileURL
        let temporaryRoot = FileManager.default.temporaryDirectory
            .resolvingSymlinksInPath()
            .appendingPathComponent(
                KernelSnapshotStoragePolicy.brokerDirectoryName,
                isDirectory: true
            )
            .resolvingSymlinksInPath()
            .standardizedFileURL
        let leaseRoot = mount.deletingLastPathComponent()
        guard mount.lastPathComponent == "volume",
              leaseRoot.lastPathComponent.hasPrefix("khaos-snapshot-broker-"),
              UUID(uuidString: String(leaseRoot.lastPathComponent.dropFirst(
                "khaos-snapshot-broker-".count
              ))) != nil,
              leaseRoot.deletingLastPathComponent()
                .resolvingSymlinksInPath().standardizedFileURL == temporaryRoot
        else {
            throw KernelSnapshotBrokerClientError.invalidLease
        }
        return mount
    }

    private static func storageRootURL() throws -> URL {
        let temporaryRoot = FileManager.default.temporaryDirectory
            .resolvingSymlinksInPath().standardizedFileURL
        let parent = Darwin.open(
            temporaryRoot.path,
            O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW
        )
        guard parent >= 0 else {
            throw KernelSnapshotBrokerClientError.invalidLease
        }
        defer { _ = Darwin.close(parent) }

        var parentInfo = stat()
        guard Darwin.fstat(parent, &parentInfo) == 0,
              (parentInfo.st_mode & S_IFMT) == S_IFDIR,
              parentInfo.st_uid == geteuid() else {
            throw KernelSnapshotBrokerClientError.invalidLease
        }

        let directoryName = KernelSnapshotStoragePolicy.brokerDirectoryName
        let created = directoryName.withCString {
            Darwin.mkdirat(parent, $0, mode_t(0o700))
        }
        guard created == 0 || errno == EEXIST else {
            throw KernelSnapshotBrokerClientError.invalidLease
        }
        let descriptor = directoryName.withCString {
            Darwin.openat(
                parent,
                $0,
                O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW
            )
        }
        guard descriptor >= 0 else {
            throw KernelSnapshotBrokerClientError.invalidLease
        }
        defer { _ = Darwin.close(descriptor) }

        var info = stat()
        guard Darwin.fstat(descriptor, &info) == 0,
              (info.st_mode & S_IFMT) == S_IFDIR,
              info.st_uid == geteuid(),
              info.st_mode & 0o777 == 0o700 else {
            throw KernelSnapshotBrokerClientError.invalidLease
        }
        let storageRoot = temporaryRoot.appendingPathComponent(
            directoryName,
            isDirectory: true
        )
        guard storageRoot.resolvingSymlinksInPath().standardizedFileURL
                == storageRoot else {
            throw KernelSnapshotBrokerClientError.invalidLease
        }
        return storageRoot
    }

    private static func safeErrorCode(_ value: String?) -> String? {
        guard let value, ["invalid_request", "operation_busy", "cancelled", "broker_failed"].contains(value) else {
            return nil
        }
        return value
    }
}

private typealias ErrorHandler = () -> Void
