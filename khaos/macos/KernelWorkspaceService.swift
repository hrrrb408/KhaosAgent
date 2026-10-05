import Darwin
import Foundation

enum KernelWorkspaceSandboxDiagnosticStage: String {
    case probeChild = "probe_child"
    case probeReadiness = "probe_readiness"
    case probeSnapshot = "probe_snapshot"
    case probeVerification = "probe_verification"
}

enum KernelWorkspaceServiceError: Error {
    case processCancelled
    case commitRejected
    case commitOutcomeUncertain
    case kernelTimeout
    case runnerFailed
    case pythonBridgeFailed
    case pythonRuntimeUnavailable
    case sandboxUnavailable(KernelWorkspaceSandboxDiagnosticStage?)
    case snapshotBrokerUnavailable(SnapshotBrokerFailureCode)
    case workspaceRejected
}

enum SnapshotBrokerFailureCode: String {
    case configurationMissing = "snapshot_broker_not_configured"
    case peerAuthenticationFailed = "snapshot_broker_peer_auth_failed"
    case connectionFailed = "snapshot_broker_connection_failed"
    case protocolFailed = "snapshot_broker_protocol_failed"
    case busy = "snapshot_broker_busy"
    case rejected = "snapshot_broker_rejected"
    case operationFailed = "snapshot_broker_operation_failed"
    case invalidLease = "snapshot_broker_invalid_lease"
    case releaseFailed = "snapshot_broker_release_failed"
    case timedOut = "snapshot_broker_timeout"
}

final class WorkspaceCancellationSignal {
    static let childDescriptor: Int32 = 197

    private let pipe = Pipe()
    private let lock = NSLock()
    private var requested = false
    private var completed = false

    var isRequested: Bool {
        lock.lock()
        defer { lock.unlock() }
        return requested
    }

    var readDescriptor: Int32 {
        Int32(pipe.fileHandleForReading.fileDescriptor)
    }

    var writeDescriptor: Int32 {
        Int32(pipe.fileHandleForWriting.fileDescriptor)
    }

    init() throws {
        let descriptor = readDescriptor
        let flags = Darwin.fcntl(descriptor, F_GETFL)
        guard flags >= 0,
              Darwin.fcntl(descriptor, F_SETFL, flags | O_NONBLOCK) == 0
        else {
            let error = errno
            pipe.fileHandleForReading.closeFile()
            pipe.fileHandleForWriting.closeFile()
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(error))
        }
    }

    func request() -> String? {
        lock.lock()
        defer { lock.unlock() }
        guard !completed else { return "process_not_active" }
        guard !requested else { return "already_cancelled" }

        var byte: UInt8 = 1
        var result: Int
        repeat {
            result = Darwin.write(writeDescriptor, &byte, 1)
        } while result < 0 && errno == EINTR
        guard result == 1 else { return "process_not_active" }
        requested = true
        return nil
    }

    func finish() {
        lock.lock()
        defer { lock.unlock() }
        guard !completed else { return }
        completed = true
        pipe.fileHandleForReading.closeFile()
        pipe.fileHandleForWriting.closeFile()
    }
}

final class KernelWorkspaceService: NSObject, KernelWorkspaceEndpoint {
    typealias Executor = (
        _ invocation: KernelWorkspaceXPC.WorkspaceInvocation,
        _ cancellation: WorkspaceCancellationSignal
    ) throws -> String

    private let executor: Executor
    private let executionLock = NSLock()
    private var activeRequestID: KernelWorkspaceXPC.RequestID?
    private var activeCancellation: WorkspaceCancellationSignal?
    private var activeConnection: NSXPCConnection?
    private var pendingBrokerEndpoint: NSXPCListenerEndpoint?
    private var pendingBrokerOwner: ObjectIdentifier?

    // The executor is fixed by trusted service composition, never selected over XPC.
    init(executor: @escaping Executor) {
        self.executor = executor
        super.init()
    }

