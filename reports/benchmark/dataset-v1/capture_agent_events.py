#!/usr/bin/env python3
"""Capture bounded Agent task markers without copying model or workspace text."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path


MAX_LOG_BYTES = 256 * 1024
MAX_HASH_BYTES = 16 * 1024 * 1024
MAX_TERMINAL_EVENTS = 27
MAX_CAPTURE_EVENTS = 128
MAX_WAIT_SECONDS = 3600
ACTION_KEYS = {
    "type", "text", "argv", "readScope", "writeScope", "pluginID",
    "candidateDigest", "generation", "pluginInput", "evolutionGoal",
}
DIAGNOSTIC_EVENTS = {
    "initial_response_failed",
    "correction_requested",
    "correction_response_failed",
    "correction_response_accepted",
    "harness_state_rejected",
}
ATTEMPT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}\Z")
SAFE_CODE = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
TASK_STATUS = re.compile(r"^Launcher task status: (finished|failed|stopped): (.+)\.$")
TASK_RECORD = re.compile(
    r"^Launcher task record: proposals=(\d+); executed command return codes="
    r"\[([0-9,\-]*)\]; cumulative Runner time=([0-9.]+)s; "
    r"bounded result bytes=(\d+); stop reason=(.*?)\. Only these command results "
    r"are verified; broader test coverage is not inferred\.$"
)


def _status_from_reason(reason: str, *, agent_host_terminated: bool = False) -> tuple[str, str, str | None]:
    lowered = reason.casefold()
    code_match = re.search(
        r"(?:Agent Host or model failed|Local Agent error): ([a-z][a-z0-9_-]{0,63})\Z",
        reason,
    )
    error_code = code_match.group(1) if code_match and SAFE_CODE.fullmatch(code_match.group(1)) else None
    if reason.startswith("finished:"):
        return "task_completed", "final_response", None
    if "budget exhausted" in lowered:
        return "budget_exhausted", "budget_exhausted", None
    if "cancelled" in lowered or "canceled" in lowered or "user denied" in lowered:
        return "task_cancelled", "user_cancelled_or_denied", None
    if agent_host_terminated and "agent host" in lowered:
        return "agent_host_terminated", "host_process_termination_observed", error_code
    if "agent host or model failed" in lowered or "agent host failed" in lowered:
        return "task_failed", "agent_host_or_model_failure", error_code
    if reason.startswith("failed:"):
        return "task_failed", "command_or_launcher_failure", error_code
    if reason.startswith("stopped:"):
        return "task_stopped", "other_launcher_stop", error_code
    if agent_host_terminated:
        return "agent_host_terminated", "host_process_termination_observed", error_code
    return "task_stopped", "unclassified_launcher_stop", error_code


def _parse_status_line(line: str) -> dict[str, str] | None:
    match = TASK_STATUS.fullmatch(line)
    if not match:
        return None
    status, reason = match.groups()
    terminal_class, reason_code, error_code = _status_from_reason(
        f"{status}: {reason}", agent_host_terminated=False
    )
    return {
        "status": status,
        "reason_code": reason_code,
        "terminal_class": terminal_class,
        "error_code": error_code or "",
    }


def _sanitize_agent_session_event(line: str) -> str | None:
    if line in {
        "remote-data=approval-presented",
        "remote-data=approved",
        "remote-data=denied",
        "tool=workspace-picker-requested",
        "tool=workspace-selection-cancelled",
        "tool=approval-presented",
        "tool=approval-denied",
        "tool=approved",
        "task=disallowed_post_result_reply_ignored",
    }:
        return line
    match = re.fullmatch(r"tool-proposal kind=(list|shell)", line)
    if match:
        return f"tool-proposal kind={match.group(1)}"
    match = re.fullmatch(
        r"tool-result kind=(list|shell) returncode=(none|-?\d{1,5}) "
        r"output_bytes=(\d{1,5}) can_continue=(true|false)",
        line,
    )
    if match:
        kind, return_code, output_bytes, can_continue = match.groups()
        if int(output_bytes) <= 32 * 1024 and (
            return_code == "none" or -32_768 <= int(return_code) <= 32_767
        ):
            return (
                f"tool-result kind={kind} returncode={return_code} "
                f"output_bytes={output_bytes} can_continue={can_continue}"
            )
    match = re.fullmatch(
        r"tool-response kind=(list|shell) status=(accepted|rejected) "
        r"can_continue=(true|false)",
        line,
    )
    if match:
        kind, status, can_continue = match.groups()
        return f"tool-response kind={kind} status={status} can_continue={can_continue}"
    match = re.fullmatch(r"tool=executed returncode=(-?\d{1,5})", line)
    if match and -32_768 <= int(match.group(1)) <= 32_767:
        return f"tool=executed returncode={match.group(1)}"
    if re.fullmatch(r"tool=stopped code=[a-z][a-z0-9_-]{0,63}", line):
        return "tool=stopped"
    if re.fullmatch(
        r"host-response=invalid stage=(xpc_transport_failure|host_returned_nil|"
        r"launcher_reply_decode_failure|unexpected_reply_type|provider_request|"
        r"provider_response|model_content_size|model_json_syntax|action_shape|"
        r"action_field_types|host_action_validation|harness_state|context_budget)",
        line,
    ):
        return "host-response=invalid"
    return None


def _parse_task_record(line: str) -> dict[str, object] | None:
    match = TASK_RECORD.fullmatch(line)
    if not match:
        return None
    proposals, codes, seconds, result_bytes, reason = match.groups()
    try:
        proposal_count = int(proposals)
        return_codes = [int(value) for value in codes.split(",")] if codes else []
        runner_seconds = float(seconds)
        bounded_result_bytes = int(result_bytes)
    except ValueError:
        return None
    if (
        not 0 <= proposal_count <= 8
        or len(return_codes) > 8
        or any(not -32_768 <= value <= 32_767 for value in return_codes)
        or not 0 <= runner_seconds <= 180
        or not 0 <= bounded_result_bytes <= 32 * 1024
    ):
        return None
    terminal_class, reason_code, error_code = _status_from_reason(reason)
    return {
        "proposals": proposal_count,
        "return_codes": return_codes,
        "runner_seconds": runner_seconds,
        "bounded_result_bytes": bounded_result_bytes,
        "reason_code": reason_code,
        "terminal_class": terminal_class,
        "error_code": error_code,
    }


def _host_diagnostic_events(text: str) -> tuple[list[dict[str, object]], dict[str, int]]:
    events: list[dict[str, object]] = []
    counts = {
        "model_response_rejected": 0,
        "correction_requested": 0,
        "correction_accepted": 0,
        "correction_failed": 0,
        "harness_state_rejected": 0,
    }
    for line in text.splitlines():
        marker = "agent-host-model-diagnostic "
        if marker not in line or len(line.encode("utf-8", errors="replace")) > 512:
            continue
        fields = dict(re.findall(r"([a-z_]+)=([^\s]+)", line.split(marker, 1)[1]))
        event = fields.get("event")
        if event not in DIAGNOSTIC_EVENTS or len(events) >= MAX_TERMINAL_EVENTS:
            continue
        item: dict[str, object] = {"event": event}
        attempt = fields.get("attempt")
        if attempt in {"initial", "correction", "none"}:
            item["attempt"] = attempt
        stage = fields.get("stage")
        if stage in {
            "provider_request", "provider_response", "model_content",
            "action_json", "action_shape", "action_field_types",
            "agent_action_validation", "harness_state", "context",
        }:
            item["stage"] = stage
        error = fields.get("error")
        if error and SAFE_CODE.fullmatch(error):
            item["error"] = error
        for key in ("expected_key_count", "actual_key_count", "unexpected_key_count"):
            value = fields.get(key)
            if value and value.isdigit() and int(value) <= 10_000:
                item[key] = int(value)
        missing = fields.get("missing_keys")
        if missing and missing != "none":
            names = missing.split(",")
            if all(name in ACTION_KEYS for name in names):
                item["missing_keys"] = names
        events.append(item)
        if event in {"initial_response_failed", "correction_response_failed"}:
            counts["model_response_rejected"] += 1
        if event == "correction_requested":
            counts["correction_requested"] += 1
        if event == "correction_response_accepted":
            counts["correction_accepted"] += 1
        if event == "correction_response_failed":
            counts["correction_failed"] += 1
        if event == "harness_state_rejected":
            counts["harness_state_rejected"] += 1
    return events, counts


def summarize_terminal(
    stdout: str,
    stderr: str,
    *,
    attempt_id: str,
    waiter_exit_code: int | None = None,
    agenthost_diagnostics: str = "",
    agent_host_termination_observed: bool = False,
    launcher_termination_observed: bool = False,
    capture_process_completed: bool = True,
    synthetic: bool = False,
) -> dict[str, object]:
    """Return bounded terminal metadata; never copy model, prompt, or tool text."""
    if not ATTEMPT_ID.fullmatch(attempt_id):
        raise ValueError("attempt_id must be a bounded stable identifier")

    status_lines = [
        parsed for line in stdout.splitlines()
        if (parsed := _parse_status_line(line)) is not None
    ]
    task_records = [
        parsed for line in stdout.splitlines()
        if (parsed := _parse_task_record(line)) is not None
    ]
    final_response_count = sum(line.startswith("Khaos: ") for line in stdout.splitlines())
    stderr_events = [
        safe_event
        for line in stderr.splitlines()
        if line.startswith("agent-session=")
        and len(line.encode("utf-8", errors="replace")) <= 512
        if (safe_event := _sanitize_agent_session_event(line.removeprefix("agent-session=")))
    ]
    host_events, host_counts = _host_diagnostic_events(agenthost_diagnostics)
    observed_error_codes = []
    for line in stderr.splitlines():
        match = re.fullmatch(
            r"(?:Local Agent error|Local Agent stopped): ([a-z][a-z0-9_-]{0,63})",
            line,
        )
        if match and match.group(1) not in observed_error_codes:
            observed_error_codes.append(match.group(1))
            if len(observed_error_codes) == 8:
                break

    event_counts = dict(host_counts)
    event_counts.update({
        "tool_proposal_observed": sum(line.startswith("tool-proposal kind=") for line in stderr_events),
        "tool_approval_presented": stderr_events.count("tool=approval-presented"),
        "tool_approval_approved": stderr_events.count("tool=approved"),
        "tool_approval_denied": stderr_events.count("tool=approval-denied"),
        "tool_result_returned": sum(line.startswith("tool-result kind=") for line in stderr_events),
        "tool_response_accepted": sum("tool-response kind=" in line and "status=accepted" in line for line in stderr_events),
        "tool_execution_completed": sum(line.startswith("tool=executed returncode=") for line in stderr_events),
        "agent_final_response_marker": final_response_count,
    })

    conflicting = len(status_lines) > 1 or len(task_records) > 1
    status = status_lines[-1] if status_lines else None
    record = task_records[-1] if task_records else None
    final_response_observed = final_response_count > 0 or any(
        terminal is not None and terminal["reason_code"] == "final_response"
        for terminal in (status, record)
    )
    if status and record and status["terminal_class"] != record["terminal_class"]:
        conflicting = True

    if conflicting:
        terminal_class = "terminal_outcome_not_captured"
        reason_code = "conflicting_or_multiple_terminal_markers"
        error_code = None
        terminal_observed = False
        source = "ambiguous_launcher_output"
    elif status:
        terminal_class = status["terminal_class"]
        reason_code = status["reason_code"]
        error_code = status["error_code"] or None
        terminal_observed = True
        source = "launcher_task_status"
    elif record:
        # Reclassify only with a separate process observation; a Host error code
        # alone does not prove that the Host process terminated.
        terminal_class = str(record["terminal_class"])
        reason_code = str(record["reason_code"])
        error_code = record["error_code"]
        if agent_host_termination_observed and reason_code == "agent_host_or_model_failure":
            terminal_class = "agent_host_terminated"
            reason_code = "host_process_termination_observed"
        terminal_observed = True
        source = "launcher_task_record"
    elif launcher_termination_observed:
        terminal_class = "launcher_terminated"
        reason_code = "process_termination_observed_without_task_terminal"
        error_code = None
        terminal_observed = True
        source = "launcher_process_observation"
    elif agent_host_termination_observed:
        terminal_class = "agent_host_terminated"
        reason_code = "process_termination_observed_without_task_terminal"
        error_code = None
        terminal_observed = True
        source = "agent_host_process_observation"
    elif final_response_count:
        terminal_class = "terminal_outcome_not_captured"
        reason_code = "final_response_without_task_terminal_record"
        error_code = None
        terminal_observed = False
        source = "launcher_final_response_marker"
    else:
        terminal_class = "terminal_outcome_not_captured"
        reason_code = "capture_process_stopped_without_task_terminal" if not capture_process_completed else "no_launcher_terminal_marker"
        error_code = None
        terminal_observed = False
        source = "capture_process" if not capture_process_completed else "launcher_output"

    if status and agent_host_termination_observed and terminal_class == "task_failed" and status.get("reason_code") == "agent_host_or_model_failure":
        terminal_class = "agent_host_terminated"
        reason_code = "host_process_termination_observed"

    return {
        "attempt_id": attempt_id,
        "synthetic": synthetic,
        "terminal_observed": terminal_observed,
        "terminal_class": terminal_class,
        "reason_code": reason_code,
        "source": source,
        "evidence_complete": terminal_observed and not conflicting,
        "conflicting_terminal_markers": conflicting,
        "task_status_present": status is not None,
        "task_record_present": record is not None,
        "agent_final_response_observed": final_response_observed,
        "observed_tool_proposals": record["proposals"] if record else event_counts["tool_proposal_observed"],
        "last_observed_tool_sequence": record["proposals"] if record else event_counts["tool_proposal_observed"],
        "executed_command_return_codes": record["return_codes"] if record else [],
        "cumulative_runner_seconds": record["runner_seconds"] if record else None,
        "bounded_result_bytes": record["bounded_result_bytes"] if record else None,
        "error_code": error_code,
        "observed_error_codes": observed_error_codes,
        "event_counts": event_counts,
        "host_diagnostic_events": host_events,
        "agent_host_termination_observed": agent_host_termination_observed,
        "launcher_termination_observed": launcher_termination_observed,
        "capture_process_completed": capture_process_completed,
        "launch_services_waiter_exit_code": waiter_exit_code,
    }


def _read_bounded(path: Path) -> tuple[str, str | None, bool]:
    before = path.stat()
    size = before.st_size
    truncated = size > MAX_LOG_BYTES
    digest_value = None
    if size <= MAX_HASH_BYTES:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(64 * 1024), b""):
                digest.update(chunk)
        digest_value = digest.hexdigest()
    else:
        truncated = True
    with path.open("rb") as stream:
        if truncated:
            stream.seek(size - MAX_LOG_BYTES)
        content = stream.read(MAX_LOG_BYTES)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        truncated = True
    return content.decode("utf-8", errors="replace"), digest_value, truncated


def _process_exists(pid: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _write_event(stream, event: dict[str, object]) -> None:
    stream.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
    stream.flush()


def _capture_summary(args, attempt_id: str) -> dict[str, object]:
    stdout, stdout_sha, stdout_truncated = _read_bounded(args.stdout)
    stderr, stderr_sha, stderr_truncated = _read_bounded(args.stderr)
    host_text = ""
    host_sha = None
    host_truncated = False
    if args.agenthost_diagnostics and args.agenthost_diagnostics.exists():
        host_text, host_sha, host_truncated = _read_bounded(args.agenthost_diagnostics)
    summary = summarize_terminal(
        stdout,
        stderr,
        attempt_id=attempt_id,
        waiter_exit_code=args.waiter_exit_code,
        agenthost_diagnostics=host_text,
        agent_host_termination_observed=args.agent_host_termination_observed,
        launcher_termination_observed=args.launcher_termination_observed,
        capture_process_completed=not args.capture_process_incomplete,
        synthetic=args.synthetic,
    )
    summary["input_sha256"] = {
        "stdout": stdout_sha,
        "stderr": stderr_sha,
        "agenthost_diagnostics": host_sha,
    }
    summary["input_truncated"] = {
        "stdout": stdout_truncated,
        "stderr": stderr_truncated,
        "agenthost_diagnostics": host_truncated,
    }
    summary["input_bytes"] = {
        "stdout": args.stdout.stat().st_size,
        "stderr": args.stderr.stat().st_size,
        "agenthost_diagnostics": (
            args.agenthost_diagnostics.stat().st_size
            if args.agenthost_diagnostics and args.agenthost_diagnostics.exists()
            else None
        ),
    }
    if any(summary["input_truncated"].values()):
        summary["evidence_complete"] = False
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdout", required=True, type=Path)
    parser.add_argument("--stderr", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--attempt-id")
    parser.add_argument("--waiter-pid", type=int)
    parser.add_argument("--waiter-exit-code", type=int)
    parser.add_argument("--agenthost-diagnostics", type=Path)
    parser.add_argument("--agent-host-termination-observed", action="store_true")
    parser.add_argument("--launcher-termination-observed", action="store_true")
    parser.add_argument("--capture-process-incomplete", action="store_true")
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--snapshot", action="store_true", help="summarize completed output files once")
    parser.add_argument("--poll-seconds", type=float, default=0.2)
    parser.add_argument("--max-wait-seconds", type=float, default=1800)
    args = parser.parse_args()
    if args.attempt_id is not None and not ATTEMPT_ID.fullmatch(args.attempt_id):
        parser.error("--attempt-id must contain 1-64 safe identifier characters")
    if args.snapshot and args.attempt_id is None:
        parser.error("--snapshot requires --attempt-id")
    if args.poll_seconds <= 0 or args.poll_seconds > 10:
        parser.error("poll interval must be between 0 and 10 seconds")
    if args.max_wait_seconds <= 0 or args.max_wait_seconds > MAX_WAIT_SECONDS:
        parser.error(f"max wait must be between 0 and {MAX_WAIT_SECONDS} seconds")
    if args.waiter_pid is not None and args.waiter_pid <= 1:
        parser.error("waiter pid must be greater than 1")
    output = args.output.expanduser().absolute()
    if output.exists():
        parser.error(f"refusing to overwrite event record: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    if args.snapshot:
        summary = _capture_summary(args, args.attempt_id)
        if args.waiter_pid is not None:
            summary["waiter_process_exit_observed"] = not _process_exists(args.waiter_pid)
        with output.open("x", encoding="utf-8") as stream:
            _write_event(stream, {
                "observed_at_utc": datetime.now(timezone.utc).isoformat(),
                "event": "terminal_outcome",
                **summary,
            })
        return

    offsets = {args.stdout: 0, args.stderr: 0}
    pending = {args.stdout: b"", args.stderr: b""}
    task_record_seen = False
    emitted_events = 0
    started = time.monotonic()
    with output.open("x", encoding="utf-8") as stream:
        while True:
            for path in (args.stderr, args.stdout):
                if not path.exists():
                    continue
                with path.open("rb") as source:
                    source.seek(offsets[path])
                    chunk = source.read()
                    offsets[path] = source.tell()
                combined = pending[path] + chunk
                complete = combined.splitlines(keepends=True)
                if complete and not complete[-1].endswith((b"\n", b"\r")):
                    pending[path] = complete.pop()
                else:
                    pending[path] = b""
                for raw_line in complete:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    event = None
                    if line.startswith("agent-session=") and len(raw_line) <= 512:
                        event = _sanitize_agent_session_event(
                            line.removeprefix("agent-session=")
                        )
                    elif line.startswith("Launcher task status:"):
                        event = "task_status"
                    elif line.startswith("Launcher task record:"):
                        event = "task_record"
                        task_record_seen = True
                    if event is not None and emitted_events < MAX_CAPTURE_EVENTS:
                        record = {
                            "observed_at_utc": datetime.now(timezone.utc).isoformat(),
                            "event": event,
                        }
                        if args.attempt_id:
                            record["attempt_id"] = args.attempt_id
                        _write_event(stream, record)
                        emitted_events += 1
            waiter_done = args.waiter_pid is not None and not _process_exists(args.waiter_pid)
            timed_out = time.monotonic() - started >= args.max_wait_seconds
            if task_record_seen or waiter_done or timed_out:
                summary = _capture_summary(args, args.attempt_id or "unknown")
                summary["waiter_process_exit_observed"] = waiter_done
                if timed_out:
                    summary["capture_process_completed"] = False
                    if not summary["terminal_observed"]:
                        summary["terminal_class"] = "terminal_outcome_not_captured"
                        summary["reason_code"] = "capture_process_stopped_without_task_terminal"
                        summary["source"] = "capture_process"
                _write_event(stream, {
                    "observed_at_utc": datetime.now(timezone.utc).isoformat(),
                    "event": "terminal_outcome",
                    **summary,
                })
                break
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
