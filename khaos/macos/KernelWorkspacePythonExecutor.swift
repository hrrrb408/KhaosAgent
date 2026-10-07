import CoreFoundation
import Darwin
import Foundation
import OSLog

private enum KernelBridgeOutputKind {
    case lifecycle
    case evolutionSource
    case workspace
    case pluginEvaluation
}

/// Fixed trusted executor. The XPC caller cannot choose the runtime or
/// inherit raw host descriptors.
enum KernelWorkspacePythonExecutor {
    private static let maximumProcessFrameBytes =
        KernelWorkspaceXPC.maximumMessageBytes + KernelWorkspaceXPC.transferLengthBytes
    private static let maximumAgentInterfaceBytes = 2 * 1024
    private static let maximumAgentInterfaceSummaryBytes = 512
    private static let maximumAgentInterfaceOperations = 16
    private static let maximumAgentInterfaceFields = 16
    private static let operationDeadlineSeconds: TimeInterval = 75
    private static let snapshotStorageBytes = KernelSnapshotStoragePolicy.storageBytes
    private static let logger = Logger(
        subsystem: "org.khaos.Seed.KernelProduction",
        category: "workspace-executor"
    )

    static func execute(
        _ invocation: KernelWorkspaceXPC.WorkspaceInvocation,
        cancellation: WorkspaceCancellationSignal
    ) throws -> String {
        let bundle: (executable: URL, resources: URL)
        do {
            bundle = try pythonBundle()
        } catch {
            throw KernelWorkspaceServiceError.pythonRuntimeUnavailable
        }
        if case let .pluginLifecycle(request) = invocation.request,
           !request.needsSnapshotBroker {
            guard !cancellation.isRequested else {
                throw KernelWorkspaceServiceError.processCancelled
            }
            let input = try KernelWorkspaceXPC.encodeBridgeInput(
                request: request,
                requestID: invocation.requestID
            )
            let rootDescriptor = Darwin.open("/dev/null", O_RDONLY | O_CLOEXEC)
            guard rootDescriptor >= 0 else {
                throw KernelWorkspaceServiceError.pythonBridgeFailed
            }
            defer { _ = Darwin.close(rootDescriptor) }
            let value = try runBridge(
                bundle: bundle,
                workspace: URL(fileURLWithPath: "/"),
                rootDescriptor: rootDescriptor,
                invocation: input,
                snapshotLease: nil,
                pluginStoreRoot: try pluginStoreRoot().path,
                pluginStateRoot: try pluginStateRoot().path,
                cancellation: cancellation
            )
            let outputKind: KernelBridgeOutputKind
            if case .source = request {
                outputKind = .evolutionSource
            } else {
                outputKind = .lifecycle
            }
            return try decodeBridgeResponse(
                value,
                requestID: invocation.requestID,
                outputKind: outputKind
            )
        }
        guard let snapshotBrokerEndpoint = invocation.snapshotBrokerEndpoint else {
            throw KernelWorkspaceServiceError.snapshotBrokerUnavailable(
                .configurationMissing
            )
        }
        if invocation.bookmark == nil {
            guard case .pluginLifecycle = invocation.request else {
                throw KernelWorkspaceServiceError.workspaceRejected
            }
            guard !cancellation.isRequested else {
                throw KernelWorkspaceServiceError.processCancelled
            }
            let lease: KernelSnapshotBrokerLease
            do {
                lease = try KernelSnapshotBrokerClient.createLease(
                    snapshotBrokerEndpoint: snapshotBrokerEndpoint,
                    caseSensitive: true,
                    cancellation: cancellation
                )
            } catch {
                if cancellation.isRequested {
                    throw KernelWorkspaceServiceError.processCancelled
                }
                throw KernelWorkspaceServiceError.snapshotBrokerUnavailable(
                    snapshotBrokerFailureCode(for: error)
                )
            }
            let rootDescriptor = Darwin.open("/dev/null", O_RDONLY | O_CLOEXEC)
            guard rootDescriptor >= 0 else {
                try? lease.release()
                throw KernelWorkspaceServiceError.pythonBridgeFailed
            }
            defer { _ = Darwin.close(rootDescriptor) }
            guard case let .pluginLifecycle(request) = invocation.request else {
                throw KernelWorkspaceServiceError.workspaceRejected
            }
            let bridgeInput = try KernelWorkspaceXPC.encodeBridgeInput(
                request: request,
                requestID: invocation.requestID
            )
            let value: Data
            do {
                value = try runBridge(
                    bundle: bundle,
                    workspace: URL(fileURLWithPath: "/"),
                    rootDescriptor: rootDescriptor,
                    invocation: bridgeInput,
                    snapshotLease: lease,
                    pluginStoreRoot: try pluginStoreRoot().path,
                    pluginStateRoot: try pluginStateRoot().path,
                    cancellation: cancellation
                )
            } catch {
                try? lease.release()
                throw error
            }
            do {
                try lease.release()
            } catch {
                lease.invalidate()
                throw KernelWorkspaceServiceError.commitOutcomeUncertain
            }
            let outputKind: KernelBridgeOutputKind
            if case .evaluate = request {
                outputKind = .pluginEvaluation
            } else {
                outputKind = .workspace
            }
            return try decodeBridgeResponse(
                value,
                requestID: invocation.requestID,
                outputKind: outputKind
            )
        }
        guard let bookmark = invocation.bookmark else {
            throw KernelWorkspaceServiceError.workspaceRejected
        }
        let bridgeRequest: KernelWorkspaceXPC.InvocationRequest = invocation.request
        let access: (value: Data, stale: Bool, refreshed: Bool)
        do {
            access = try KernelWorkspaceRoot.withScopedBookmark(bookmark) {
                workspace, rootDescriptor, activeBookmark in
                do {
                    guard !cancellation.isRequested else {
                        throw KernelWorkspaceServiceError.processCancelled
                    }
                    let bridgeInput: Data
                    switch bridgeRequest {
                    case let .workspaceRun(request):
                        bridgeInput = try KernelWorkspaceXPC.encodeBridgeInput(
                            request: request,
                            requestID: invocation.requestID,
                            bookmark: activeBookmark
                        )
                    case let .pluginLifecycle(request):
                        bridgeInput = try KernelWorkspaceXPC.encodeBridgeInput(
                            request: request,
                            requestID: invocation.requestID,
                            bookmark: activeBookmark
                        )
                    }
                    let caseSensitive = try workspaceCaseSensitivity(
                        workspace,
                        cancellation: cancellation
                    )
                    guard !cancellation.isRequested else {
                        throw KernelWorkspaceServiceError.processCancelled
                    }
                    let lease: KernelSnapshotBrokerLease
                    do {
                        lease = try KernelSnapshotBrokerClient.createLease(
                            snapshotBrokerEndpoint: snapshotBrokerEndpoint,
                            caseSensitive: caseSensitive,
                            cancellation: cancellation
                        )
                    } catch {
                        if cancellation.isRequested {
                            throw KernelWorkspaceServiceError.processCancelled
                        }
                        throw KernelWorkspaceServiceError.snapshotBrokerUnavailable(
                            snapshotBrokerFailureCode(for: error)
                        )
                    }
                    let value: Data
                    do {
                        value = try runBridge(
                            bundle: bundle,
                            workspace: workspace,
                            rootDescriptor: rootDescriptor,
                            invocation: bridgeInput,
                            snapshotLease: lease,
                            pluginStoreRoot: try pluginStoreRoot().path,
                            pluginStateRoot: try pluginStateRoot().path,
                            cancellation: cancellation
                        )
                    } catch {
                        Self.logBridgeFailure(error)
                        do {
                            try lease.release()
                        } catch {
                            lease.invalidate()
                            throw KernelWorkspaceServiceError.commitOutcomeUncertain
                        }
                        throw error
                    }
                    do {
                        try lease.release()
                    } catch {
                        lease.invalidate()
                        throw KernelWorkspaceServiceError.commitOutcomeUncertain
                    }
                    return value
                } catch let error as KernelWorkspaceServiceError {
                    throw error
                } catch let error as NSError where error.code == Int(ETIMEDOUT) {
                    throw KernelWorkspaceServiceError.kernelTimeout
                } catch {
                    throw KernelWorkspaceServiceError.pythonBridgeFailed
                }
            }
        } catch let error as KernelWorkspaceServiceError {
            throw error
        } catch let error as KernelWorkspaceRootFailure {
            logger.error(
                "executor=workspace-root-rejected stage=\(error.diagnosticCode, privacy: .public)"
            )
            throw KernelWorkspaceServiceError.workspaceRejected
        } catch {
            throw KernelWorkspaceServiceError.workspaceRejected
        }
        return try decodeBridgeResponse(
            access.value,
            requestID: invocation.requestID,
            outputKind: .workspace
        )
    }

