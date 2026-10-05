import Darwin
import Foundation

private enum KernelService {
    case execution
    case production

    func serviceName(bundleID: String) -> String {
        switch self {
        case .execution:
            return "\(bundleID).KernelExecution"
        case .production:
            return "\(bundleID).KernelProduction"
        }
    }

    var peerRequirementKey: String {
        switch self {
        case .execution:
            return "KhaosKernelExecutionServiceRequirement"
        case .production:
            return "KhaosKernelProductionServiceRequirement"
        }
    }
}

@main
struct WorkspaceGrant {
    static func main() {
        do {
            try run()
        } catch {
            FileHandle.standardError.write(Data("workspace-grant-error: \(error)\n".utf8))
            exit(2)
        }
    }

    private static func run() throws {
        guard CommandLine.arguments.count >= 3 else {
            throw ProbeError.invalidArguments
        }
        let bundleID = CommandLine.arguments[1]
        guard !bundleID.isEmpty else {
            throw ProbeError.invalidArguments
        }

        if CommandLine.arguments[2] == "--untrusted-host-bootstrap-check" {
            guard CommandLine.arguments.count == 4 else {
                throw ProbeError.invalidArguments
            }
            let result = try WorkspaceGrantHostClient.checkWorkspaceWrite(
                serviceName: "\(bundleID).UntrustedHost",
                path: CommandLine.arguments[3],
                kernelServiceName: "\(bundleID).KernelProduction"
            )
            guard result.contains("untrusted-xpc-container-write=allowed"),
                  result.contains("untrusted-xpc-kernel-bootstrap=peer=connection-invalidated")
            else {
                throw ProbeError.clientFailed(
                    "sandboxed sibling XPC obtained the Kernel bootstrap: \(result)"
                )
            }
            FileHandle.standardOutput.write(
                Data("\(result)\nuntrusted-host-kernel-bootstrap=denied\n".utf8)
            )
            return
        }
        if CommandLine.arguments[2] == "--production-app-container-workspace-check" {
            let evidence = try runProductionAppContainerWorkspaceCheck(bundleID: bundleID)
            FileHandle.standardOutput.write(Data("\(evidence)\n".utf8))
            return
        }
        if CommandLine.arguments[2] == "--production-bootstrap-check" {
            let evidence = try runProductionBootstrapCheck(bundleID: bundleID)
            FileHandle.standardOutput.write(Data("\(evidence)\n".utf8))
            return
        }
        if CommandLine.arguments[2] == "--production-missing-broker-check" {
            guard CommandLine.arguments.count == 4,
                  Bundle.main.bundleIdentifier == bundleID
            else {
                throw ProbeError.invalidArguments
            }
            let evidence = try runProductionMissingBrokerCheck(
                bundleID: bundleID,
                hostFallbackCanaryPath: CommandLine.arguments[3]
            )
            FileHandle.standardOutput.write(Data("\(evidence)\n".utf8))
            return
        }
        if CommandLine.arguments[2] == "--client-peer-identity-check" {
            guard CommandLine.arguments.count == 4 else {
                throw ProbeError.invalidArguments
            }
            let evidence = try rejectMisidentifiedKernelService(
                bundleID: bundleID,
                outsidePath: CommandLine.arguments[3]
            )
            FileHandle.standardOutput.write(Data("\(evidence)\n".utf8))
            return
        }
        if CommandLine.arguments[2] == "--relay-peer-check" {
            try runRelayedPeerCheck(bundleID: bundleID)
            return
        }
        throw ProbeError.invalidArguments
    }

    private static func submitWorkspaceCommand(
        endpoint: KernelWorkspaceTarget,
        request: KernelWorkspaceXPC.WorkspaceRunRequest,
        bookmark: Data,
        snapshotBrokerEndpoint: NSXPCListenerEndpoint? = nil
    ) throws -> KernelWorkspaceXPC.Reply {
        let requestID = KernelWorkspaceXPC.newRequestID()
        return try requestWorkspaceReply(
            endpoint: endpoint,
            requestID: requestID,
            snapshotBrokerEndpoint: snapshotBrokerEndpoint
        ) {
            proxy, withReply in
            try KernelWorkspaceXPC.submit(
                proxy,
                requestID: requestID,
                request: request,
                bookmark: bookmark,
                withReply: withReply
            )
        }
    }

