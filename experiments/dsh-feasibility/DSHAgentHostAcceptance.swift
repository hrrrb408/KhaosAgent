import Darwin
import CoreFoundation
import CryptoKit
import Foundation

private struct DSHProposal: Decodable {
    let argv: [String]
    let readScope: [String]
    let writeScope: [String]
}

private enum DSHAgentHostError: Error {
    case childUnavailable
    case frameTooLarge
    case invalidFrame
    case timedOut
    case childExited
}

private final class DSHModelBridgeClient {
    private let connection: NSXPCConnection

    init(endpoint: NSXPCListenerEndpoint) throws {
        guard let requirement = Bundle.main.object(
            forInfoDictionaryKey: DSHModelBridgeLimits.bridgeRequirementInfoKey
        ) as? String,
        !requirement.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw DSHAgentHostError.childUnavailable
        }
        let connection = NSXPCConnection(listenerEndpoint: endpoint)
        connection.setCodeSigningRequirement(requirement)
        connection.remoteObjectInterface = NSXPCInterface(
            with: DSHModelBridgeEndpoint.self
        )
        connection.resume()
        self.connection = connection
    }

    deinit {
        connection.invalidate()
    }

    func complete(
        body: Any,
        headers: Any,
        apiKey: String?,
        timeoutSeconds: Int
    ) -> (completion: [String: Any]?, error: String?, elapsedMilliseconds: Int) {
        let started = ProcessInfo.processInfo.systemUptime
        guard let apiKey else {
            return (nil, "model_credentials_unavailable", 0)
        }
        guard JSONSerialization.isValidJSONObject(body),
              JSONSerialization.isValidJSONObject(headers),
              let bodyData = try? JSONSerialization.data(
                withJSONObject: body,
                options: [.sortedKeys, .withoutEscapingSlashes]
              ), bodyData.count <= DSHModelBridgeLimits.maximumRequestBytes,
              let headerData = try? JSONSerialization.data(
                withJSONObject: headers,
                options: [.sortedKeys, .withoutEscapingSlashes]
              ), headerData.count <= 1_024 else {
            return (nil, "invalid_model_request", 0)
        }

        let semaphore = DispatchSemaphore(value: 0)
        let lock = NSLock()
        var completion: [String: Any]?
        var errorCode: String?
        var elapsedMilliseconds = 0
        var finished = false
        let finish: (Data?, String?, Int) -> Void = { data, error, elapsed in
            lock.lock()
            guard !finished else {
                lock.unlock()
                return
            }
            finished = true
            errorCode = error
            elapsedMilliseconds = elapsed
            if let data, data.count <= DSHModelBridgeLimits.maximumResponseBytes {
                completion = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            } else if data != nil {
                errorCode = "model_output_too_large"
            }
            lock.unlock()
            semaphore.signal()
        }
        guard let endpoint = connection.remoteObjectProxyWithErrorHandler({ _ in
            finish(nil, "model_bridge_unavailable", 0)
        }) as? DSHModelBridgeEndpoint else {
            return (nil, "model_bridge_unavailable", 0)
        }
        endpoint.complete(
            bodyData as NSData,
            headers: headerData as NSData,
            apiKey: apiKey as NSString,
            timeoutSeconds: NSNumber(value: min(120, max(1, timeoutSeconds)))
        ) { data, error, elapsed in
            finish(
                data.map(Data.init(referencing:)),
                error.map(String.init),
                elapsed.intValue
            )
        }
        guard semaphore.wait(timeout: .now() + .seconds(max(1, timeoutSeconds) + 10)) == .success else {
            connection.invalidate()
            return (nil, "model_bridge_timed_out", elapsedSince(started))
        }
        lock.lock()
        let result = (completion, errorCode, elapsedMilliseconds)
        lock.unlock()
        if result.0 == nil, result.1 == nil {
            return (nil, "invalid_model_response", elapsedSince(started))
        }
        return (result.0, result.1, result.2)
    }

    private func elapsedSince(_ started: TimeInterval) -> Int {
        max(0, Int((ProcessInfo.processInfo.systemUptime - started) * 1_000))
    }
}

private final class DSHRuntimeProcess {
    private let processID: pid_t
    private let processGroupID: pid_t
    private let input: FileHandle
    private let output: FileHandle
    private let lock = NSLock()
    private var processReaped = false
    private var processStopped = false
    private var modelCallsThisTask = 0
    private var telemetrySequence = 0
    private var telemetryTrialID: String?
    private var telemetrySessionID: String?
    private var telemetryBenchmarkTaskID: String?
    private var lastTelemetryRecord: [String: Any]?
    private let maximumTelemetryReplyBytes = 40 * 1_024

