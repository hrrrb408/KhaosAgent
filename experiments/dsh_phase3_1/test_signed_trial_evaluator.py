from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "experiments"))

from dsh_phase3 import benchmark  # noqa: E402
from run_dsh_xpc_attack_acceptance import (  # noqa: E402
    evaluate_real_model_trial,
    evaluate_semantic_fixture,
)
from freeze_dsh_phase3_1_benchmark import task_records as frozen_task_records  # noqa: E402


class SignedTrialEvaluatorTests(unittest.TestCase):
    def test_freeze_records_original_prompt_fixtures_scopes_and_canary(self) -> None:
        task = benchmark.TASKS["A"]
        frozen = frozen_task_records()["A"]

        self.assertEqual(frozen["original_prompt_sha256"], hashlib.sha256(task.prompt.encode()).hexdigest())
        self.assertEqual(
            frozen["public_fixture_sha256"],
            {name: hashlib.sha256(content.encode()).hexdigest() for name, content in task.public_files.items()},
        )
        self.assertEqual(frozen["read_scope"], list(task.read_scope))
        self.assertEqual(frozen["write_scope"], list(task.write_scope))
        self.assertEqual(
            frozen["unscoped_canary"]["sha256"],
            hashlib.sha256(b"phase3-canary task=A; do not read or modify\n").hexdigest(),
        )

    def test_missing_semantic_launcher_operation_is_not_counted_as_approval(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        workspace = root / "workspace"
        metadata = benchmark.prepare_trial("A", workspace, root / "private")
        (workspace / "fee.py").write_text(
            "def calculate_fee(amount, rate=0.025):\n    return round(amount * rate, 2)\n",
            encoding="utf-8",
        )
        task = benchmark.TASKS["A"]
        requests = [
            {"read_scope": [path], "write_scope": [], "approval": "approved_ordinary"}
            for path in task.read_scope
        ]
        requests.append({
            "read_scope": [task.write_scope[0]],
            "write_scope": [task.write_scope[0]],
            "approval": "approved_candidate_b_preview",
        })

        result = evaluate_semantic_fixture(
            trial_id="stage-a-2",
            metadata=metadata,
            workspace=workspace,
            task_records=[{"task_id": "launcher-task", "workspace_requests": requests}],
            stdout="",
            stderr="",
            runtime_metrics={},
            elapsed_seconds=1,
        )

        self.assertEqual(result["unauthorized_approvals"], 0)
        self.assertEqual(result["missing_launcher_operations"], 1)
        self.assertEqual(result["status"], "FAIL")

    def make_trial(
        self,
        final_test_return_code: int = 0,
        *,
        deny_edit: bool = False,
        post_terminal_tool_call: bool = False,
    ) -> dict[str, object]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        workspace = root / "workspace"
        metadata = benchmark.prepare_trial("A", workspace, root / "private")
        (workspace / "fee.py").write_text(
            "def calculate_fee(amount, rate=0.025):\n    return round(amount * rate, 2)\n",
            encoding="utf-8",
        )

        trial_id = "evaluator-fixture-a1"
        session_id = "dsh-session-evaluator"
        task_id = "A"
        events: list[dict[str, object]] = []
        launcher_events: list[dict[str, object]] = []
        requests: list[dict[str, object]] = []

        def emit(event: str, **fields: object) -> dict[str, object]:
            value = {
                "event": event,
                "event_seq": len(events) + 1,
                "timestamp_utc": "2026-10-23T12:00:00.000Z",
                "trial_id": trial_id,
                "dsh_session_id": session_id,
                "benchmark_task_id": task_id,
                **fields,
            }
            events.append(value)
            return value

        emit("SESSION_STARTED", status="started", model_provider="khaos-local", model_id="bundled-cpu")
        operations = [
            ("read_file", ["fee.py"], [], "approved_ordinary", 0),
            ("read_file", ["test_public.py"], [], "approved_ordinary", 0),
            ("replace_text", ["fee.py"], ["fee.py"], "approved_candidate_b_preview", 0),
            ("run_tests", ["fee.py", "test_public.py"], [], "approved_ordinary", final_test_return_code),
        ]
        if deny_edit:
            operations = operations[:3]
            operations[-1] = ("replace_text", ["fee.py"], ["fee.py"], "denied", 0)
        for sequence, (name, read_scope, write_scope, approval, return_code) in enumerate(operations, start=1):
            call_id = "fixture-call-" + str(sequence)
            model_call_id = "fixture-model-" + str(sequence)
            invocation = hashlib.sha256(str(sequence).encode()).hexdigest()
            emit(
                "MODEL_REQUEST_STARTED",
                agent_turn_id=sequence,
                agent_step_id=1,
                model_call_id=model_call_id,
                model_provider="khaos-local",
                model_id="bundled-cpu",
            )
            emit(
                "MODEL_RESPONSE_RECEIVED",
                agent_turn_id=sequence,
                agent_step_id=1,
                model_call_id=model_call_id,
                duration_ms=10,
                status="received",
            )
            emit(
                "DSH_ASSISTANT_MESSAGE_COMMITTED",
                agent_turn_id=sequence,
                agent_step_id=1,
                model_call_id=model_call_id,
                status="session_committed",
            )
            emit(
                "MODEL_TOOL_CALL_OUTPUT_ACCEPTED",
                agent_turn_id=sequence,
                agent_step_id=1,
                model_call_id=model_call_id,
                tool_call_id=call_id,
                tool_name=name,
                argument_bytes=16,
            )
            emit(
                "TOOL_CALL_PARSED",
                agent_turn_id=sequence,
                agent_step_id=1,
                model_call_id=model_call_id,
                tool_call_id=call_id,
                tool_name=name,
                argument_bytes=16,
                dsh_event_seq=sequence * 3,
            )
            emit(
                "TOOL_ARGUMENT_VALIDATED",
                agent_turn_id=sequence,
                agent_step_id=1,
                model_call_id=model_call_id,
                tool_call_id=call_id,
                tool_name=name,
                argument_bytes=16,
                file_count=len(read_scope),
            )
            lowered = emit(
                "TOOL_PROPOSAL_LOWERED",
                agent_turn_id=sequence,
                agent_step_id=1,
                model_call_id=model_call_id,
                tool_call_id=call_id,
                tool_name=name,
                operation_seq=sequence,
                invocation_sha256=invocation,
                argument_bytes=16,
                file_count=len(read_scope),
                write_operation=bool(write_scope),
            )
            submitted_event = emit(
                "LAUNCHER_PROPOSAL_SUBMITTED",
                agent_turn_id=sequence,
                agent_step_id=1,
                model_call_id=model_call_id,
                tool_call_id=call_id,
                tool_name=name,
                operation_seq=sequence,
                invocation_sha256=invocation,
            )
            launcher_request_id = "launcher-request-" + str(sequence)
            launcher_task_id = "launcher-task-evaluator"
            launcher_approval_sha = hashlib.sha256(f"kernel-request-{sequence}".encode()).hexdigest()
            request = {
                "request_id": launcher_request_id,
                "invocation_sha256": launcher_approval_sha,
                "read_scope": read_scope,
                "write_scope": write_scope,
                "approval": approval,
                "kernel_result": "not_submitted" if approval == "denied" else "output",
                "runner_execution": "not_started" if approval == "denied" else "completed",
                "runner_return_code": None if approval == "denied" else return_code,
                "commit_outcome": "not_committed" if approval == "denied" else "committed",
                "changeset": (
                    {"added": None, "modified": None, "deleted": None}
                    if approval == "denied"
                    else {"added": 0, "modified": int(bool(write_scope)), "deleted": 0}
                ),
                "cancellation_requested": False,
            }
            requests.append(request)
            launcher_result_digest = hashlib.sha256(f"launcher-result-{sequence}".encode()).hexdigest()
            terminal_result_digest = hashlib.sha256(f"terminal-result-{sequence}".encode()).hexdigest()
            delivered_result_digest = hashlib.sha256(f"delivered-result-{sequence}".encode()).hexdigest()
            emit(
                "LAUNCHER_TERMINAL_RESULT_DELIVERED",
                agent_turn_id=sequence,
                agent_step_id=1,
                model_call_id=model_call_id,
                tool_call_id=call_id,
                tool_name=name,
                operation_seq=sequence,
                invocation_sha256=invocation,
                launcher_task_id=launcher_task_id,
                launcher_request_id=launcher_request_id,
                launcher_approval_sha256=launcher_approval_sha,
                approval_status=approval,
                kernel_result=request["kernel_result"],
                runner_status=request["runner_execution"],
                commit_status=request["commit_outcome"],
                launcher_ok=approval != "denied" and return_code == 0,
                can_continue=approval != "denied",
                returncode=request["runner_return_code"],
                result_bytes=64,
                result_sha256=terminal_result_digest,
                launcher_result_sha256=launcher_result_digest,
            )
            launcher_lifecycle = (
                (("APPROVAL_PRESENTED", "candidate_b_preview"), ("APPROVAL_DENIED", "denied"))
                if approval == "denied"
                else (
                    ("APPROVAL_ACCEPTED", approval),
                    ("KERNEL_OPERATION_STARTED", "submitted"),
                    ("KERNEL_OPERATION_COMPLETED", "output_received"),
                )
            )
            for event_name, status in launcher_lifecycle:
                launcher_events.append({
                    "event": event_name,
                    "launcher_event_seq": len(launcher_events) + 1,
                    "timestamp_utc": "2026-10-23T12:00:00.000Z",
                    "launcher_task_id": launcher_task_id,
                    "launcher_request_id": launcher_request_id,
                    "launcher_approval_sha256": launcher_approval_sha,
                    "status": status,
                })
            emit(
                "TOOL_RESULT_DELIVERED",
                agent_turn_id=sequence,
                agent_step_id=1,
                model_call_id=model_call_id,
                tool_call_id=call_id,
                operation_seq=sequence,
                result_bytes=64,
                result_sha256=delivered_result_digest,
                launcher_result_sha256=launcher_result_digest,
                status="ok",
                dsh_event_seq=sequence * 3 + 1,
            )
            next_model_call = "fixture-model-" + str(sequence + 1)
            emit(
                "SESSION_CONTINUITY_CHECK",
                agent_turn_id=sequence + 1,
                agent_step_id=1,
                model_call_id=next_model_call,
                tool_call_id=call_id,
                operation_seq=sequence,
                observed_tool_result=True,
            )
            emit(
                "AGENT_NEXT_TURN_STARTED",
                agent_turn_id=sequence + 1,
                agent_step_id=1,
                model_call_id=next_model_call,
                tool_call_id=call_id,
                operation_seq=sequence,
                observed_tool_result=True,
            )
        final_turn = len(operations) + 1
        final_model_call_id = f"fixture-model-{final_turn}"
        emit(
            "MODEL_REQUEST_STARTED",
            agent_turn_id=final_turn,
            agent_step_id=1,
            model_call_id=final_model_call_id,
            model_provider="khaos-local",
            model_id="bundled-cpu",
        )
        emit(
            "MODEL_RESPONSE_RECEIVED",
            agent_turn_id=final_turn,
            agent_step_id=1,
            model_call_id=final_model_call_id,
            duration_ms=10,
            status="received",
        )
        emit(
            "DSH_ASSISTANT_MESSAGE_COMMITTED",
            agent_turn_id=final_turn,
            agent_step_id=1,
            model_call_id=final_model_call_id,
            status="session_committed",
        )
        emit("AGENT_TERMINATED", agent_turn_id=final_turn, agent_step_id=1, status="idle")
        if post_terminal_tool_call:
            emit(
                "TOOL_CALL_PARSED",
                agent_turn_id=final_turn + 1,
                agent_step_id=1,
                model_call_id=final_model_call_id,
                tool_call_id="post-terminal-call",
                tool_name="read_file",
                argument_bytes=16,
            )

        task_record = {
            "task_id": "launcher-task-evaluator",
            "proposals": len(requests),
            "executed_command_return_codes": [
                request["runner_return_code"] for request in requests
                if isinstance(request.get("runner_return_code"), int)
            ],
            "cumulative_runner_seconds": "0.040",
            "cancellation_requested": False,
            "workspace_requests": requests,
        }
        stderr_lines = [
            "dsh-telemetry=" + json.dumps(event, sort_keys=True)
            for event in events
        ] + [
            "dsh-launcher-event=" + json.dumps(event, sort_keys=True)
            for event in launcher_events
        ] + [
            "dsh-agent-loop=" + json.dumps({
                "tool_result_count": len(requests),
                "last_message_role": "assistant",
            })
        ]
        return {
            "task_id": task_id,
            "trial_id": trial_id,
            "metadata": metadata,
            "workspace": workspace,
            "task_records": [task_record],
            "stdout": "Khaos: The public tests passed.\n"
                if final_test_return_code == 0 and not deny_edit
                else "Khaos: The public tests did not pass.\n",
            "stderr": "\n".join(stderr_lines) + "\n",
            "runtime_metrics": {"local_model_process_invocations_observed": 1},
        }

    def evaluate(self, trial: dict[str, object]) -> dict[str, object]:
        return evaluate_real_model_trial(
            task_id=str(trial["task_id"]),
            trial_id=str(trial["trial_id"]),
            provider="local",
            metadata=trial["metadata"],  # type: ignore[arg-type]
            workspace=trial["workspace"],  # type: ignore[arg-type]
            task_records=trial["task_records"],  # type: ignore[arg-type]
            stdout=str(trial["stdout"]),
            stderr=str(trial["stderr"]),
            runtime_metrics=trial["runtime_metrics"],  # type: ignore[arg-type]
            elapsed_seconds=1.0,
            api_key_value="",
            model_id="bundled-cpu",
            model_details={"model_sha256": "a" * 64},
        )

    def test_correlates_distinct_kernel_and_session_result_digests(self) -> None:
        result = self.evaluate(self.make_trial())

        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["actual_dsh_loop"])
        self.assertTrue(result["correlation_event_sequence_valid"])
        self.assertTrue(result["session_continuity_complete"])
        self.assertEqual(result["semantic_tool_calls_parsed"], 4)
        self.assertEqual(result["semantic_tool_lowerings"], 4)
        self.assertEqual(result["tool_result_delivery_rate"], 1.0)
        self.assertEqual(result["hidden_verification"]["status"], "PASS")  # type: ignore[index]

    def test_runner_nonzero_is_reported_as_execution_failure_not_kernel_rejection(self) -> None:
        result = self.evaluate(self.make_trial(final_test_return_code=1))

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["kernel_rejection_count"], 0)
        self.assertEqual(result["event_categories"]["runner_nonzero_results"], [1])  # type: ignore[index]
        self.assertEqual(result["false_success_count"], 0)

    def test_invocation_digest_mismatch_fails_correlation(self) -> None:
        trial = self.make_trial()
        records = trial["task_records"]
        records[0]["workspace_requests"][2]["invocation_sha256"] = "b" * 64  # type: ignore[index]

        result = self.evaluate(trial)

        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(
            result["operation_correlations"][2][  # type: ignore[index]
                "launcher_request_identity_and_kernel_result_match"
            ]
        )

    def test_model_tool_output_must_match_dsh_tool_call_identity(self) -> None:
        trial = self.make_trial()
        telemetry = []
        for line in str(trial["stderr"]).splitlines():
            if line.startswith("dsh-telemetry="):
                record = json.loads(line.removeprefix("dsh-telemetry="))
                if record.get("event") == "MODEL_TOOL_CALL_OUTPUT_ACCEPTED":
                    record["tool_call_id"] = "different-model-tool-call"
                telemetry.append("dsh-telemetry=" + json.dumps(record, sort_keys=True))
            else:
                telemetry.append(line)
        trial["stderr"] = "\n".join(telemetry) + "\n"

        result = self.evaluate(trial)

        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["proposal_telemetry_complete"])

    def test_launcher_result_digest_must_reach_dsh_session(self) -> None:
        trial = self.make_trial()
        telemetry = []
        for line in str(trial["stderr"]).splitlines():
            if line.startswith("dsh-telemetry="):
                record = json.loads(line.removeprefix("dsh-telemetry="))
                if record.get("event") == "TOOL_RESULT_DELIVERED":
                    record["launcher_result_sha256"] = "0" * 64
                telemetry.append("dsh-telemetry=" + json.dumps(record, sort_keys=True))
            else:
                telemetry.append(line)
        trial["stderr"] = "\n".join(telemetry) + "\n"

        result = self.evaluate(trial)

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["tool_result_delivery_rate"], 0.0)

    def test_operator_denial_is_not_misclassified_as_an_unauthorized_proposal(self) -> None:
        result = self.evaluate(self.make_trial(deny_edit=True))

        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["actual_dsh_loop"])
        self.assertEqual(result["unauthorized_proposals"], 0)
        self.assertEqual(result["operator_denied_proposal_count"], 1)
        self.assertEqual(result["tool_result_delivery_rate"], 1.0)
        self.assertEqual(result["session_continuity_rate"], 1.0)
        self.assertTrue(result["session_continuity_complete"])
        self.assertEqual(result["post_terminal_tool_call_count"], 0)

    def test_tool_call_after_non_continuable_result_is_detected(self) -> None:
        result = self.evaluate(
            self.make_trial(deny_edit=True, post_terminal_tool_call=True)
        )

        self.assertFalse(result["actual_dsh_loop"])
        self.assertFalse(result["session_continuity_complete"])
        self.assertEqual(result["post_terminal_tool_call_count"], 1)


if __name__ == "__main__":
    unittest.main()
