#!/usr/bin/env python3
"""Build a disposable signed Seed app with DSH in a test-only AgentHost XPC."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import build_macos_seed as seed_builder  # noqa: E402
from run_dsh_signed_runtime_probe import (  # noqa: E402
    PINNED_DSH_SHA,
    PINNED_NODE_ARCHIVE_SHA256,
    PINNED_NODE_VERSION,
    PINNED_PNPM,
    build_dsh_bundle,
    digest,
    output,
)
from experimental_artifact_retention import (  # noqa: E402
    disk_space_preflight,
    local_model_size,
)


KHAOS_BASE_SHA = "b08ab11e01663d2b26304cb541efb5361dea0417"
REPLACED_SOURCE = "khaos/macos/AgentHost.swift"
REMOTE_MODEL_DISCLOSURE_SOURCE = "khaos/macos/TrustedWorkspaceLauncherMain.swift"
EXPERIMENTAL_MODEL_ID = "glm-5.3"
LOCAL_MODEL_ID = "bundled-cpu"
DSH_MODEL_BRIDGE_ID = "org.khaos.Seed.DSHModelBridge"


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def signed_entitlements(path: Path) -> dict[str, object]:
    result = subprocess.run(
        ["codesign", "-d", "--entitlements", ":-", str(path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    for output in (result.stdout, result.stderr):
        try:
            value = plistlib.loads(output)
        except Exception:
            continue
        if isinstance(value, dict):
            return value
    raise RuntimeError(f"could not read signed entitlements from {path.name}")


def candidate_b_fixed_script(candidate_probe: Path) -> str:
    result = run([str(candidate_probe), "--fixed-script-json"])
    payload = json.loads(result.stdout)
    fixed_script = payload.get("fixed_script") if isinstance(payload, dict) else None
    if not isinstance(fixed_script, str) or not fixed_script:
        raise RuntimeError("Candidate B probe returned no fixed script")
    return fixed_script


def local_model_inputs(app_path: Path) -> tuple[Path, Path, Path, dict[str, object]]:
    source_app = app_path.expanduser().resolve(strict=True)
    run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(source_app)])
    host_contents = source_app / "Contents/XPCServices/KhaosAgentHost.xpc/Contents"
    executable = host_contents / "Frameworks/KhaosLlama/llama-cli"
    model = host_contents / "Resources/agent-model.gguf"
    license_file = host_contents / "Resources/THIRD_PARTY_NOTICES/AgentModel-LICENSE"
    info_path = host_contents / "Info.plist"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError("local model app has no executable CPU llama.cpp runtime")
    if not model.is_file() or model.stat().st_nlink != 1 or not 0 < model.stat().st_size <= 24 * 1024**3:
        raise RuntimeError("local model must be a bounded, single-link regular file")
    if not license_file.is_file() or license_file.stat().st_size > 1024**2:
        raise RuntimeError("local model app is missing its bounded model license")
    with info_path.open("rb") as stream:
        host_info = plistlib.load(stream)
    model_sha = seed_builder._sha256_file(model)
    if host_info.get("KhaosLocalModelSHA256") != model_sha:
        raise RuntimeError("local model digest does not match its signed AgentHost metadata")
    otool = shutil.which("otool")
    if otool is None:
        raise RuntimeError("otool is required to inspect the CPU model runtime")
    linked = run([otool, "-L", str(executable)]).stdout.lower()
    if "metal.framework" in linked or "metalperformance" in linked:
        raise RuntimeError("local model runtime links a Metal framework")
    metadata: dict[str, object] = {
        "model_id": LOCAL_MODEL_ID,
        "model_sha256": model_sha,
        "model_bytes": model.stat().st_size,
        "llama_cli_sha256": seed_builder._sha256_file(executable),
        "model_license_sha256": seed_builder._sha256_file(license_file),
        "model_runtime": host_info.get("KhaosLocalModelRuntime"),
        "network": "none; offline llama.cpp child of the network-denied AgentHost",
        "compute_backend": "CPU only; no Metal framework dependency",
    }
    return executable, model, license_file, metadata


def preflight_local_model_build(
    app_path: Path,
    output_parent: Path,
) -> dict[str, int | str | bool]:
    source_app = app_path.expanduser().resolve(strict=True)
    model_path = (
        source_app
        / "Contents/XPCServices/KhaosAgentHost.xpc/Contents/Resources/agent-model.gguf"
    )
    report = disk_space_preflight(local_model_size(model_path), output_parent)
    if report["status"] != "PASS":
        raise RuntimeError(
            "INSUFFICIENT_DISK_SPACE: need "
            f"{report['required_free_bytes']} bytes, have {report['free_bytes']} bytes"
        )
    return report


def apply_experimental_model_disclosure(source_root: Path) -> dict[str, str]:
    path = source_root / REMOTE_MODEL_DISCLOSURE_SOURCE
    original = path.read_text(encoding="utf-8")
    old = (
        '            ? "BigModel GLM-5.3-Flash Coding Plan"\n'
        '            : "BigModel GLM-5.3-Flash"'
    )
    replacement = (
        f'            ? "BigModel GLM-5.3 Coding Plan (model id: {EXPERIMENTAL_MODEL_ID})"\n'
        f'            : "BigModel GLM-5.3 (model id: {EXPERIMENTAL_MODEL_ID})"'
    )
    if original.count(old) != 1:
        raise RuntimeError("expected one remote model disclosure string in the Launcher source")
    no_remote_attack_consent = (
        "            if modelProvider.isRemote,\n"
        "               !approveRemoteModelData(\n"
    )
    test_only_no_remote_attack_consent = (
        "            if modelProvider.isRemote,\n"
        "               prompt != \"KHAOS_DSH_XPC_ATTACK\",\n"
        "               !approveRemoteModelData(\n"
    )
    if original.count(no_remote_attack_consent) != 1:
        raise RuntimeError("expected one Launcher remote-data consent gate")
    transformed = original.replace(old, replacement).replace(
        no_remote_attack_consent,
        test_only_no_remote_attack_consent,
    )
    path.write_text(transformed, encoding="utf-8")
    return {
        "path": REMOTE_MODEL_DISCLOSURE_SOURCE,
        "original_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
        "experimental_sha256": digest(path),
        "reason": "show the fixed model id and bypass remote consent only for the exact deterministic hostile-XPC marker, which uses the MockAdapter and sends no task data",
    }


def apply_experimental_model_bridge_client(source_root: Path) -> dict[str, str]:
    relative_path = "khaos/macos/AgentHostClient.swift"
    path = source_root / relative_path
    original = path.read_text(encoding="utf-8")
    transformed = original
    replacements = (
        (
            "    private let modelAPIKey: String?\n",
            "    private let modelAPIKey: String?\n"
            "    private let modelBridgeEndpoint: NSXPCListenerEndpoint?\n"
            "    private let modelBridgeBootstrapConnection: NSXPCConnection?\n",
        ),
        (
            "        let provider = AgentModelProvider.from(bundle: .main)\n"
            "        modelAPIKey = provider.isRemote\n"
            "            ? ProcessInfo.processInfo.environment[\"KHAOS_BIGMODEL_API_KEY\"]\n"
            "            : nil\n"
            "        connection = NSXPCConnection(serviceName: \"org.khaos.Seed.AgentHost\")\n"
            "        connection.remoteObjectInterface = NSXPCInterface(\n"
            "            with: AgentHostSessionEndpoint.self\n"
            "        )\n"
            "        connection.resume()\n",
            "        let provider = AgentModelProvider.from(bundle: .main)\n"
            "        modelAPIKey = provider.isRemote\n"
            "            ? ProcessInfo.processInfo.environment[\"KHAOS_BIGMODEL_API_KEY\"]\n"
            "            : nil\n"
            "        let bridge = provider.isRemote\n"
            "            ? DSHModelBridgeBootstrapClient.connectIfAvailable()\n"
            "            : nil\n"
            "        modelBridgeEndpoint = bridge?.endpoint\n"
            "        modelBridgeBootstrapConnection = bridge?.connection\n"
            "        connection = NSXPCConnection(serviceName: \"org.khaos.Seed.AgentHost\")\n"
            "        let interface = NSXPCInterface(with: AgentHostSessionEndpoint.self)\n"
            "        connection.remoteObjectInterface = interface\n"
            "        connection.resume()\n",
        ),
        (
            "        endpoint.handle(NSData(data: frame)) { value in\n",
            "        endpoint.handle(\n"
            "            NSData(data: frame),\n"
            "            modelBridgeEndpoint: modelBridgeEndpoint\n"
            "        ) { value in\n",
        ),
        (
            "        endpoint.handle(NSData(data: frame)) { [weak self] value in\n",
            "        endpoint.handle(\n"
            "            NSData(data: frame),\n"
            "            modelBridgeEndpoint: modelBridgeEndpoint\n"
            "        ) { [weak self] value in\n",
        ),
    )
    for replacement in replacements:
        old, new = replacement[:2]
        expected = replacement[2] if len(replacement) == 3 else 1
        if transformed.count(old) != expected:
            raise RuntimeError(f"unexpected AgentHostClient overlay target count in {relative_path}")
        transformed = transformed.replace(old, new)
    helper = '''
private enum DSHModelBridgeBootstrapClient {
    static func connectIfAvailable() -> (endpoint: NSXPCListenerEndpoint, connection: NSXPCConnection)? {
        guard let requirement = Bundle.main.object(
            forInfoDictionaryKey: DSHModelBridgeLimits.bridgeRequirementInfoKey
        ) as? String,
        !requirement.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return nil
        }
        let connection = NSXPCConnection(serviceName: DSHModelBridgeLimits.serviceName)
        connection.setCodeSigningRequirement(requirement)
        let interface = NSXPCInterface(with: DSHModelBridgeBootstrapEndpoint.self)
        connection.remoteObjectInterface = interface
        let lock = NSLock()
        let completed = DispatchSemaphore(value: 0)
        var finished = false
        var received: NSXPCListenerEndpoint?
        let finish: (NSXPCListenerEndpoint?) -> Void = { endpoint in
            lock.lock()
            guard !finished else {
                lock.unlock()
                return
            }
            finished = true
            received = endpoint
            lock.unlock()
            completed.signal()
        }
        connection.invalidationHandler = { finish(nil) }
        connection.interruptionHandler = { finish(nil) }
        connection.resume()
        guard let bootstrap = connection.remoteObjectProxyWithErrorHandler({ _ in
            finish(nil)
        }) as? DSHModelBridgeBootstrapEndpoint else {
            connection.invalidate()
            return nil
        }
        bootstrap.modelEndpoint { finish($0) }
        guard completed.wait(timeout: .now() + .seconds(10)) == .success else {
            connection.invalidate()
            return nil
        }
        lock.lock()
        let endpoint = received
        lock.unlock()
        guard let endpoint else {
            connection.invalidate()
            return nil
        }
        return (endpoint, connection)
    }
}

'''
    marker = "final class AgentHostClient {\n"
    if transformed.count(marker) != 1:
        raise RuntimeError("expected one AgentHostClient declaration")
    transformed = transformed.replace(marker, helper + marker)
    path.write_text(transformed, encoding="utf-8")
    return {
        "path": relative_path,
        "original_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
        "experimental_sha256": digest(path),
        "reason": "bootstrap the bounded model XPC from the trusted Launcher and pass only its opaque endpoint to the signed AgentHost",
    }


def apply_experimental_tool_trace_protocol(source_root: Path) -> dict[str, str]:
    relative_path = "khaos/macos/AgentHostProtocol.swift"
    path = source_root / relative_path
    original = path.read_text(encoding="utf-8")
    transformed = original
    old_tool_result = (
        '            ], allowModelAPIKey: true),\n'
        '                  let ok = object["ok"] as? Bool,\n'
    )
    new_tool_result = (
        '            ], allowModelAPIKey: true, allowExperimentalToolTrace: true),\n'
        '                  let ok = object["ok"] as? Bool,\n'
    )
    if transformed.count(old_tool_result) != 1:
        raise RuntimeError("expected one tool_result input validation clause")
    transformed = transformed.replace(old_tool_result, new_tool_result)
    old_signature = (
        "        allowModelAPIKey: Bool\n"
        "    ) -> Bool {\n"
        "        var expected = required\n"
    )
    new_signature = (
        "        allowModelAPIKey: Bool,\n"
        "        allowExperimentalToolTrace: Bool = false\n"
        "    ) -> Bool {\n"
        "        var expected = required\n"
    )
    if transformed.count(old_signature) != 1:
        raise RuntimeError("expected one protocol input-key validator signature")
    transformed = transformed.replace(old_signature, new_signature)
    old_return = "        return Set(object.keys) == expected\n    }\n\n    private static func validModelAPIKey"
    new_return = '''        if object.keys.contains("returncode") || object.keys.contains("launcher_trace") {
            guard allowExperimentalToolTrace else { return false }
            if object.keys.contains("returncode") {
                guard validExperimentalReturnCode(object["returncode"]) else { return false }
                expected.insert("returncode")
            }
            if object.keys.contains("launcher_trace") {
                guard validExperimentalLauncherTrace(object["launcher_trace"]) else { return false }
                expected.insert("launcher_trace")
            }
        }
        return Set(object.keys) == expected
    }

    private static func validExperimentalReturnCode(_ value: Any?) -> Bool {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite,
              number.doubleValue.rounded(.towardZero) == number.doubleValue else { return false }
        return number.int64Value >= Int64(Int32.min) && number.int64Value <= Int64(Int32.max)
    }

    private static func validExperimentalLauncherTrace(_ value: Any?) -> Bool {
        guard let record = value as? [String: Any] else { return false }
        let required: Set<String> = [
            "trial_id", "dsh_session_id", "runtime_trial_id", "benchmark_task_id", "agent_turn_id", "agent_step_id",
            "tool_call_id", "tool_name", "operation_seq", "invocation_sha256",
            "launcher_task_id", "launcher_request_id", "launcher_approval_sha256",
            "approval_status", "kernel_result", "runner_status", "commit_status",
            "launcher_ok", "can_continue",
        ]
        let optional: Set<String> = ["model_call_id", "returncode"]
        guard required.isSubset(of: Set(record.keys)),
              Set(record.keys).subtracting(required).isSubset(of: optional) else { return false }
        func safeID(_ key: String) -> Bool {
            guard let value = record[key] as? String else { return false }
            return value.range(of: #"^[A-Za-z0-9_.:-]{1,128}$"#, options: .regularExpression) != nil
        }
        func safeStatus(_ key: String) -> Bool {
            guard let value = record[key] as? String else { return false }
            return value.range(of: #"^[A-Za-z0-9_.:-]{1,128}$"#, options: .regularExpression) != nil
        }
        func safeInteger(_ key: String, minimum: Int, maximum: Int) -> Bool {
            guard let number = record[key] as? NSNumber,
                  CFGetTypeID(number) != CFBooleanGetTypeID(),
                  number.doubleValue.isFinite,
                  number.doubleValue.rounded(.towardZero) == number.doubleValue else { return false }
            return number.int64Value >= Int64(minimum) && number.int64Value <= Int64(maximum)
        }
        func safeBoolean(_ key: String) -> Bool {
            guard let number = record[key] as? NSNumber else { return false }
            return CFGetTypeID(number) == CFBooleanGetTypeID()
        }
        guard ["trial_id", "dsh_session_id", "runtime_trial_id", "tool_call_id", "launcher_task_id", "launcher_request_id"]
                .allSatisfy(safeID),
              ["agent_turn_id", "agent_step_id"].allSatisfy({ safeInteger($0, minimum: 0, maximum: 1_000_000) }),
              safeInteger("operation_seq", minimum: 1, maximum: 12),
              ["benchmark_task_id", "tool_name", "approval_status", "kernel_result", "runner_status", "commit_status"]
                .allSatisfy(safeStatus),
              ["read_file", "replace_text", "run_tests"].contains(record["tool_name"] as? String ?? ""),
              ["invocation_sha256", "launcher_approval_sha256"].allSatisfy({ key in
                  (record[key] as? String)?.range(of: #"^[0-9a-f]{64}$"#, options: .regularExpression) != nil
              }),
              safeBoolean("launcher_ok"), safeBoolean("can_continue"),
              record["model_call_id"] == nil || safeID("model_call_id"),
              record["returncode"] == nil || validExperimentalReturnCode(record["returncode"]) else {
            return false
        }
        guard let approval = record["approval_status"] as? String,
              ["approved_ordinary", "approved_candidate_b_preview", "denied", "preview_incomplete"].contains(approval) else {
            return false
        }
        return true
    }

    private static func validModelAPIKey'''
    if transformed.count(old_return) != 1:
        raise RuntimeError("expected one protocol input-key validator return")
    transformed = transformed.replace(old_return, new_return)
    path.write_text(transformed, encoding="utf-8")
    return {
        "path": relative_path,
        "original_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
        "experimental_sha256": digest(path),
        "reason": "allow only bounded result metadata on the disposable experimental tool_result path; it conveys Runner return status and audit correlation, never authority",
    }


def apply_experimental_telemetry_transport_client(source_root: Path) -> dict[str, str]:
    relative_path = "khaos/macos/AgentHostClient.swift"
    path = source_root / relative_path
    original = path.read_text(encoding="utf-8")
    transformed = original
    property_marker = "    private let modelAPIKey: String?\n"
    telemetry_properties = (
        property_marker
        + "    private let experimentalTelemetryLock = NSLock()\n"
        + "    private var experimentalTelemetrySequence = 0\n"
        + "    private var experimentalTelemetryIdentity: (trial: String, session: String, task: String)?\n"
        + "    private var pendingDSHCorrelation: [String: Any]?\n"
    )
    if transformed.count(property_marker) != 1:
        raise RuntimeError("expected one AgentHostClient model-key property")
    transformed = transformed.replace(property_marker, telemetry_properties)
    old_method = '''    func sendToolResultAsync(
        ok: Bool,
        canContinue: Bool,
        text: String,
        activePlugin: AgentHostPluginMetadata?,
        completion: @escaping (Result<AgentHostReply, Error>) -> Void
    ) throws {
        let frame = try AgentHostProtocol.toolResult(
            ok: ok,
            canContinue: canContinue,
            text: text,
            activePlugin: activePlugin,
            modelAPIKey: modelAPIKey
        )
        requestAsync(frame, completion: completion)
    }
'''
    new_method = '''    func sendToolResultAsync(
        ok: Bool,
        canContinue: Bool,
        text: String,
        activePlugin: AgentHostPluginMetadata?,
        launcherTrace: [String: Any]? = nil,
        completion: @escaping (Result<AgentHostReply, Error>) -> Void
    ) throws {
        let frame = try AgentHostProtocol.toolResult(
            ok: ok,
            canContinue: canContinue,
            text: text,
            activePlugin: activePlugin,
            modelAPIKey: modelAPIKey
        )
        let tracedFrame = try experimentalToolResultFrame(
            frame,
            launcherTrace: launcherTrace,
            ok: ok,
            canContinue: canContinue
        )
        requestAsync(tracedFrame, completion: completion)
    }
'''
    if transformed.count(old_method) != 1:
        raise RuntimeError("expected one AgentHostClient tool-result method")
    transformed = transformed.replace(old_method, new_method)
    for indentation, receiver in (("            ", "self?."), ("        ", "self.")):
        old_decode = indentation + "guard let reply = AgentHostProtocol.decodeReply(data) else {\n"
        new_decode = (
            indentation + f"guard let sanitizedData = {receiver}acceptExperimentalTelemetry(data),\n"
            + indentation + "      let reply = AgentHostProtocol.decodeReply(sanitizedData) else {\n"
        )
        if transformed.count(old_decode) != 1:
            raise RuntimeError("expected one AgentHost reply decoder at each call site")
        transformed = transformed.replace(old_decode, new_decode)
    helper = r'''
    private func experimentalToolResultFrame(
        _ frame: Data,
        launcherTrace: [String: Any]?,
        ok: Bool,
        canContinue: Bool
    ) throws -> Data {
        experimentalTelemetryLock.lock()
        let correlation = pendingDSHCorrelation
        pendingDSHCorrelation = nil
        experimentalTelemetryLock.unlock()
        guard let launcherTrace, let correlation else { return frame }
        guard var object = try JSONSerialization.jsonObject(with: frame) as? [String: Any] else {
            throw AgentHostClientError.invalidResponse(.launcherReplyDecodeFailure)
        }
        var trace = launcherTrace
        for key in [
            "trial_id", "dsh_session_id", "benchmark_task_id", "agent_turn_id", "agent_step_id",
            "tool_call_id", "tool_name", "operation_seq", "invocation_sha256",
        ] {
            guard let value = correlation[key] else {
                throw AgentHostClientError.invalidResponse(.launcherReplyDecodeFailure)
            }
            trace[key] = value
        }
        if let modelCallID = correlation["model_call_id"] {
            trace["model_call_id"] = modelCallID
        } else {
            trace.removeValue(forKey: "model_call_id")
        }
        trace["launcher_ok"] = ok
        trace["can_continue"] = canContinue
        if let returncode = launcherTrace["returncode"] as? Int {
            trace["returncode"] = returncode
            object["returncode"] = returncode
        }
        object["launcher_trace"] = trace
        let data = try JSONSerialization.data(
            withJSONObject: object,
            options: [.sortedKeys, .withoutEscapingSlashes]
        )
        guard data.count <= AgentHostProtocol.maximumFrameBytes else {
            throw AgentHostClientError.invalidResponse(.launcherReplyDecodeFailure)
        }
        return data
    }

    private func acceptExperimentalTelemetry(_ data: Data) -> Data? {
        guard var object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        guard let rawRecords = object.removeValue(forKey: "dsh_telemetry") else { return data }
        guard let records = rawRecords as? [[String: Any]], !records.isEmpty, records.count <= 128 else {
            return nil
        }
        let allowedFields: Set<String> = [
            "event", "event_seq", "timestamp_utc", "trial_id", "dsh_session_id", "benchmark_task_id",
            "agent_turn_id", "agent_step_id", "model_call_id", "tool_call_id", "tool_name",
            "operation_seq", "invocation_sha256", "argument_bytes", "file_count", "write_operation",
            "duration_ms", "status", "error_code", "returncode", "can_continue", "result_bytes",
            "result_sha256", "launcher_result_sha256", "observed_tool_result", "dsh_event_seq",
            "token_input", "token_output", "model_provider", "model_id", "launcher_task_id",
            "launcher_request_id", "launcher_approval_sha256", "approval_status", "kernel_result",
            "runner_status", "commit_status", "launcher_ok",
            "tool_operations_remaining", "write_operations_remaining", "repair_attempts_remaining",
            "tests_run", "failures", "errors", "skipped",
            "turn_end_sequence", "assistant_message_count", "tool_result_count", "turn_end_reason",
            "last_message_role", "last_message_text_only", "unresolved_kernel_result",
        ]
        let allowedEvents: Set<String> = [
            "SESSION_STARTED", "MODEL_REQUEST_STARTED", "MODEL_RESPONSE_RECEIVED",
            "MODEL_TOOL_CALL_OUTPUT_ACCEPTED", "DSH_ASSISTANT_MESSAGE_COMMITTED", "MODEL_REQUEST_FAILED",
            "MODEL_OUTPUT_REJECTED", "TOOL_CALL_PARSED", "TOOL_ARGUMENT_VALIDATED", "TOOL_ARGUMENT_REJECTED",
            "TOOL_SUBMISSION_FAILED", "TOOL_PROPOSAL_LOWERED", "LAUNCHER_PROPOSAL_SUBMITTED",
            "APPROVAL_ACCEPTED", "APPROVAL_DENIED", "KERNEL_OPERATION_STARTED", "KERNEL_OPERATION_COMPLETED",
            "LAUNCHER_TERMINAL_RESULT_DELIVERED", "PUBLIC_TEST_RESULT_VERIFIED", "TOOL_RESULT_DELIVERED",
            "TOOL_OPERATION_ABORTED", "TOOL_RESULT_DISCARDED", "NO_PROGRESS_DETECTED", "TURN_END_OBSERVED",
            "AGENT_NEXT_TURN_STARTED",
            "SESSION_CONTINUITY_CHECK", "AGENT_TERMINATED",
        ]
        func boundedTelemetryInteger(_ value: Any?, maximum: Int) -> Bool {
            guard let number = value as? NSNumber,
                  CFGetTypeID(number) != CFBooleanGetTypeID(),
                  number.doubleValue.isFinite,
                  number.doubleValue.rounded(.towardZero) == number.doubleValue else { return false }
            return number.int64Value >= 0 && number.int64Value <= Int64(maximum)
        }
        var encodedRecords: [Data] = []
        var totalBytes = 0
        for record in records {
            guard Set(record.keys).isSubset(of: allowedFields),
                  let event = record["event"] as? String, allowedEvents.contains(event),
                  let trial = record["trial_id"] as? String,
                  let session = record["dsh_session_id"] as? String,
                  let task = record["benchmark_task_id"] as? String,
                  let timestamp = record["timestamp_utc"] as? String,
                  trial.range(of: #"^[A-Za-z0-9_.:-]{1,128}$"#, options: .regularExpression) != nil,
                  session.range(of: #"^[A-Za-z0-9_.:-]{1,128}$"#, options: .regularExpression) != nil,
                  task.range(of: #"^[A-Za-z0-9_.:-]{1,128}$"#, options: .regularExpression) != nil,
                  timestamp.range(of: #"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"#, options: .regularExpression) != nil,
                  (record["tool_operations_remaining"] == nil || boundedTelemetryInteger(record["tool_operations_remaining"], maximum: 12)),
                  (record["write_operations_remaining"] == nil || boundedTelemetryInteger(record["write_operations_remaining"], maximum: 3)),
                  (record["repair_attempts_remaining"] == nil || boundedTelemetryInteger(record["repair_attempts_remaining"], maximum: 3)),
                  (record["tests_run"] == nil || boundedTelemetryInteger(record["tests_run"], maximum: 10_000)),
                  (record["failures"] == nil || boundedTelemetryInteger(record["failures"], maximum: 10_000)),
                  (record["errors"] == nil || boundedTelemetryInteger(record["errors"], maximum: 10_000)),
                  (record["skipped"] == nil || boundedTelemetryInteger(record["skipped"], maximum: 10_000)),
                  record.values.allSatisfy({
                      if let text = $0 as? String {
                          return text.utf8.count <= 256 && !text.unicodeScalars.contains(where: CharacterSet.controlCharacters.contains)
                      }
                      return $0 is NSNumber
                  }),
                  let encoded = try? JSONSerialization.data(
                    withJSONObject: record,
                    options: [.sortedKeys, .withoutEscapingSlashes]
                  ), encoded.count <= 4 * 1_024 else { return nil }
            if event == "PUBLIC_TEST_RESULT_VERIFIED" {
                guard record["tool_name"] as? String == "run_tests",
                      let status = record["status"] as? String,
                      ["passed", "failed", "invalid", "unverified", "mismatch"].contains(status) else {
                    return nil
                }
            }
            totalBytes += encoded.count
            guard totalBytes <= 40 * 1_024 else { return nil }
            encodedRecords.append(encoded)
        }

        experimentalTelemetryLock.lock()
        defer { experimentalTelemetryLock.unlock() }
        var identity = experimentalTelemetryIdentity
        var sequence = experimentalTelemetrySequence
        var pending = pendingDSHCorrelation
        for record in records {
            guard let event = record["event"] as? String,
                  let eventSequence = record["event_seq"] as? Int,
                  let trial = record["trial_id"] as? String,
                  let session = record["dsh_session_id"] as? String,
                  let task = record["benchmark_task_id"] as? String else { return nil }
            if event == "SESSION_STARTED" {
                guard eventSequence == 1, pending == nil else { return nil }
                identity = (trial, session, task)
                sequence = 0
            } else {
                guard let identity,
                      identity.trial == trial, identity.session == session, identity.task == task else { return nil }
            }
            guard eventSequence == sequence + 1 else { return nil }
            if event == "LAUNCHER_PROPOSAL_SUBMITTED" {
                guard pending == nil,
                      record["tool_call_id"] is String,
                      record["tool_name"] is String,
                      record["operation_seq"] is Int,
                      record["invocation_sha256"] is String else { return nil }
                pending = record
            }
            sequence = eventSequence
        }
        experimentalTelemetryIdentity = identity
        experimentalTelemetrySequence = sequence
        pendingDSHCorrelation = pending
        for encoded in encodedRecords {
            fputs("dsh-telemetry=\(String(decoding: encoded, as: UTF8.self))\n", stderr)
        }
        fflush(stderr)
        guard let sanitized = try? JSONSerialization.data(
            withJSONObject: object,
            options: [.sortedKeys, .withoutEscapingSlashes]
        ), sanitized.count <= AgentHostProtocol.maximumFrameBytes else { return nil }
        return sanitized
    }
'''
    marker = "    private func request(\n"
    if transformed.count(marker) != 1:
        raise RuntimeError("expected one AgentHostClient synchronous request method")
    transformed = transformed.replace(marker, helper + "\n" + marker)
    path.write_text(transformed, encoding="utf-8")
    return {
        "path": relative_path,
        "original_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
        "experimental_sha256": digest(path),
        "reason": "forward bounded DSH lifecycle telemetry through the signed Launcher while stripping it before strict AgentHost reply decoding, and return exact Runner/task correlation as non-authoritative metadata",
    }


def apply_experimental_launcher_semantic_trace(source_root: Path) -> dict[str, str]:
    relative_path = "khaos/macos/TrustedWorkspaceLauncherMain.swift"
    path = source_root / relative_path
    original = path.read_text(encoding="utf-8")
    transformed = original
    marker = "    private static func runAgentSession() throws {\n"
    helper = r'''
    private static var semanticLauncherEventSequence = 0
    private static let semanticLauncherEventLock = NSLock()

    private static func semanticLauncherTrace(
        _ outcome: AgentToolOutcome,
        taskID: UUID
    ) -> [String: Any]? {
        guard let record = outcome.workspaceRecord,
              let runtimeTrialID = phase322RuntimeTrialID(for: taskID) else { return nil }
        var trace: [String: Any] = [
            "runtime_trial_id": runtimeTrialID.uuidString.lowercased(),
            "launcher_task_id": taskID.uuidString.lowercased(),
            "launcher_request_id": record.requestID,
            "launcher_approval_sha256": record.approvalSHA256,
            "approval_status": record.approval,
            "kernel_result": record.kernelResult,
            "runner_status": record.runnerExecution,
            "commit_status": record.commitOutcome,
        ]
        if let returncode = outcome.returncode { trace["returncode"] = returncode }
        return trace
    }

    private static func writeDshLauncherEvent(
        _ event: String,
        taskID: UUID,
        requestID: String,
        approvalSHA256: String,
        status: String
    ) {
        semanticLauncherEventLock.lock()
        semanticLauncherEventSequence += 1
        let sequence = semanticLauncherEventSequence
        semanticLauncherEventLock.unlock()
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let record: [String: Any] = [
            "event": event,
            "launcher_event_seq": sequence,
            "timestamp_utc": formatter.string(from: Date()),
            "launcher_task_id": taskID.uuidString.lowercased(),
            "launcher_request_id": requestID,
            "launcher_approval_sha256": approvalSHA256,
            "status": status,
        ]
        guard let data = try? JSONSerialization.data(
            withJSONObject: record,
            options: [.sortedKeys, .withoutEscapingSlashes]
        ), data.count <= 2 * 1_024 else { return }
        fputs("dsh-launcher-event=\(String(decoding: data, as: UTF8.self))\n", stderr)
        fflush(stderr)
    }

'''
    if transformed.count(marker) != 1:
        raise RuntimeError("expected one experimental Launcher Agent session entry")
    transformed = transformed.replace(marker, helper + marker)

    replacements = (
        (
            '            writeAgentDiagnostic("tool=approval-denied")\n',
            '            writeAgentDiagnostic("tool=approval-denied")\n'
            '            writeDshLauncherEvent("APPROVAL_DENIED", taskID: taskID, requestID: requestID.token, approvalSHA256: approvalDigest, status: "denied")\n',
        ),
        (
            '        writeAgentDiagnostic("tool=approved kind=\\(approvalKind)")\n',
            '        writeAgentDiagnostic("tool=approved kind=\\(approvalKind)")\n'
            '        writeDshLauncherEvent("APPROVAL_ACCEPTED", taskID: taskID, requestID: requestID.token, approvalSHA256: approvalDigest, status: "approved_\\(approvalKind)")\n',
        ),
        (
            '            approvalKind = "ordinary"\n'
            '            approved = approveReviewedRequest(',
            '            approvalKind = "ordinary"\n'
            '            writeDshLauncherEvent("APPROVAL_PRESENTED", taskID: taskID, requestID: requestID.token, approvalSHA256: approvalDigest, status: approvalKind)\n'
            '            approved = approveReviewedRequest(',
        ),
        (
            '            approvalKind = "candidate_b_preview"\n'
            '            let decision = TrustedCandidateBApproval.present(',
            '            approvalKind = "candidate_b_preview"\n'
            '            writeDshLauncherEvent("APPROVAL_PRESENTED", taskID: taskID, requestID: requestID.token, approvalSHA256: approvalDigest, status: approvalKind)\n'
            '            let decision = TrustedCandidateBApproval.present(',
        ),
        (
            '                    handle.start { observation in\n',
            '                    writeDshLauncherEvent("KERNEL_OPERATION_STARTED", taskID: taskID, requestID: requestID.token, approvalSHA256: approvalDigest, status: "submitted")\n'
            '                    handle.start { observation in\n',
        ),
        (
            '        let elapsed = observation.submittedAt.map {\n',
            '''        let kernelCompletionStatus: String
        switch observation.reply {
        case let .failure(error):
            kernelCompletionStatus = "transport_failure:\\(failureCode(for: error))"
        case let .success(reply):
            if let errorCode = reply.errorCode {
                kernelCompletionStatus = "kernel_rejected:\\(errorCode)"
            } else if reply.output != nil {
                kernelCompletionStatus = "output_received"
            } else {
                kernelCompletionStatus = "missing_output"
            }
        }
        writeDshLauncherEvent(
            "KERNEL_OPERATION_COMPLETED",
            taskID: taskID,
            requestID: requestID.token,
            approvalSHA256: approvalDigest,
            status: kernelCompletionStatus
        )
        let elapsed = observation.submittedAt.map {
''',
        ),
    )
    for old, new in replacements:
        if transformed.count(old) != 1:
            raise RuntimeError("unexpected Launcher semantic-event injection site")
        transformed = transformed.replace(old, new)

    cancelled_result = '''                            try host.sendToolResultAsync(
                                ok: outcome.ok,
                                canContinue: false,
                                text: outcome.text,
                                activePlugin: currentAgentPluginMetadata(),
                                completion: completion
                            )'''
    cancelled_result_new = '''                            try host.sendToolResultAsync(
                                ok: outcome.ok,
                                canContinue: false,
                                text: outcome.text,
                                activePlugin: currentAgentPluginMetadata(),
                                launcherTrace: Self.semanticLauncherTrace(outcome, taskID: taskID),
                                completion: completion
                            )'''
    if transformed.count(cancelled_result) != 1:
        raise RuntimeError("expected one cancelled-operation result delivery")
    transformed = transformed.replace(cancelled_result, cancelled_result_new)
    normal_result = '''                        try host.sendToolResultAsync(
                            ok: outcome.ok,
                            canContinue: canContinue,
                            text: outcome.text,
                            activePlugin: currentAgentPluginMetadata(),
                            completion: completion
                        )'''
    normal_result_new = '''                        try host.sendToolResultAsync(
                            ok: outcome.ok,
                            canContinue: canContinue,
                            text: outcome.text,
                            activePlugin: currentAgentPluginMetadata(),
                            launcherTrace: Self.semanticLauncherTrace(outcome, taskID: taskID),
                            completion: completion
                        )'''
    if transformed.count(normal_result) != 1:
        raise RuntimeError("expected one ordinary workspace result delivery")
    transformed = transformed.replace(normal_result, normal_result_new)

    ordinary_approval = "\n".join((
        '                title: "Approve this local Agent tool once?",',
        '                details: command,',
        '                workspace: selection.scopeURL,',
    )) + "\n"
    ordinary_approval_with_identity = "\n".join((
        '                title: "Approve this local Agent tool once?",',
        '                details: "Task ID: \\(taskID.uuidString.lowercased())\\n\\n\\(command)",',
        '                workspace: selection.scopeURL,',
    )) + "\n"
    if transformed.count(ordinary_approval) != 1:
        raise RuntimeError("expected one ordinary semantic approval dialog")
    transformed = transformed.replace(ordinary_approval, ordinary_approval_with_identity)

    candidate_approval = "\n".join((
        '                workspacePath: selection.scopeURL.path,',
        '                requestID: requestID.token,',
    )) + "\n"
    candidate_approval_with_identity = "\n".join((
        '                workspacePath: selection.scopeURL.path,',
        '                taskID: taskID,',
        '                requestID: requestID.token,',
    )) + "\n"
    if transformed.count(candidate_approval) != 1:
        raise RuntimeError("expected one Candidate B semantic approval dialog")
    transformed = transformed.replace(candidate_approval, candidate_approval_with_identity)
    path.write_text(transformed, encoding="utf-8")
    return {
        "path": relative_path,
        "original_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
        "experimental_sha256": digest(path),
        "reason": "add payload-free task/request/approval/Kernel lifecycle events and pass result correlation to the experimental AgentHost; no execution or approval policy changes",
    }


def apply_experimental_candidate_approval_identity(source_root: Path) -> dict[str, str]:
    relative_path = "khaos/macos/TrustedEditApproval.swift"
    path = source_root / relative_path
    original = path.read_text(encoding="utf-8")
    transformed = original
    signature = "\n".join((
        "        workspacePath: String,",
        "        requestID: String,",
    )) + "\n"
    signature_with_identity = "\n".join((
        "        workspacePath: String,",
        "        taskID: UUID,",
        "        requestID: String,",
    )) + "\n"
    if transformed.count(signature) != 1:
        raise RuntimeError("expected one Candidate B approval signature")
    transformed = transformed.replace(signature, signature_with_identity)

    summary_marker = "        let details = edit.completeDetails(\n"
    identity = '        let operationIdentity = "Task ID: \\(taskID.uuidString.lowercased())\\n\\n"\n'
    if transformed.count(summary_marker) != 1:
        raise RuntimeError("expected one Candidate B details assembly")
    transformed = transformed.replace(summary_marker, identity + summary_marker)

    old_guard = "\n".join((
        "        guard summary.utf8.count <= TrustedCandidateBPreview.maximumPreviewBytes,",
        "              details.utf8.count <= TrustedCandidateBPreview.maximumDetailsBytes else {",
    )) + "\n"
    new_guard = "\n".join((
        "        guard (operationIdentity + summary).utf8.count <= TrustedCandidateBPreview.maximumPreviewBytes,",
        "              (operationIdentity + details).utf8.count <= TrustedCandidateBPreview.maximumDetailsBytes else {",
    )) + "\n"
    if transformed.count(old_guard) != 1:
        raise RuntimeError("expected one bounded Candidate B view size check")
    transformed = transformed.replace(old_guard, new_guard)

    for view_name in ("summary", "details"):
        old_view = f"alert.accessoryView = scrollableText({view_name})"
        new_view = f"alert.accessoryView = scrollableText(operationIdentity + {view_name})"
        if transformed.count(old_view) != 1:
            raise RuntimeError(f"expected one Candidate B {view_name} review view")
        transformed = transformed.replace(old_view, new_view)

    path.write_text(transformed, encoding="utf-8")
    return {
        "path": relative_path,
        "original_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
        "experimental_sha256": digest(path),
        "reason": "show the current experimental Task ID in both Candidate B review screens without changing edit validation or execution",
    }


def apply_experimental_workspace_runtime_binding(source_root: Path) -> dict[str, str]:
    relative_path = "khaos/macos/TrustedWorkspaceLauncherMain.swift"
    path = source_root / relative_path
    original = path.read_text(encoding="utf-8")
    transformed = original
    helper = r'''
    private static let phase322MarkerName = ".khaos-phase322-identity.json"
    private static let phase322IdentityLock = NSLock()
    private static var phase322TrialIDs: [UUID: UUID] = [:]
    private static var phase322WorkspaceIdentities: [UUID: Phase322WorkspaceIdentity] = [:]
    private static var phase322FailedTrials = Set<UUID>()

    private static func phase322BeginTrial(taskID: UUID) -> UUID {
        let trialID = UUID()
        phase322IdentityLock.lock()
        phase322TrialIDs[taskID] = trialID
        phase322WorkspaceIdentities.removeValue(forKey: taskID)
        phase322FailedTrials.remove(taskID)
        phase322IdentityLock.unlock()
        return trialID
    }

    private static func phase322EndTrial(taskID: UUID) {
        phase322IdentityLock.lock()
        phase322TrialIDs.removeValue(forKey: taskID)
        phase322WorkspaceIdentities.removeValue(forKey: taskID)
        phase322FailedTrials.remove(taskID)
        phase322IdentityLock.unlock()
    }

    private static func phase322RuntimeTrialID(for taskID: UUID) -> UUID? {
        phase322IdentityLock.lock()
        defer { phase322IdentityLock.unlock() }
        return phase322TrialIDs[taskID]
    }

    private static func phase322RejectTrial(taskID: UUID) {
        phase322IdentityLock.lock()
        phase322WorkspaceIdentities.removeValue(forKey: taskID)
        phase322FailedTrials.insert(taskID)
        phase322IdentityLock.unlock()
    }

    private static func phase322CanonicalPath(_ path: String) -> String? {
        path.withCString { source -> String? in
            var resolvedPath = [CChar](repeating: 0, count: Int(PATH_MAX))
            guard Darwin.realpath(source, &resolvedPath) != nil else { return nil }
            return String(cString: resolvedPath)
        }
    }

    private static func phase322ReadMarker(
        directoryFD: Int32
    ) -> Phase322MarkerSnapshot? {
        let descriptor = phase322MarkerName.withCString {
            Darwin.openat(directoryFD, $0, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
        }
        guard descriptor >= 0 else { return nil }
        defer { Darwin.close(descriptor) }

        var before = stat()
        guard Darwin.fstat(descriptor, &before) == 0,
              before.st_mode & mode_t(S_IFMT) == mode_t(S_IFREG),
              before.st_nlink == 1,
              before.st_uid == getuid(),
              before.st_mode & 0o777 == 0o600,
              before.st_size > 0,
              before.st_size <= 4_096 else { return nil }

        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 1_024)
        while true {
            let amount = buffer.withUnsafeMutableBytes { bytes in
                Darwin.read(descriptor, bytes.baseAddress, bytes.count)
            }
            guard amount >= 0 else { return nil }
            if amount == 0 { break }
            guard data.count + amount <= 4_096 else { return nil }
            data.append(contentsOf: buffer.prefix(amount))
        }

        var after = stat()
        guard Darwin.fstat(descriptor, &after) == 0,
              before.st_dev == after.st_dev,
              before.st_ino == after.st_ino,
              before.st_size == after.st_size,
              before.st_uid == after.st_uid,
              before.st_mode == after.st_mode,
              before.st_nlink == after.st_nlink,
              data.count == Int(after.st_size) else { return nil }
        var namedMarker = stat()
        let namedStatus = phase322MarkerName.withCString {
            Darwin.fstatat(directoryFD, $0, &namedMarker, AT_SYMLINK_NOFOLLOW)
        }
        guard namedStatus == 0,
              namedMarker.st_dev == after.st_dev,
              namedMarker.st_ino == after.st_ino else { return nil }
        return Phase322MarkerSnapshot(
            sha256: KernelWorkspaceXPC.sha256Hex(data),
            device: UInt64(after.st_dev),
            inode: UInt64(after.st_ino)
        )
    }

    private static func phase322WorkspaceSnapshot(
        _ selection: TrustedWorkspaceSelection,
        trialID: UUID,
        taskID: UUID
    ) -> Phase322WorkspaceIdentity? {
        var bookmarkIsStale = false
        guard let resolvedURL = try? URL(
            resolvingBookmarkData: selection.bookmark,
            options: [],
            relativeTo: nil,
            bookmarkDataIsStale: &bookmarkIsStale
        ), !bookmarkIsStale else { return nil }

        let workspaceURL = resolvedURL.standardizedFileURL
        let selectedURL = selection.scopeURL.standardizedFileURL
        guard workspaceURL.path == selectedURL.path,
              workspaceURL.startAccessingSecurityScopedResource() else { return nil }
        defer { workspaceURL.stopAccessingSecurityScopedResource() }

        guard let canonicalBefore = phase322CanonicalPath(workspaceURL.path) else { return nil }
        let directoryFD = workspaceURL.path.withCString {
            Darwin.open($0, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        }
        guard directoryFD >= 0 else { return nil }
        defer { Darwin.close(directoryFD) }

        var directoryInfo = stat()
        guard Darwin.fstat(directoryFD, &directoryInfo) == 0,
              directoryInfo.st_mode & mode_t(S_IFMT) == mode_t(S_IFDIR),
              phase322CanonicalPath(workspaceURL.path) == canonicalBefore else { return nil }
        var namedDirectoryInfo = stat()
        let namedDirectoryStatus = workspaceURL.path.withCString {
            Darwin.fstatat(AT_FDCWD, $0, &namedDirectoryInfo, 0)
        }
        guard namedDirectoryStatus == 0,
              namedDirectoryInfo.st_dev == directoryInfo.st_dev,
              namedDirectoryInfo.st_ino == directoryInfo.st_ino else { return nil }
        guard let marker = phase322ReadMarker(directoryFD: directoryFD),
              phase322CanonicalPath(workspaceURL.path) == canonicalBefore else { return nil }

        return Phase322WorkspaceIdentity(
            trialID: trialID,
            taskID: taskID,
            workspaceSessionID: selection.identity,
            bookmarkSHA256: KernelWorkspaceXPC.sha256Hex(selection.bookmark),
            canonicalPath: canonicalBefore,
            pathSHA256: KernelWorkspaceXPC.sha256Hex(Data(canonicalBefore.utf8)),
            directoryDevice: UInt64(directoryInfo.st_dev),
            directoryInode: UInt64(directoryInfo.st_ino),
            markerSHA256: marker.sha256,
            markerDevice: marker.device,
            markerInode: marker.inode
        )
    }

    private static func phase322ValidateWorkspaceIdentity(
        _ selection: TrustedWorkspaceSelection,
        taskID: UUID,
        requestID: String,
        checkpoint: String,
        approvalSHA256: String
    ) -> Bool {
        phase322IdentityLock.lock()
        let trialID = phase322TrialIDs[taskID]
        let existing = phase322WorkspaceIdentities[taskID]
        let alreadyFailed = phase322FailedTrials.contains(taskID)
        phase322IdentityLock.unlock()
        guard let trialID else { return false }

        let candidate = alreadyFailed
            ? nil
            : phase322WorkspaceSnapshot(selection, trialID: trialID, taskID: taskID)
        let matchesBaseline = candidate.map { current in
            existing.map { $0 == current } ?? true
        } ?? false
        var valid = candidate != nil && matchesBaseline
        if valid, existing == nil, let candidate {
            phase322IdentityLock.lock()
            if phase322TrialIDs[taskID] == trialID,
               phase322WorkspaceIdentities[taskID] == nil,
               !phase322FailedTrials.contains(taskID) {
                phase322WorkspaceIdentities[taskID] = candidate
            } else {
                valid = false
            }
            phase322IdentityLock.unlock()
        }

        let event: [String: Any] = [
            "runtime_trial_id": trialID.uuidString.lowercased(),
            "launcher_task_id": taskID.uuidString.lowercased(),
            "launcher_request_id": requestID,
            "workspace_session_id": selection.identity.uuidString.lowercased(),
            "checkpoint": checkpoint,
            "selected_path_sha256": candidate?.pathSHA256 ?? "unavailable",
            "directory_device": candidate?.directoryDevice ?? 0,
            "directory_inode": candidate?.directoryInode ?? 0,
            "directory_identity_matches": matchesBaseline,
            "marker_readable": candidate != nil,
            "marker_sha256": candidate?.markerSHA256 ?? "unavailable",
            "marker_device": candidate?.markerDevice ?? 0,
            "marker_inode": candidate?.markerInode ?? 0,
            "snapshot_identity": "NOT_AVAILABLE",
            "status": valid ? "verified" : "rejected",
            "approval_sha256": approvalSHA256,
        ]
        if let data = try? JSONSerialization.data(
            withJSONObject: event,
            options: [.sortedKeys, .withoutEscapingSlashes]
        ), data.count <= 2 * 1_024 {
            fputs("dsh-workspace-identity=\(String(decoding: data, as: UTF8.self))\n", stderr)
            fflush(stderr)
        }
        if !valid { phase322RejectTrial(taskID: taskID) }
        return valid
    }

'''
    phase322_structs = '''private struct Phase322MarkerSnapshot {
    let sha256: String
    let device: UInt64
    let inode: UInt64
}

private struct Phase322WorkspaceIdentity: Equatable {
    let trialID: UUID
    let taskID: UUID
    let workspaceSessionID: UUID
    let bookmarkSHA256: String
    let canonicalPath: String
    let pathSHA256: String
    let directoryDevice: UInt64
    let directoryInode: UInt64
    let markerSHA256: String
    let markerDevice: UInt64
    let markerInode: UInt64
}

'''
    type_marker = "enum TrustedWorkspaceLauncherMain {\n"
    if transformed.count(type_marker) != 1:
        raise RuntimeError("expected one Launcher type declaration")
    transformed = transformed.replace(type_marker, type_marker + phase322_structs)

    session_marker = "    private static func runAgentSession() throws {\n"
    if transformed.count(session_marker) != 1:
        raise RuntimeError("expected one Agent session entry")
    transformed = transformed.replace(session_marker, helper + session_marker)

    task_marker = "            let taskID = UUID()\n"
    task_replacement = '''            let taskID = UUID()
            workspace = nil
            _ = phase322BeginTrial(taskID: taskID)
            defer {
                phase322EndTrial(taskID: taskID)
                workspace = nil
            }
'''
    if transformed.count(task_marker) != 1:
        raise RuntimeError("expected one Agent task identity creation point")
    transformed = transformed.replace(task_marker, task_replacement)

    record_marker = '            "task_id": taskID.uuidString.lowercased(),\n'
    if transformed.count(record_marker) != 1:
        raise RuntimeError("expected one Launcher task-record identity field")
    transformed = transformed.replace(
        record_marker,
        record_marker
        + '            "runtime_trial_id": phase322RuntimeTrialID(for: taskID)?.uuidString.lowercased() ?? "unavailable",\n',
    )

    request_marker = '''        var frozenRequest = AgentWorkspaceRequest(
            requestID: requestID,
            request: request,
            invocation: invocation,
            approvalSHA256: approvalDigest,
            workspaceSessionID: selection.identity,
            connectionID: nil
        )
'''
    request_replacement = request_marker + '''        guard phase322ValidateWorkspaceIdentity(
            selection,
            taskID: taskID,
            requestID: requestID.token,
            checkpoint: "before_approval",
            approvalSHA256: approvalDigest
        ) else {
            workspace = nil
            let record = agentWorkspaceRequestRecord(
                frozenRequest,
                approval: "workspace_identity_rejected",
                cancellationRequested: false,
                cancellationResult: "not_requested",
                kernelResult: "not_submitted:workspace_identity_mismatch",
                runnerExecution: "not_started",
                workspaceResult: nil,
                commitOutcome: "not_committed"
            )
            return AgentToolOutcome(
                ok: false,
                canContinue: false,
                text: "Launcher could not verify the selected workspace identity. The request was not submitted.",
                returncode: nil,
                executionSeconds: 0,
                stopReason: "workspace identity verification failed",
                workspaceRecord: record
            )
        }
'''
    if transformed.count(request_marker) != 1:
        raise RuntimeError("expected one frozen workspace request before approval")
    transformed = transformed.replace(request_marker, request_replacement)

    approval_marker = '        writeAgentDiagnostic("tool=approved kind=\\(approvalKind)")\n'
    approval_replacement = '''        guard phase322ValidateWorkspaceIdentity(
            selection,
            taskID: taskID,
            requestID: requestID.token,
            checkpoint: "after_approval",
            approvalSHA256: approvalDigest
        ) else {
            workspace = nil
            let record = agentWorkspaceRequestRecord(
                frozenRequest,
                approval: "approved_\\(approvalKind)",
                cancellationRequested: false,
                cancellationResult: "not_requested",
                kernelResult: "not_submitted:workspace_identity_changed",
                runnerExecution: "not_started",
                workspaceResult: nil,
                commitOutcome: "not_committed"
            )
            return AgentToolOutcome(
                ok: false,
                canContinue: false,
                text: "Launcher rejected the approved request because the workspace identity changed. No Kernel request was submitted.",
                returncode: nil,
                executionSeconds: 0,
                stopReason: "workspace identity changed after approval",
                workspaceRecord: record
            )
        }
'''
    if transformed.count(approval_marker) != 1:
        raise RuntimeError("expected one approval acceptance point")
    transformed = transformed.replace(approval_marker, approval_replacement + approval_marker)

    result_marker = "        let elapsed = observation.submittedAt.map {\n"
    result_replacement = '''        guard phase322ValidateWorkspaceIdentity(
            selection,
            taskID: taskID,
            requestID: requestID.token,
            checkpoint: "after_kernel_result",
            approvalSHA256: approvalDigest
        ) else {
            workspace = nil
            let record = agentWorkspaceRequestRecord(
                frozenRequest,
                approval: "approved_\\(approvalKind)",
                cancellationRequested: waited.cancellationRequested,
                cancellationResult: cancellationLabel(observation.cancellation),
                kernelResult: "result_withheld:workspace_identity_mismatch",
                runnerExecution: "unknown",
                workspaceResult: nil,
                commitOutcome: "unknown"
            )
            return AgentToolOutcome(
                ok: false,
                canContinue: false,
                text: "The Kernel returned, but Launcher rejected the workspace identity. The result was withheld and the workspace outcome is unknown.",
                returncode: nil,
                executionSeconds: 0,
                stopReason: "workspace identity changed after Kernel result",
                taskCancelled: waited.cancellationRequested,
                workspaceRecord: record
            )
        }
'''
    if transformed.count(result_marker) != 1:
        raise RuntimeError("expected one Kernel result boundary")
    transformed = transformed.replace(result_marker, result_replacement + result_marker)

    path.write_text(transformed, encoding="utf-8")
    return {
        "path": relative_path,
        "original_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
        "experimental_sha256": digest(path),
        "reason": "bind the actual security-scoped Picker selection to a fresh task Trial ID and recheck the same directory, bookmark, and marker identity before approval, after approval, and before result delivery",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsh-source", type=Path, required=True)
    parser.add_argument("--node-archive", type=Path, required=True)
    parser.add_argument("--signing-identity", required=True)
    parser.add_argument("--output-app", type=Path, required=True)
    parser.add_argument("--probe-workspace-read-path", type=Path, required=True)
    parser.add_argument("--probe-workspace-write-path", type=Path, required=True)
    parser.add_argument("--probe-credential-path", type=Path, required=True)
    parser.add_argument("--probe-local-port", type=int, required=True)
    parser.add_argument(
        "--model-provider",
        choices=("local", "bigmodel", "bigmodel-coding-plan"),
        default="local",
        help="remote providers are for synthetic experimental tasks only",
    )
    parser.add_argument("--cancellation-case", choices=("b32", "pre-commit", "post-commit"))
    parser.add_argument("--cancellation-control-path", type=Path)
    parser.add_argument(
        "--semantic-tools",
        action="store_true",
        help="embed the test-only fixed Candidate B script used by semantic coding tools",
    )
    parser.add_argument("--pnpm", default="pnpm")
    parser.add_argument("--keychain", type=Path)
    parser.add_argument("--local-model-app", type=Path,
                        help="signed local Khaos app supplying its existing CPU-only llama.cpp model")
    parser.add_argument("--python-executable", type=Path, default=Path(sys.executable))
    args = parser.parse_args()

    if platform.system() != "Darwin":
        parser.error("the signed XPC acceptance app requires macOS")
    source_sha = output(["git", "rev-parse", "HEAD"], cwd=ROOT)
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", KHAOS_BASE_SHA, "HEAD"],
        cwd=ROOT,
        check=False,
    ).returncode != 0:
        parser.error(f"Khaos HEAD must descend from verified PR #41 head {KHAOS_BASE_SHA}")
    merges = output(["git", "rev-list", "--merges", f"{KHAOS_BASE_SHA}..HEAD"], cwd=ROOT)
    if merges:
        parser.error("integration commits after PR #41 must not contain merge commits")
    if output(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT):
        parser.error("Khaos integration worktree must be clean so the build binds to its exact source SHA")
    dsh_source = args.dsh_source.resolve(strict=True)
    if output(["git", "rev-parse", "HEAD"], cwd=dsh_source) != PINNED_DSH_SHA:
        parser.error(f"DSH must be pinned at {PINNED_DSH_SHA}")
    if output(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=dsh_source):
        parser.error("DSH checkout must be clean")
    pnpm = shutil.which(args.pnpm)
    if pnpm is None or output([pnpm, "--version"], cwd=dsh_source) != PINNED_PNPM:
        parser.error(f"pnpm {PINNED_PNPM} is required")
    node_archive = args.node_archive.resolve(strict=True)
    if digest(node_archive) != PINNED_NODE_ARCHIVE_SHA256:
        parser.error("Node archive hash differs from the pinned official macOS arm64 release")
    identity = seed_builder._require_signing_identity(args.signing_identity, args.keychain)
    if args.model_provider != "local" and args.local_model_app is not None:
        parser.error("--local-model-app is supported only with the local provider")
    output_app = args.output_app.expanduser().absolute()
    if output_app.suffix != ".app" or os.path.lexists(output_app):
        parser.error("--output-app must be a new .app path")
    disk_preflight: dict[str, int | str | bool] = {"status": "NOT_REQUIRED"}
    if args.local_model_app is not None:
        try:
            disk_preflight = preflight_local_model_build(args.local_model_app, output_app.parent)
        except (OSError, ValueError, RuntimeError) as error:
            parser.error(f"local-model disk preflight failed: {error}")
    local_model = local_model_inputs(args.local_model_app) if args.local_model_app is not None else None
    output_app.parent.mkdir(parents=True, exist_ok=True)
    probe_paths = {
        "KhaosDSHProbeWorkspaceReadPath": args.probe_workspace_read_path.resolve(strict=True),
        "KhaosDSHProbeWorkspaceWritePath": args.probe_workspace_write_path.resolve(strict=True),
        "KhaosDSHProbeCredentialPath": args.probe_credential_path.resolve(strict=True),
    }
    if not all(path.is_file() for path in probe_paths.values()):
        parser.error("DSH attack probe read, write, and credential canaries must be regular files")
    if not (1 <= args.probe_local_port <= 65_535):
        parser.error("--probe-local-port must be a valid TCP port")
    if (args.cancellation_case is None) != (args.cancellation_control_path is None):
        parser.error("--cancellation-case and --cancellation-control-path must be supplied together")
    cancellation_control = None
    if args.cancellation_control_path is not None:
        cancellation_control = args.cancellation_control_path.resolve(strict=True)
        if not cancellation_control.is_dir() \
                or not (cancellation_control / "kernel-events.jsonl").is_file() \
                or (cancellation_control / "release").exists():
            parser.error("cancellation control must contain an empty event file and no release marker")

    probe_dir = ROOT / "experiments/dsh-feasibility"
    override = probe_dir / "DSHAgentHostAcceptance.swift"
    model_bridge_protocol = probe_dir / "DSHModelBridgeProtocol.swift"
    model_bridge_service_source = probe_dir / "DSHModelBridgeService.swift"
    model_bridge_probe_source = probe_dir / "DSHModelBridgePeerProbe.swift"
    test_inputs = (
        override,
        model_bridge_protocol,
        model_bridge_service_source,
        model_bridge_probe_source,
        probe_dir / "dsh-agenthost-runtime.ts",
        probe_dir / "dsh-agent-telemetry.ts",
        probe_dir / "khaos-model-bridge.ts",
        probe_dir / "khaos-local-model.ts",
        probe_dir / "khaos-semantic-tools.ts",
        probe_dir / "khaos-semantic-tools.spec.ts",
        probe_dir / "dsh-agent-lifecycle.ts",
        probe_dir / "dsh-agent-lifecycle.test.ts",
        probe_dir / "dsh-semantic-fixture.ts",
        probe_dir / "dsh-capability-lifecycle-probe.ts",
        probe_dir / "dsh-tool-result.ts",
        probe_dir / "khaos-capability-adapter.ts",
        probe_dir / "malicious-cordis-plugin.ts",
        ROOT / "tools/build_dsh_xpc_acceptance_app.py",
        ROOT / "tools/run_dsh_xpc_attack_acceptance.py",
        ROOT / "tools/run_dsh_signed_runtime_probe.py",
        ROOT / "tools/run_dsh_feasibility_probe.py",
        ROOT / "tools/run_dsh_model_bridge_tests.py",
        ROOT / "tools/run_dsh_semantic_tool_tests.py",
        ROOT / "tools/run_dsh_plugin_evaluation.py",
        ROOT / "experiments/dsh-feasibility/khaos-model-bridge.test.ts",
        ROOT / "experiments/dsh_phase3/benchmark.py",
        ROOT / "experiments/dsh_phase3/test_acceptance_policy.py",
        ROOT / "experiments/dsh_phase3/test_benchmark.py",
        ROOT / "experiments/dsh_phase3/plugin_evolution/tag-plugin.ts",
        ROOT / "experiments/dsh_phase3/plugin_evolution/baseline.ts",
        ROOT / "experiments/dsh_phase3/plugin_evolution/candidate_v1.ts",
        ROOT / "experiments/dsh_phase3/plugin_evolution/malicious_candidate.ts",
        ROOT / "experiments/dsh_phase3/plugin_evolution/runner.ts",
        ROOT / "tests/signed_cancellation_fixture.py",
        ROOT / "tests/macos_xpc_probe/TrustedEditApprovalProbe.swift",
    )
    temporary = Path(tempfile.mkdtemp(prefix="khaos-dsh-xpc-acceptance-", dir=output_app.parent))
    completed = False
    try:
        source_root = temporary / "inputs"
        source_hashes = seed_builder._snapshot_sources(source_root, None)
        protocol_target = source_root / "khaos/macos/AgentHostProtocol.swift"
        protocol_original = protocol_target.read_text(encoding="utf-8")
        protocol_extension = model_bridge_protocol.read_text(encoding="utf-8")
        if "enum DSHModelBridgeLimits" in protocol_original:
            raise RuntimeError("base AgentHost protocol unexpectedly contains the experimental bridge")
        old_handle_signature = (
            "@objc protocol AgentHostSessionEndpoint {\n"
            "    func handle(\n"
            "        _ frame: NSData,\n"
            "        withReply reply: @escaping (NSData?) -> Void\n"
            "    )\n"
            "}\n"
        )
        new_handle_signature = (
            "@objc protocol AgentHostSessionEndpoint {\n"
            "    func handle(\n"
            "        _ frame: NSData,\n"
            "        modelBridgeEndpoint: NSXPCListenerEndpoint?,\n"
            "        withReply reply: @escaping (NSData?) -> Void\n"
            "    )\n"
            "}\n"
        )
        if protocol_original.count(old_handle_signature) != 1:
            raise RuntimeError("expected one bounded AgentHost XPC method for the endpoint overlay")
        protocol_target.write_text(
            protocol_original.replace(old_handle_signature, new_handle_signature).rstrip()
            + "\n\n" + protocol_extension,
            encoding="utf-8",
        )
        protocol_endpoint_sha256 = digest(protocol_target)
        protocol_trace_overlay = apply_experimental_tool_trace_protocol(source_root)
        source_hashes["khaos/macos/AgentHostProtocol.swift"] = protocol_trace_overlay["experimental_sha256"]
        protocol_overlay = {
            "path": "khaos/macos/AgentHostProtocol.swift",
            "original_sha256": hashlib.sha256(protocol_original.encode("utf-8")).hexdigest(),
            "experimental_sha256": protocol_endpoint_sha256,
            "reason": "pass one opaque model-listener endpoint over the disposable Launcher-to-AgentHost XPC",
        }
        model_bridge_client_overlay = apply_experimental_model_bridge_client(source_root)
        source_hashes[model_bridge_client_overlay["path"]] = model_bridge_client_overlay["experimental_sha256"]
        telemetry_client_overlay = apply_experimental_telemetry_transport_client(source_root)
        source_hashes[telemetry_client_overlay["path"]] = telemetry_client_overlay["experimental_sha256"]
        launcher_trace_overlay = apply_experimental_launcher_semantic_trace(source_root)
        source_hashes[launcher_trace_overlay["path"]] = launcher_trace_overlay["experimental_sha256"]
        candidate_approval_identity_overlay = apply_experimental_candidate_approval_identity(source_root)
        source_hashes[candidate_approval_identity_overlay["path"]] = candidate_approval_identity_overlay["experimental_sha256"]
        workspace_runtime_overlay = (
            apply_experimental_workspace_runtime_binding(source_root)
            if args.semantic_tools else None
        )
        if workspace_runtime_overlay is not None:
            source_hashes[workspace_runtime_overlay["path"]] = workspace_runtime_overlay["experimental_sha256"]
        disclosure_override = (
            apply_experimental_model_disclosure(source_root)
            if args.model_provider != "local" else None
        )
        if disclosure_override is not None:
            source_hashes[REMOTE_MODEL_DISCLOSURE_SOURCE] = disclosure_override["experimental_sha256"]
        cancellation_overlay_hashes: dict[str, str] = {}
        if args.cancellation_case is not None and cancellation_control is not None:
            sys.path.insert(0, str(ROOT / "tests"))
            import signed_cancellation_fixture  # noqa: E402

            cancellation_overlay_hashes = signed_cancellation_fixture.overlay(
                source_root,
                cancellation_control,
                args.cancellation_case,
            )
            source_hashes.update(cancellation_overlay_hashes)
        replacement_hash = digest(override)
        replacement_target = source_root / REPLACED_SOURCE
        shutil.copy2(override, replacement_target)
        source_hashes[REPLACED_SOURCE] = replacement_hash

        node_root = temporary / "node"
        node_root.mkdir()
        with tarfile.open(node_archive, "r:xz") as archive:
            archive.extractall(node_root, filter="data")
        node_dir = node_root / "node-v22.19.0-darwin-arm64"
        node_source = node_dir / "bin/node"
        if not node_source.is_file() or output([str(node_source), "--version"]) != PINNED_NODE_VERSION:
            raise RuntimeError("verified Node archive does not contain the expected Node runtime")
        runtime_bundle, runtime_hash = build_dsh_bundle(
            dsh_source,
            probe_dir,
            pnpm,
            temporary,
            runtime_entry="dsh-agenthost-runtime.ts",
            bundle_name="agenthost-runtime.mjs",
        )

        app = temporary / output_app.name
        sdk = output(["xcrun", "--sdk", "macosx", "--show-sdk-path"])
        swiftc = output(["xcrun", "--find", "swiftc"])
        install_name_tool = output(["xcrun", "--find", "install_name_tool"])
        python = seed_builder._python_framework(args.python_executable.resolve(strict=True))
        test_sources = {str(path.relative_to(ROOT)): digest(path) for path in test_inputs}
        fixed_script_argument = None
        if args.cancellation_case is not None or args.semantic_tools:
            candidate_probe = temporary / "TrustedEditApprovalProbe"
            run([
                swiftc,
                "-sdk", sdk,
                "-target", f"{platform.machine()}-apple-macosx26.0",
                str(source_root / "khaos/macos/KernelWorkspaceXPC.swift"),
                str(source_root / "khaos/macos/AgentHostProtocol.swift"),
                str(source_root / "khaos/macos/TrustedEditApproval.swift"),
                str(ROOT / "tests/macos_xpc_probe/TrustedEditApprovalProbe.swift"),
                "-o", str(candidate_probe),
            ])
            fixed_script = candidate_b_fixed_script(candidate_probe)
            fixed_script_argument = "exec(" + json.dumps(fixed_script, separators=(",", ":")) + ")"
        build_record = {
            "schema": 1,
            "source_sha256": source_hashes,
            "build_version": "1",
            "builder_sha256": seed_builder._sha256_file(Path(seed_builder.__file__)),
            "certificate_sha1": identity,
            "architecture": platform.machine(),
            "macos": platform.mac_ver()[0],
            "swift": output([swiftc, "--version"]),
            "sdk": output(["xcrun", "--sdk", "macosx", "--show-sdk-version"]),
            "python_version": output([str(args.python_executable), "-I", "-S", "-c", "import sys; print(sys.version)"]),
            "input_policy": "dsh-test-agenthost-override",
            "khaos_experiment_base_sha": KHAOS_BASE_SHA,
            "khaos_source_sha": source_sha,
            "agent_action_diagnostics": False,
            "test_only_sources_sha256": test_sources,
            "workspace_binding_mode": "runtime-per-trial-v1" if args.semantic_tools else None,
            "disposable_workspace_identity": None,
            "probe_fixture_sha256": {
                key: digest(path) for key, path in probe_paths.items()
            },
            "probe_local_port": args.probe_local_port,
            "cancellation_case": args.cancellation_case,
            "cancellation_overlay_sha256": cancellation_overlay_hashes,
            "semantic_tools": args.semantic_tools,
            "dsh_model_provider": args.model_provider,
            "disk_preflight": disk_preflight,
            "dsh_model_id": EXPERIMENTAL_MODEL_ID if args.model_provider != "local"
                else (LOCAL_MODEL_ID if local_model is not None else None),
            "dsh_local_model": None if local_model is None else local_model[3],
            "experimental_source_overrides": (
                [protocol_overlay, protocol_trace_overlay, model_bridge_client_overlay,
                 telemetry_client_overlay, launcher_trace_overlay, candidate_approval_identity_overlay]
                + ([workspace_runtime_overlay] if workspace_runtime_overlay is not None else [])
                + ([disclosure_override] if disclosure_override is not None else [])
            ),
            "dsh_model_data_policy": (
                "synthetic benchmark data only; Launcher task-scoped consent; exact hostile-XPC marker uses MockAdapter and skips provider data flow"
                if args.model_provider != "local" else (
                    "synthetic benchmark data only; bundled local CPU model; no remote data flow"
                    if local_model is not None else "no model configured"
                )
            ),
            "dsh_model_limits": {
                    "model_id": EXPERIMENTAL_MODEL_ID if args.model_provider != "local"
                        else (LOCAL_MODEL_ID if local_model is not None else None),
                    "max_completion_tokens_per_call": 2_048,
                    "max_model_calls_per_task": 12,
                    "max_task_seconds": 600,
                    "max_request_bytes": 56 * 1_024,
                    "max_response_bytes": 56 * 1_024,
                    "agent_host_network_entitlement": False,
                    "node_network_entitlement": False,
                    "model_bridge_network_entitlement": args.model_provider != "local",
                    **({
                        "model_bridge_service": "org.khaos.Seed.DSHModelBridge",
                        "model_bridge_peer": "anonymous bridge listener; Launcher transfers endpoint to signed AgentHost XPC; bridge checks Host identity",
                        "api_key_delivery": "Launcher to AgentHost XPC frame, then fixed AgentHost-to-bridge XPC; not in Node environment",
                    } if args.model_provider != "local" else {
                        "local_model_process": "untrusted Node child; fixed bundled CPU llama.cpp executable; offline; task cancellation kills the process group",
                        "local_model_files": "signed AgentHost bundle resources; prompt files mode 0600 and removed after each call",
                    }),
                },
            "model_network_boundary": (
                "only the dedicated fixed-endpoint model XPC has network.client; Launcher, AgentHost, and Node do not"
                if args.model_provider != "local" else (
                    "offline local CPU model; Launcher, AgentHost, and Node have no network.client entitlement"
                    if local_model is not None else "no model configured; no network.client entitlement"
                )
            ),
            "dsh_sha": PINNED_DSH_SHA,
            "dsh_host_build": [
                "tsc -b tsconfig.host.json",
                "tsdown --config-loader native --env.DSH_BUILD_FACE host",
            ],
            "dsh_license_sha256": digest(dsh_source / "LICENSE"),
            "dsh_third_party_notices_sha256": digest(dsh_source / "THIRD_PARTY_NOTICES.md"),
            "node_version": PINNED_NODE_VERSION,
            "node_archive_sha256": PINNED_NODE_ARCHIVE_SHA256,
            "node_license_sha256": digest(node_dir / "LICENSE"),
            "dsh_runtime_bundle_sha256": runtime_hash,
        }
        seed_builder._assemble_app(
            app,
            source_root=source_root,
            build_record=build_record,
            sdk=sdk,
            swiftc=swiftc,
            install_name_tool=install_name_tool,
            python=python,
            architecture=platform.machine(),
            signing_identity=identity,
            keychain=args.keychain,
            # Keep the DSH Host sandbox network-free. Remote requests go through
            # the separately signed, peer-verified model XPC below.
            model_provider="local",
            llama_cli=local_model[0] if local_model is not None else None,
            model_file=local_model[1] if local_model is not None else None,
            model_license=local_model[2] if local_model is not None else None,
        )

        host = app / "Contents/XPCServices/KhaosAgentHost.xpc"
        host_resources = host / "Contents/Resources"
        host_info_path = host / "Contents/Info.plist"
        with host_info_path.open("rb") as stream:
            host_info = plistlib.load(stream)
        for key, path in probe_paths.items():
            host_info[key] = str(path)
        host_info["KhaosDSHProbeKernelPath"] = str(
            output_app / "Contents/XPCServices/KernelProduction.xpc/Contents/MacOS/KernelProduction"
        )
        host_info["KhaosDSHProbeLocalPort"] = str(args.probe_local_port)
        if fixed_script_argument is not None:
            host_info["KhaosDSHCandidateBFixedScriptArgument"] = fixed_script_argument
        host_info["KhaosModelProvider"] = args.model_provider
        dsh_resources = host_resources / "dsh"
        dsh_resources.mkdir(parents=True)
        node = host_resources / "node"
        shutil.copy2(node_source, node)
        shutil.copy2(runtime_bundle, dsh_resources / "agenthost-runtime.mjs")
        shutil.copy2(node_dir / "LICENSE", host_resources / "NODE_LICENSE")
        shutil.copy2(dsh_source / "LICENSE", host_resources / "DSH_LICENSE")
        shutil.copy2(dsh_source / "THIRD_PARTY_NOTICES.md", host_resources / "DSH_THIRD_PARTY_NOTICES.md")
        (host_resources / "package.json").write_text(
            json.dumps({"name": "khaos-dsh-xpc-acceptance", "version": "0.2.1-rc.2"}) + "\n",
            encoding="utf-8",
        )

        node_entitlements = temporary / "node-entitlements.plist"
        node_entitlements.write_bytes(plistlib.dumps({"com.apple.security.cs.allow-jit": True}))
        sign = ["codesign", "--force"]
        if args.keychain is not None:
            sign.extend(("--keychain", str(args.keychain.expanduser().resolve(strict=True))))
        run(sign + [
            "--options", "runtime", "--timestamp=none", "--sign", identity,
            "--entitlements", str(node_entitlements), "--identifier",
            "org.khaos.Seed.AgentHost.DSHAcceptanceRuntime", str(node),
        ])

        launcher_info_path = app / "Contents/Info.plist"
        with launcher_info_path.open("rb") as stream:
            launcher_info = plistlib.load(stream)
        launcher_info["KhaosModelProvider"] = args.model_provider
        launcher_requirement = seed_builder._designated_requirement(
            app / "Contents/MacOS/KhaosSeed",
            seed_builder.APP_ID,
        )
        with launcher_info_path.open("wb") as stream:
            plistlib.dump(launcher_info, stream, sort_keys=True)

        if args.model_provider != "local":
            host_binary = host / "Contents/MacOS/KhaosAgentHost"
            host_requirement = seed_builder._designated_requirement(
                host_binary,
                seed_builder.AGENT_HOST_ID,
            )
            model_bridge_probe = host_resources / "dsh-model-bridge-peer-probe"
            run([
                swiftc,
                "-sdk", sdk,
                "-target", f"{platform.machine()}-apple-macosx26.0",
                str(source_root / "khaos/macos/AgentHostProtocol.swift"),
                str(model_bridge_probe_source),
                "-o", str(model_bridge_probe),
            ])
            run(sign + [
                "--options", "runtime", "--timestamp=none", "--sign", identity,
                "--identifier", "org.khaos.Seed.AgentHost.DSHModelBridgePeerProbe",
                str(model_bridge_probe),
            ])
            host_info["KhaosDSHModelBridgeProbePath"] = model_bridge_probe.name
            bridge = app / "Contents/XPCServices/DSHModelBridge.xpc"
            bridge_contents = bridge / "Contents"
            bridge_binary = bridge_contents / "MacOS/DSHModelBridge"
            bridge_binary.parent.mkdir(parents=True)
            run([
                swiftc,
                "-sdk", sdk,
                "-target", f"{platform.machine()}-apple-macosx26.0",
                str(source_root / "khaos/macos/AgentHostProtocol.swift"),
                str(model_bridge_service_source),
                "-o", str(bridge_binary),
            ])
            plistlib.dump({
                "CFBundleIdentifier": DSH_MODEL_BRIDGE_ID,
                "CFBundleExecutable": "DSHModelBridge",
                "CFBundleInfoDictionaryVersion": "6.0",
                "CFBundlePackageType": "XPC!",
                "CFBundleName": "Khaos DSH Model Bridge",
                "CFBundleShortVersionString": "0.1.0",
                "CFBundleVersion": "1",
                "LSMinimumSystemVersion": "26.0",
                "KhaosAgentHostRequirement": host_requirement,
                "KhaosLauncherRequirement": launcher_requirement,
                "KhaosModelProvider": args.model_provider,
                "XPCService": {"ServiceType": "Application", "RunLoopType": "NSRunLoop"},
            }, (bridge_contents / "Info.plist").open("wb"), sort_keys=True)
            bridge_entitlements = temporary / "dsh-model-bridge-entitlements.plist"
            bridge_entitlements.write_bytes(plistlib.dumps({
                "com.apple.security.app-sandbox": True,
                "com.apple.security.network.client": True,
            }))
            run(sign + [
                "--sign", identity,
                "--entitlements", str(bridge_entitlements),
                str(bridge),
            ])
            bridge_requirement = seed_builder._designated_requirement(
                bridge_binary,
                DSH_MODEL_BRIDGE_ID,
            )
            host_info["KhaosDSHModelBridgeRequirement"] = bridge_requirement
            with launcher_info_path.open("rb") as stream:
                launcher_info = plistlib.load(stream)
            launcher_info["KhaosDSHModelBridgeRequirement"] = bridge_requirement
            with launcher_info_path.open("wb") as stream:
                plistlib.dump(launcher_info, stream, sort_keys=True)
        with host_info_path.open("wb") as stream:
            plistlib.dump(host_info, stream, sort_keys=True)

        host_entitlements = app.parent / "agent-host-entitlements.plist"
        run(sign + ["--sign", identity, "--entitlements", str(host_entitlements), str(host)])

        node_entitlement_values = signed_entitlements(node)
        host_entitlement_values = signed_entitlements(host)
        if node_entitlement_values.get("com.apple.security.network.client") is True:
            raise RuntimeError("signed DSH Node unexpectedly has network.client")
        if host_entitlement_values.get("com.apple.security.network.client") is True:
            raise RuntimeError("signed DSH AgentHost unexpectedly has network.client")
        build_record["signed_network_entitlement_check"] = {
            "node_network_client": False,
            "agent_host_network_client": False,
            "model_bridge_network_client": (
                signed_entitlements(app / "Contents/XPCServices/DSHModelBridge.xpc").get(
                    "com.apple.security.network.client"
                ) is True
                if args.model_provider != "local" else False
            ),
        }
        if args.model_provider != "local" and not build_record["signed_network_entitlement_check"]["model_bridge_network_client"]:
            raise RuntimeError("signed model bridge is missing network.client")

        embedded = {
            str(path.relative_to(app)): seed_builder._sha256_file(path)
            for path in sorted(app.rglob("*"))
            if path.is_file() and not path.is_symlink()
            and path.relative_to(app).parts[1:2] == ("XPCServices",)
        }
        build_record["embedded_sha256"] = embedded
        build_record_path = app / "Contents/Resources/build-inputs.json"
        build_record_path.write_text(json.dumps(build_record, sort_keys=True, indent=2) + "\n")
        app_entitlements = app.parent / "app-entitlements.plist"
        run(sign + ["--sign", identity, "--entitlements", str(app_entitlements), str(app)])
        seed_builder.verify_app(app, identity)
        if args.model_provider != "local":
            run([
                "codesign", "--verify", "--deep", "--strict",
                f'-R=identifier "{DSH_MODEL_BRIDGE_ID}" and certificate leaf = H"{identity}"',
                str(app / "Contents/XPCServices/DSHModelBridge.xpc"),
            ])
        run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)])
        seed_builder._publish_app(app, output_app)
        seed_builder.verify_app(output_app, identity)

        host_binary = output_app / "Contents/XPCServices/KhaosAgentHost.xpc/Contents/MacOS/KhaosAgentHost"
        kernel_binary = output_app / "Contents/XPCServices/KernelProduction.xpc/Contents/MacOS/KernelProduction"
        print("signed_xpc_acceptance_build=PASS")
        print(f"khaos_base_sha={KHAOS_BASE_SHA}")
        print(f"khaos_source_sha={source_sha}")
        print(f"dsh_sha={PINNED_DSH_SHA}")
        print(f"host_source_override_sha256={replacement_hash}")
        print(f"node_sha256={digest(output_app / 'Contents/XPCServices/KhaosAgentHost.xpc/Contents/Resources/node')}")
        print(f"dsh_runtime_bundle_sha256={runtime_hash}")
        print(f"agent_host_binary_sha256={digest(host_binary)}")
        if args.model_provider != "local":
            print(f"model_bridge_binary_sha256={digest(output_app / 'Contents/XPCServices/DSHModelBridge.xpc/Contents/MacOS/DSHModelBridge')}")
        print(f"kernel_binary_sha256={digest(kernel_binary)}")
        print(f"app_bundle={output_app}")
        print(f"app_bundle_bytes={sum(path.stat().st_size for path in output_app.rglob('*') if path.is_file())}")
        completed = True
        return 0
    finally:
        if not completed and output_app.exists():
            shutil.rmtree(output_app, ignore_errors=True)
        shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