    private static func runProductionBootstrapCheck(bundleID: String) throws -> String {
        let endpoint = try kernelEndpoint(bundleID: bundleID, service: .production)
        try requireIdleCancellation(endpoint: endpoint)
        let digestEvidence = try rejectMismatchedRunnerSourceDigest(endpoint: endpoint)
        let duplicateFieldEvidence = try rejectDuplicateJSONObjectFields(endpoint: endpoint)
        let nestingEvidence = try rejectExcessiveJSONNesting(endpoint: endpoint)
        let scopeEvidence = try rejectMalformedWorkspaceScopes(endpoint: endpoint)
        let authorityFieldEvidence = try rejectCallerSuppliedAuthorityFields(
            endpoint: endpoint
        )
        try requireIdleCancellation(endpoint: endpoint)
        return [
            "production-xpc-bootstrap=authenticated",
            digestEvidence,
            duplicateFieldEvidence,
            nestingEvidence,
            scopeEvidence,
            authorityFieldEvidence,
            "production-xpc-after-invalid-requests=responsive",
        ].joined(separator: "\n")
    }

    private static func runProductionMissingBrokerCheck(
        bundleID: String,
        hostFallbackCanaryPath: String
    ) throws -> String {
        let endpoint = try kernelEndpoint(bundleID: bundleID, service: .production)
        let runnerSource = productionCommandRunner(
            argv: ["/usr/bin/touch", hostFallbackCanaryPath]
        )
        let request = KernelWorkspaceXPC.WorkspaceRunRequest(
            timeoutSeconds: 5,
            runnerSource: runnerSource,
            runnerSourceSHA256: KernelWorkspaceXPC.runnerSourceSHA256(runnerSource),
            workspaceReadScope: []
        )
        let reply = try submitWorkspaceCommand(
            endpoint: endpoint,
            request: request,
            bookmark: Data("invalid-test-bookmark".utf8)
        )
        guard reply.errorCode == "snapshot_broker_not_configured",
              reply.output == nil,
              reply.cancellationAccepted == nil
        else {
            throw ProbeError.clientFailed(
                "missing Broker did not reject before Runner execution: "
                    + (reply.errorCode ?? reply.output ?? "empty reply")
            )
        }
        return "production-xpc-missing-broker=snapshot_broker_not_configured"
    }

    private static func requireIdleCancellation(
        endpoint: KernelWorkspaceTarget
    ) throws {
        let requestID = KernelWorkspaceXPC.newRequestID()
        let reply = try requestWorkspaceReply(
            endpoint: endpoint,
            requestID: requestID
        ) { proxy, withReply in
            proxy.cancelWorkspaceCommand(
                KernelWorkspaceXPC.version,
                requestIDHigh: requestID.high,
                requestIDLow: requestID.low,
                withReply: withReply
            )
        }
        guard reply.errorCode == "process_not_active",
              reply.output == nil,
              reply.cancellationAccepted == nil
        else {
            throw ProbeError.clientFailed(
                "production XPC service did not answer an idle cancellation"
            )
        }
    }

    private static func rejectMismatchedRunnerSourceDigest(
        endpoint: KernelWorkspaceTarget
    ) throws -> String {
        guard KernelWorkspaceXPC.runnerSourceSHA256("abc")
                == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        else {
            throw ProbeError.clientFailed("SHA-256 known-vector check failed")
        }

        let requestID = KernelWorkspaceXPC.newRequestID()
        let source = "def run():\n    return 0\n"
        let requestFrame = try WorkspaceProbeRequest.rawWorkspaceRequestFrame(
            requestID: requestID,
            payload: [
                "timeout_seconds": 5,
                "runner_source": source,
                "runner_source_sha256": String(repeating: "0", count: 64),
                "workspace_read_scope": [],
                "workspace_write_scope": [],
            ]
        )
        try rejectUnbookmarkedWorkspaceRequest(
            endpoint: endpoint,
            requestID: requestID,
            requestFrame: requestFrame,
            attack: "a Runner source with a mismatched SHA-256"
        )
        return "production-xpc-runner-source-digest=mismatch-rejected-before-bookmark"
    }