    @objc func setSnapshotBrokerEndpoint(
        _ version: Int,
        endpoint: NSXPCListenerEndpoint,
        withReply reply: @escaping (Bool) -> Void
    ) {
        guard version == KernelWorkspaceXPC.version,
              let connection = NSXPCConnection.current() else {
            reply(false)
            return
        }
        let owner = ObjectIdentifier(connection)
        executionLock.lock()
        guard activeRequestID == nil,
              pendingBrokerEndpoint == nil,
              pendingBrokerOwner == nil else {
            executionLock.unlock()
            reply(false)
            return
        }
        pendingBrokerEndpoint = endpoint
        pendingBrokerOwner = owner
        let clearPendingEndpoint = { [weak self, weak connection] in
            guard let self, let connection else { return }
            self.discardPendingBrokerEndpoint(owner: ObjectIdentifier(connection))
        }
        connection.interruptionHandler = clearPendingEndpoint
        connection.invalidationHandler = clearPendingEndpoint
        executionLock.unlock()
        reply(true)
    }

    @objc func runWorkspaceCommand(
        _ version: Int,
        requestIDHigh: UInt64,
        requestIDLow: UInt64,
        invocationStream: FileHandle,
        withReply reply: @escaping (Data) -> Void
    ) {
        defer { invocationStream.closeFile() }
        let requestID = KernelWorkspaceXPC.RequestID(
            high: requestIDHigh,
            low: requestIDLow
        )
        guard let connection = NSXPCConnection.current() else {
            reply(KernelWorkspaceXPC.failure(requestID: requestID, code: "kernel_failed"))
            return
        }
        guard version == KernelWorkspaceXPC.version else {
            reply(KernelWorkspaceXPC.failure(
                requestID: requestID,
                code: "unsupported_version"
            ))
            return
        }

        let cancellation: WorkspaceCancellationSignal
        do {
            cancellation = try WorkspaceCancellationSignal()
        } catch {
            reply(KernelWorkspaceXPC.failure(requestID: requestID, code: "kernel_failed"))
            return
        }

        executionLock.lock()
        guard activeRequestID == nil else {
            executionLock.unlock()
            cancellation.finish()
            reply(KernelWorkspaceXPC.failure(requestID: requestID, code: "operation_busy"))
            return
        }
        activeRequestID = requestID
        activeCancellation = cancellation
        activeConnection = connection
        let owner = ObjectIdentifier(connection)
        let brokerEndpoint = pendingBrokerOwner == owner
            ? pendingBrokerEndpoint
            : nil
        if pendingBrokerOwner == owner {
            pendingBrokerEndpoint = nil
            pendingBrokerOwner = nil
        }
        // A disconnected caller must not leave its Kernel-owned operation detached.
        let cancelDisconnectedRequest: () -> Void = { [weak self, weak connection] in
            guard let self, let connection else { return }
            _ = self.requestWorkspaceCancellation(
                requestID: requestID,
                connection: connection
            )
        }
        connection.interruptionHandler = cancelDisconnectedRequest
        connection.invalidationHandler = cancelDisconnectedRequest
        executionLock.unlock()

        let result = KernelWorkspaceXPC.readInvocation(
            from: invocationStream,
            requestID: requestID,
            expectedPeerProcessID: connection.processIdentifier,
            snapshotBrokerEndpoint: brokerEndpoint
        )
        guard let invocation = result.invocation else {
            finishWorkspaceRequest(requestID, cancellation: cancellation)
            reply(KernelWorkspaceXPC.failure(
                requestID: requestID,
                code: result.errorCode
            ))
            return
        }
        guard !cancellation.isRequested else {
            finishWorkspaceRequest(requestID, cancellation: cancellation)
            reply(KernelWorkspaceXPC.failure(
                requestID: requestID,
                code: "process_cancelled"
            ))
            return
        }

        DispatchQueue.global(qos: .userInitiated).async {
            let response: Data
            do {
                let output = try self.executor(
                    invocation,
                    cancellation
                )
                response = KernelWorkspaceXPC.success(
                    requestID: requestID,
                    output: output
                )
            } catch KernelWorkspaceServiceError.processCancelled {
                response = KernelWorkspaceXPC.failure(
                    requestID: requestID,
                    code: "process_cancelled"
                )
            } catch KernelWorkspaceServiceError.commitRejected {
                response = KernelWorkspaceXPC.failure(
                    requestID: requestID,
                    code: "commit_rejected"
                )
            } catch KernelWorkspaceServiceError.commitOutcomeUncertain {
                response = KernelWorkspaceXPC.failure(
                    requestID: requestID,
                    code: "commit_outcome_uncertain"
                )
            } catch KernelWorkspaceServiceError.kernelTimeout {
                response = KernelWorkspaceXPC.failure(
                    requestID: requestID,
                    code: "kernel_timeout"
                )
            } catch KernelWorkspaceServiceError.runnerFailed {
                response = KernelWorkspaceXPC.failure(
                    requestID: requestID,
                    code: "runner_failed"
                )
            } catch KernelWorkspaceServiceError.pythonBridgeFailed {
                response = KernelWorkspaceXPC.failure(
                    requestID: requestID,
                    code: "kernel_bridge_failed"
                )
            } catch KernelWorkspaceServiceError.pythonRuntimeUnavailable {
                response = KernelWorkspaceXPC.failure(
                    requestID: requestID,
                    code: "kernel_runtime_unavailable"
                )
            } catch let KernelWorkspaceServiceError.sandboxUnavailable(stage) {
                let code = stage.map {
                    "sandbox_unavailable_\($0.rawValue)"
                } ?? "sandbox_unavailable"
                response = KernelWorkspaceXPC.failure(
                    requestID: requestID,
                    code: code
                )
            } catch let KernelWorkspaceServiceError.snapshotBrokerUnavailable(code) {
                response = KernelWorkspaceXPC.failure(
                    requestID: requestID,
                    code: code.rawValue
                )
            } catch KernelWorkspaceServiceError.workspaceRejected {
                response = KernelWorkspaceXPC.failure(
                    requestID: requestID,
                    code: "workspace_rejected"
                )
            } catch {
                response = KernelWorkspaceXPC.failure(
                    requestID: requestID,
                    code: "kernel_failed"
                )
            }
            self.finishWorkspaceRequest(requestID, cancellation: cancellation)
            reply(response)
        }
    }

