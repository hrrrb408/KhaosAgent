import CoreFoundation
import Darwin
import Foundation
import OSLog

/// Fixed trusted executor. The XPC caller cannot choose the runtime or
/// inherit raw host descriptors.
enum KernelWorkspacePythonExecutor {
    private static let maximumProcessFrameBytes =
        KernelWorkspaceXPC.maximumMessageBytes + KernelWorkspaceXPC.transferLengthBytes
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
        guard let snapshotBrokerEndpoint = invocation.snapshotBrokerEndpoint else {
            throw KernelWorkspaceServiceError.snapshotBrokerUnavailable(
                .configurationMissing
            )
        }
        let bundle: (executable: URL, resources: URL)
        do {
            bundle = try pythonBundle()
        } catch {
            throw KernelWorkspaceServiceError.pythonRuntimeUnavailable
        }
        let access: (value: Data, stale: Bool, refreshed: Bool)
        do {
            access = try KernelWorkspaceRoot.withScopedBookmark(invocation.bookmark) {
                workspace, rootDescriptor, activeBookmark in
                do {
                    guard !cancellation.isRequested else {
                        throw KernelWorkspaceServiceError.processCancelled
                    }
                    let bridgeInput = try KernelWorkspaceXPC.encodeBridgeInput(
                        request: invocation.request,
                        requestID: invocation.requestID,
                        bookmark: activeBookmark
                    )
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
        guard access.value.count >= KernelWorkspaceXPC.transferLengthBytes else {
            logger.error(
                "executor=python-bridge-invalid-frame reason=short actual-bytes=\(access.value.count, privacy: .public)"
            )
            throw KernelWorkspaceServiceError.pythonBridgeFailed
        }
        let responseBody = Data(
            access.value.dropFirst(KernelWorkspaceXPC.transferLengthBytes)
        )
        let declaredLength = Int(readUInt32(access.value))
        guard declaredLength == responseBody.count else {
            logger.error(
                "executor=python-bridge-invalid-frame reason=length-mismatch declared-bytes=\(declaredLength, privacy: .public) actual-bytes=\(responseBody.count, privacy: .public)"
            )
            throw KernelWorkspaceServiceError.pythonBridgeFailed
        }
        guard let reply = KernelWorkspaceXPC.decode(
            responseBody,
            requestID: invocation.requestID,
            protocolVersion: KernelWorkspaceXPC.operationProtocolVersion
        ) else {
            Self.logInvalidBridgeEnvelope(
                responseBody,
                requestID: invocation.requestID,
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
            try validateResult(output)
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
        snapshotLease: KernelSnapshotBrokerLease,
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
        // Reuse the container temp root where this request's Broker storage was created.
        var environment = try KernelCStringArray.create([
            "PATH=/usr/bin:/bin:/usr/sbin:/sbin",
            "TMPDIR=\(snapshotLease.temporaryDirectory.path)",
            "KHAOS_SNAPSHOT_MOUNT_PATH=\(snapshotLease.mountPath.path)",
            "KHAOS_SNAPSHOT_STORAGE_BYTES=\(snapshotStorageBytes)",
            "PYTHONDONTWRITEBYTECODE=1",
        ])
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

    private static func validateResult(_ output: String) throws {
        guard let data = output.data(using: .utf8),
              let value = try? JSONSerialization.jsonObject(with: data),
              let result = value as? [String: Any],
              Set(result.keys) == [
                "returncode", "stdout", "stderr", "added", "modified", "deleted",
              ],
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