    private static func rejectDuplicateJSONObjectFields(
        endpoint: KernelWorkspaceTarget
    ) throws -> String {
        let source = "def run():\n    return 0\n"
        let attacks = [
            (
                "a request with an exact duplicate JSON field",
                "\"workspace_read_scope\":[],\"workspace_read_scope\":[]"
            ),
            (
                "a request with an escaped duplicate JSON field",
                "\"workspace_read_scope\":[],\"\\u0077orkspace_read_scope\":[]"
            ),
        ]
        for (attack, duplicateField) in attacks {
            let requestID = KernelWorkspaceXPC.newRequestID()
            let request = KernelWorkspaceXPC.WorkspaceRunRequest(
                timeoutSeconds: 5,
                runnerSource: source,
                runnerSourceSHA256: KernelWorkspaceXPC.runnerSourceSHA256(source),
                workspaceReadScope: []
            )
            let validFrame = try request.encodeFrame(requestID: requestID)
            let validBody = Data(
                validFrame.dropFirst(KernelWorkspaceXPC.transferLengthBytes)
            )
            guard let body = String(data: validBody, encoding: .utf8),
                  let scopeField = body.range(of: "\"workspace_read_scope\":[]")
            else {
                throw ProbeError.clientFailed("could not prepare duplicate-key request")
            }
            let duplicateBody = body.replacingCharacters(
                in: scopeField,
                with: duplicateField
            )
            let requestFrame = try WorkspaceProbeRequest.rawJSONWorkspaceRequestFrame(
                body: Data(duplicateBody.utf8)
            )
            try rejectUnbookmarkedWorkspaceRequest(
                endpoint: endpoint,
                requestID: requestID,
                requestFrame: requestFrame,
                attack: attack
            )
        }
        return "production-xpc-json-duplicate-field=exact-and-escaped-alias-rejected-before-bookmark"
    }

    private static func rejectExcessiveJSONNesting(
        endpoint: KernelWorkspaceTarget
    ) throws -> String {
        let limit = KernelWorkspaceXPC.maximumJSONNestingDepth
        let withinLimit = Data(
            (String(repeating: "[", count: limit) + "0"
                + String(repeating: "]", count: limit)).utf8
        )
        let overLimit = Data(
            (String(repeating: "[", count: limit + 1) + "0"
                + String(repeating: "]", count: limit + 1)).utf8
        )
        let quotedDelimiters = Data(
            ("{\"source\":\"" + String(repeating: "[]{}", count: 64) + "\"}").utf8
        )
        guard KernelWorkspaceXPC.isJSONNestingWithinLimit(withinLimit),
              !KernelWorkspaceXPC.isJSONNestingWithinLimit(overLimit),
              KernelWorkspaceXPC.isJSONNestingWithinLimit(quotedDelimiters)
        else {
            throw ProbeError.clientFailed("JSON nesting guard boundary is invalid")
        }

        let requestID = KernelWorkspaceXPC.newRequestID()
        var nestedPayload: Any = 0
        for _ in 0...limit {
            nestedPayload = [nestedPayload]
        }
        let envelope: [String: Any] = [
            "version": KernelWorkspaceXPC.operationProtocolVersion,
            "request_id": requestID.token,
            "operation": "workspace.run",
            "payload": ["unexpected": nestedPayload],
        ]
        let body = try JSONSerialization.data(
            withJSONObject: envelope,
            options: [.sortedKeys]
        )
        let requestFrame = try WorkspaceProbeRequest.rawJSONWorkspaceRequestFrame(
            body: body
        )
        try rejectUnbookmarkedWorkspaceRequest(
            endpoint: endpoint,
            requestID: requestID,
            requestFrame: requestFrame,
            attack: "an over-depth JSON request"
        )
        return "production-xpc-json-nesting=over-limit-rejected"
    }

