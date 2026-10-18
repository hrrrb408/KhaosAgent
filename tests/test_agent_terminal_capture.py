from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CAPTURE_SCRIPT = ROOT / "reports/benchmark/dataset-v1/capture_agent_events.py"
SPEC = importlib.util.spec_from_file_location("capture_agent_events", CAPTURE_SCRIPT)
assert SPEC is not None and SPEC.loader is not None
capture_agent_events = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture_agent_events)


def task_record(reason: str, *, proposals: int = 1, return_codes: str = "0") -> str:
    return (
        f"Launcher task record: proposals={proposals}; executed command return codes=[{return_codes}]; "
        f"cumulative Runner time=1.250s; bounded result bytes=128; stop reason={reason}. "
        "Only these command results are verified; broader test coverage is not inferred."
    )


class AgentTerminalCaptureTests(unittest.TestCase):
    def summarize(self, stdout: str = "", stderr: str = "", **kwargs):
        return capture_agent_events.summarize_terminal(
            stdout,
            stderr,
            attempt_id=kwargs.pop("attempt_id", "synthetic-01"),
            synthetic=True,
            **kwargs,
        )

    def test_final_text_and_launcher_status_are_task_completion(self) -> None:
        stdout = (
            "Khaos: MODEL_RESPONSE_SECRET_CANARY\n"
            "Launcher task status: finished: Agent Host returned a final response.\n"
            + task_record("finished: Agent Host returned a final response")
        )
        summary = self.summarize(
            stdout,
            "agent-session=tool-proposal kind=shell\nagent-session=tool=executed returncode=0\n",
            waiter_exit_code=0,
        )
        self.assertEqual(summary["terminal_class"], "task_completed")
        self.assertTrue(summary["terminal_observed"])
        self.assertTrue(summary["evidence_complete"])
        self.assertEqual(summary["observed_tool_proposals"], 1)
        self.assertEqual(summary["executed_command_return_codes"], [0])
        self.assertEqual(summary["event_counts"]["tool_proposal_observed"], 1)
        self.assertNotIn("MODEL_RESPONSE_SECRET_CANARY", json.dumps(summary))

    def test_final_response_after_seven_successful_tools_is_task_completion(self) -> None:
        stderr = "\n".join(
            event
            for _ in range(7)
            for event in (
                "agent-session=tool-proposal kind=shell",
                "agent-session=tool=approval-presented",
                "agent-session=tool=approved",
                "agent-session=tool=executed returncode=0",
                "agent-session=tool-result kind=shell returncode=0 output_bytes=0 can_continue=true",
                "agent-session=tool-response kind=shell status=accepted can_continue=true",
            )
        )
        stdout = (
            "Khaos: all seven reviewed commands returned zero.\n"
            "Launcher task status: finished: Agent Host returned a final response.\n"
            + task_record(
                "finished: Agent Host returned a final response",
                proposals=7,
                return_codes=",".join(["0"] * 7),
            )
        )
        summary = self.summarize(stdout, stderr)
        self.assertTrue(summary["synthetic"])
        self.assertEqual(summary["terminal_class"], "task_completed")
        self.assertEqual(summary["observed_tool_proposals"], 7)
        self.assertEqual(summary["executed_command_return_codes"], [0] * 7)
        self.assertEqual(summary["event_counts"]["tool_approval_approved"], 7)
        self.assertEqual(summary["event_counts"]["tool_result_returned"], 7)
        self.assertEqual(summary["event_counts"]["tool_response_accepted"], 7)
        self.assertTrue(summary["agent_final_response_observed"])
        self.assertEqual(summary["event_counts"]["agent_final_response_marker"], 1)

    def test_task_record_final_response_without_text_marker_is_observed(self) -> None:
        summary = self.summarize(
            task_record("finished: Agent Host returned a final response"),
            waiter_exit_code=0,
        )
        self.assertEqual(summary["terminal_class"], "task_completed")
        self.assertTrue(summary["agent_final_response_observed"])
        self.assertEqual(summary["event_counts"]["agent_final_response_marker"], 0)

    def test_task_status_final_response_without_text_marker_is_observed(self) -> None:
        summary = self.summarize(
            "Launcher task status: finished: Agent Host returned a final response.\n",
            waiter_exit_code=0,
        )
        self.assertEqual(summary["terminal_class"], "task_completed")
        self.assertTrue(summary["agent_final_response_observed"])
        self.assertEqual(summary["event_counts"]["agent_final_response_marker"], 0)

    def test_failure_text_cannot_override_stopped_terminal_status(self) -> None:
        summary = self.summarize(
            "Launcher task status: stopped: post-stop note says Agent Host returned a final response.\n",
            waiter_exit_code=0,
        )
        self.assertEqual(summary["terminal_class"], "task_stopped")
        self.assertFalse(summary["agent_final_response_observed"])

    def test_shape_failure_and_correction_failure_are_attributed(self) -> None:
        diagnostics = "\n".join([
            "agent-host-model-diagnostic event=initial_response_failed attempt=initial stage=action_shape error=invalid_model_output_shape root_is_object=true expected_key_count=10 actual_key_count=9 missing_keys=text unexpected_key_count=0",
            "agent-host-model-diagnostic event=correction_requested cause=model_shape",
            "agent-host-model-diagnostic event=correction_response_failed attempt=correction stage=action_shape error=invalid_model_output_shape root_is_object=true expected_key_count=10 actual_key_count=9 missing_keys=text unexpected_key_count=0",
        ])
        reason = "Agent Host or model failed: invalid_model_output_shape"
        summary = self.summarize(
            task_record(reason, proposals=7, return_codes="0,0,0,0,0,0,0"),
            "Local Agent error: invalid_model_output_shape\n",
            agenthost_diagnostics=diagnostics,
            waiter_exit_code=0,
        )
        self.assertEqual(summary["terminal_class"], "task_failed")
        self.assertEqual(summary["error_code"], "invalid_model_output_shape")
        self.assertEqual(summary["observed_tool_proposals"], 7)
        self.assertEqual(summary["executed_command_return_codes"], [0] * 7)
        self.assertEqual(summary["event_counts"]["model_response_rejected"], 2)
        self.assertEqual(summary["event_counts"]["correction_requested"], 1)
        self.assertEqual(summary["event_counts"]["correction_failed"], 1)
        self.assertEqual(summary["host_diagnostic_events"][0]["missing_keys"], ["text"])
        self.assertNotIn("raw response", json.dumps(summary))

    def test_all_production_host_diagnostic_stages_are_preserved(self) -> None:
        stages = [
            "provider_request",
            "provider_response",
            "model_content",
            "action_json",
            "action_shape",
            "action_field_types",
            "agent_action_validation",
            "harness_state",
            "context",
        ]
        diagnostics = "\n".join(
            "agent-host-model-diagnostic event=initial_response_failed "
            f"attempt=initial stage={stage} error=invalid_model_output_json "
            "raw_model_output=MODEL_OUTPUT_SECRET_CANARY unknown_field=DROP_CANARY"
            for stage in stages
        )
        summary = self.summarize(
            task_record("Agent Host or model failed: invalid_model_output_json"),
            agenthost_diagnostics=diagnostics,
        )

        events = summary["host_diagnostic_events"]
        self.assertEqual([event["event"] for event in events], ["initial_response_failed"] * len(stages))
        self.assertEqual([event["stage"] for event in events], stages)
        self.assertEqual([event["error"] for event in events], ["invalid_model_output_json"] * len(stages))
        self.assertEqual(summary["event_counts"]["model_response_rejected"], len(stages))
        serialized = json.dumps(summary)
        self.assertNotIn("MODEL_OUTPUT_SECRET_CANARY", serialized)
        self.assertNotIn("DROP_CANARY", serialized)
        self.assertNotIn("raw_model_output", serialized)

    def test_launcher_response_stages_match_the_production_client_contract(self) -> None:
        stages = [
            "xpc_transport_failure",
            "host_returned_nil",
            "launcher_reply_decode_failure",
            "unexpected_reply_type",
        ]
        for stage in stages:
            self.assertEqual(
                capture_agent_events._sanitize_agent_session_event(
                    f"host-response=invalid stage={stage}"
                ),
                "host-response=invalid",
            )

    def test_unknown_host_diagnostic_stage_is_filtered_and_oversized_event_rejected(self) -> None:
        diagnostics = "\n".join([
            "agent-host-model-diagnostic event=initial_response_failed attempt=initial "
            "stage=unknown_stage error=invalid_model_output_json unknown=DROP_CANARY",
            "agent-host-model-diagnostic event=initial_response_failed attempt=initial "
            "stage=action_shape error=invalid_model_output_shape unknown=" + "X" * 513,
        ])
        summary = self.summarize(
            task_record("Agent Host or model failed: invalid_model_output_shape"),
            agenthost_diagnostics=diagnostics,
        )

        self.assertEqual(summary["host_diagnostic_events"], [{
            "event": "initial_response_failed",
            "attempt": "initial",
            "error": "invalid_model_output_json",
        }])
        self.assertEqual(summary["event_counts"]["model_response_rejected"], 1)
        serialized = json.dumps(summary)
        self.assertNotIn("unknown_stage", serialized)
        self.assertNotIn("DROP_CANARY", serialized)
        self.assertNotIn("X" * 513, serialized)

    def test_invalid_json_and_correction_failure_keep_the_json_stage(self) -> None:
        diagnostics = (
            "agent-host-model-diagnostic event=initial_response_failed attempt=initial "
            "stage=action_json error=invalid_model_output_json\n"
            "agent-host-model-diagnostic event=correction_requested cause=model_json\n"
            "agent-host-model-diagnostic event=correction_response_failed attempt=correction "
            "stage=action_json error=invalid_model_output_json"
        )
        summary = self.summarize(
            task_record("Agent Host or model failed: invalid_model_output_json"),
            agenthost_diagnostics=diagnostics,
        )
        self.assertEqual(summary["terminal_class"], "task_failed")
        self.assertEqual(summary["error_code"], "invalid_model_output_json")
        self.assertEqual(summary["event_counts"]["model_response_rejected"], 2)
        self.assertEqual(summary["event_counts"]["correction_requested"], 1)
        self.assertEqual(summary["event_counts"]["correction_failed"], 1)
        stages = [
            event["stage"]
            for event in summary["host_diagnostic_events"]
            if "stage" in event
        ]
        self.assertEqual(stages, ["action_json", "action_json"])

    def test_correction_acceptance_is_separate_from_task_completion(self) -> None:
        diagnostics = (
            "agent-host-model-diagnostic event=correction_requested cause=model_shape\n"
            "agent-host-model-diagnostic event=correction_response_accepted attempt=correction"
        )
        stdout = (
            "Khaos: answer\n"
            "Launcher task status: finished: Agent Host returned a final response.\n"
            + task_record("finished: Agent Host returned a final response")
        )
        summary = self.summarize(stdout, agenthost_diagnostics=diagnostics)
        self.assertEqual(summary["terminal_class"], "task_completed")
        self.assertEqual(summary["event_counts"]["correction_requested"], 1)
        self.assertEqual(summary["event_counts"]["correction_accepted"], 1)
        self.assertEqual(summary["event_counts"]["correction_failed"], 0)

    def test_successful_tool_result_and_next_response_are_distinct_events(self) -> None:
        stderr = "\n".join([
            "agent-session=tool-proposal kind=list",
            "agent-session=tool=approval-presented",
            "agent-session=tool=approved",
            "agent-session=tool=executed returncode=0",
            "agent-session=tool-result kind=list returncode=0 output_bytes=12 can_continue=true",
            "agent-session=tool-response kind=list status=accepted can_continue=true",
        ])
        summary = self.summarize(
            "Launcher task status: finished: Agent Host returned a final response.\n"
            + task_record("finished: Agent Host returned a final response"),
            stderr,
        )
        self.assertEqual(summary["event_counts"]["tool_proposal_observed"], 1)
        self.assertEqual(summary["event_counts"]["tool_approval_presented"], 1)
        self.assertEqual(summary["event_counts"]["tool_approval_approved"], 1)
        self.assertEqual(summary["event_counts"]["tool_execution_completed"], 1)
        self.assertEqual(summary["event_counts"]["tool_result_returned"], 1)
        self.assertEqual(summary["event_counts"]["tool_response_accepted"], 1)

    def test_nonzero_command_result_is_not_task_success(self) -> None:
        reason = "failed: last executed command returned code 1"
        summary = self.summarize(
            "Launcher task status: failed: last executed command returned code 1.\n"
            + task_record(reason, return_codes="1"),
            waiter_exit_code=0,
        )
        self.assertEqual(summary["terminal_class"], "task_failed")
        self.assertEqual(summary["executed_command_return_codes"], [1])
        self.assertEqual(summary["launch_services_waiter_exit_code"], 0)

    def test_workspace_picker_cancellation_is_not_success(self) -> None:
        reason = "stopped: user cancelled workspace selection"
        summary = self.summarize(
            "Launcher task status: stopped: user cancelled workspace selection.\n"
            + task_record(reason),
        )
        self.assertEqual(summary["terminal_class"], "task_cancelled")
        self.assertNotEqual(summary["terminal_class"], "task_completed")

    def test_user_denial_is_distinct_from_tool_execution(self) -> None:
        reason = "stopped: user denied the proposed operation; it was not executed"
        summary = self.summarize(
            "Launcher task status: " + reason + ".\n" + task_record(reason),
            "agent-session=tool=approval-denied\n",
        )
        self.assertEqual(summary["terminal_class"], "task_cancelled")
        self.assertEqual(summary["event_counts"]["tool_execution_completed"], 0)
        self.assertEqual(summary["event_counts"]["tool_approval_denied"], 1)

    def test_budget_exhaustion_is_not_task_success(self) -> None:
        reason = "stopped: tool-call budget exhausted"
        summary = self.summarize(
            "Launcher task status: " + reason + ".\n" + task_record(reason, proposals=8, return_codes=",".join(["0"] * 8)),
            waiter_exit_code=0,
        )
        self.assertEqual(summary["terminal_class"], "budget_exhausted")
        self.assertEqual(summary["observed_tool_proposals"], 8)

    def test_host_termination_requires_a_process_observation(self) -> None:
        reason = "Agent Host failed while receiving a tool result"
        stdout = task_record(reason)
        without_process_evidence = self.summarize(stdout)
        with_process_evidence = self.summarize(
            stdout,
            agent_host_termination_observed=True,
        )
        self.assertEqual(without_process_evidence["terminal_class"], "task_failed")
        self.assertEqual(with_process_evidence["terminal_class"], "agent_host_terminated")

    def test_launcher_termination_is_separate_from_waiter_exit(self) -> None:
        summary = self.summarize(
            waiter_exit_code=0,
            launcher_termination_observed=True,
        )
        self.assertEqual(summary["terminal_class"], "launcher_terminated")
        self.assertTrue(summary["terminal_observed"])
        self.assertNotEqual(summary["terminal_class"], "task_completed")

    def test_waiter_exit_zero_without_task_record_is_unknown(self) -> None:
        summary = self.summarize(
            waiter_exit_code=0,
            stderr="agent-session=tool=executed returncode=0\n",
        )
        self.assertFalse(summary["terminal_observed"])
        self.assertFalse(summary["evidence_complete"])
        self.assertEqual(summary["terminal_class"], "terminal_outcome_not_captured")

    def test_final_text_without_launcher_terminal_record_is_not_task_completion(self) -> None:
        summary = self.summarize("Khaos: final response observed\n", waiter_exit_code=0)
        self.assertTrue(summary["agent_final_response_observed"])
        self.assertFalse(summary["terminal_observed"])
        self.assertEqual(summary["terminal_class"], "terminal_outcome_not_captured")
        self.assertEqual(summary["reason_code"], "final_response_without_task_terminal_record")

    def test_capture_process_stop_without_task_marker_is_unknown(self) -> None:
        summary = self.summarize(
            waiter_exit_code=0,
            capture_process_completed=False,
        )
        self.assertEqual(summary["terminal_class"], "terminal_outcome_not_captured")
        self.assertEqual(summary["reason_code"], "capture_process_stopped_without_task_terminal")

    def test_multiple_attempts_do_not_share_terminal_state(self) -> None:
        success = self.summarize(
            "Khaos: done\n" + task_record("finished: Agent Host returned a final response"),
            attempt_id="m8-2-glm53-02",
        )
        missing = self.summarize(attempt_id="m8-2-glm53-01", waiter_exit_code=0)
        self.assertEqual(success["attempt_id"], "m8-2-glm53-02")
        self.assertEqual(success["terminal_class"], "task_completed")
        self.assertEqual(missing["attempt_id"], "m8-2-glm53-01")
        self.assertEqual(missing["terminal_class"], "terminal_outcome_not_captured")

    def test_conflicting_launcher_markers_fail_closed(self) -> None:
        stdout = (
            "Launcher task status: finished: Agent Host returned a final response.\n"
            + task_record("failed: last executed command returned code 1")
        )
        summary = self.summarize(stdout)
        self.assertEqual(summary["terminal_class"], "terminal_outcome_not_captured")
        self.assertTrue(summary["conflicting_terminal_markers"])

    def test_unknown_diagnostic_fields_and_raw_canaries_are_discarded(self) -> None:
        diagnostics = (
            "agent-host-model-diagnostic event=initial_response_failed attempt=initial "
            "stage=action_shape error=invalid_model_output_shape missing_keys=text "
            "unknown_model_field=MODEL_RESPONSE_SECRET_CANARY"
        )
        summary = self.summarize(
            task_record("Agent Host or model failed: invalid_model_output_shape"),
            agenthost_diagnostics=diagnostics,
        )
        serialized = json.dumps(summary)
        self.assertNotIn("MODEL_RESPONSE_SECRET_CANARY", serialized)
        self.assertNotIn("unknown_model_field", serialized)
        self.assertEqual(summary["host_diagnostic_events"][0]["missing_keys"], ["text"])

    def test_attempt_id_rejects_unbounded_or_injectable_values(self) -> None:
        with self.assertRaises(ValueError):
            self.summarize(attempt_id="attempt\nsecret")

    def test_normalization_counts_require_subsequent_semantic_acceptance(self) -> None:
        events = [
            "event=action_response_received attempt=initial",
            "event=action_text_normalized attempt=initial raw=PRIVATE_CANARY",
            "event=initial_response_failed attempt=initial stage=action_field_types error=invalid_model_output_field_types",
            "event=correction_requested cause=model_field_types",
            "event=action_response_received attempt=correction",
            "event=action_text_normalized attempt=correction",
            "event=action_response_accepted attempt=correction",
            "event=correction_response_accepted attempt=correction",
            "event=action_response_received attempt=initial",
            "event=action_response_accepted attempt=initial",
        ]
        summary = self.summarize(agenthost_diagnostics="\n".join(
            "agent-host-model-diagnostic " + event for event in events
        ))
        counts = summary["event_counts"]
        for key, expected in {
            "initial_action_responses": 2, "initial_action_accepted": 1,
            "initial_action_rejected": 1, "normalization_applied": 2,
            "normalization_accepted": 1, "missing_text": 2,
            "correction_requested": 1, "correction_accepted": 1,
        }.items():
            self.assertEqual(counts[key], expected, key)
        self.assertNotIn("PRIVATE_CANARY", json.dumps(summary))
        self.assertNotIn("raw", summary["host_diagnostic_events"][1])

    def test_diagnostic_capacity_covers_budget_and_reports_overflow(self) -> None:
        events = "\n".join(
            "agent-host-model-diagnostic event=action_response_received attempt=initial"
            for _ in range(200)
        )
        summary = self.summarize(agenthost_diagnostics=events)
        self.assertEqual(len(summary["host_diagnostic_events"]), 128)
        self.assertEqual(summary["event_counts"]["diagnostic_events_dropped"], 72)
        self.assertFalse(summary["diagnostic_capture_complete"])

    def test_snapshot_cli_writes_only_sanitized_attempt_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stdout = root / "launcher.stdout"
            stderr = root / "launcher.stderr"
            host = root / "agenthost.log"
            output = root / "terminal.jsonl"
            stdout.write_text(
                "Khaos: FINAL_TEXT_SECRET_CANARY\n"
                "Launcher task status: finished: Agent Host returned a final response.\n"
                + task_record("finished: Agent Host returned a final response"),
                encoding="utf-8",
            )
            stderr.write_text("", encoding="utf-8")
            host.write_text("", encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    str(CAPTURE_SCRIPT),
                    "--snapshot",
                    "--attempt-id", "synthetic-cli-01",
                    "--stdout", str(stdout),
                    "--stderr", str(stderr),
                    "--agenthost-diagnostics", str(host),
                    "--waiter-exit-code", "0",
                    "--synthetic",
                    "--output", str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            event = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(event["attempt_id"], "synthetic-cli-01")
            self.assertEqual(event["terminal_class"], "task_completed")
            self.assertIn("stdout", event["input_sha256"])
            self.assertNotIn("FINAL_TEXT_SECRET_CANARY", output.read_text(encoding="utf-8"))

    def test_live_capture_reports_waiter_exit_without_task_record_as_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stdout = root / "launcher.stdout"
            stderr = root / "launcher.stderr"
            output = root / "terminal.jsonl"
            stdout.write_text("partial output\n", encoding="utf-8")
            stderr.write_text("agent-session=tool=executed returncode=0\n", encoding="utf-8")
            waiter = subprocess.Popen([sys.executable, "-c", "pass"])
            waiter.wait(timeout=5)
            subprocess.run(
                [
                    sys.executable,
                    str(CAPTURE_SCRIPT),
                    "--attempt-id", "synthetic-ended-01",
                    "--waiter-pid", str(waiter.pid),
                    "--stdout", str(stdout),
                    "--stderr", str(stderr),
                    "--output", str(output),
                    "--max-wait-seconds", "1",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            events = [json.loads(line) for line in output.read_text().splitlines()]
            terminal = events[-1]
            self.assertEqual(terminal["event"], "terminal_outcome")
            self.assertTrue(terminal["waiter_process_exit_observed"])
            self.assertFalse(terminal["terminal_observed"])
            self.assertEqual(terminal["terminal_class"], "terminal_outcome_not_captured")

    def test_live_capture_caps_event_count_and_discards_event_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stdout = root / "launcher.stdout"
            stderr = root / "launcher.stderr"
            output = root / "terminal.jsonl"
            stdout.write_text(
                task_record("finished: Agent Host returned a final response") + "\n",
                encoding="utf-8",
            )
            stderr.write_text(
                "agent-session=tool=approved\n" * 300
                + "agent-session=MODEL_OUTPUT_SECRET_CANARY\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    sys.executable,
                    str(CAPTURE_SCRIPT),
                    "--attempt-id", "synthetic-bounded-01",
                    "--stdout", str(stdout),
                    "--stderr", str(stderr),
                    "--output", str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            serialized = output.read_text(encoding="utf-8")
            self.assertLessEqual(len(serialized.splitlines()), 129)
            self.assertNotIn("MODEL_OUTPUT_SECRET_CANARY", serialized)

    def test_truncated_capture_keeps_terminal_class_but_marks_evidence_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stdout = root / "launcher.stdout"
            stderr = root / "launcher.stderr"
            host = root / "agenthost.log"
            output = root / "terminal.jsonl"
            stdout.write_text(
                "x" * (capture_agent_events.MAX_LOG_BYTES + 1)
                + "\nLauncher task status: finished: Agent Host returned a final response.\n"
                + task_record("finished: Agent Host returned a final response"),
                encoding="utf-8",
            )
            stderr.write_text("", encoding="utf-8")
            host.write_text("", encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    str(CAPTURE_SCRIPT),
                    "--snapshot",
                    "--attempt-id", "synthetic-truncated-01",
                    "--stdout", str(stdout),
                    "--stderr", str(stderr),
                    "--agenthost-diagnostics", str(host),
                    "--output", str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            terminal = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(terminal["terminal_class"], "task_completed")
            self.assertTrue(terminal["terminal_observed"])
            self.assertFalse(terminal["evidence_complete"])
            self.assertTrue(terminal["input_truncated"]["stdout"])

    def test_oversized_input_is_not_fully_hashed_or_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "large.log"
            with source.open("wb") as stream:
                stream.truncate(capture_agent_events.MAX_HASH_BYTES + 1)
            content, digest, truncated = capture_agent_events._read_bounded(source)
            self.assertEqual(len(content.encode("utf-8")), capture_agent_events.MAX_LOG_BYTES)
            self.assertIsNone(digest)
            self.assertTrue(truncated)


if __name__ == "__main__":
    unittest.main()