    private static let pluginLifecycleErrorCodes: Set<String> = [
        "activation_outcome_uncertain", "activation_state_corrupt",
        "activation_state_unavailable", "approval_binding_mismatch",
        "approval_expired", "candidate_corrupt", "candidate_missing",
        "candidate_store_failed", "invalid_rollback_target", "invalid_time",
        "evaluation_workspace_changed",
        "manifest_rejected", "no_active_candidate", "plugin_lifecycle_failed",
        "plugin_source_rejected", "stale_approval", "store_unavailable",
        "plugin_input_too_large", "plugin_invocation_unsupported",
        "plugin_output_too_large", "plugin_state_corrupt",
        "plugin_state_outcome_uncertain", "plugin_state_too_large",
        "plugin_state_unavailable", "capability_denied",
    ]

    private static func pluginStoreRoot() throws -> URL {
        try pluginDataRoot(prefix: "org.khaos.Seed.PluginStore-")
    }

    private static func pluginStateRoot() throws -> URL {
        try pluginDataRoot(prefix: "org.khaos.Seed.PluginState-")
    }

    private static func pluginDataRoot(prefix: String) throws -> URL {
        guard let callerRequirement = Bundle.main.object(
            forInfoDictionaryKey: "KhaosWorkspaceCallerRequirement"
        ) as? String, !callerRequirement.isEmpty else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(ENOENT))
        }
        let namespace = KernelWorkspaceXPC.sha256Hex(Data(callerRequirement.utf8))
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library", isDirectory: true)
            .appendingPathComponent("Application Support", isDirectory: true)
            .appendingPathComponent(
                "\(prefix)\(namespace)",
                isDirectory: true
            )
    }

    private static func decodeBridgeResponse(
        _ value: Data,
        requestID: KernelWorkspaceXPC.RequestID,
        outputKind: KernelBridgeOutputKind
    ) throws -> String {
        guard value.count >= KernelWorkspaceXPC.transferLengthBytes else {
            logger.error(
                "executor=python-bridge-invalid-frame reason=short actual-bytes=\(value.count, privacy: .public)"
            )
            throw KernelWorkspaceServiceError.pythonBridgeFailed
        }
        let responseBody = Data(value.dropFirst(KernelWorkspaceXPC.transferLengthBytes))
        let declaredLength = Int(readUInt32(value))
        guard declaredLength == responseBody.count else {
            logger.error(
                "executor=python-bridge-invalid-frame reason=length-mismatch declared-bytes=\(declaredLength, privacy: .public) actual-bytes=\(responseBody.count, privacy: .public)"
            )
            throw KernelWorkspaceServiceError.pythonBridgeFailed
        }
        guard let reply = KernelWorkspaceXPC.decode(
            responseBody,
            requestID: requestID,
            protocolVersion: KernelWorkspaceXPC.operationProtocolVersion
        ) else {
            Self.logInvalidBridgeEnvelope(
                responseBody,
                requestID: requestID,
                protocolVersion: KernelWorkspaceXPC.operationProtocolVersion
            )
            throw KernelWorkspaceServiceError.pythonBridgeFailed
        }
        if let code = reply.errorCode {
            // Keep the XPC surface small; the trusted bridge owns detailed codes.
            switch code {
            case "process_cancelled":
                throw KernelWorkspaceServiceError.processCancelled
            case "commit_rejected":
                throw KernelWorkspaceServiceError.commitRejected
            case "commit_outcome_uncertain":
                throw KernelWorkspaceServiceError.commitOutcomeUncertain
            case "kernel_timeout":
                throw KernelWorkspaceServiceError.kernelTimeout
            case "runner_failed":
                throw KernelWorkspaceServiceError.runnerFailed
            case "sandbox_unavailable":
                logger.error("executor=python-bridge-rejected category=sandbox-unavailable")
                throw KernelWorkspaceServiceError.sandboxUnavailable(nil)
            case let code where code.hasPrefix("sandbox_unavailable_"):
                let rawStage = String(code.dropFirst("sandbox_unavailable_".count))
                guard let stage = KernelWorkspaceSandboxDiagnosticStage(
                    rawValue: rawStage
                ) else {
                    logger.error("executor=python-bridge-unclassified-error")
                    throw KernelWorkspaceServiceError.pythonBridgeFailed
                }
                logger.error(
                    "executor=python-bridge-rejected category=sandbox-unavailable stage=\(stage.rawValue, privacy: .public)"
                )
                throw KernelWorkspaceServiceError.sandboxUnavailable(stage)
            case let code where code == "workspace_rejected"
                || code.hasPrefix("workspace_rejected_"):
                logger.error("executor=python-bridge-rejected category=workspace")
                throw KernelWorkspaceServiceError.workspaceRejected
            case let code where Self.pluginLifecycleErrorCodes.contains(code)
                || code.hasPrefix("activation_")
                || code.hasPrefix("approval_")
                || code.hasPrefix("candidate_")
                || code == "invalid_rollback_target"
                || code == "invalid_time"
                || code == "manifest_rejected"
                || code == "no_active_candidate"
                || code == "plugin_lifecycle_failed"
                || code == "plugin_source_rejected"
                || code == "stale_approval"
                || code == "store_unavailable":
                throw KernelWorkspaceServiceError.pluginLifecycleRejected(code)
            case let code where code.hasPrefix("kernel_")
                || code.hasPrefix("snapshot_broker_"):
                logger.error(
                    "executor=python-bridge-failed category=kernel-or-broker code=\(code, privacy: .public)"
                )
                throw KernelWorkspaceServiceError.pythonBridgeFailed
            default:
                logger.error("executor=python-bridge-unclassified-error")
                throw KernelWorkspaceServiceError.pythonBridgeFailed
            }
        }
        guard let output = reply.output else {
            logger.error("executor=python-bridge-output-missing")
            throw KernelWorkspaceServiceError.pythonBridgeFailed
        }
        do {
            switch outputKind {
            case .workspace:
                try validateResult(output)
            case .lifecycle:
                try validateLifecycleResult(output)
            case .evolutionSource:
                try validateEvolutionSourceResult(output)
            case .pluginEvaluation:
                try validatePluginEvaluationResult(output)
            }
        } catch {
            logger.error("executor=python-bridge-output-invalid")
            throw KernelWorkspaceServiceError.pythonBridgeFailed
        }
        return output
    }

    private static func logBridgeFailure(_ error: Error) {
        let failure = error as NSError
        guard failure.domain == NSPOSIXErrorDomain else {
            logger.error("executor=python-bridge-failed category=other")
            return
        }
        logger.error(
            "executor=python-bridge-failed category=posix code=\(failure.code, privacy: .public)"
        )
    }

    private static func logInvalidBridgeEnvelope(
        _ body: Data,
        requestID: KernelWorkspaceXPC.RequestID,
        protocolVersion: Int
    ) {
        guard let object = try? JSONSerialization.jsonObject(with: body),
              let envelope = object as? [String: Any]
        else {
            logger.error(
                "executor=python-bridge-invalid-envelope reason=non-json body-bytes=\(body.count, privacy: .public)"
            )
            return
        }
        let versionMatches = (envelope["version"] as? Int)
            == protocolVersion
        let requestIDMatches = (envelope["request_id"] as? String)
            == requestID.token
        logger.error(
            "executor=python-bridge-invalid-envelope version-match=\(versionMatches, privacy: .public) request-id-match=\(requestIDMatches, privacy: .public) body-bytes=\(body.count, privacy: .public)"
        )
    }

    private static func snapshotBrokerFailureCode(
        for error: Error
    ) -> SnapshotBrokerFailureCode {
        guard let error = error as? KernelSnapshotBrokerClientError else {
            return .operationFailed
        }
        switch error {
        case .missingServiceConfiguration:
            return .configurationMissing
        case .invalidPeerRequirement:
            return .peerAuthenticationFailed
        case .connectionFailed:
            return .connectionFailed
        case .invalidProxy:
            return .protocolFailed
        case .brokerRejected(let code):
            switch code {
            case "operation_busy": return .busy
            case "invalid_request": return .rejected
            case "cancelled", "broker_failed": return .operationFailed
            default: return .protocolFailed
            }
        case .invalidLease:
            return .invalidLease
        case .releaseFailed:
            return .releaseFailed
        case .timedOut:
            return .timedOut
        }
    }

    private static func pythonBundle() throws -> (executable: URL, resources: URL) {
        guard let version = Bundle.main.object(
            forInfoDictionaryKey: "KhaosPythonVersion"
        ) as? String,
        version.range(of: #"^\d+\.\d+$"#, options: .regularExpression) != nil
        else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(ENOEXEC))
        }
        let contents = Bundle.main.bundleURL.appendingPathComponent("Contents")
        let pythonHome = contents
            .appendingPathComponent("Frameworks/Python.framework/Versions")
            .appendingPathComponent(version)
        let executable = pythonHome
            .appendingPathComponent("bin")
            .appendingPathComponent("python\(version)")
        let resources = contents.appendingPathComponent("Resources")
        let bridge = resources
            .appendingPathComponent("khaos/kernel/workspace_xpc_bridge.py")
        guard FileManager.default.isExecutableFile(atPath: executable.path),
              FileManager.default.fileExists(atPath: bridge.path)
        else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(ENOENT))
        }
        return (executable, resources)
    }

    private static func runBridge(
        bundle: (executable: URL, resources: URL),
        workspace: URL,
        rootDescriptor: Int32,
        invocation: Data,
        snapshotLease: KernelSnapshotBrokerLease?,
        pluginStoreRoot: String,
        pluginStateRoot: String,
        cancellation: WorkspaceCancellationSignal
    ) throws -> Data {
        let input = Pipe()
        let output = Pipe()
        let inputRead = Int32(input.fileHandleForReading.fileDescriptor)
        let inputWrite = Int32(input.fileHandleForWriting.fileDescriptor)
        let outputRead = Int32(output.fileHandleForReading.fileDescriptor)
        let outputWrite = Int32(output.fileHandleForWriting.fileDescriptor)
        let nullDescriptor = Darwin.open("/dev/null", O_WRONLY | O_CLOEXEC)
        guard nullDescriptor >= 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }
        defer { _ = Darwin.close(nullDescriptor) }

        let sourceDescriptors = [
            rootDescriptor,
            cancellation.readDescriptor,
            cancellation.writeDescriptor,
            inputRead,
            inputWrite,
            outputRead,
            outputWrite,
            nullDescriptor,
        ]
        guard sourceDescriptors.allSatisfy({ $0 > STDERR_FILENO }),
              Set(sourceDescriptors).count == sourceDescriptors.count
        else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(EBADF))
        }
        let rootChildDescriptor = sourceDescriptors.max()! + 1
        let cancellationChildDescriptor = rootChildDescriptor + 1

        var actions: posix_spawn_file_actions_t? = nil
        var status = posix_spawn_file_actions_init(&actions)
        guard status == 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(status))
        }
        defer { posix_spawn_file_actions_destroy(&actions) }

        func add(_ result: Int32) throws {
            guard result == 0 else {
                throw NSError(domain: NSPOSIXErrorDomain, code: Int(result))
            }
        }
        // Close every inherited descriptor by default; dup2 below is the full child allowlist.
        try add(posix_spawn_file_actions_adddup2(
            &actions,
            rootDescriptor,
            rootChildDescriptor
        ))
        try add(posix_spawn_file_actions_adddup2(
            &actions,
            cancellation.readDescriptor,
            cancellationChildDescriptor
        ))
        try add(posix_spawn_file_actions_adddup2(&actions, inputRead, STDIN_FILENO))
        try add(posix_spawn_file_actions_adddup2(&actions, outputWrite, STDOUT_FILENO))
        try add(posix_spawn_file_actions_adddup2(&actions, nullDescriptor, STDERR_FILENO))
        for descriptor in sourceDescriptors {
            try add(posix_spawn_file_actions_addclose(&actions, descriptor))
        }

        let bootstrap = "import sys; sys.path.insert(0, sys.argv[1]); "
            + "from khaos.kernel.workspace_xpc_bridge import main; "
            + "raise SystemExit(main())"
        let argumentValues = [
            bundle.executable.path,
            "-I",
            "-S",
            "-B",
            "-c",
            bootstrap,
            bundle.resources.path,
            workspace.path,
            String(rootChildDescriptor),
            String(cancellationChildDescriptor),
        ]
        var arguments = try KernelCStringArray.create(argumentValues)
        defer { KernelCStringArray.release(arguments) }
        var environmentValues = [
            "PATH=/usr/bin:/bin:/usr/sbin:/sbin",
            "KHAOS_PLUGIN_STORE_PATH=\(pluginStoreRoot)",
            "KHAOS_PLUGIN_STATE_PATH=\(pluginStateRoot)",
            "PYTHONDONTWRITEBYTECODE=1",
        ]
        if let snapshotLease {
            environmentValues.append(contentsOf: [
                "TMPDIR=\(snapshotLease.temporaryDirectory.path)",
                "KHAOS_SNAPSHOT_MOUNT_PATH=\(snapshotLease.mountPath.path)",
                "KHAOS_SNAPSHOT_STORAGE_BYTES=\(snapshotStorageBytes)",
            ])
        }
        var environment = try KernelCStringArray.create(environmentValues)
        defer { KernelCStringArray.release(environment) }

        var attributes: posix_spawnattr_t? = nil
        status = posix_spawnattr_init(&attributes)
        guard status == 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(status))
        }
        defer { posix_spawnattr_destroy(&attributes) }
        try add(posix_spawnattr_setpgroup(&attributes, 0))
        try add(posix_spawnattr_setflags(
            &attributes,
            Int16(POSIX_SPAWN_SETPGROUP | POSIX_SPAWN_CLOEXEC_DEFAULT)
        ))

        var processID: pid_t = 0
        status = bundle.executable.path.withCString { path in
            arguments.withUnsafeMutableBufferPointer { argv in
                environment.withUnsafeMutableBufferPointer { envp in
                    posix_spawn(
                        &processID,
                        path,
                        &actions,
                        &attributes,
                        argv.baseAddress!,
                        envp.baseAddress!
                    )
                }
            }
        }
        guard status == 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(status))
        }

        output.fileHandleForWriting.closeFile()
        let inputFlags = fcntl(inputWrite, F_GETFL)
        let outputFlags = fcntl(outputRead, F_GETFL)
        guard inputFlags >= 0, outputFlags >= 0,
              fcntl(inputWrite, F_SETFL, inputFlags | O_NONBLOCK) == 0,
              fcntl(outputRead, F_SETFL, outputFlags | O_NONBLOCK) == 0
        else {
            stop(processID, cancellation: cancellation)
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }

        var reaped = false
        var inputWriterClosed = false
        var childStatus: Int32 = 0
        defer {
            if !reaped {
                stop(processID, cancellation: cancellation)
            }
            input.fileHandleForReading.closeFile()
            if !inputWriterClosed {
                input.fileHandleForWriting.closeFile()
            }
            output.fileHandleForReading.closeFile()
        }

        try writeAll(invocation, descriptor: inputWrite, deadline: Date().addingTimeInterval(5))
        input.fileHandleForWriting.closeFile()
        inputWriterClosed = true

        let readResult = try readAll(
            descriptor: outputRead,
            processID: processID,
            childStatus: &childStatus
        )
        reaped = true
        guard childStatus == 0 else {
            logger.error(
                "executor=python-bridge-child-exit wait-status=\(childStatus, privacy: .public)"
            )
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(ECHILD))
        }
        return readResult
    }

    private static func workspaceCaseSensitivity(
        _ workspace: URL,
        cancellation: WorkspaceCancellationSignal
    ) throws -> Bool {
        guard !cancellation.isRequested else {
            throw KernelWorkspaceServiceError.processCancelled
        }
        do {
            let resourceValues = try workspace.resourceValues(
                forKeys: [.volumeSupportsCaseSensitiveNamesKey]
            )
            guard let caseSensitive = resourceValues.volumeSupportsCaseSensitiveNames else {
                throw KernelWorkspaceServiceError.workspaceRejected
            }
            guard !cancellation.isRequested else {
                throw KernelWorkspaceServiceError.processCancelled
            }
            return caseSensitive
        } catch let error as KernelWorkspaceServiceError {
            throw error
        } catch {
            throw KernelWorkspaceServiceError.workspaceRejected
        }
    }

    private static func writeAll(
        _ data: Data,
        descriptor: Int32,
        deadline: Date
    ) throws {
        var offset = 0
        while offset < data.count {
            guard Date() < deadline else {
                throw NSError(domain: NSPOSIXErrorDomain, code: Int(ETIMEDOUT))
            }
            var event = pollfd(fd: descriptor, events: Int16(POLLOUT), revents: 0)
            let ready = poll(&event, 1, 100)
            if ready < 0 && errno == EINTR { continue }
            guard ready >= 0 else {
                throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
            }
            guard ready > 0 else { continue }
            let count = data.withUnsafeBytes { buffer -> Int in
                guard let base = buffer.baseAddress else { return -1 }
                return Darwin.write(
                    descriptor,
                    base.advanced(by: offset),
                    data.count - offset
                )
            }
            if count > 0 {
                offset += count
            } else if count < 0 && (errno == EINTR || errno == EAGAIN) {
                continue
            } else {
                throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
            }
        }
    }

    private static func readAll(
        descriptor: Int32,
        processID: pid_t,
        childStatus: inout Int32
    ) throws -> Data {
        var result = Data()
        var reaped = false
        var eof = false
        let deadline = Date().addingTimeInterval(operationDeadlineSeconds)
        while !eof {
            guard Date() < deadline else {
                throw NSError(domain: NSPOSIXErrorDomain, code: Int(ETIMEDOUT))
            }
            var event = pollfd(
                fd: descriptor,
                events: Int16(POLLIN | POLLHUP),
                revents: 0
            )
            let ready = poll(&event, 1, 100)
            if ready < 0 && errno == EINTR { continue }
            guard ready >= 0 else {
                throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
            }
            if ready > 0 {
                while true {
                    var chunk = [UInt8](repeating: 0, count: 8192)
                    let count = Darwin.read(descriptor, &chunk, chunk.count)
                    if count > 0 {
                        guard result.count + count <= maximumProcessFrameBytes else {
                            throw NSError(domain: NSPOSIXErrorDomain, code: Int(EMSGSIZE))
                        }
                        result.append(contentsOf: chunk.prefix(count))
                    } else if count == 0 {
                        eof = true
                        break
                    } else if errno == EINTR {
                        continue
                    } else if errno == EAGAIN || errno == EWOULDBLOCK {
                        break
                    } else {
                        throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
                    }
                }
            }
            if !reaped {
                let waited = waitpid(processID, &childStatus, WNOHANG)
                if waited == processID {
                    reaped = true
                } else if waited < 0 && errno != EINTR {
                    throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
                }
            }
        }
        if !reaped {
            var waited: pid_t
            repeat {
                waited = waitpid(processID, &childStatus, 0)
            } while waited < 0 && errno == EINTR
            guard waited == processID else {
                throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
            }
        }
        return result
    }

    private static func stop(
        _ processID: pid_t,
        cancellation: WorkspaceCancellationSignal
    ) {
        _ = cancellation.request()
        _ = kill(-processID, SIGINT)
        let deadline = Date().addingTimeInterval(5)
        while Date() < deadline {
            var status: Int32 = 0
            let result = waitpid(processID, &status, WNOHANG)
            if result == processID || (result < 0 && errno == ECHILD) { return }
            usleep(50_000)
        }
        _ = kill(-processID, SIGKILL)
        var status: Int32 = 0
        while waitpid(processID, &status, 0) < 0 && errno == EINTR {}
    }

    private static let workspaceResultKeys: Set<String> = [
        "returncode", "stdout", "stderr", "added", "modified", "deleted",
    ]

    private static func validatedWorkspaceResult(
        _ output: String,
        additionalKeys: Set<String> = []
    ) throws -> [String: Any] {
        guard let data = output.data(using: .utf8),
              let value = try? JSONSerialization.jsonObject(with: data),
              let result = value as? [String: Any],
              Set(result.keys) == workspaceResultKeys.union(additionalKeys),
              let returncode = integer(result["returncode"]),
              let stdout = result["stdout"] as? String,
              let stderr = result["stderr"] as? String,
              let added = integer(result["added"]), added >= 0,
              let modified = integer(result["modified"]), modified >= 0,
              let deleted = integer(result["deleted"]), deleted >= 0,
              returncode >= Int(Int32.min), returncode <= Int(Int32.max),
              stdout.utf8.count <= KernelWorkspaceXPC.maximumMessageBytes,
              stderr.utf8.count <= KernelWorkspaceXPC.maximumMessageBytes
        else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(EPROTO))
        }
        return result
    }

    private static func validateResult(_ output: String) throws {
        _ = try validatedWorkspaceResult(output)
    }

    private static func validatePluginEvaluationResult(_ output: String) throws {
        let result = try validatedWorkspaceResult(
            output,
            additionalKeys: ["plugin_state_sha256"]
        )
        guard let stateDigest = result["plugin_state_sha256"] as? String,
              stateDigest.range(
                of: #"^[0-9a-f]{64}$"#,
                options: .regularExpression
              ) != nil else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(EPROTO))
        }
    }

    private static func validateLifecycleResult(_ output: String) throws {
        guard let data = output.data(using: .utf8),
              data.count <= KernelWorkspaceXPC.maximumMessageBytes,
              let result = try? JSONSerialization.jsonObject(with: data)
                as? [String: Any]
        else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(EPROTO))
        }
        if Set(result.keys) == ["candidate", "generation"],
           let candidate = result["candidate"] as? [String: Any],
           let generation = integer(result["generation"]), generation >= 0,
           validCandidateSummary(candidate, activation: false) {
            return
        }
        guard Set(result.keys) == ["active", "previous", "generation"],
              let generation = integer(result["generation"]), generation >= 0,
              validSlot(result["active"]), validSlot(result["previous"]) else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(EPROTO))
        }
    }

    private static func validateEvolutionSourceResult(_ output: String) throws {
        guard let data = output.data(using: .utf8),
              data.count <= KernelWorkspaceXPC.maximumMessageBytes,
              let result = try? JSONSerialization.jsonObject(with: data)
                as? [String: Any],
              Set(result.keys) == [
                "candidate_digest", "generation", "manifest_base64", "source_base64",
              ],
              let candidateDigest = result["candidate_digest"] as? String,
              candidateDigest.range(
                of: #"^[0-9a-f]{64}$"#,
                options: .regularExpression
              ) != nil,
              let generation = integer(result["generation"]), generation >= 0,
              boundedUTF8Base64(result["manifest_base64"], maximumBytes: 4_096) != nil,
              boundedUTF8Base64(result["source_base64"], maximumBytes: 10_240) != nil
        else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(EPROTO))
        }
    }

    private static func boundedUTF8Base64(
        _ value: Any?,
        maximumBytes: Int
    ) -> Data? {
        guard let encoded = value as? String,
              let data = Data(base64Encoded: encoded),
              !data.isEmpty,
              data.count <= maximumBytes,
              data.base64EncodedString() == encoded,
              String(data: data, encoding: .utf8) != nil else {
            return nil
        }
        return data
    }

    private static func validSlot(_ value: Any?) -> Bool {
        if value is NSNull { return true }
        guard let slot = value as? [String: Any] else { return false }
        return validCandidateSummary(slot, activation: true)
    }

    private static func validCandidateSummary(
        _ value: [String: Any],
        activation: Bool
    ) -> Bool {
        let candidateKeys: Set<String> = [
            "plugin_id", "candidate_digest", "manifest_digest", "scope_digest",
            "process_exec", "read_scope", "write_scope", "agent_interface",
        ]
        let activationKeys = candidateKeys.union([
            "slot", "approved_at", "expires_at", "approval_validity_seconds",
        ])
        guard Set(value.keys) == (activation ? activationKeys : candidateKeys),
              let pluginID = value["plugin_id"] as? String,
              pluginID.range(of: #"^[a-z][a-z0-9-]{0,63}$"#, options: .regularExpression) != nil,
              ["candidate_digest", "manifest_digest", "scope_digest"].allSatisfy({ key in
                  guard let digest = value[key] as? String else { return false }
                  return digest.range(of: #"^[0-9a-f]{64}$"#, options: .regularExpression) != nil
              }),
              let process = value["process_exec"] as? NSNumber,
              CFGetTypeID(process) == CFBooleanGetTypeID(),
              let readScope = value["read_scope"] as? [String],
              let writeScope = value["write_scope"] as? [String],
              let agentInterface = value["agent_interface"],
              validAgentInterface(agentInterface),
              readScope.count + writeScope.count <= 8,
              (readScope + writeScope).allSatisfy({ !$0.isEmpty && !$0.contains("\0") }),
              agentInterface is NSNull
                || (!process.boolValue && readScope.isEmpty && writeScope.isEmpty)
        else {
            return false
        }
        guard activation else { return true }
        guard value["slot"] as? String == "primary",
              let approvedAt = integer(value["approved_at"]), approvedAt >= 0,
              let expiresAt = integer(value["expires_at"]),
              expiresAt - approvedAt == 30 * 24 * 60 * 60,
              integer(value["approval_validity_seconds"]) == 30 * 24 * 60 * 60
        else {
            return false
        }
        return true
    }

    private static func validAgentInterface(_ value: Any) -> Bool {
        if value is NSNull { return true }
        guard let interface = value as? [String: Any],
              Set(interface.keys) == ["summary", "operations"],
              let summary = interface["summary"] as? String,
              !summary.isEmpty,
              summary.utf8.count <= maximumAgentInterfaceSummaryBytes,
              let operations = interface["operations"] as? [[String: Any]],
              (1...maximumAgentInterfaceOperations).contains(operations.count),
              let encoded = try? JSONSerialization.data(
                withJSONObject: interface,
                options: [.sortedKeys, .withoutEscapingSlashes]
              ),
              encoded.count <= maximumAgentInterfaceBytes else {
            return false
        }

        var operationNames = Set<String>()
        for operation in operations {
            guard Set(operation.keys) == ["name", "fields"],
                  let name = operation["name"] as? String,
                  validAgentInterfaceName(name),
                  operationNames.insert(name).inserted,
                  let fields = operation["fields"] as? [String],
                  fields.count <= maximumAgentInterfaceFields,
                  fields.allSatisfy({
                    $0 != "operation" && validAgentInterfaceName($0)
                  }),
                  Set(fields).count == fields.count else {
                return false
            }
        }
        return true
    }

    private static func validAgentInterfaceName(_ value: String) -> Bool {
        value.range(
            of: #"^[a-z][a-z0-9_]{0,63}$"#,
            options: .regularExpression
        ) != nil
    }

    private static func integer(_ value: Any?) -> Int? {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.rounded(.towardZero) == number.doubleValue
        else {
            return nil
        }
        return number.intValue
    }

    private static func readUInt32(_ data: Data) -> UInt32 {
        data.prefix(4).reduce(UInt32(0)) { ($0 << 8) | UInt32($1) }
    }

}