    private static func rejectMalformedWorkspaceScopes(
        endpoint: KernelWorkspaceTarget
    ) throws -> String {
        let source = "def run():\n    return 0\n"
        let digest = KernelWorkspaceXPC.runnerSourceSHA256(source)
        let attacks: [(String, [String], [String])] = [
            ("a traversal read scope", ["../outside"], []),
            ("an absolute write scope", [], ["/outside"]),
            ("an empty read-scope path", [""], []),
            ("a scope with an empty path component", ["inside//file"], []),
            ("a scope with a dot path component", [], ["inside/../outside"]),
            ("a NUL-containing scope path", ["input\0file"], []),
            (
                "a scope deeper than the ABI limit",
                [String(repeating: "x/", count: KernelWorkspaceXPC.maximumWorkspacePathDepth)
                    + "leaf"],
                []
            ),
            (
                "a scope with too many paths",
                (0...KernelWorkspaceXPC.maximumWorkspaceScopePaths).map {
                    "file-\($0)"
                },
                []
            ),
            (
                "a scope over its byte budget",
                (0..<42).map {
                    "f\($0)-" + String(repeating: "x", count: 100)
                },
                []
            ),
            ("a duplicated write-scope path", [], ["output.txt", "output.txt"]),
        ]

        for (attack, readScope, writeScope) in attacks {
            let requestID = KernelWorkspaceXPC.newRequestID()
            let requestFrame = try WorkspaceProbeRequest.rawWorkspaceRequestFrame(
                requestID: requestID,
                payload: [
                    "timeout_seconds": 5,
                    "runner_source": source,
                    "runner_source_sha256": digest,
                    "workspace_read_scope": readScope,
                    "workspace_write_scope": writeScope,
                ]
            )
            try rejectUnbookmarkedWorkspaceRequest(
                endpoint: endpoint,
                requestID: requestID,
                requestFrame: requestFrame,
                attack: attack
            )
        }
        return "production-xpc-workspace-scope=malformed-and-over-budget-rejected-before-bookmark"
    }

    private static func rejectCallerSuppliedAuthorityFields(
        endpoint: KernelWorkspaceTarget
    ) throws -> String {
        let source = "def run():\n    return 0\n"
        let fields: [(String, String, Any)] = [
            ("a self-asserted approval boolean", "approval", true),
            (
                "caller-supplied capability strings",
                "capabilities",
                ["filesystem.read", "filesystem.write"]
            ),
        ]
        for (attack, field, value) in fields {
            let requestID = KernelWorkspaceXPC.newRequestID()
            let payload: [String: Any] = [
                "timeout_seconds": 5,
                "runner_source": source,
                "runner_source_sha256": KernelWorkspaceXPC.runnerSourceSHA256(source),
                "workspace_read_scope": [],
                "workspace_write_scope": [],
                field: value,
            ]
            let requestFrame = try WorkspaceProbeRequest.rawWorkspaceRequestFrame(
                requestID: requestID,
                payload: payload
            )
            try rejectUnbookmarkedWorkspaceRequest(
                endpoint: endpoint,
                requestID: requestID,
                requestFrame: requestFrame,
                attack: attack
            )
        }
        return "production-xpc-authority-fields=approval-and-capability-claims-rejected-before-bookmark"
    }