    init(modelBridgeAvailable: Bool) throws {
        let resources = Bundle.main.bundleURL.appendingPathComponent(
            "Contents/Resources", isDirectory: true
        )
        let node = resources.appendingPathComponent("node", isDirectory: false)
        let script = resources.appendingPathComponent(
            "dsh/agenthost-runtime.mjs", isDirectory: false
        )
        guard FileManager.default.isExecutableFile(atPath: node.path),
              script.isFileURL,
              FileManager.default.fileExists(atPath: script.path) else {
            throw DSHAgentHostError.childUnavailable
        }

        let inputPipe = Pipe()
        let outputPipe = Pipe()
        var environment = [
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": NSHomeDirectory(),
            "TMPDIR": NSTemporaryDirectory(),
            "KHAOS_DSH_NODE_PATH": node.path,
            "KHAOS_DSH_MODEL_BRIDGE_AVAILABLE": modelBridgeAvailable ? "1" : "0",
        ]
        let bundleContents = Bundle.main.bundleURL.appendingPathComponent("Contents", isDirectory: true)
        let localModelExecutable = bundleContents
            .appendingPathComponent("Frameworks/KhaosLlama", isDirectory: true)
            .appendingPathComponent("llama-cli", isDirectory: false)
        let localModelFile = bundleContents
            .appendingPathComponent("Resources/agent-model.gguf", isDirectory: false)
        // Pass only paths to model files already sealed into this signed experimental Host bundle.
        // The Node child remains untrusted and network-denied; this adds no workspace or Kernel authority.
        if FileManager.default.isExecutableFile(atPath: localModelExecutable.path),
           FileManager.default.fileExists(atPath: localModelFile.path),
           let modelDigest = Bundle.main.object(forInfoDictionaryKey: "KhaosLocalModelSHA256") as? String,
           modelDigest.range(of: #"^[0-9a-f]{64}$"#, options: .regularExpression) != nil {
            environment["KHAOS_DSH_LOCAL_MODEL_EXECUTABLE"] = localModelExecutable.path
            environment["KHAOS_DSH_LOCAL_MODEL_FILE"] = localModelFile.path
            environment["KHAOS_DSH_LOCAL_MODEL_SHA256"] = modelDigest
        }
        environment["KHAOS_DSH_AGENTHOST_PID"] = String(getpid())
        if let requirement = Bundle.main.object(
            forInfoDictionaryKey: DSHModelBridgeLimits.bridgeRequirementInfoKey
        ) as? String,
           !requirement.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            environment["KHAOS_DSH_MODEL_BRIDGE_REQUIREMENT"] = requirement
        }
        for (infoKey, environmentKey) in [
            ("KhaosDSHProbeWorkspaceReadPath", "KHAOS_DSH_WORKSPACE_READ_PATH"),
            ("KhaosDSHProbeWorkspaceWritePath", "KHAOS_DSH_WORKSPACE_WRITE_PATH"),
            ("KhaosDSHProbeCredentialPath", "KHAOS_DSH_CREDENTIAL_PATH"),
            ("KhaosDSHProbeKernelPath", "KHAOS_DSH_KERNEL_PATH"),
            ("KhaosDSHProbeLocalPort", "KHAOS_DSH_LOCAL_PORT"),
            ("KhaosDSHCandidateBFixedScriptArgument", "KHAOS_DSH_CANDIDATE_B_FIXED_SCRIPT"),
        ] {
            if let value = Bundle.main.object(forInfoDictionaryKey: infoKey) as? String {
                environment[environmentKey] = value
            }
        }
        if let probeName = Bundle.main.object(
            forInfoDictionaryKey: "KhaosDSHModelBridgeProbePath"
        ) as? String,
           !probeName.isEmpty,
           URL(fileURLWithPath: probeName).lastPathComponent == probeName {
            environment["KHAOS_DSH_MODEL_BRIDGE_PROBE_PATH"] = resources
                .appendingPathComponent(probeName, isDirectory: false).path
        }

        var actions: posix_spawn_file_actions_t? = nil
        guard posix_spawn_file_actions_init(&actions) == 0 else {
            throw DSHAgentHostError.childUnavailable
        }
        defer { posix_spawn_file_actions_destroy(&actions) }
        let nullDescriptor = Darwin.open("/dev/null", O_WRONLY | O_CLOEXEC)
        guard nullDescriptor >= 0 else { throw DSHAgentHostError.childUnavailable }
        defer { Darwin.close(nullDescriptor) }
        let inputRead = inputPipe.fileHandleForReading.fileDescriptor
        let inputWrite = inputPipe.fileHandleForWriting.fileDescriptor
        let outputRead = outputPipe.fileHandleForReading.fileDescriptor
        let outputWrite = outputPipe.fileHandleForWriting.fileDescriptor
        let setup = [
            posix_spawn_file_actions_adddup2(&actions, inputRead, STDIN_FILENO),
            posix_spawn_file_actions_adddup2(&actions, outputWrite, STDOUT_FILENO),
            posix_spawn_file_actions_adddup2(&actions, nullDescriptor, STDERR_FILENO),
            posix_spawn_file_actions_addclose(&actions, inputRead),
            posix_spawn_file_actions_addclose(&actions, inputWrite),
            posix_spawn_file_actions_addclose(&actions, outputRead),
            posix_spawn_file_actions_addclose(&actions, outputWrite),
            posix_spawn_file_actions_addclose(&actions, nullDescriptor),
        ]
        guard setup.allSatisfy({ $0 == 0 }) else { throw DSHAgentHostError.childUnavailable }

        var attributes: posix_spawnattr_t? = nil
        guard posix_spawnattr_init(&attributes) == 0 else {
            throw DSHAgentHostError.childUnavailable
        }
        defer { posix_spawnattr_destroy(&attributes) }
        // The JavaScript runtime receives only its explicit stdio pipes, never
        // unrelated descriptors owned by this untrusted XPC Host.
        guard posix_spawnattr_setflags(
            &attributes,
            Int16(POSIX_SPAWN_SETPGROUP | POSIX_SPAWN_CLOEXEC_DEFAULT)
        ) == 0,
              posix_spawnattr_setpgroup(&attributes, 0) == 0 else {
            throw DSHAgentHostError.childUnavailable
        }

