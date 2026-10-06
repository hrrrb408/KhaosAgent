import CoreFoundation
import CryptoKit
import Darwin
import Foundation

@objc protocol KernelWorkspaceBootstrapEndpoint {
    func kernelEndpoint(withReply reply: @escaping (NSXPCListenerEndpoint) -> Void)
}

enum KernelWorkspaceXPC {
    static let version = 8
    static let operationProtocolVersion = 10
    static let maximumMessageBytes = 64 * 1024
    static let transferLengthBytes = 4
    static let maximumRequestFrameBytes = maximumMessageBytes + transferLengthBytes
    static let maximumJSONNestingDepth = 8
    static let maximumWorkspaceScopePaths = 128
    static let maximumWorkspaceScopeBytes = 4 * 1024
    static let maximumWorkspacePathDepth = 64
    static let maximumPluginInputBytes = 8 * 1024
    static let maximumPluginInputDepth = 6
    private static let transferTimeout: TimeInterval = 5

    struct WorkspaceRunRequest {
        let timeoutSeconds: Double
        let runnerSource: String
        let runnerSourceSHA256: String
        let workspaceReadScope: [String]
        var workspaceWriteScope: [String] = []

        func encodeFrame(requestID: RequestID) throws -> Data {
            try KernelWorkspaceXPC.validateRunRequest(self)
            let object: [String: Any] = [
                "version": KernelWorkspaceXPC.operationProtocolVersion,
                "request_id": requestID.token,
                "operation": "workspace.run",
                "payload": [
                    "timeout_seconds": timeoutSeconds,
                    "runner_source": runnerSource,
                    "runner_source_sha256": runnerSourceSHA256,
                    "workspace_read_scope": workspaceReadScope,
                    "workspace_write_scope": workspaceWriteScope,
                ],
            ]
            guard let payload = try? JSONSerialization.data(
                withJSONObject: object,
                options: [.sortedKeys]
            ), !payload.isEmpty, payload.count <= KernelWorkspaceXPC.maximumMessageBytes
            else {
                throw NSError(domain: NSPOSIXErrorDomain, code: Int(EMSGSIZE))
            }
            var frame = Data()
            frame.reserveCapacity(KernelWorkspaceXPC.transferLengthBytes + payload.count)
            KernelWorkspaceXPC.appendUInt32(UInt32(payload.count), to: &frame)
            frame.append(payload)
            return frame
        }
    }

    enum PluginLifecycleRequest {
        case admit(manifest: Data, source: Data)
        case activate(
            candidateDigest: String,
            manifestDigest: String,
            scopeDigest: String,
            expectedGeneration: Int
        )
        case state
        case rollback(
            candidateDigest: String,
            manifestDigest: String,
            scopeDigest: String,
            expectedGeneration: Int
        )
        case run(
            pluginID: String,
            candidateDigest: String,
            manifestDigest: String,
            scopeDigest: String,
            expectedGeneration: Int,
            inputJSON: Data?,
            workspaceRequired: Bool
        )

        var needsBookmark: Bool {
            if case let .run(_, _, _, _, _, _, workspaceRequired) = self {
                return workspaceRequired
            }
            return false
        }

        var needsSnapshotBroker: Bool {
            if case .run = self { return true }
            return false
        }

        func encodeFrame(requestID: RequestID) throws -> Data {
            let operation: String
            let payload: [String: Any]
            switch self {
            case let .admit(manifest, source):
                guard !manifest.isEmpty, manifest.count <= 4_096,
                      !source.isEmpty, source.count <= 10_240,
                      String(data: manifest, encoding: .utf8) != nil,
                      String(data: source, encoding: .utf8) != nil else {
                    throw NSError(domain: NSPOSIXErrorDomain, code: Int(EINVAL))
                }
                operation = "plugin.admit"
                payload = [
                    "manifest_base64": manifest.base64EncodedString(),
                    "source_base64": source.base64EncodedString(),
                ]
            case let .activate(candidate, manifest, scope, generation):
                operation = "plugin.activate"
                payload = try KernelWorkspaceXPC.approvalPayload(
                    candidate: candidate,
                    manifest: manifest,
                    scope: scope,
                    generation: generation
                )
            case .state:
                operation = "plugin.state"
                payload = [:]
            case let .rollback(candidate, manifest, scope, generation):
                operation = "plugin.rollback"
                payload = try KernelWorkspaceXPC.approvalPayload(
                    candidate: candidate,
                    manifest: manifest,
                    scope: scope,
                    generation: generation
                )
            case let .run(pluginID, candidate, manifest, scope, generation, inputJSON, workspaceRequired):
                operation = "plugin.run"
                var value = try KernelWorkspaceXPC.approvalPayload(
                    candidate: candidate,
                    manifest: manifest,
                    scope: scope,
                    generation: generation
                )
                guard KernelWorkspaceXPC.validPluginID(pluginID),
                      let input = KernelWorkspaceXPC.pluginInputObject(inputJSON)
                else {
                    throw NSError(domain: NSPOSIXErrorDomain, code: Int(EINVAL))
                }
                value["plugin_id"] = pluginID
                value["input"] = input
                value["workspace_required"] = workspaceRequired
                payload = value
            }
            return try KernelWorkspaceXPC.encodeFrame(
                operation: operation,
                payload: payload,
                requestID: requestID
            )
        }
    }