    private static func rejectUnbookmarkedWorkspaceRequest(
        endpoint: KernelWorkspaceTarget,
        requestID: KernelWorkspaceXPC.RequestID,
        requestFrame: Data,
        attack: String
    ) throws {
        var descriptors: [Int32] = [-1, -1]
        guard socketpair(AF_UNIX, SOCK_STREAM, 0, &descriptors) == 0 else {
            throw ProbeError.clientFailed("invalid-request socketpair failed")
        }
        let reader = FileHandle(fileDescriptor: descriptors[0], closeOnDealloc: true)
        let writer = descriptors[1]
        defer {
            reader.closeFile()
            _ = Darwin.close(writer)
        }
        var noSignal: Int32 = 1
        guard setsockopt(
            writer,
            SOL_SOCKET,
            SO_NOSIGPIPE,
            &noSignal,
            socklen_t(MemoryLayout<Int32>.size)
        ) == 0 else {
            throw ProbeError.clientFailed("invalid-request socket setup failed")
        }

        var requestLength = UInt32(requestFrame.count).bigEndian
        var invocationPrefix = Data()
        withUnsafeBytes(of: &requestLength) {
            invocationPrefix.append(contentsOf: $0)
        }
        invocationPrefix.append(requestFrame)
        var offset = 0
        try invocationPrefix.withUnsafeBytes { bytes in
            guard let baseAddress = bytes.baseAddress else {
                throw ProbeError.clientFailed("invalid-request frame is empty")
            }
            while offset < bytes.count {
                let amount = Darwin.send(
                    writer,
                    baseAddress.advanced(by: offset),
                    bytes.count - offset,
                    0
                )
                if amount > 0 {
                    offset += amount
                } else if amount < 0 && errno == EINTR {
                    continue
                } else {
                    throw ProbeError.clientFailed("invalid-request frame write failed")
                }
            }
        }
        guard Darwin.shutdown(writer, SHUT_WR) == 0 else {
            throw ProbeError.clientFailed("invalid-request stream shutdown failed")
        }

        let reply = try requestWorkspaceReply(
            endpoint: endpoint,
            requestID: requestID
        ) { proxy, withReply in
            proxy.runWorkspaceCommand(
                KernelWorkspaceXPC.version,
                requestIDHigh: requestID.high,
                requestIDLow: requestID.low,
                invocationStream: reader,
                withReply: withReply
            )
        }
        guard reply.errorCode == "invalid_request",
              reply.output == nil,
              reply.cancellationAccepted == nil
        else {
            throw ProbeError.clientFailed(
                "Kernel did not reject \(attack) before bookmark handling"
            )
        }
    }

    private static func runProductionAppContainerWorkspaceCheck(
        bundleID: String
    ) throws -> String {
        let applicationSupport = try FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let root = applicationSupport.appendingPathComponent(
            "KhaosAppContainerWorkspace-\(UUID().uuidString)",
            isDirectory: true
        )
        let workspace = root.appendingPathComponent("workspace", isDirectory: true)
        try FileManager.default.createDirectory(
            at: workspace,
            withIntermediateDirectories: true
        )
        defer { try? FileManager.default.removeItem(at: root) }

        try Data("production-xpc-input".utf8).write(
            to: workspace.appendingPathComponent("production-input.txt")
        )
        let outputURL = workspace.appendingPathComponent("production-output.txt")
        let bypassURL = workspace.appendingPathComponent(
            "kernel-production-bypass.txt"
        )
        let runnerSource = "def run():\n    return 0\n"
        let request = KernelWorkspaceXPC.WorkspaceRunRequest(
            timeoutSeconds: 5,
            runnerSource: runnerSource,
            runnerSourceSHA256: KernelWorkspaceXPC.runnerSourceSHA256(runnerSource),
            workspaceReadScope: []
        )

        func requireRejectedWithoutWriteback(
            _ reply: KernelWorkspaceXPC.Reply,
            attempt: String
        ) throws {
            guard reply.errorCode == "workspace_rejected",
                  reply.output == nil,
                  try String(
                    contentsOf: workspace.appendingPathComponent(
                        "production-input.txt"
                    ),
                    encoding: .utf8
                  ) == "production-xpc-input",
                  !FileManager.default.fileExists(atPath: outputURL.path),
                  !FileManager.default.fileExists(atPath: bypassURL.path)
            else {
                throw ProbeError.clientFailed(
                    "Kernel accepted \(attempt) or changed its workspace"
                )
            }
        }

        let appContainerBookmark = try workspace.bookmarkData(
            options: [],
            includingResourceValuesForKeys: nil,
            relativeTo: nil
        )
        let endpoint = try kernelEndpoint(bundleID: bundleID, service: .production)
        let reply = try submitWorkspaceCommand(
            endpoint: endpoint,
            request: request,
            bookmark: appContainerBookmark
        )
        try requireRejectedWithoutWriteback(
            reply,
            attempt: "an unselected bookmark"
        )

        let appContainerScopedBookmark = try workspace.bookmarkData(
            options: [.withSecurityScope],
            includingResourceValuesForKeys: nil,
            relativeTo: nil
        )
        let scopedReply = try submitWorkspaceCommand(
            endpoint: endpoint,
            request: request,
            bookmark: appContainerScopedBookmark
        )
        try requireRejectedWithoutWriteback(
            scopedReply,
            attempt: "an app-container bookmark with a requested scope"
        )

        return [
            "production-xpc-app-container-bookmark=workspace_rejected",
            "production-xpc-app-container-bookmark-no-writeback=verified",
            "production-xpc-app-container-issued-scope=workspace_rejected",
            "production-xpc-app-container-issued-scope-no-writeback=verified",
        ].joined(separator: "\n")
    }