    @objc func cancelWorkspaceCommand(
        _ version: Int,
        requestIDHigh: UInt64,
        requestIDLow: UInt64,
        withReply reply: @escaping (Data) -> Void
    ) {
        let requestID = KernelWorkspaceXPC.RequestID(
            high: requestIDHigh,
            low: requestIDLow
        )
        guard let connection = NSXPCConnection.current() else {
            reply(KernelWorkspaceXPC.failure(requestID: requestID, code: "process_not_active"))
            return
        }
        guard version == KernelWorkspaceXPC.version else {
            reply(KernelWorkspaceXPC.failure(
                requestID: requestID,
                code: "unsupported_version"
            ))
            return
        }
        if let errorCode = requestWorkspaceCancellation(
            requestID: requestID,
            connection: connection
        ) {
            reply(KernelWorkspaceXPC.failure(requestID: requestID, code: errorCode))
            return
        }
        reply(KernelWorkspaceXPC.cancellationAccepted(requestID: requestID))
    }

    private func requestWorkspaceCancellation(
        requestID: KernelWorkspaceXPC.RequestID,
        connection: NSXPCConnection
    ) -> String? {
        executionLock.lock()
        // A request ID is scoped to the XPC connection that admitted it.
        let cancellation = activeRequestID == requestID
            && activeConnection === connection
            ? activeCancellation
            : nil
        executionLock.unlock()
        guard let cancellation else { return "process_not_active" }
        return cancellation.request()
    }

    private func finishWorkspaceRequest(
        _ requestID: KernelWorkspaceXPC.RequestID,
        cancellation: WorkspaceCancellationSignal
    ) {
        cancellation.finish()
        executionLock.lock()
        var completedConnection: NSXPCConnection?
        if activeRequestID == requestID, activeCancellation === cancellation {
            activeRequestID = nil
            activeCancellation = nil
            completedConnection = activeConnection
            activeConnection = nil
        }
        executionLock.unlock()
        completedConnection?.interruptionHandler = nil
        completedConnection?.invalidationHandler = nil
    }

    private func discardPendingBrokerEndpoint(owner: ObjectIdentifier) {
        executionLock.lock()
        if pendingBrokerOwner == owner {
            pendingBrokerEndpoint = nil
            pendingBrokerOwner = nil
        }
        executionLock.unlock()
    }
}