        let argumentValues = [node.path, script.path]
        let environmentValues = environment.map { "\($0.key)=\($0.value)" }
        var argumentPointers = argumentValues.map { strdup($0) } + [nil]
        var environmentPointers = environmentValues.map { strdup($0) } + [nil]
        defer {
            argumentPointers.forEach { free($0) }
            environmentPointers.forEach { free($0) }
        }
        var spawnedID: pid_t = 0
        let spawnStatus = argumentPointers.withUnsafeMutableBufferPointer { arguments in
            environmentPointers.withUnsafeMutableBufferPointer { environment in
                node.path.withCString { executable in
                    posix_spawn(
                        &spawnedID,
                        executable,
                        &actions,
                        &attributes,
                        arguments.baseAddress,
                        environment.baseAddress
                    )
                }
            }
        }
        guard spawnStatus == 0 else { throw DSHAgentHostError.childUnavailable }
        try? inputPipe.fileHandleForReading.close()
        try? outputPipe.fileHandleForWriting.close()
        processID = spawnedID
        processGroupID = spawnedID
        input = inputPipe.fileHandleForWriting
        output = outputPipe.fileHandleForReading
        fputs("dsh-runtime=spawned pid=\(processID) process_group=\(processGroupID)\n", stderr)
        fflush(stderr)
    }

    func beginTask() {
        lock.lock()
        modelCallsThisTask = 0
        telemetrySequence = 0
        telemetryTrialID = nil
        telemetrySessionID = nil
        telemetryBenchmarkTaskID = nil
        lastTelemetryRecord = nil
        lock.unlock()
    }

    func validatesSemanticCorrelation(
        _ correlation: [String: Any],
        proposal: DSHProposal
    ) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard Set(correlation.keys) == Set([
            "trial_id", "dsh_session_id", "benchmark_task_id", "agent_turn_id", "agent_step_id",
            "model_call_id", "tool_call_id", "operation_seq", "tool_name", "invocation_sha256",
        ]) else { return false }
        guard let last = lastTelemetryRecord,
              last["event"] as? String == "LAUNCHER_PROPOSAL_SUBMITTED",
              let trialID = telemetryTrialID,
              let sessionID = telemetrySessionID,
              let benchmarkTaskID = telemetryBenchmarkTaskID,
              correlation["trial_id"] as? String == trialID,
              correlation["dsh_session_id"] as? String == sessionID,
              correlation["benchmark_task_id"] as? String == benchmarkTaskID,
              (correlation["benchmark_task_id"] as? String) == (last["benchmark_task_id"] as? String),
              (correlation["agent_turn_id"] as? Int) == (last["agent_turn_id"] as? Int),
              (correlation["agent_step_id"] as? Int) == (last["agent_step_id"] as? Int),
              (correlation["model_call_id"] as? String) == (last["model_call_id"] as? String),
              (correlation["tool_call_id"] as? String) == (last["tool_call_id"] as? String),
              (correlation["operation_seq"] as? Int) == (last["operation_seq"] as? Int),
              (correlation["tool_name"] as? String) == (last["tool_name"] as? String),
              (correlation["invocation_sha256"] as? String) == (last["invocation_sha256"] as? String),
              let digest = correlation["invocation_sha256"] as? String,
              digest == Self.proposalDigest(proposal) else {
            return false
        }
        return true
    }

    private static func proposalDigest(_ proposal: DSHProposal) -> String {
        let value: [String: Any] = [
            "argv": proposal.argv,
            "readScope": proposal.readScope,
            "writeScope": proposal.writeScope,
        ]
        guard let data = try? JSONSerialization.data(
            withJSONObject: value,
            options: [.sortedKeys, .withoutEscapingSlashes]
        ) else { return "" }
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private func acceptTelemetry(_ record: [String: Any]) -> Bool {
        let allowedKeys: Set<String> = [
            "event", "event_seq", "timestamp_utc", "trial_id", "dsh_session_id", "benchmark_task_id",
            "agent_turn_id", "agent_step_id", "model_call_id", "tool_call_id", "tool_name",
            "operation_seq", "invocation_sha256", "argument_bytes", "file_count",
            "write_operation", "duration_ms", "status", "error_code", "returncode",
            "can_continue", "result_bytes", "result_sha256", "launcher_result_sha256", "observed_tool_result",
            "dsh_event_seq", "token_input", "token_output", "model_provider", "model_id",
            "launcher_task_id", "launcher_request_id", "launcher_approval_sha256", "approval_status",
            "kernel_result", "runner_status", "commit_status", "launcher_ok",
            "turn_end_sequence", "assistant_message_count", "tool_result_count", "turn_end_reason",
            "last_message_role", "last_message_text_only", "unresolved_kernel_result",
            "tool_operations_remaining", "write_operations_remaining", "repair_attempts_remaining",
            "tests_run", "failures", "errors", "skipped",
        ]
        let allowedEvents: Set<String> = [
            "SESSION_STARTED", "MODEL_REQUEST_STARTED", "MODEL_RESPONSE_RECEIVED",
            "MODEL_TOOL_CALL_OUTPUT_ACCEPTED",
            "MODEL_REQUEST_FAILED", "MODEL_OUTPUT_REJECTED", "TOOL_CALL_PARSED",
            "TOOL_ARGUMENT_VALIDATED", "TOOL_ARGUMENT_REJECTED", "TOOL_SUBMISSION_FAILED",
            "TOOL_PROPOSAL_LOWERED",
            "LAUNCHER_PROPOSAL_SUBMITTED", "APPROVAL_ACCEPTED", "APPROVAL_DENIED",
            "KERNEL_OPERATION_STARTED", "KERNEL_OPERATION_COMPLETED",
            "LAUNCHER_TERMINAL_RESULT_DELIVERED", "PUBLIC_TEST_RESULT_VERIFIED", "TOOL_RESULT_DELIVERED",
            "TOOL_OPERATION_ABORTED", "TOOL_RESULT_DISCARDED", "NO_PROGRESS_DETECTED", "TURN_END_OBSERVED",
            "AGENT_NEXT_TURN_STARTED", "SESSION_CONTINUITY_CHECK",
            "DSH_ASSISTANT_MESSAGE_COMMITTED", "AGENT_TERMINATED",
        ]
        func safeID(_ value: Any?) -> String? {
            guard let value = value as? String,
                  value.range(of: #"^[A-Za-z0-9_.:-]{1,128}$"#, options: .regularExpression) != nil else {
                return nil
            }
            return value
        }
        func boundedInteger(_ name: String, maximum: Int) -> Bool {
            guard let value = record[name] else { return true }
            guard let integer = value as? Int else { return false }
            return integer >= 0 && integer <= maximum
        }
        guard Set(record.keys).isSubset(of: allowedKeys),
              let event = record["event"] as? String, allowedEvents.contains(event),
              let sequence = record["event_seq"] as? Int, sequence == telemetrySequence + 1,
              let timestamp = record["timestamp_utc"] as? String,
              timestamp.range(of: #"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"#, options: .regularExpression) != nil,
              let trialID = safeID(record["trial_id"]),
              let sessionID = safeID(record["dsh_session_id"]),
              let benchmarkTaskID = record["benchmark_task_id"] as? String,
              safeID(benchmarkTaskID) != nil,
              boundedInteger("agent_turn_id", maximum: 1_000_000),
              boundedInteger("agent_step_id", maximum: 1_000_000),
              boundedInteger("operation_seq", maximum: 12),
              boundedInteger("argument_bytes", maximum: 32 * 1_024),
              boundedInteger("file_count", maximum: 8),
              boundedInteger("duration_ms", maximum: 600_000),
              boundedInteger("result_bytes", maximum: 4 * 1_024),
              boundedInteger("dsh_event_seq", maximum: 1_000_000),
              boundedInteger("turn_end_sequence", maximum: 1_000_000),
              boundedInteger("assistant_message_count", maximum: 128),
              boundedInteger("tool_result_count", maximum: 128),
              boundedInteger("token_input", maximum: 1_000_000),
              boundedInteger("token_output", maximum: 1_000_000),
              boundedInteger("tool_operations_remaining", maximum: 12),
              boundedInteger("write_operations_remaining", maximum: 3),
              boundedInteger("repair_attempts_remaining", maximum: 3),
              boundedInteger("tests_run", maximum: 10_000),
              boundedInteger("failures", maximum: 10_000),
              boundedInteger("errors", maximum: 10_000),
              boundedInteger("skipped", maximum: 10_000) else {
            return false
        }
        if event == "PUBLIC_TEST_RESULT_VERIFIED" {
            guard record["tool_name"] as? String == "run_tests",
                  let status = record["status"] as? String,
                  ["passed", "failed", "invalid", "unverified", "mismatch"].contains(status) else {
                return false
            }
        }
        if event == "SESSION_STARTED" {
            guard telemetrySequence == 0, telemetryTrialID == nil, telemetrySessionID == nil,
                  telemetryBenchmarkTaskID == nil else { return false }
            telemetryTrialID = trialID
            telemetrySessionID = sessionID
            telemetryBenchmarkTaskID = benchmarkTaskID
        } else if telemetryTrialID != trialID || telemetrySessionID != sessionID
            || telemetryBenchmarkTaskID != benchmarkTaskID {
            return false
        }
        for name in ["model_call_id", "tool_call_id"] where record[name] != nil {
            guard safeID(record[name]) != nil else { return false }
        }
        if let name = record["tool_name"] as? String,
           !["read_file", "replace_text", "run_tests"].contains(name) { return false }
        for name in [
            "invocation_sha256", "result_sha256", "launcher_result_sha256", "launcher_approval_sha256",
        ] where record[name] != nil {
            guard let digest = record[name] as? String,
                  digest.range(of: #"^[0-9a-f]{64}$"#, options: .regularExpression) != nil else { return false }
        }
        for name in [
            "write_operation", "can_continue", "observed_tool_result", "launcher_ok",
            "last_message_text_only", "unresolved_kernel_result",
        ] where record[name] != nil {
            guard record[name] is Bool else { return false }
        }
        for name in [
            "status", "error_code", "model_provider", "model_id", "approval_status",
            "kernel_result", "runner_status", "commit_status",
            "turn_end_reason", "last_message_role",
        ] where record[name] != nil {
            guard let value = record[name] as? String, value.utf8.count <= 128,
                  value.range(of: #"^[A-Za-z0-9_.:-]{1,128}$"#, options: .regularExpression) != nil else { return false }
        }
        for name in ["launcher_task_id", "launcher_request_id"] where record[name] != nil {
            guard safeID(record[name]) != nil else { return false }
        }
        if let rawReturnCode = record["returncode"] {
            guard let returncode = rawReturnCode as? Int,
                  returncode >= Int(Int32.min), returncode <= Int(Int32.max) else { return false }
        }
        telemetrySequence = sequence
        lastTelemetryRecord = record
        return true
    }

    func exchange(
        _ frame: [String: Any],
        modelAPIKey: String? = nil,
        modelBridgeClient: DSHModelBridgeClient? = nil,
        taskDeadlineUptime: TimeInterval? = nil
    ) throws -> [String: Any] {
        lock.lock()
        defer { lock.unlock() }
        guard isRunning() else { throw DSHAgentHostError.childExited }
        try writeFrame(frame)
        var replyTelemetry: [[String: Any]] = []
        var replyTelemetryBytes = 0
        while true {
            let readTimeout: Int
            if modelAPIKey != nil {
                let remaining = taskDeadlineUptime.map {
                    max(1, Int($0 - ProcessInfo.processInfo.systemUptime))
                } ?? 120
                readTimeout = min(120, remaining)
            } else if let deadline = taskDeadlineUptime {
                // A local CPU inference may exceed the ordinary 60-second protocol read, but the
                // enclosing synthetic task deadline remains the hard upper bound.
                readTimeout = max(1, min(DSHModelBridgeLimits.maximumTaskSeconds,
                                         Int(deadline - ProcessInfo.processInfo.systemUptime)))
            } else {
                readTimeout = 60
            }
            let line = try readLine(timeoutSeconds: readTimeout)
            guard let value = try JSONSerialization.jsonObject(with: line) as? [String: Any] else {
                throw DSHAgentHostError.invalidFrame
            }
            if value["type"] as? String == "telemetry" {
                guard let record = value["record"] as? [String: Any],
                      acceptTelemetry(record),
                      let encoded = try? JSONSerialization.data(
                        withJSONObject: record,
                        options: [.sortedKeys, .withoutEscapingSlashes]
                      ), encoded.count <= 4 * 1_024,
                      replyTelemetry.count < 128,
                      replyTelemetryBytes + encoded.count <= maximumTelemetryReplyBytes else {
                    throw DSHAgentHostError.invalidFrame
                }
                replyTelemetry.append(record)
                replyTelemetryBytes += encoded.count
                fputs("dsh-telemetry=\(String(decoding: encoded, as: UTF8.self))\n", stderr)
                fflush(stderr)
                continue
            }
            if value["type"] as? String == "model_diagnostic" {
                // Node's completion metrics are untrusted telemetry; accept only bounded fields and
                // never use them to authorize a workspace or Kernel operation.
                guard let status = value["status"] as? String,
                      status == "ok" || status == "failed" else {
                    throw DSHAgentHostError.invalidFrame
                }
                let elapsed = value["elapsed_ms"] as? Int
                guard let elapsed,
                      (0...DSHModelBridgeLimits.maximumTaskSeconds * 1_000).contains(elapsed) else {
                    throw DSHAgentHostError.invalidFrame
                }
                var diagnostic: [String: Any] = ["status": status, "elapsed_ms": elapsed]
                if let code = value["code"] as? String,
                   code.range(of: #"^[a-z][a-z0-9_]{0,79}$"#, options: .regularExpression) != nil {
                    diagnostic["code"] = code
                }
                if let data = try? JSONSerialization.data(withJSONObject: diagnostic, options: [.sortedKeys]) {
                    fputs("dsh-model-call=\(String(decoding: data, as: UTF8.self))\n", stderr)
                    fflush(stderr)
                }
                continue
            }
            guard value["type"] as? String == "model_request" else {
                var result = value
                if !replyTelemetry.isEmpty { result["dsh_telemetry"] = replyTelemetry }
                return result
            }
            guard let requestID = value["request_id"] as? String,
                  !requestID.isEmpty, requestID.utf8.count <= 64 else {
                throw DSHAgentHostError.invalidFrame
            }

            let call: (completion: [String: Any]?, error: String?, elapsedMilliseconds: Int)
            if modelCallsThisTask >= DSHModelBridgeLimits.maximumModelCallsPerTask {
                call = (nil, "model_call_budget_exceeded", 0)
            } else if let deadline = taskDeadlineUptime,
                      deadline <= ProcessInfo.processInfo.systemUptime {
                call = (nil, "model_provider_timed_out", 0)
            } else {
                modelCallsThisTask += 1
                let remaining = taskDeadlineUptime.map {
                    max(1, Int($0 - ProcessInfo.processInfo.systemUptime))
                } ?? 120
                call = modelBridgeClient?.complete(
                    body: value["body"] as Any,
                    headers: value["headers"] as Any,
                    apiKey: modelAPIKey,
                    timeoutSeconds: min(120, remaining)
                ) ?? (nil, "model_bridge_unavailable", 0)
            }
            let modelCallRecord: [String: Any] = [
                "status": call.error ?? "ok",
                "elapsed_ms": call.elapsedMilliseconds,
                "call_number": modelCallsThisTask,
            ]
            if let diagnostic = try? JSONSerialization.data(
                withJSONObject: modelCallRecord,
                options: [.sortedKeys]
            ) {
                fputs("dsh-model-call=\(String(decoding: diagnostic, as: UTF8.self))\n", stderr)
                fflush(stderr)
            }
            var response: [String: Any] = [
                "operation": "model_result",
                "request_id": requestID,
                "ok": call.error == nil,
                "elapsed_ms": call.elapsedMilliseconds,
            ]
            if let completion = call.completion {
                response["response"] = completion
            }
            if let error = call.error {
                response["error"] = ["code": error]
            }
            try writeFrame(response)
        }
    }

    private func writeFrame(_ frame: [String: Any]) throws {
        let encoded = try JSONSerialization.data(withJSONObject: frame, options: [.sortedKeys])
        guard encoded.count <= AgentHostProtocol.maximumFrameBytes else {
            throw DSHAgentHostError.frameTooLarge
        }
        input.write(encoded)
        input.write(Data([0x0a]))
    }

    func stop() {
        lock.lock()
        defer { lock.unlock() }
        guard !processStopped else { return }
        processStopped = true
        _ = Darwin.kill(-processGroupID, SIGTERM)
        let deadline = Date().addingTimeInterval(2)
        while Date() < deadline {
            _ = reapIfExited()
            if !processGroupExists() { break }
            usleep(10_000)
        }
        if processGroupExists() { _ = Darwin.kill(-processGroupID, SIGKILL) }
        if !processReaped {
            var status: Int32 = 0
            while waitpid(processID, &status, 0) < 0 && errno == EINTR {}
            processReaped = true
        }
        fputs("dsh-runtime=stopped pid=\(processID) process_group=\(processGroupID)\n", stderr)
        fflush(stderr)
    }

    func interrupt() {
        _ = Darwin.kill(-processGroupID, SIGTERM)
    }

    deinit { stop() }

    private func readLine(timeoutSeconds: Int) throws -> Data {
        let descriptor = output.fileDescriptor
        let deadline = Date().addingTimeInterval(TimeInterval(timeoutSeconds))
        var data = Data()
        while Date() < deadline {
            var pollDescriptor = pollfd(fd: descriptor, events: Int16(POLLIN), revents: 0)
            let remaining = max(1, Int(deadline.timeIntervalSinceNow * 1_000))
            let ready = Darwin.poll(&pollDescriptor, 1, Int32(min(remaining, Int(Int32.max))))
            if ready < 0 {
                if errno == EINTR { continue }
                throw DSHAgentHostError.childExited
            }
            if ready == 0 { throw DSHAgentHostError.timedOut }
            var byte: UInt8 = 0
            let count = Darwin.read(descriptor, &byte, 1)
            if count == 0 { throw DSHAgentHostError.childExited }
            if count < 0 {
                if errno == EINTR { continue }
                throw DSHAgentHostError.childExited
            }
            if byte == 0x0a { return data }
            data.append(byte)
            guard data.count <= AgentHostProtocol.maximumFrameBytes else {
                throw DSHAgentHostError.frameTooLarge
            }
        }
        throw DSHAgentHostError.timedOut
    }

    private func isRunning() -> Bool {
        !reapIfExited()
    }

    private func reapIfExited() -> Bool {
        if processReaped { return true }
        var status: Int32 = 0
        let result = waitpid(processID, &status, WNOHANG)
        if result == processID || (result < 0 && errno == ECHILD) {
            processReaped = true
            return true
        }
        return false
    }

    private func processGroupExists() -> Bool {
        if Darwin.kill(-processGroupID, 0) == 0 { return true }
        return errno == EPERM
    }
}

private final class DSHAgentHostSession: NSObject, AgentHostSessionEndpoint {
    private let lock = NSLock()
    private var runtime: DSHRuntimeProcess?
    private var modelBridgeClient: DSHModelBridgeClient?
    private var handlingRequest = false
    private var awaitingToolResult = false
    private var crashAfterToolResult = false
    private var cancelled = false
    private var realModelTask = false
    private var phase31Task = false
    private var pendingSemanticCorrelation: [String: Any]?
    private var taskDeadlineUptime: TimeInterval?

    override init() {
        super.init()
    }

    func handle(
        _ frame: NSData,
        modelBridgeEndpoint: NSXPCListenerEndpoint?,
        withReply reply: @escaping (NSData?) -> Void
    ) {
        let data = Data(referencing: frame)
        guard data.count <= AgentHostProtocol.maximumFrameBytes else {
            reply(response(.failure("invalid_request")).map(NSData.init(data:)))
            return
        }
        lock.lock()
        guard !handlingRequest else {
            lock.unlock()
            reply(response(.failure("invalid_request")).map(NSData.init(data:)))
            return
        }
        handlingRequest = true
        lock.unlock()

        DispatchQueue.global(qos: .userInitiated).async {
            let result = self.process(data, modelBridgeEndpoint: modelBridgeEndpoint)
            self.lock.lock()
            self.handlingRequest = false
            self.lock.unlock()
            reply(result.map(NSData.init(data:)))
        }
    }

    private func process(
        _ data: Data,
        modelBridgeEndpoint: NSXPCListenerEndpoint?
    ) -> Data? {
        guard let frame = AgentHostProtocol.decodeInput(data),
              let operation = frame["operation"] as? String else {
            return response(.failure("invalid_request"))
        }
        lock.lock()
        let isCancelled = cancelled
        lock.unlock()
        guard !isCancelled else { return response(.failure("dsh_runtime_unavailable")) }
        if AgentModelProvider.from(bundle: .main).isRemote {
            guard let modelBridgeEndpoint,
                  let client = try? DSHModelBridgeClient(endpoint: modelBridgeEndpoint) else {
                return response(.failure("model_bridge_unavailable"))
            }
            lock.lock()
            modelBridgeClient = client
            lock.unlock()
        }
        if operation == "stop" {
            let current = runtimeSnapshot()
            current?.stop()
            replaceRuntime(nil)
            return nil
        }
        if runtimeSnapshot() == nil {
            guard operation == "user" else {
                return response(.failure("dsh_runtime_unavailable"))
            }
            guard let created = try? DSHRuntimeProcess(
                modelBridgeAvailable: modelBridgeClient != nil
            ) else {
                return response(.failure("dsh_runtime_unavailable"))
            }
            replaceRuntime(created)
        }
        guard let runtime = runtimeSnapshot() else { return response(.failure("dsh_runtime_unavailable")) }

        var failureStage = "request"
        do {
            switch operation {
            case "user":
                guard !awaitingToolResult,
                      let text = frame["text"] as? String else {
                    return response(.failure("invalid_request"))
                }
                crashAfterToolResult = text.contains("KHAOS_DSH_AGENTHOST_CRASH_ON_TOOL_RESULT")
                let realModelPrefix = "KHAOS_DSH_REAL_MODEL_CODING: "
                let phase31RealPrefix = "KHAOS_DSH_PHASE3_1_REAL: "
                let phase31FixturePrefix = "KHAOS_DSH_PHASE3_1_FIXTURE: "
                phase31Task = text.hasPrefix(phase31RealPrefix) || text.hasPrefix(phase31FixturePrefix)
                realModelTask = text.hasPrefix(realModelPrefix) || text.hasPrefix(phase31RealPrefix)
                pendingSemanticCorrelation = nil
                let taskText: String
                if text.hasPrefix(realModelPrefix) {
                    taskText = String(text.dropFirst(realModelPrefix.count))
                } else if text.hasPrefix(phase31RealPrefix) {
                    taskText = String(text.dropFirst(phase31RealPrefix.count))
                } else if text.hasPrefix(phase31FixturePrefix) {
                    taskText = String(text.dropFirst(phase31FixturePrefix.count))
                } else {
                    taskText = text
                }
                guard !taskText.isEmpty else { return response(.failure("invalid_request")) }
                if realModelTask {
                    let provider = AgentModelProvider.from(bundle: .main)
                    if provider.isRemote {
                        guard frame["model_api_key"] as? String != nil else {
                            return response(.failure("model_credentials_unavailable"))
                        }
                        guard modelBridgeClient != nil else {
                            return response(.failure("model_bridge_unavailable"))
                        }
                    } else {
                        let contents = Bundle.main.bundleURL.appendingPathComponent("Contents", isDirectory: true)
                        let executable = contents.appendingPathComponent(
                            "Frameworks/KhaosLlama/llama-cli", isDirectory: false
                        )
                        let model = contents.appendingPathComponent(
                            "Resources/agent-model.gguf", isDirectory: false
                        )
                        guard FileManager.default.isExecutableFile(atPath: executable.path),
                              FileManager.default.fileExists(atPath: model.path),
                              let modelDigest = Bundle.main.object(
                                forInfoDictionaryKey: "KhaosLocalModelSHA256"
                              ) as? String,
                              modelDigest.range(of: #"^[0-9a-f]{64}$"#,
                                                options: .regularExpression) != nil else {
                            return response(.failure("local_model_bundle_unavailable"))
                        }
                    }
                }
                if realModelTask || phase31Task {
                    taskDeadlineUptime = ProcessInfo.processInfo.systemUptime
                        + TimeInterval(DSHModelBridgeLimits.maximumTaskSeconds)
                    runtime.beginTask()
                } else {
                    taskDeadlineUptime = nil
                }
                failureStage = "runtime_exchange"
                let event = try runtime.exchange(
                    ["operation": "user", "text": text],
                    modelAPIKey: realModelTask && AgentModelProvider.from(bundle: .main).isRemote
                        ? frame["model_api_key"] as? String : nil,
                    modelBridgeClient: modelBridgeClient,
                    taskDeadlineUptime: taskDeadlineUptime
                )
                failureStage = "action_encode"
                return try encodeAgentAction(
                    event,
                    activePlugin: AgentHostProtocol.activePlugin(in: frame),
                    runtime: runtime
                )
            case "tool_result":
                guard awaitingToolResult,
                      let ok = frame["ok"] as? Bool,
                      let canContinue = frame["can_continue"] as? Bool,
                      let text = frame["text"] as? String else {
                    return response(.failure("invalid_request"))
                }
                if let correlation = pendingSemanticCorrelation {
                    let launcherTrace = frame["launcher_trace"] as? [String: Any]
                    guard !phase31Task || launcherTrace.map({
                        launcherTraceMatches($0, correlation: correlation)
                    }) == true else {
                        return response(.failure("dsh_launcher_trace_mismatch"))
                    }
                    logLauncherTerminalResult(
                        correlation,
                        launcherTrace: launcherTrace,
                        ok: ok,
                        canContinue: canContinue,
                        text: text
                    )
                    pendingSemanticCorrelation = nil
                } else if phase31Task || frame["launcher_trace"] != nil {
                    return response(.failure("dsh_unexpected_launcher_trace"))
                }
                if crashAfterToolResult {
                    crashAfterToolResult = false
                    exit(86)
                }
                var toolResult: [String: Any] = [
                    "operation": "tool_result",
                    "ok": ok,
                    "can_continue": canContinue,
                    "text": text,
                ]
                if let returncode = frame["returncode"] as? Int {
                    toolResult["returncode"] = returncode
                }
                if let launcherTrace = frame["launcher_trace"] as? [String: Any] {
                    toolResult["launcher_trace"] = launcherTrace
                }
                failureStage = "runtime_exchange"
                let event = try runtime.exchange(
                    toolResult,
                    modelAPIKey: realModelTask && AgentModelProvider.from(bundle: .main).isRemote
                        ? frame["model_api_key"] as? String : nil,
                    modelBridgeClient: modelBridgeClient,
                    taskDeadlineUptime: taskDeadlineUptime
                )
                failureStage = "action_encode"
                return try encodeAgentAction(
                    event,
                    activePlugin: AgentHostProtocol.activePlugin(in: frame),
                    runtime: runtime
                )
            default:
                return response(.failure("invalid_request"))
            }
        } catch {
            let failureCategory: String
            if let rejection = error as? AgentActionRejection {
                failureCategory = rejection.rawValue
            } else {
                switch error as? DSHAgentHostError {
                case .childUnavailable: failureCategory = "child_unavailable"
                case .frameTooLarge: failureCategory = "frame_too_large"
                case .invalidFrame: failureCategory = "invalid_frame"
                case .timedOut: failureCategory = "timed_out"
                case .childExited: failureCategory = "child_exited"
                case nil: failureCategory = "exchange_error"
                }
            }
            fputs("dsh-agenthost-failure stage=\(failureStage) category=\(failureCategory)\n", stderr)
            fflush(stderr)
            runtime.stop()
            replaceRuntime(nil)
            awaitingToolResult = false
            realModelTask = false
            taskDeadlineUptime = nil
            let failureCode: String
            if !phase31Task {
                failureCode = "dsh_runtime_failed"
            } else if failureStage == "runtime_exchange" {
                failureCode = "dsh_runtime_exchange_\(failureCategory)"
            } else if failureStage == "action_encode",
                      error is AgentActionRejection {
                failureCode = "dsh_action_encode_\(failureCategory)"
            } else {
                failureCode = "dsh_\(failureStage)_failed"
            }
            return response(.failure(failureCode))
        }
    }

    func cancel() {
        lock.lock()
        cancelled = true
        let current = runtime
        lock.unlock()
        current?.interrupt()
        if let current {
            DispatchQueue.global(qos: .utility).async { current.stop() }
        }
    }

    private func runtimeSnapshot() -> DSHRuntimeProcess? {
        lock.lock()
        defer { lock.unlock() }
        return runtime
    }

    private func replaceRuntime(_ value: DSHRuntimeProcess?) {
        lock.lock()
        runtime = value
        lock.unlock()
    }

    private func encodeAgentAction(
        _ event: [String: Any],
        activePlugin: AgentHostPluginMetadata?,
        runtime: DSHRuntimeProcess
    ) throws -> Data? {
        guard let type = event["type"] as? String else {
            return response(.failure("dsh_invalid_result"))
        }
        let action: AgentAction
        switch type {
        case "proposal":
            guard let proposalObject = event["proposal"] as? [String: Any],
                  let proposalData = try? JSONSerialization.data(withJSONObject: proposalObject),
                  let proposal = try? JSONDecoder().decode(DSHProposal.self, from: proposalData) else {
                return response(.failure("dsh_invalid_proposal"))
            }
            if phase31Task {
                guard let correlation = event["correlation"] as? [String: Any],
                      runtime.validatesSemanticCorrelation(correlation, proposal: proposal),
                      pendingSemanticCorrelation == nil else {
                    return response(.failure("dsh_invalid_semantic_correlation"))
                }
                pendingSemanticCorrelation = correlation
                logSemanticProposal(correlation)
            } else {
                guard event["correlation"] == nil else {
                    return response(.failure("dsh_invalid_semantic_correlation"))
                }
            }
            let proposalRecord: [String: Any] = [
                "argv": proposal.argv,
                "read_scope": proposal.readScope,
                "write_scope": proposal.writeScope,
            ]
            if !phase31Task, let diagnostic = try? JSONSerialization.data(
                withJSONObject: proposalRecord,
                options: [.sortedKeys, .withoutEscapingSlashes]
            ), diagnostic.count <= 16 * 1_024 {
                fputs("dsh-tool-proposal=\(String(decoding: diagnostic, as: UTF8.self))\n", stderr)
                fflush(stderr)
            }
            awaitingToolResult = true
            action = AgentAction(
                type: "shell",
                text: "",
                argv: proposal.argv,
                readScope: proposal.readScope,
                writeScope: proposal.writeScope,
                pluginID: "",
                candidateDigest: "",
                generation: 0,
                pluginInput: "",
                evolutionGoal: ""
            )
        case "reply":
            guard let responseText = event["text"] as? String else {
                return response(.failure("dsh_invalid_result"))
            }
            if !phase31Task, let toolResults = event["toolResults"],
               JSONSerialization.isValidJSONObject(toolResults),
               let data = try? JSONSerialization.data(
                withJSONObject: toolResults,
                options: [.sortedKeys, .withoutEscapingSlashes]
               ), data.count <= 48 * 1_024 {
                fputs("dsh-tool-results=\(String(decoding: data, as: UTF8.self))\n", stderr)
                fflush(stderr)
            }
            if let statistics = event["model_stats"] as? [String: Any],
               JSONSerialization.isValidJSONObject(statistics),
               let data = try? JSONSerialization.data(withJSONObject: statistics, options: [.sortedKeys]),
               data.count <= 1_024 {
                fputs("dsh-model-stats=\(String(decoding: data, as: UTF8.self))\n", stderr)
                fflush(stderr)
            }
            if let diagnostics = event["diagnostics"] as? [String: Any] {
                let safeDiagnostics: [String: Any] = [
                    "assistant_message_count": diagnostics["assistantMessageCount"] ?? NSNull(),
                    "tool_result_count": diagnostics["toolResultCount"] ?? NSNull(),
                    "last_message_role": diagnostics["lastMessageRole"] ?? NSNull(),
                    "last_message_block_types": diagnostics["lastMessageBlockTypes"] ?? NSNull(),
                    "terminal_status": diagnostics["terminalStatus"] ?? NSNull(),
                    "incomplete_reason": diagnostics["incompleteReason"] ?? NSNull(),
                    "turn_end_reason": diagnostics["turnEndReason"] ?? NSNull(),
                    "turn_end_sequence": diagnostics["turnEndSequence"] ?? NSNull(),
                    "adapter_rejected_proposal_count": diagnostics["adapterRejectedProposalCount"] ?? NSNull(),
                    "agent_error_count": (diagnostics["agentErrors"] as? [Any])?.count ?? 0,
                ]
                if let data = try? JSONSerialization.data(
                    withJSONObject: safeDiagnostics,
                    options: [.sortedKeys]
                ), data.count <= 1_024 {
                    fputs("dsh-agent-loop=\(String(decoding: data, as: UTF8.self))\n", stderr)
                    fflush(stderr)
                }
            }
            awaitingToolResult = false
            realModelTask = false
            taskDeadlineUptime = nil
            action = AgentAction(
                type: "text",
                text: responseText,
                argv: [],
                readScope: [],
                writeScope: [],
                pluginID: "",
                candidateDigest: "",
                generation: 0,
                pluginInput: "",
                evolutionGoal: ""
            )
        default:
            return response(.failure("dsh_invalid_result"))
        }
        let encoded = try AgentHostActionOutput.encodeAction(action, activePlugin: activePlugin)
        guard phase31Task,
              let records = event["dsh_telemetry"] as? [[String: Any]],
              !records.isEmpty,
              let object = try JSONSerialization.jsonObject(with: encoded) as? [String: Any] else {
            return encoded
        }
        var responseObject = object
        responseObject["dsh_telemetry"] = records
        let responseData = try JSONSerialization.data(
            withJSONObject: responseObject,
            options: [.sortedKeys, .withoutEscapingSlashes]
        )
        guard responseData.count <= AgentHostProtocol.maximumFrameBytes else {
            return response(.failure("dsh_telemetry_frame_too_large"))
        }
        return responseData
    }

    private func logSemanticProposal(_ correlation: [String: Any]) {
        var record = correlation
        record["event"] = "SEMANTIC_PROPOSAL_FORWARDED"
        guard let data = try? JSONSerialization.data(
            withJSONObject: record,
            options: [.sortedKeys, .withoutEscapingSlashes]
        ), data.count <= 2 * 1_024 else { return }
        fputs("dsh-semantic-proposal=\(String(decoding: data, as: UTF8.self))\n", stderr)
        fflush(stderr)
    }

    private func logLauncherTerminalResult(
        _ correlation: [String: Any],
        launcherTrace: [String: Any]?,
        ok: Bool,
        canContinue: Bool,
        text: String
    ) {
        var record = correlation
        let digest = SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
        record["event"] = "LAUNCHER_TERMINAL_RESULT_DELIVERED"
        record["launcher_ok"] = ok
        record["launcher_can_continue"] = canContinue
        record["result_bytes"] = text.utf8.count
        record["result_sha256"] = digest
        if let launcherTrace {
            for key in [
                "launcher_task_id", "launcher_request_id", "launcher_approval_sha256",
                "approval_status", "kernel_result", "runner_status", "commit_status", "returncode",
            ] {
                record[key] = launcherTrace[key]
            }
        }
        guard let data = try? JSONSerialization.data(
            withJSONObject: record,
            options: [.sortedKeys, .withoutEscapingSlashes]
        ), data.count <= 2 * 1_024 else { return }
        fputs("dsh-launcher-terminal=\(String(decoding: data, as: UTF8.self))\n", stderr)
        fflush(stderr)
    }

    private func launcherTraceMatches(
        _ trace: [String: Any],
        correlation: [String: Any]
    ) -> Bool {
        [
            "trial_id", "dsh_session_id", "benchmark_task_id", "agent_turn_id", "agent_step_id",
            "model_call_id", "tool_call_id", "tool_name", "operation_seq", "invocation_sha256",
        ].allSatisfy { trace[$0] as? NSObject == correlation[$0] as? NSObject }
            && trace["launcher_task_id"] is String
            && trace["launcher_request_id"] is String
            && trace["launcher_approval_sha256"] is String
            && trace["approval_status"] is String
            && trace["kernel_result"] is String
            && trace["runner_status"] is String
            && trace["commit_status"] is String
    }

    private func response(_ reply: AgentHostReply) -> Data? {
        try? AgentHostProtocol.encodeReply(reply)
    }
}

private final class DSHAgentHostService: NSObject, NSXPCListenerDelegate {
    private let listener = NSXPCListener.service()
    private let launcherRequirement: String

    init(launcherRequirement: String) {
        self.launcherRequirement = launcherRequirement
    }

    func run() {
        listener.delegate = self
        listener.resume()
        RunLoop.main.run()
    }

    func listener(
        _ listener: NSXPCListener,
        shouldAcceptNewConnection connection: NSXPCConnection
    ) -> Bool {
        connection.setCodeSigningRequirement(launcherRequirement)
        let interface = NSXPCInterface(with: AgentHostSessionEndpoint.self)
        connection.exportedInterface = interface
        let session = DSHAgentHostSession()
        connection.exportedObject = session
        connection.invalidationHandler = { [weak session] in session?.cancel() }
        connection.resume()
        return true
    }
}

@main
enum DSHAgentHostMain {
    static func main() {
        guard let requirement = Bundle.main.object(
            forInfoDictionaryKey: "KhaosLauncherRequirement"
        ) as? String,
        !requirement.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            exit(EXIT_FAILURE)
        }
        let service = DSHAgentHostService(launcherRequirement: requirement)
        service.run()
    }
}