    enum InvocationRequest {
        case workspaceRun(WorkspaceRunRequest)
        case pluginLifecycle(PluginLifecycleRequest)

        var needsBookmark: Bool {
            switch self {
            case .workspaceRun: return true
            case let .pluginLifecycle(request): return request.needsBookmark
            }
        }

        var needsSnapshotBroker: Bool {
            switch self {
            case .workspaceRun: return true
            case let .pluginLifecycle(request): return request.needsSnapshotBroker
            }
        }

        func encodeFrame(requestID: RequestID) throws -> Data {
            switch self {
            case let .workspaceRun(request):
                return try request.encodeFrame(requestID: requestID)
            case let .pluginLifecycle(request):
                return try request.encodeFrame(requestID: requestID)
            }
        }
    }

    struct WorkspaceInvocation {
        let requestID: RequestID
        let request: InvocationRequest
        let bookmark: Data?
        let snapshotBrokerEndpoint: NSXPCListenerEndpoint?
    }

    static func encodeInvocation(
        request: WorkspaceRunRequest,
        requestID: RequestID,
        bookmark: Data
    ) throws -> Data {
        var frame = try encodeInvocationPrefix(
            request: request,
            requestID: requestID
        )
        try appendBookmarkTransfer(bookmark, to: &frame)
        return frame
    }

    static func encodeBridgeInput(
        request: WorkspaceRunRequest,
        requestID: RequestID,
        bookmark: Data
    ) throws -> Data {
        var frame = try request.encodeFrame(requestID: requestID)
        try appendBookmarkTransfer(bookmark, to: &frame)
        return frame
    }

    static func encodeInvocationPrefix(
        request: WorkspaceRunRequest,
        requestID: RequestID
    ) throws -> Data {
        try encodeInvocationPrefix(
            requestFrame: request.encodeFrame(requestID: requestID)
        )
    }

    static func encodeInvocationPrefix(
        request: PluginLifecycleRequest,
        requestID: RequestID
    ) throws -> Data {
        try encodeInvocationPrefix(
            requestFrame: request.encodeFrame(requestID: requestID)
        )
    }

    private static func encodeInvocationPrefix(requestFrame: Data) throws -> Data {
        var prefix = Data()
        prefix.reserveCapacity(transferLengthBytes + requestFrame.count)
        appendUInt32(UInt32(requestFrame.count), to: &prefix)
        prefix.append(requestFrame)
        return prefix
    }