    private static func productionCommandRunner(argv: [String]) -> String {
        let arguments = String(reflecting: argv)
        return """
        from khaos.runner_sdk import process_exec, workspace_commit

        def run():
            result = process_exec(\(arguments))
            if result["returncode"] != 0:
                raise SystemExit(60)
            workspace_commit()
            return result["returncode"]
        """
    }

    private static func rejectMisidentifiedKernelService(
        bundleID: String,
        outsidePath: String
    ) throws -> String {
        let connection = try KernelWorkspaceClient.connectToService(
            serviceName: "\(bundleID).UntrustedHost",
            peerRequirementKey: KernelService.production.peerRequirementKey,
            remoteInterface: WorkspaceGrantHostProbe.self
        )
        defer { connection.invalidate() }

        let semaphore = DispatchSemaphore(value: 0)
        let lock = NSLock()
        var outcome: (reply: String?, errorCode: Int?)?
        let finish: (String?, Int?) -> Void = { reply, errorCode in
            lock.lock()
            let shouldComplete = outcome == nil
            if shouldComplete {
                outcome = (reply, errorCode)
            }
            lock.unlock()
            if shouldComplete {
                semaphore.signal()
            }
        }
        let proxy = connection.remoteObjectProxyWithErrorHandler { error in
            finish(nil, (error as NSError).code)
        } as? WorkspaceGrantHostProbe
        guard let proxy else {
            throw ProbeError.invalidProxy
        }
        proxy.checkWorkspaceWrite(
            outsidePath,
            "\(bundleID).KernelProduction"
        ) { reply in
            finish(reply, nil)
        }
        guard semaphore.wait(timeout: .now() + 10) == .success else {
            throw ProbeError.xpcTimeout
        }
        lock.lock()
        let completedOutcome = outcome
        lock.unlock()
        guard completedOutcome?.reply == nil,
              completedOutcome?.errorCode
                == NSXPCConnectionCodeSigningRequirementFailure
        else {
            throw ProbeError.clientFailed(
                "a service with the wrong code identity passed the Kernel peer check"
            )
        }
        return "xpc-kernel-client-peer-mismatch=rejected-by-os"
    }

    private static func runRelayedPeerCheck(bundleID: String) throws {
        let request = KernelWorkspaceXPC.WorkspaceRunRequest(
            timeoutSeconds: 5,
            runnerSource: "def run(ctx):\n    return None\n",
            runnerSourceSHA256: KernelWorkspaceXPC.runnerSourceSHA256(
                "def run(ctx):\n    return None\n"
            ),
            workspaceReadScope: []
        )
        let requestID = KernelWorkspaceXPC.newRequestID()
        let endpoint = try kernelEndpoint(bundleID: bundleID, service: .execution)
        let evidence = try rejectRelayedInvocation(
            endpoint: endpoint,
            serviceName: "\(bundleID).UntrustedHost",
            request: request,
            requestID: requestID
        )
        FileHandle.standardOutput.write(Data("\(evidence)\n".utf8))
    }

    private static func rejectRelayedInvocation(
        endpoint: KernelWorkspaceTarget,
        serviceName: String,
        request: KernelWorkspaceXPC.WorkspaceRunRequest,
        requestID: KernelWorkspaceXPC.RequestID = KernelWorkspaceXPC.newRequestID()
    ) throws -> String {
        let prefix = try KernelWorkspaceXPC.encodeInvocationPrefix(
            request: request,
            requestID: requestID
        )
        let response = try WorkspaceGrantHostClient.withRelayedInvocationStream(
            serviceName: serviceName,
            requestPrefix: prefix
        ) { stream, _ in
            try requestWorkspaceReply(
                endpoint: endpoint,
                requestID: requestID
            ) { proxy, withReply in
                proxy.runWorkspaceCommand(
                    KernelWorkspaceXPC.version,
                    requestIDHigh: requestID.high,
                    requestIDLow: requestID.low,
                    invocationStream: stream,
                    withReply: withReply
                )
            }
        }
        guard response.errorCode == "invalid_request",
              response.output == nil,
              response.cancellationAccepted == nil
        else {
            throw ProbeError.clientFailed(
                "Kernel accepted a workspace stream relayed from another process"
            )
        }
        return "xpc-kernel-relay=peer-pid-mismatch-rejected-before-parse"
    }

