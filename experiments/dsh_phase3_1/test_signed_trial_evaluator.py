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
from run_dsh_xpc_attack_acceptance import evaluate_real_model_trial  # noqa: E402


class SignedTrialEvaluatorTests(unittest.TestCase):
    def make_trial(self, final_test_return_code: int = 0) -> dict[str, object]:
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
        forwarded: list[dict[str, object]] = []
        terminal: list[dict[str, object]] = []
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
            correlation = {
                key: lowered[key]
                for key in (
                    "trial_id", "dsh_session_id", "benchmark_task_id",
                    "agent_turn_id", "agent_step_id", "model_call_id",
                    "tool_call_id", "tool_name", "operation_seq", "invocation_sha256",
                )
            }
            forwarded.append({**correlation, "event": "SEMANTIC_PROPOSAL_FORWARDED"})
            request = {
                "request_id": "launcher-request-" + str(sequence),
                "invocation_sha256": invocation,
                "read_scope": read_scope,
                "write_scope": write_scope,
                "approval": approval,
                "kernel_result": "output",
                "runner_execution": "completed",
                "runner_return_code": return_code,
                "commit_outcome": "committed",
                "changeset": {"added": 0, "modified": int(bool(write_scope)), "deleted": 0},
                "cancellation_requested": False,
            }
            requests.append(request)
            terminal.append({
                **correlation,
                "event": "LAUNCHER_TERMINAL_RESULT_DELIVERED",
                "launcher_ok": return_code == 0,
                "launcher_can_continue": True,
                "result_bytes": 64,
                "result_sha256": hashlib.sha256(call_id.encode()).hexdigest(),
            })
            emit(
                "TOOL_RESULT_DELIVERED",
                agent_turn_id=sequence,
                agent_step_id=1,
                model_call_id=model_call_id,
                tool_call_id=call_id,
                operation_seq=sequence,
                result_bytes=64,
                result_sha256=hashlib.sha256(call_id.encode()).hexdigest(),
                launcher_result_sha256=hashlib.sha256(call_id.encode()).hexdigest(),
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
        emit(
            "MODEL_REQUEST_STARTED",
            agent_turn_id=5,
            agent_step_id=1,
            model_call_id="fixture-model-5",
            model_provider="khaos-local",
            model_id="bundled-cpu",
        )
        emit(
            "MODEL_RESPONSE_RECEIVED",
            agent_turn_id=5,
            agent_step_id=1,
            model_call_id="fixture-model-5",
            duration_ms=10,
            status="received",
        )
        emit("AGENT_TERMINATED", agent_turn_id=5, agent_step_id=1, status="idle")

        task_record = {
            "task_id": "launcher-task-evaluator",
            "proposals": len(requests),
            "executed_command_return_codes": [0, 0, 0, final_test_return_code],
            "cumulative_runner_seconds": "0.040",
            "cancellation_requested": False,
            "workspace_requests": requests,
        }
        stderr_lines = [
            "dsh-telemetry=" + json.dumps(event, sort_keys=True)
            for event in events
        ] + [
            "dsh-semantic-proposal=" + json.dumps(event, sort_keys=True)
            for event in forwarded
        ] + [
            "dsh-launcher-terminal=" + json.dumps(event, sort_keys=True)
            for event in terminal
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
            "stdout": "Khaos: The public tests passed.\n" if final_test_return_code == 0
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

    def test_correlates_semantic_session_launcher_and_runner_evidence(self) -> None:
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
                "invocation_digest_matches_dsh_lowering_agenthost_and_launcher"
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


if __name__ == "__main__":
    unittest.main()