    static func encodeInvocation(
        request: PluginLifecycleRequest,
        requestID: RequestID,
        bookmark: Data? = nil
    ) throws -> Data {
        guard request.needsBookmark == (bookmark != nil) else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(EINVAL))
        }
        var frame = try encodeInvocationPrefix(request: request, requestID: requestID)
        if let bookmark {
            try appendBookmarkTransfer(bookmark, to: &frame)
        }
        return frame
    }

    // Share one bookmark limit and check it before either side allocates a frame body.
    static func boundedBookmarkLength(_ length: Int) throws -> Int {
        guard length > 0,
              length <= maximumMessageBytes
        else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(EMSGSIZE))
        }
        return length
    }

    private static func appendBookmarkTransfer(
        _ bookmark: Data,
        to frame: inout Data
    ) throws {
        let bookmarkLength = try boundedBookmarkLength(bookmark.count)
        frame.reserveCapacity(frame.count + transferLengthBytes + bookmarkLength)
        appendUInt32(UInt32(bookmarkLength), to: &frame)
        frame.append(bookmark)
    }

    static func encodeBridgeInput(
        request: PluginLifecycleRequest,
        requestID: RequestID,
        bookmark: Data? = nil
    ) throws -> Data {
        guard request.needsBookmark == (bookmark != nil) else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(EINVAL))
        }
        var frame = try request.encodeFrame(requestID: requestID)
        if let bookmark {
            try appendBookmarkTransfer(bookmark, to: &frame)
        }
        return frame
    }

    static func encodeFrame(
        operation: String,
        payload: [String: Any],
        requestID: RequestID
    ) throws -> Data {
        let object: [String: Any] = [
            "version": operationProtocolVersion,
            "request_id": requestID.token,
            "operation": operation,
            "payload": payload,
        ]
        guard let body = try? JSONSerialization.data(
            withJSONObject: object,
            options: [.sortedKeys]
        ), !body.isEmpty, body.count <= maximumMessageBytes else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(EMSGSIZE))
        }
        var frame = Data()
        frame.reserveCapacity(transferLengthBytes + body.count)
        appendUInt32(UInt32(body.count), to: &frame)
        frame.append(body)
        return frame
    }

    static func submit(
        _ proxy: KernelWorkspaceEndpoint,
        version: Int = KernelWorkspaceXPC.version,
        requestID: RequestID = KernelWorkspaceXPC.newRequestID(),
        request: PluginLifecycleRequest,
        bookmark: Data? = nil,
        withReply reply: @escaping (Data) -> Void
    ) throws {
        let transfer = try WorkspaceInvocationTransfer(
            request: request,
            requestID: requestID,
            bookmark: bookmark
        )
        proxy.runWorkspaceCommand(
            version,
            requestIDHigh: requestID.high,
            requestIDLow: requestID.low,
            invocationStream: transfer.reader
        ) { data in
            transfer.closeWriter()
            reply(data)
        }
        DispatchQueue.global(qos: .utility).async {
            do {
                try transfer.send()
            } catch {
                transfer.closeWriter()
            }
        }
    }

    struct RequestID: Equatable {
        let high: UInt64
        let low: UInt64

        var token: String {
            Self.hex(high) + Self.hex(low)
        }

        private static func hex(_ value: UInt64) -> String {
            let digits = String(value, radix: 16)
            return String(repeating: "0", count: 16 - digits.count) + digits
        }
    }

    struct Reply {
        let output: String?
        let cancellationAccepted: Bool?
        let errorCode: String?
    }

    static func newRequestID() -> RequestID {
        var value = UUID().uuid
        let halves = withUnsafeBytes(of: &value) { bytes in
            var high: UInt64 = 0
            var low: UInt64 = 0
            for byte in bytes.prefix(8) {
                high = (high << 8) | UInt64(byte)
            }
            for byte in bytes.suffix(8) {
                low = (low << 8) | UInt64(byte)
            }
            return (high, low)
        }
        return RequestID(high: halves.0, low: halves.1)
    }

    static func runnerSourceSHA256(_ source: String) -> String {
        sha256Hex(Data(source.utf8))
    }

    static func validPluginID(_ value: String) -> Bool {
        value.range(
            of: #"^[a-z][a-z0-9-]{0,63}$"#,
            options: .regularExpression
        ) != nil
    }

    private static func pluginInputObject(_ data: Data?) -> Any? {
        guard let data else { return NSNull() }
        guard !data.isEmpty,
              data.count <= maximumPluginInputBytes,
              isJSONNestingWithinLimit(
                data,
                maximumDepth: maximumPluginInputDepth
              ),
              let value = try? JSONSerialization.jsonObject(with: data),
              let object = value as? [String: Any],
              let canonical = try? JSONSerialization.data(
                withJSONObject: object,
                options: [.sortedKeys, .withoutEscapingSlashes]
              ),
              canonical == data else {
            return nil
        }
        return object
    }

    static func sha256Hex(_ data: Data) -> String {
        SHA256.hash(data: data)
            .map { String(format: "%02x", $0) }
            .joined()
    }

    static func success(requestID: RequestID, output: String) -> Data {
        encode([
            "version": version,
            "request_id": requestID.token,
            "ok": true,
            "output": output,
        ], fallbackRequestID: requestID.token)
    }

    static func cancellationAccepted(requestID: RequestID) -> Data {
        encode([
            "version": version,
            "request_id": requestID.token,
            "ok": true,
            "cancel_accepted": true,
        ], fallbackRequestID: requestID.token)
    }

    static func failure(requestID: RequestID, code: String) -> Data {
        encode([
            "version": version,
            "request_id": requestID.token,
            "ok": false,
            "error": ["code": code],
        ], fallbackRequestID: requestID.token)
    }

    static func decode(_ data: Data, requestID: RequestID) -> Reply? {
        decode(data, requestID: requestID, protocolVersion: version)
    }

    static func decode(
        _ data: Data,
        requestID: RequestID,
        protocolVersion: Int
    ) -> Reply? {
        guard data.count <= maximumMessageBytes,
              let object = try? JSONSerialization.jsonObject(with: data),
              let envelope = object as? [String: Any],
              integer(envelope["version"]) == protocolVersion,
              envelope["request_id"] as? String == requestID.token,
              let ok = boolean(envelope["ok"])
        else {
            return nil
        }

        if ok {
            if Set(envelope.keys) == ["version", "request_id", "ok", "output"],
               let output = envelope["output"] as? String {
                return Reply(output: output, cancellationAccepted: nil, errorCode: nil)
            }
            if Set(envelope.keys)
                == ["version", "request_id", "ok", "cancel_accepted"],
               boolean(envelope["cancel_accepted"]) == true {
                return Reply(output: nil, cancellationAccepted: true, errorCode: nil)
            }
            return nil
        }

        guard Set(envelope.keys) == ["version", "request_id", "ok", "error"],
              let error = envelope["error"] as? [String: Any],
              Set(error.keys) == ["code"],
              let code = error["code"] as? String,
              !code.isEmpty,
              code.utf8.count <= 64
        else {
            return nil
        }
        return Reply(output: nil, cancellationAccepted: nil, errorCode: code)
    }

    static func submit(
        _ proxy: KernelWorkspaceEndpoint,
        version: Int = KernelWorkspaceXPC.version,
        requestID: RequestID = KernelWorkspaceXPC.newRequestID(),
        request: WorkspaceRunRequest,
        bookmark: Data,
        withReply reply: @escaping (Data) -> Void
    ) throws {
        let transfer = try WorkspaceInvocationTransfer(
            request: request,
            requestID: requestID,
            bookmark: bookmark
        )
        proxy.runWorkspaceCommand(
            version,
            requestIDHigh: requestID.high,
            requestIDLow: requestID.low,
            invocationStream: transfer.reader
        ) { data in
            transfer.closeWriter()
            reply(data)
        }
        DispatchQueue.global(qos: .utility).async {
            do {
                try transfer.send()
            } catch {
                transfer.closeWriter()
            }
        }
    }

    static func readInvocation(
        from handle: FileHandle,
        requestID: RequestID,
        expectedPeerProcessID: pid_t,
        snapshotBrokerEndpoint: NSXPCListenerEndpoint? = nil
    ) -> (invocation: WorkspaceInvocation?, errorCode: String) {
        let descriptor = handle.fileDescriptor
        var socketType: Int32 = 0
        var socketTypeLength = socklen_t(MemoryLayout<Int32>.size)
        guard getsockopt(
            descriptor,
            SOL_SOCKET,
            SO_TYPE,
            &socketType,
            &socketTypeLength
        ) == 0,
        socketType == SOCK_STREAM
        else {
            return (nil, "invalid_request")
        }

        // XPC authenticates the method caller; bind the delegated stream to that caller too.
        var peerProcessID: pid_t = 0
        var peerProcessIDLength = socklen_t(MemoryLayout<pid_t>.size)
        let peerPIDResult = getsockopt(
            descriptor,
            SOL_LOCAL,
            LOCAL_PEERPID,
            &peerProcessID,
            &peerProcessIDLength
        )
        guard expectedPeerProcessID > 0,
              peerPIDResult == 0,
              peerProcessIDLength == MemoryLayout<pid_t>.size,
              peerProcessID == expectedPeerProcessID
        else {
            return (nil, "invalid_request")
        }

        let flags = fcntl(descriptor, F_GETFL)
        guard flags >= 0, fcntl(descriptor, F_SETFL, flags | O_NONBLOCK) == 0 else {
            return (nil, "invalid_request")
        }
        let deadline = Date().addingTimeInterval(transferTimeout)
        guard let requestLengthBytes = readExactly(
            descriptor,
            count: transferLengthBytes,
            deadline: deadline
        ) else {
            return (nil, "invalid_request")
        }
        let requestLength = Int(readUInt32(requestLengthBytes, offset: 0))
        guard requestLength > transferLengthBytes,
              requestLength <= maximumRequestFrameBytes,
              let requestFrame = readExactly(
                descriptor,
                count: requestLength,
                deadline: deadline
              ),
              let request = decodeInvocationRequest(requestFrame, requestID: requestID)
        else {
            return (nil, "invalid_request")
        }
        let bookmark: Data?
        if request.needsBookmark {
            guard let bookmarkLengthBytes = readExactly(
                descriptor,
                count: transferLengthBytes,
                deadline: deadline
            ),
            let bookmarkLength = try? boundedBookmarkLength(
                Int(readUInt32(bookmarkLengthBytes, offset: 0))
            ),
            let transferredBookmark = readExactly(
                descriptor,
                count: bookmarkLength,
                deadline: deadline
            ),
            reachesEOF(descriptor, deadline: deadline)
            else {
                return (nil, "invalid_bookmark")
            }
            bookmark = transferredBookmark
        } else {
            guard reachesEOF(descriptor, deadline: deadline) else {
                return (nil, "invalid_request")
            }
            bookmark = nil
        }
        return (
            WorkspaceInvocation(
                requestID: requestID,
                request: request,
                bookmark: bookmark,
                snapshotBrokerEndpoint: snapshotBrokerEndpoint
            ),
            ""
        )
    }

    static func decodeRunRequest(
        _ frame: Data,
        requestID: RequestID? = nil
    ) -> WorkspaceRunRequest? {
        guard case let .workspaceRun(request)? = decodeInvocationRequest(
            frame,
            requestID: requestID
        ) else { return nil }
        return request
    }

    static func decodeInvocationRequest(
        _ frame: Data,
        requestID: RequestID? = nil
    ) -> InvocationRequest? {
        guard let (operation, payload) = decodeEnvelope(frame, requestID: requestID)
        else { return nil }
        if operation == "workspace.run" {
            return decodeWorkspaceRequest(payload).map(InvocationRequest.workspaceRun)
        }
        guard let request = decodePluginLifecycleRequest(
            operation: operation,
            payload: payload
        ) else { return nil }
        return .pluginLifecycle(request)
    }

    static func decodePluginRequest(
        _ frame: Data,
        requestID: RequestID? = nil
    ) -> PluginLifecycleRequest? {
        guard let (operation, payload) = decodeEnvelope(frame, requestID: requestID),
              operation != "workspace.run" else { return nil }
        return decodePluginLifecycleRequest(operation: operation, payload: payload)
    }

    private static func decodeEnvelope(
        _ frame: Data,
        requestID: RequestID? = nil
    ) -> (String, [String: Any])? {
        guard frame.count > transferLengthBytes,
              frame.count <= maximumRequestFrameBytes
        else {
            return nil
        }
        let body = Data(frame.dropFirst(transferLengthBytes))
        // Keep recursive Foundation parsing within the shallow XPC schema.
        guard Int(readUInt32(frame, offset: 0)) == body.count,
              isJSONNestingWithinLimit(body),
              let object = try? JSONSerialization.jsonObject(
                with: body
              ),
              let envelope = object as? [String: Any],
              // Dictionary decoding erases duplicate keys; admit only the local wire encoding.
              let canonicalBody = try? JSONSerialization.data(
                withJSONObject: envelope,
                options: [.sortedKeys]
              ),
              canonicalBody == body,
              Set(envelope.keys) == ["version", "request_id", "operation", "payload"],
              integer(envelope["version"]) == operationProtocolVersion,
              let token = envelope["request_id"] as? String,
              isValidToken(token),
              requestID == nil || token == requestID?.token,
              let operation = envelope["operation"] as? String,
              operation.utf8.count <= 64,
              let payload = envelope["payload"] as? [String: Any]
        else {
            return nil
        }
        return (operation, payload)
    }

    private static func decodeWorkspaceRequest(
        _ payload: [String: Any]
    ) -> WorkspaceRunRequest? {
        guard Set(payload.keys) == [
            "timeout_seconds", "runner_source", "runner_source_sha256",
            "workspace_read_scope", "workspace_write_scope",
        ],
        let timeout = finiteNumber(payload["timeout_seconds"]),
        let runnerSource = payload["runner_source"] as? String,
        let runnerSourceSHA256 = payload["runner_source_sha256"] as? String,
        let workspaceReadScope = payload["workspace_read_scope"] as? [String],
        let workspaceWriteScope = payload["workspace_write_scope"] as? [String]
        else { return nil }
        let request = WorkspaceRunRequest(
            timeoutSeconds: timeout,
            runnerSource: runnerSource,
            runnerSourceSHA256: runnerSourceSHA256,
            workspaceReadScope: workspaceReadScope,
            workspaceWriteScope: workspaceWriteScope
        )
        return (try? validateRunRequest(request)) == nil ? nil : request
    }

    private static func decodePluginLifecycleRequest(
        operation: String,
        payload: [String: Any]
    ) -> PluginLifecycleRequest? {
        switch operation {
        case "plugin.admit":
            guard Set(payload.keys) == ["manifest_base64", "source_base64"],
                  let manifestText = payload["manifest_base64"] as? String,
                  let sourceText = payload["source_base64"] as? String,
                  let manifest = Data(base64Encoded: manifestText),
                  manifest.base64EncodedString() == manifestText,
                  let source = Data(base64Encoded: sourceText),
                  source.base64EncodedString() == sourceText,
                  !manifest.isEmpty, manifest.count <= 4_096,
                  !source.isEmpty, source.count <= 10_240,
                  String(data: manifest, encoding: .utf8) != nil,
                  String(data: source, encoding: .utf8) != nil
            else { return nil }
            return .admit(manifest: manifest, source: source)
        case "plugin.activate", "plugin.rollback":
            guard Set(payload.keys) == [
                "candidate_digest", "manifest_digest", "scope_digest",
                "expected_generation",
            ],
            let candidate = payload["candidate_digest"] as? String,
            let manifest = payload["manifest_digest"] as? String,
            let scope = payload["scope_digest"] as? String,
            let generation = integer(payload["expected_generation"]),
            (try? validateApprovalBinding(
                candidate: candidate,
                manifest: manifest,
                scope: scope,
                generation: generation
            )) != nil
            else { return nil }
            if operation == "plugin.activate" {
                return .activate(
                    candidateDigest: candidate,
                    manifestDigest: manifest,
                    scopeDigest: scope,
                    expectedGeneration: generation
                )
            }
            return .rollback(
                candidateDigest: candidate,
                manifestDigest: manifest,
                scopeDigest: scope,
                expectedGeneration: generation
            )
        case "plugin.run":
            guard Set(payload.keys) == [
                "plugin_id", "candidate_digest", "manifest_digest", "scope_digest",
                "expected_generation", "input", "workspace_required",
            ],
            let pluginID = payload["plugin_id"] as? String,
            validPluginID(pluginID),
            let candidate = payload["candidate_digest"] as? String,
            let manifest = payload["manifest_digest"] as? String,
            let scope = payload["scope_digest"] as? String,
            let generation = integer(payload["expected_generation"]),
            (try? validateApprovalBinding(
                candidate: candidate,
                manifest: manifest,
                scope: scope,
                generation: generation
            )) != nil,
            let workspaceRequired = boolean(payload["workspace_required"]),
            let input = pluginInputData(payload["input"])
            else { return nil }
            return .run(
                pluginID: pluginID,
                candidateDigest: candidate,
                manifestDigest: manifest,
                scopeDigest: scope,
                expectedGeneration: generation,
                inputJSON: input,
                workspaceRequired: workspaceRequired
            )
        case "plugin.state":
            guard payload.isEmpty else { return nil }
            return .state
        default:
            return nil
        }
    }

    private static func validateApprovalBinding(
        candidate: String,
        manifest: String,
        scope: String,
        generation: Int
    ) throws {
        guard isDigest(candidate), isDigest(manifest), isDigest(scope),
              generation >= 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(EINVAL))
        }
    }

    private static func approvalPayload(
        candidate: String,
        manifest: String,
        scope: String,
        generation: Int
    ) throws -> [String: Any] {
        try validateApprovalBinding(
            candidate: candidate,
            manifest: manifest,
            scope: scope,
            generation: generation
        )
        return [
            "candidate_digest": candidate,
            "manifest_digest": manifest,
            "scope_digest": scope,
            "expected_generation": generation,
        ]
    }

    private static func pluginInputData(_ value: Any?) -> Data?? {
        if value is NSNull { return .some(nil) }
        guard let object = value as? [String: Any],
              let data = try? JSONSerialization.data(
                withJSONObject: object,
                options: [.sortedKeys, .withoutEscapingSlashes]
              ),
              data.count <= maximumPluginInputBytes,
              isJSONNestingWithinLimit(
                data,
                maximumDepth: maximumPluginInputDepth
              ) else {
            return nil
        }
        return .some(data)
    }

    private static func isDigest(_ value: String) -> Bool {
        value.utf8.count == 64 && value.utf8.allSatisfy {
            (48...57).contains($0) || (97...102).contains($0)
        }
    }

    static func isJSONNestingWithinLimit(
        _ data: Data,
        maximumDepth: Int = maximumJSONNestingDepth
    ) -> Bool {
        var depth = 0
        var inString = false
        var escaped = false

        for byte in data {
            if inString {
                if escaped {
                    escaped = false
                } else if byte == 0x5c {
                    escaped = true
                } else if byte == 0x22 {
                    inString = false
                }
                continue
            }

            switch byte {
            case 0x22:
                inString = true
            case 0x7b, 0x5b:
                depth += 1
                guard depth <= maximumDepth else { return false }
            case 0x7d, 0x5d:
                depth -= 1
                guard depth >= 0 else { return false }
            default:
                break
            }
        }
        return !inString && !escaped && depth == 0
    }

    private static func encode(
        _ object: [String: Any],
        fallbackRequestID: String
    ) -> Data {
        if let data = try? JSONSerialization.data(
            withJSONObject: object,
            options: [.sortedKeys]
        ), data.count <= maximumMessageBytes {
            return data
        }
        let fallback: [String: Any] = [
            "version": version,
            "request_id": fallbackRequestID,
            "ok": false,
            "error": ["code": "response_too_large"],
        ]
        return (try? JSONSerialization.data(
            withJSONObject: fallback,
            options: [.sortedKeys]
        )) ?? Data()
    }

    private static func readExactly(
        _ descriptor: Int32,
        count: Int,
        deadline: Date
    ) -> Data? {
        var bytes = Data(count: count)
        var offset = 0
        while offset < count {
            guard waitForRead(descriptor, deadline: deadline) else {
                return nil
            }
            let amount = bytes.withUnsafeMutableBytes { buffer -> Int in
                guard let base = buffer.baseAddress else { return -1 }
                return recv(
                    descriptor,
                    base.advanced(by: offset),
                    count - offset,
                    0
                )
            }
            if amount > 0 {
                offset += amount
            } else if amount == 0 {
                return nil
            } else if errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK {
                return nil
            }
        }
        return bytes
    }

    private static func reachesEOF(_ descriptor: Int32, deadline: Date) -> Bool {
        while waitForRead(descriptor, deadline: deadline) {
            var byte: UInt8 = 0
            let amount = recv(descriptor, &byte, 1, 0)
            if amount == 0 {
                return true
            }
            if amount > 0 {
                return false
            }
            if errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK {
                return false
            }
        }
        return false
    }

    private static func waitForRead(_ descriptor: Int32, deadline: Date) -> Bool {
        while true {
            let remaining = deadline.timeIntervalSinceNow
            guard remaining > 0 else { return false }
            var event = pollfd(
                fd: descriptor,
                events: Int16(POLLIN),
                revents: 0
            )
            let timeout = max(1, min(Int(remaining * 1000), Int(Int32.max)))
            let result = poll(&event, 1, Int32(timeout))
            if result > 0 {
                return event.revents & Int16(POLLNVAL | POLLERR) == 0
                    && event.revents & Int16(POLLIN | POLLHUP) != 0
            }
            if result == 0 {
                return false
            }
            if errno != EINTR {
                return false
            }
        }
    }

    fileprivate static func readUInt32(_ data: Data, offset: Int) -> UInt32 {
        data[offset..<(offset + 4)].reduce(UInt32(0)) {
            ($0 << 8) | UInt32($1)
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

    private static func boolean(_ value: Any?) -> Bool? {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) == CFBooleanGetTypeID()
        else {
            return nil
        }
        return number.boolValue
    }

    private static func finiteNumber(_ value: Any?) -> Double? {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite
        else {
            return nil
        }
        return number.doubleValue
    }

    private static func validateRunRequest(_ request: WorkspaceRunRequest) throws {
        guard request.timeoutSeconds.isFinite,
              request.timeoutSeconds > 0,
              request.timeoutSeconds <= 30,
              !request.runnerSource.isEmpty,
              !request.runnerSource.contains("\0"),
              request.runnerSource.utf8.count <= 10_240,
              request.runnerSourceSHA256.utf8.count == 64,
              request.runnerSourceSHA256.utf8.allSatisfy({
                  (48...57).contains($0) || (97...102).contains($0)
              })
        else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(EINVAL))
        }
        guard request.runnerSourceSHA256 == runnerSourceSHA256(request.runnerSource) else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(EINVAL))
        }

        try validateWorkspaceScope(request.workspaceReadScope)
        try validateWorkspaceScope(request.workspaceWriteScope)
    }

    private static func validateWorkspaceScope(_ paths: [String]) throws {
        guard paths.count <= maximumWorkspaceScopePaths else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(EINVAL))
        }

        var encodedPaths = Set<Data>()
        var totalBytes = 0
        for path in paths {
            guard !path.isEmpty,
                  !path.hasPrefix("/"),
                  !path.contains("\0")
            else {
                throw NSError(domain: NSPOSIXErrorDomain, code: Int(EINVAL))
            }

            let components = path.split(
                separator: "/",
                maxSplits: maximumWorkspacePathDepth,
                omittingEmptySubsequences: false
            )
            guard components.count <= maximumWorkspacePathDepth,
                  components.allSatisfy({
                      !$0.isEmpty && $0 != "." && $0 != ".." && !$0.contains("/")
                  })
            else {
                throw NSError(domain: NSPOSIXErrorDomain, code: Int(EINVAL))
            }

            let encodedPath = Data(path.utf8)
            totalBytes += encodedPath.count + 1
            guard totalBytes <= maximumWorkspaceScopeBytes else {
                throw NSError(domain: NSPOSIXErrorDomain, code: Int(EMSGSIZE))
            }
            guard encodedPaths.insert(encodedPath).inserted else {
                throw NSError(domain: NSPOSIXErrorDomain, code: Int(EINVAL))
            }
        }
    }

    private static func isValidToken(_ value: String) -> Bool {
        value.utf8.count == 32
            && value.utf8.allSatisfy {
                (48...57).contains($0) || (97...102).contains($0)
            }
    }

    private static func appendUInt32(_ value: UInt32, to data: inout Data) {
        var bigEndian = value.bigEndian
        withUnsafeBytes(of: &bigEndian) {
            data.append(contentsOf: $0)
        }
    }
}