    private static func requestWorkspaceReply(
        endpoint: KernelWorkspaceTarget,
        requestID: KernelWorkspaceXPC.RequestID,
        snapshotBrokerEndpoint: NSXPCListenerEndpoint? = nil,
        afterSubmit: ((KernelWorkspaceEndpoint) throws -> Void)? = nil,
        submit: (
            KernelWorkspaceEndpoint,
            @escaping (Data) -> Void
        ) throws -> Void
    ) throws -> KernelWorkspaceXPC.Reply {
        do {
            return try KernelWorkspaceClient.request(
                endpoint,
                requestID: requestID,
                snapshotBrokerEndpoint: snapshotBrokerEndpoint
            ) { proxy, withReply in
                try submit(proxy, withReply)
                try afterSubmit?(proxy)
            }
        } catch let error as KernelWorkspaceClientError {
            switch error {
            case let .missingPeerRequirement(key):
                throw ProbeError.missingPeerRequirement(key)
            case .invalidBootstrapProxy, .invalidWorkspaceProxy:
                throw ProbeError.invalidProxy
            case .bootstrapFailed:
                throw ProbeError.clientFailed("Kernel XPC bootstrap failed")
            case .requestFailed:
                throw ProbeError.clientFailed("Kernel XPC request failed")
            case .invalidResponse:
                throw ProbeError.clientFailed("invalid Kernel XPC response")
            case .snapshotBrokerEndpointRejected:
                throw ProbeError.clientFailed("snapshot Broker endpoint rejected")
            case .timedOut:
                throw ProbeError.xpcTimeout
            }
        }
    }

    private static func kernelEndpoint(
        bundleID: String,
        service: KernelService
    ) throws -> KernelWorkspaceTarget {
        do {
            return try KernelWorkspaceClient.connect(
                serviceName: service.serviceName(bundleID: bundleID),
                peerRequirementKey: service.peerRequirementKey
            )
        } catch let error as KernelWorkspaceClientError {
            switch error {
            case let .missingPeerRequirement(key):
                throw ProbeError.missingPeerRequirement(key)
            case .invalidWorkspaceProxy:
                throw ProbeError.invalidProxy
            case .requestFailed, .invalidResponse:
                throw ProbeError.clientFailed("Kernel XPC request failed")
            case .invalidBootstrapProxy, .bootstrapFailed:
                throw ProbeError.invalidProxy
            case .snapshotBrokerEndpointRejected:
                throw ProbeError.clientFailed("snapshot Broker endpoint rejected")
            case .timedOut:
                throw ProbeError.xpcTimeout
            }
        }
    }

    private static func withFailureContext<T>(
        _ context: String,
        operation: () throws -> T
    ) throws -> T {
        do {
            return try operation()
        } catch {
            throw ProbeError.clientFailed("\(context): \(error)")
        }
    }
}

private enum ProbeError: Error, CustomStringConvertible {
    case invalidArguments
    case invalidProxy
    case missingPeerRequirement(String)
    case clientFailed(String)
    case unexpectedKernelOutput
    case kernelBypassPresent
    case unexpectedSelection(
        selected: String,
        expected: String
    )
    case xpcTimeout

    var description: String {
        switch self {
        case let .unexpectedSelection(selected, expected):
            return "unexpectedSelection(selected=\(selected), expected=\(expected))"
        case .invalidArguments:
            return "invalidArguments"
        case .invalidProxy:
            return "invalidProxy"
        case let .missingPeerRequirement(key):
            return "missingPeerRequirement(\(key))"
        case let .clientFailed(message):
            return "clientFailed(\(message))"
        case .unexpectedKernelOutput:
            return "unexpectedKernelOutput"
        case .kernelBypassPresent:
            return "kernelBypassPresent"
        case .xpcTimeout:
            return "xpcTimeout"
        }
    }
}