private final class WorkspaceInvocationTransfer {
    let reader: FileHandle
    private let frame: Data
    private let lock = NSLock()
    private var writer: Int32
    private var sending = false
    private var closeRequested = false

    convenience init(
        request: KernelWorkspaceXPC.WorkspaceRunRequest,
        requestID: KernelWorkspaceXPC.RequestID,
        bookmark: Data
    ) throws {
        try self.init(frame: KernelWorkspaceXPC.encodeInvocation(
            request: request,
            requestID: requestID,
            bookmark: bookmark
        ))
    }

    convenience init(
        request: KernelWorkspaceXPC.PluginLifecycleRequest,
        requestID: KernelWorkspaceXPC.RequestID,
        bookmark: Data?
    ) throws {
        try self.init(frame: KernelWorkspaceXPC.encodeInvocation(
            request: request,
            requestID: requestID,
            bookmark: bookmark
        ))
    }

    private init(frame framed: Data) throws {

        var sockets: [Int32] = [-1, -1]
        guard socketpair(AF_UNIX, SOCK_STREAM, 0, &sockets) == 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }
        var noSignal: Int32 = 1
        guard setsockopt(
            sockets[1],
            SOL_SOCKET,
            SO_NOSIGPIPE,
            &noSignal,
            socklen_t(MemoryLayout<Int32>.size)
        ) == 0 else {
            let error = errno
            _ = close(sockets[0])
            _ = close(sockets[1])
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(error))
        }
        var timeout = timeval(tv_sec: 5, tv_usec: 0)
        guard setsockopt(
            sockets[1],
            SOL_SOCKET,
            SO_SNDTIMEO,
            &timeout,
            socklen_t(MemoryLayout<timeval>.size)
        ) == 0 else {
            let error = errno
            _ = close(sockets[0])
            _ = close(sockets[1])
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(error))
        }

        reader = FileHandle(fileDescriptor: sockets[0], closeOnDealloc: true)
        writer = sockets[1]
        frame = framed
    }

    func send() throws {
        lock.lock()
        let descriptor = writer
        guard descriptor >= 0, !sending else {
            lock.unlock()
            return
        }
        sending = true
        lock.unlock()
        var frameSent = false
        defer {
            lock.lock()
            sending = false
            let closeDescriptor = !frameSent || closeRequested
            if closeDescriptor {
                writer = -1
            }
            lock.unlock()
            if closeDescriptor {
                _ = close(descriptor)
            }
        }

        var offset = 0
        while offset < frame.count {
            let amount = frame.withUnsafeBytes { buffer -> Int in
                guard let base = buffer.baseAddress else { return -1 }
                return Darwin.send(
                    descriptor,
                    base.advanced(by: offset),
                    frame.count - offset,
                    0
                )
            }
            if amount > 0 {
                offset += amount
            } else if amount < 0 && errno == EINTR {
                continue
            } else {
                throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
            }
        }
        guard shutdown(descriptor, SHUT_WR) == 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }
        frameSent = true
    }

    func closeWriter() {
        lock.lock()
        guard writer >= 0 else {
            lock.unlock()
            return
        }
        if sending {
            closeRequested = true
            lock.unlock()
            return
        }
        let descriptor = writer
        writer = -1
        lock.unlock()
        _ = close(descriptor)
    }

    deinit {
        closeWriter()
    }

}

@objc protocol KernelWorkspaceEndpoint {
    func setSnapshotBrokerEndpoint(
        _ version: Int,
        endpoint: NSXPCListenerEndpoint,
        withReply reply: @escaping (Bool) -> Void
    )
    func runWorkspaceCommand(
        _ version: Int,
        requestIDHigh: UInt64,
        requestIDLow: UInt64,
        invocationStream: FileHandle,
        withReply reply: @escaping (Data) -> Void
    )
    func cancelWorkspaceCommand(
        _ version: Int,
        requestIDHigh: UInt64,
        requestIDLow: UInt64,
        withReply reply: @escaping (Data) -> Void
    )
}
