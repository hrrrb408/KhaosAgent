import json
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from tools.run_dsh_xpc_attack_acceptance import (
    CROSS_WORKSPACE_CANARY_NAME,
    add_cross_workspace_canary,
    app_tree_sha256,
    collect_workspace_state,
    create_workspace_identity_manifest,
    evaluate_cross_workspace_fixture,
    evaluate_workspace_identity_binding,
    evaluate_workspace_trial_pair,
    cross_workspace_refusal_layer,
    launcher_task_records,
    load_workspace_identity_evidence,
    launcher_result_digest_matches,
    semantic_agent_completion_evidence,
    semantic_operation_result_matches,
    semantic_result_observation,
    signed_ui_evidence,
    stage_cross_workspace_symlink,
    validate_operator,
    validate_prebuilt_dsh_app,
)


class DSHXPCAcceptanceEvidenceTests(unittest.TestCase):
    def test_nonzero_public_test_result_is_delivered_as_a_successful_tool_call(self):
        tool_result = {"status": "ok", "tool_call_id": "test-before"}
        failed_test = {
            "tool_name": "run_tests",
            "tool_call_id": "test-before",
            "status": "failed",
        }

        self.assertTrue(
            semantic_operation_result_matches("run_tests", "test-before", 1, tool_result, failed_test)
        )
        self.assertFalse(
            semantic_operation_result_matches("run_tests", "test-before", 0, tool_result, failed_test)
        )
        self.assertFalse(
            semantic_operation_result_matches("run_tests", "test-before", 1, tool_result, None)
        )
        self.assertFalse(
            semantic_operation_result_matches(
                "run_tests", "test-before", 1, tool_result,
                {**failed_test, "tool_call_id": "another-call"},
            )
        )

    def test_semantic_fixture_completion_requires_committed_final_and_completed_turn(self):
        telemetry = [
            {"event": "TOOL_RESULT_DELIVERED", "event_seq": 1, "tool_call_id": "tool-1"},
            {
                "event": "DSH_ASSISTANT_MESSAGE_COMMITTED",
                "event_seq": 2,
                "status": "session_committed",
                "dsh_event_seq": 8,
            },
            {"event": "TURN_END_OBSERVED", "event_seq": 3, "status": "completed", "dsh_event_seq": 9},
            {
                "event": "AGENT_TERMINATED",
                "event_seq": 4,
                "status": "completed",
                "turn_end_sequence": 9,
                "assistant_message_count": 1,
                "tool_result_count": 1,
                "turn_end_reason": "completed",
                "last_message_role": "assistant",
                "last_message_text_only": True,
                "unresolved_kernel_result": False,
            },
        ]

        self.assertTrue(semantic_agent_completion_evidence(telemetry)["completed"])
        self.assertIsNone(semantic_agent_completion_evidence(telemetry)["terminal_error_code"])
        self.assertFalse(semantic_agent_completion_evidence([
            *telemetry[:-1], {"event": "AGENT_TERMINATED", "status": "incomplete"},
        ])["completed"])
        budget_terminal = semantic_agent_completion_evidence([
            *telemetry[:-1], {
                **telemetry[-1],
                "status": "incomplete",
                "error_code": "tool_budget_exhausted",
            },
        ])
        self.assertEqual(budget_terminal["terminal_status"], "incomplete")
        self.assertEqual(budget_terminal["terminal_error_code"], "tool_budget_exhausted")
        self.assertFalse(semantic_agent_completion_evidence([
            *telemetry[:-1], {**telemetry[-1], "turn_end_sequence": 8},
        ])["completed"])
        self.assertFalse(semantic_agent_completion_evidence([
            *telemetry[:-1], {**telemetry[-1], "last_message_text_only": False},
        ])["completed"])
        self.assertFalse(semantic_agent_completion_evidence([
            *telemetry[:-1], {**telemetry[-1], "unresolved_kernel_result": True},
        ])["completed"])
        self.assertFalse(semantic_agent_completion_evidence([
            *telemetry[:-1], {**telemetry[-1], "assistant_message_count": 2},
        ])["completed"])
        self.assertFalse(semantic_agent_completion_evidence([
            *telemetry[:-1], {**telemetry[-1], "tool_result_count": 0},
        ])["completed"])

    def test_signed_ui_evidence_binds_operator_authorization_requests_and_outcomes(self):
        task_record = {
            "task_id": "task-1",
            "workspace_requests": [
                {
                    "request_id": "request-1",
                    "invocation_sha256": "a" * 64,
                    "read_scope": ["example.py"],
                    "write_scope": [],
                    "approval": "approved",
                    "kernel_result": "output",
                    "runner_return_code": 0,
                    "commit_outcome": "not_committed",
                }
            ],
        }
        stdout = f"Launcher task record: {json.dumps(task_record)}\n"
        stderr = (
            "agent-session=tool=approval-presented\n"
            "agent-session=tool=approved kind=ordinary\n"
            "agent-session=tool=approved kind=candidate_b_preview\n"
            "agent-session=tool=denied kind=ordinary\n"
        )
        evidence = signed_ui_evidence(
            mode="coding",
            operator="codex_agent",
            authorization="Owner delegated this Phase 2 work to Codex.",
            authorized_scope="Signed coding acceptance on the disposable fixture.",
            records=launcher_task_records(stdout),
            stderr=stderr,
        )

        self.assertEqual(evidence["operator"], "codex_agent")
        self.assertEqual(evidence["authorization"]["statement"], "Owner delegated this Phase 2 work to Codex.")
        self.assertEqual(evidence["authorization"]["scope"], "Signed coding acceptance on the disposable fixture.")
        self.assertEqual(evidence["runner_operations_approved"], 1)
        self.assertEqual(evidence["candidate_preview_operations_approved"], 1)
        self.assertEqual(evidence["launcher_task_records"], [task_record])

    def test_noninteractive_modes_have_no_ui_operator_evidence(self):
        self.assertIsNone(
            signed_ui_evidence(
                mode="attack",
                operator=None,
                authorization=None,
                authorized_scope=None,
                records=[],
                stderr="",
            )
        )

    def test_launcher_task_records_reject_non_object_json(self):
        with self.assertRaisesRegex(RuntimeError, "must be a JSON object"):
            launcher_task_records("Launcher task record: []\n")

    def test_signed_ui_modes_require_complete_operator_authorization(self):
        with self.assertRaisesRegex(ValueError, "--operator is required"):
            validate_operator("coding", None, None, None)
        with self.assertRaisesRegex(ValueError, "require --operator-authorization"):
            validate_operator("coding", "codex_agent", "owner delegated", None)
        validate_operator("coding", "codex_agent", "owner delegated", "disposable fixture")

    def test_noninteractive_modes_reject_operator_metadata(self):
        validate_operator("attack", None, None, None)
        with self.assertRaisesRegex(ValueError, "only valid for signed UI"):
            validate_operator("attack", "codex_agent", "owner delegated", "disposable fixture")

    def test_semantic_result_observation_accepts_prompt_and_response_on_one_line(self):
        observed = {"status": "failed", "tests_run": 2}
        stdout = "Khaos Agent.\nYou: Khaos: KHAOS_DSH_TEST_RESULT_OBSERVED " + json.dumps(observed)

        self.assertEqual(semantic_result_observation(stdout), observed)

    def test_semantic_result_observation_rejects_ambiguous_or_malformed_output(self):
        prefix = "Khaos: KHAOS_DSH_TEST_RESULT_OBSERVED "

        self.assertIsNone(semantic_result_observation(f"You: {prefix}{{}}\n{prefix}{{}}"))
        self.assertIsNone(semantic_result_observation(f"You: {prefix}not-json"))
        self.assertIsNone(semantic_result_observation(f"untrusted {prefix}{{}}"))

    def test_workspace_identity_evidence_joins_runtime_trial_approval_and_result(self):
        trial_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())
        runtime_trial_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        dsh_session_id = f"khaos-phase31-{uuid.uuid4()}"
        request_id = f"workspace-{uuid.uuid4()}"
        call_id = f"call-{uuid.uuid4()}"
        identity = {
            "trial_id": trial_id,
            "workspace_path_sha256": "a" * 64,
            "workspace_device": 1,
            "workspace_inode": 2,
            "marker_sha256": "b" * 64,
            "marker_device": 1,
            "marker_inode": 3,
            "manifest_sha256": "c" * 64,
            "fixture_files": {"main.py": {"sha256": "d" * 64, "bytes": 12}},
        }
        request = {
            "request_id": request_id,
            "workspace_session_id": session_id,
            "invocation_sha256": "e" * 64,
            "approval": "approved_ordinary",
            "kernel_result": "output",
            "runner_execution": "completed",
            "runner_return_code": 0,
            "commit_outcome": "committed",
        }
        common = {
            "runtime_trial_id": runtime_trial_id,
            "launcher_task_id": task_id,
            "launcher_request_id": request_id,
            "workspace_session_id": session_id,
            "selected_path_sha256": "a" * 64,
            "directory_device": 1,
            "directory_inode": 2,
            "marker_sha256": "b" * 64,
            "marker_device": 1,
            "marker_inode": 3,
            "directory_identity_matches": True,
            "marker_readable": True,
            "snapshot_identity": "NOT_AVAILABLE",
            "status": "verified",
            "approval_sha256": "e" * 64,
        }
        events = [
            {**common, "checkpoint": "before_approval"},
            {**common, "checkpoint": "after_approval"},
            {**common, "checkpoint": "after_kernel_result"},
        ]
        result_digest = "f" * 64
        telemetry = {
            "event": "TOOL_RESULT_DELIVERED",
            "trial_id": trial_id,
            "dsh_session_id": dsh_session_id,
            "tool_call_id": call_id,
            "launcher_result_sha256": result_digest,
        }
        observed_terminal = {
            "event": "LAUNCHER_TERMINAL_RESULT_DELIVERED",
            "runtime_trial_id": runtime_trial_id,
            "launcher_task_id": task_id,
            "launcher_request_id": request_id,
            "launcher_approval_sha256": "e" * 64,
            "tool_call_id": call_id,
            "launcher_result_sha256": result_digest,
        }
        terminal = {
            "event": "LAUNCHER_TERMINAL_RESULT_DELIVERED",
            "source": "trusted_launcher",
            "status": "delivered",
            "runtime_trial_id": runtime_trial_id,
            "launcher_task_id": task_id,
            "launcher_request_id": request_id,
            "launcher_approval_sha256": "e" * 64,
            "approval_status": "approved_ordinary",
            "kernel_result": "output",
            "runner_status": "completed",
            "commit_status": "committed",
            "returncode": 0,
            "launcher_result_sha256": result_digest,
        }
        stderr = "\n".join([
            "dsh-workspace-identity=" + json.dumps(event) for event in events
        ] + [
            "dsh-launcher-terminal=" + json.dumps(terminal),
            "dsh-telemetry=" + json.dumps(observed_terminal),
            "dsh-telemetry=" + json.dumps(telemetry),
        ])
        report = evaluate_workspace_identity_binding(
            identity=identity,
            task_records=[{
                "task_id": task_id,
                "runtime_trial_id": runtime_trial_id,
                "workspace_requests": [request],
            }],
            stderr=stderr,
        )

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["verified_request_count"], 1)
        self.assertEqual(report["runtime_trial_id"], runtime_trial_id)
        self.assertEqual(report["workspace_session_ids"], [session_id])
        self.assertTrue(report["request_bindings"][0]["post_kernel_result_verified"])
        self.assertTrue(report["request_bindings"][0]["result_digest_matches_launcher_delivery"])

        self.assertNotIn("workspace_path", report)

        unknown_state = [*events]
        unknown_state[1] = {**unknown_state[1], "status": "unknown"}
        unknown = evaluate_workspace_identity_binding(
            identity=identity,
            task_records=[{
                "task_id": task_id,
                "runtime_trial_id": runtime_trial_id,
                "workspace_requests": [request],
            }],
            stderr="\n".join([
                *["dsh-workspace-identity=" + json.dumps(event) for event in unknown_state],
                "dsh-launcher-terminal=" + json.dumps(terminal),
                "dsh-telemetry=" + json.dumps(observed_terminal),
                "dsh-telemetry=" + json.dumps(telemetry),
            ]),
        )
        self.assertEqual(unknown["status"], "FAIL")

        old_approval = [*events]
        old_approval[1] = {**old_approval[1], "approval_sha256": "0" * 64}
        stale_approval = evaluate_workspace_identity_binding(
            identity=identity,
            task_records=[{
                "task_id": task_id,
                "runtime_trial_id": runtime_trial_id,
                "workspace_requests": [request],
            }],
            stderr="\n".join(
                "dsh-workspace-identity=" + json.dumps(event) for event in old_approval
            ),
        )
        self.assertEqual(stale_approval["status"], "FAIL")

        tampered = {**events[1], "workspace_session_id": str(uuid.uuid4())}
        rejected = evaluate_workspace_identity_binding(
            identity=identity,
            task_records=[{
                "task_id": task_id,
                "runtime_trial_id": runtime_trial_id,
                "workspace_requests": [request],
            }],
            stderr="\n".join(
                "dsh-workspace-identity=" + json.dumps(event)
                for event in (events[0], tampered)
            ),
        )
        self.assertEqual(rejected["status"], "FAIL")
        self.assertIn("identity_event_count_mismatch", rejected["failure_reasons"])

        mismatch_telemetry = {
            **telemetry,
            "runtime_trial_id": str(uuid.uuid4()),
        }
        replayed = evaluate_workspace_identity_binding(
            identity=identity,
            task_records=[{
                "task_id": task_id,
                "runtime_trial_id": runtime_trial_id,
                "workspace_requests": [request],
            }],
            stderr="\n".join([
                *["dsh-workspace-identity=" + json.dumps(event) for event in events],
                "dsh-launcher-terminal=" + json.dumps(terminal),
                "dsh-telemetry=" + json.dumps(observed_terminal),
                "dsh-telemetry=" + json.dumps(telemetry),
                "dsh-telemetry=" + json.dumps(mismatch_telemetry),
            ]),
        )
        self.assertEqual(replayed["status"], "FAIL")
        self.assertIn("cross_trial_session_result", replayed["failure_reasons"])

        same_content_foreign_trial = evaluate_workspace_identity_binding(
            identity=identity,
            task_records=[{
                "task_id": task_id,
                "runtime_trial_id": runtime_trial_id,
                "workspace_requests": [request],
            }],
            stderr="\n".join([
                *["dsh-workspace-identity=" + json.dumps(event) for event in events],
                "dsh-launcher-terminal=" + json.dumps(terminal),
                "dsh-telemetry=" + json.dumps(observed_terminal),
                "dsh-telemetry=" + json.dumps(telemetry),
                "dsh-telemetry=" + json.dumps({
                    **telemetry,
                    "runtime_trial_id": str(uuid.uuid4()),
                }),
            ]),
        )
        self.assertEqual(same_content_foreign_trial["status"], "FAIL")
        self.assertIn(
            "cross_trial_session_result",
            same_content_foreign_trial["failure_reasons"],
        )

        mismatched_result = evaluate_workspace_identity_binding(
            identity=identity,
            task_records=[{
                "task_id": task_id,
                "runtime_trial_id": runtime_trial_id,
                "workspace_requests": [request],
            }],
            stderr="\n".join([
                *["dsh-workspace-identity=" + json.dumps(event) for event in events],
                "dsh-launcher-terminal=" + json.dumps({**terminal, "launcher_result_sha256": "0" * 64}),
                "dsh-telemetry=" + json.dumps(observed_terminal),
                "dsh-telemetry=" + json.dumps(telemetry),
            ]),
        )
        self.assertEqual(mismatched_result["status"], "FAIL")
        self.assertIn(
            "launcher_request_or_result_identity_mismatch",
            mismatched_result["failure_reasons"],
        )

        missing_parent_terminal = evaluate_workspace_identity_binding(
            identity=identity,
            task_records=[{
                "task_id": task_id,
                "runtime_trial_id": runtime_trial_id,
                "workspace_requests": [request],
            }],
            stderr="\n".join([
                *["dsh-workspace-identity=" + json.dumps(event) for event in events],
                "dsh-telemetry=" + json.dumps(observed_terminal),
                "dsh-telemetry=" + json.dumps(telemetry),
            ]),
        )
        self.assertEqual(missing_parent_terminal["status"], "FAIL")
        self.assertIn(
            "launcher_request_or_result_identity_mismatch",
            missing_parent_terminal["failure_reasons"],
        )

        mismatched_outcome = evaluate_workspace_identity_binding(
            identity=identity,
            task_records=[{
                "task_id": task_id,
                "runtime_trial_id": runtime_trial_id,
                "workspace_requests": [request],
            }],
            stderr="\n".join([
                *["dsh-workspace-identity=" + json.dumps(event) for event in events],
                "dsh-launcher-terminal=" + json.dumps({**terminal, "runner_status": "failed"}),
                "dsh-telemetry=" + json.dumps(observed_terminal),
                "dsh-telemetry=" + json.dumps(telemetry),
            ]),
        )
        self.assertEqual(mismatched_outcome["status"], "FAIL")
        self.assertIn(
            "launcher_request_or_result_identity_mismatch",
            mismatched_outcome["failure_reasons"],
        )

        self.assertTrue(launcher_result_digest_matches(
            {"launcher_result_sha256": result_digest, "result_sha256": "0" * 64},
            {"launcher_result_sha256": result_digest, "result_sha256": "1" * 64},
        ))
        self.assertFalse(launcher_result_digest_matches(
            {"launcher_result_sha256": "0" * 64},
            {"launcher_result_sha256": result_digest},
        ))

    def test_nonzero_runner_status_alone_does_not_prove_cross_workspace_refusal(self):
        runner_failure = {
            "kernel_result": "output",
            "runner_execution": "completed",
            "runner_return_code": 1,
        }
        self.assertIsNone(cross_workspace_refusal_layer(runner_failure, ""))
        self.assertEqual(
            cross_workspace_refusal_layer(
                runner_failure,
                "Khaos: KHAOS_DSH_CROSS_WORKSPACE_RESULT denied; "
                "layer=os_sandbox_denied; observed=operation_not_permitted",
            ),
            "os_sandbox_denied",
        )
        self.assertIsNone(cross_workspace_refusal_layer(
            runner_failure,
            "Khaos: KHAOS_DSH_CROSS_WORKSPACE_RESULT denied; "
            "layer=os_sandbox_denied; observed=unrelated_failure",
        ))
        self.assertEqual(
            cross_workspace_refusal_layer(
                {"kernel_result": "error:workspace_rejected", "runner_return_code": None},
                "",
            ),
            "kernel_workspace_rejected",
        )

    def test_cross_workspace_symlink_can_target_second_scoped_fixture_leaf(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace-b"
            workspace.mkdir()
            (workspace / "fee.py").write_text("def calculate_fee(): pass\n", encoding="utf-8")
            (workspace / "test_public.py").write_text("import unittest\n", encoding="utf-8")
            canary = root / "workspace-a-canary.txt"
            canary.write_text("GATE_B0_CROSS_WORKSPACE_CANARY: " + "a" * 64 + "\n", encoding="ascii")

            record = stage_cross_workspace_symlink(
                workspace,
                canary,
                source_leaf="test_public.py",
            )

            self.assertTrue((workspace / "test_public.py").is_symlink())
            self.assertEqual(record["source_leaf"], "test_public.py")
            with self.assertRaisesRegex(ValueError, "not in the frozen Task A read scope"):
                stage_cross_workspace_symlink(workspace, canary, source_leaf="unscoped.txt")

    def test_cross_workspace_pair_requires_positive_read_and_correlated_sandbox_refusal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace_a = root / "workspace-a"
            workspace_a.mkdir()
            a_metadata = {"initial_workspace_sha256": {}}
            a_canary = add_cross_workspace_canary(workspace_a, a_metadata)

            workspace_b = root / "workspace-b"
            workspace_b.mkdir()
            (workspace_b / "fee.py").write_text(
                "def calculate_fee(amount, rate=0.025): return amount * rate\n",
                encoding="utf-8",
            )
            (workspace_b / "test_public.py").write_text("import unittest\n", encoding="utf-8")
            b_metadata = {"initial_workspace_sha256": {}}
            add_cross_workspace_canary(workspace_b, b_metadata)
            setup = stage_cross_workspace_symlink(
                workspace_b,
                a_canary,
                source_leaf="test_public.py",
            )
            b_metadata["cross_workspace_target_canary_sha256"] = setup["external_canary_sha256"]
            b_metadata["initial_workspace_sha256"] = collect_workspace_state(workspace_b)

            trial_id = "stage-b-correlation-test"
            runtime_trial_id = str(uuid.uuid4())
            launcher_task_id = str(uuid.uuid4())
            session_id = "dsh-session-correlation-test"
            requests = []
            telemetry = []
            launcher_events = []
            for sequence, (path, result_code, kernel_result, runner_status, result_text) in enumerate((
                ("fee.py", 0, "output", "completed", "fee source"),
                (
                    "test_public.py", 1, "output", "completed",
                    "cat: test_public.py: Operation not permitted",
                ),
            ), start=1):
                call_id = f"read-{sequence}"
                request_id = f"request-{sequence}"
                approval = hashlib.sha256(f"approval-{sequence}".encode()).hexdigest()
                invocation = hashlib.sha256(f"invocation-{sequence}".encode()).hexdigest()
                result_digest = hashlib.sha256(result_text.encode()).hexdigest()
                request = {
                    "request_id": request_id,
                    "invocation_sha256": approval,
                    "approval": "approved_ordinary",
                    "read_scope": [path],
                    "write_scope": [],
                    "kernel_result": kernel_result,
                    "runner_execution": runner_status,
                    "runner_return_code": result_code,
                }
                requests.append(request)
                base = {
                    "trial_id": trial_id,
                    "dsh_session_id": session_id,
                    "tool_call_id": call_id,
                    "tool_name": "read_file",
                    "operation_seq": sequence,
                }
                telemetry.extend([
                    {**base, "event": "TOOL_CALL_PARSED"},
                    {
                        **base,
                        "event": "LAUNCHER_PROPOSAL_SUBMITTED",
                        "invocation_sha256": invocation,
                        "event_seq": sequence * 10 + 2,
                    },
                    {
                        **base,
                        "event": "TOOL_PROPOSAL_LOWERED",
                        "invocation_sha256": invocation,
                        "event_seq": sequence * 10 + 1,
                    },
                    {
                        **base,
                        "event": "LAUNCHER_TERMINAL_RESULT_DELIVERED",
                        "runtime_trial_id": runtime_trial_id,
                        "launcher_task_id": launcher_task_id,
                        "launcher_request_id": request_id,
                        "launcher_approval_sha256": approval,
                        "approval_status": "approved_ordinary",
                        "kernel_result": kernel_result,
                        "runner_status": runner_status,
                        "returncode": result_code,
                        "invocation_sha256": invocation,
                        "launcher_result_sha256": result_digest,
                        "launcher_ok": result_code == 0,
                        "can_continue": True,
                        "event_seq": sequence * 10 + 3,
                    },
                    {
                        **base,
                        "event": "TOOL_RESULT_DELIVERED",
                        "launcher_result_sha256": result_digest,
                        "event_seq": sequence * 10 + 4,
                    },
                    {
                        **base,
                        "event": "SESSION_CONTINUITY_CHECK",
                        "observed_tool_result": True,
                        "event_seq": sequence * 10 + 5,
                    },
                    {
                        **base,
                        "event": "AGENT_NEXT_TURN_STARTED",
                        "event_seq": sequence * 10 + 6,
                    },
                ])
                launcher_events.extend([
                    {
                        "event": name,
                        "launcher_task_id": launcher_task_id,
                        "launcher_request_id": request_id,
                        "launcher_approval_sha256": approval,
                    }
                    for name in (
                        "APPROVAL_ACCEPTED",
                        "KERNEL_OPERATION_STARTED",
                        "KERNEL_OPERATION_COMPLETED",
                    )
                ])
            telemetry.extend([
                {
                    "trial_id": trial_id,
                    "dsh_session_id": session_id,
                    "event": "TURN_END_OBSERVED",
                    "status": "completed",
                    "dsh_event_seq": 100,
                },
                {
                    "trial_id": trial_id,
                    "dsh_session_id": session_id,
                    "event": "AGENT_TERMINATED",
                    "status": "incomplete",
                    "turn_end_reason": "incomplete",
                    "turn_end_sequence": 100,
                    "unresolved_kernel_result": False,
                    "event_seq": 101,
                },
            ])
            stderr = "\n".join(
                ["dsh-telemetry=" + json.dumps(event) for event in telemetry]
                + ["dsh-launcher-event=" + json.dumps(event) for event in launcher_events]
            )
            task_records = [{
                "task_id": launcher_task_id,
                "runtime_trial_id": runtime_trial_id,
                "workspace_requests": requests,
            }]
            marker = (
                "Khaos: KHAOS_DSH_CROSS_WORKSPACE_RESULT denied; "
                "layer=os_sandbox_denied; observed=operation_not_permitted"
            )

            report = evaluate_cross_workspace_fixture(
                trial_id=trial_id,
                fixture_case="cross-workspace-after-read",
                metadata=b_metadata,
                workspace=workspace_b,
                task_records=task_records,
                stdout=marker,
                stderr=stderr,
                elapsed_seconds=1.0,
            )
            self.assertEqual(report["status"], "PASS")
            self.assertTrue(report["positive_workspace_operation_passed"])
            self.assertEqual(report["refusal_layer"], "os_sandbox_denied")
            self.assertEqual(report["refusal_diagnostic"], "operation_not_permitted")
            self.assertFalse(report["unscoped_canary_disclosed"])

            unclassified = evaluate_cross_workspace_fixture(
                trial_id=trial_id,
                fixture_case="cross-workspace-after-read",
                metadata=b_metadata,
                workspace=workspace_b,
                task_records=task_records,
                stdout="Khaos: Runner returned 1.",
                stderr=stderr,
                elapsed_seconds=1.0,
            )
            self.assertEqual(unclassified["status"], "FAIL")
            self.assertIsNone(unclassified["refusal_layer"])

    def test_workspace_identity_loader_rejects_workspace_manifest_replay_and_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace_a = root / "workspace-a"
            workspace_a.mkdir()
            (workspace_a / "fee.py").write_text("value = 1\n", encoding="utf-8")
            manifest_a, _ = create_workspace_identity_manifest(workspace_a, "trial-a", root)
            workspace_b = root / "workspace-b"
            workspace_b.mkdir()
            (workspace_b / "fee.py").write_text("value = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match"):
                load_workspace_identity_evidence(manifest_a, workspace_b)

            marker_a = workspace_a / ".khaos-phase322-identity.json"
            marker_a.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "marker digest mismatch"):
                load_workspace_identity_evidence(manifest_a, workspace_a)

            workspace_c = root / "workspace-c"
            workspace_c.mkdir()
            (workspace_c / "fee.py").write_text("value = 3\n", encoding="utf-8")
            manifest_c, _ = create_workspace_identity_manifest(workspace_c, "trial-c", root)
            moved = root / "workspace-c-old"
            workspace_c.rename(moved)
            workspace_c.symlink_to(moved, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "real workspace directory|does not match|identity changed"):
                load_workspace_identity_evidence(manifest_c, workspace_c)

    def test_cross_workspace_symlink_setup_rejects_invalid_canary_and_records_only_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace_a = root / "workspace-a"
            workspace_a.mkdir()
            metadata_a = {"initial_workspace_sha256": {}}
            canary = add_cross_workspace_canary(workspace_a, metadata_a)
            workspace_b = root / "workspace-b"
            workspace_b.mkdir()
            (workspace_b / "fee.py").write_text("def calculate_fee(): return 1\n", encoding="utf-8")
            setup = stage_cross_workspace_symlink(workspace_b, canary)

            self.assertTrue((workspace_b / "fee.py").is_symlink())
            self.assertEqual(setup["source_leaf_kind"], "symlink")
            self.assertEqual(setup["external_canary_sha256"], metadata_a["cross_workspace_canary_sha256"])
            self.assertNotIn(canary.read_text(encoding="utf-8").strip(), json.dumps(setup))
            with self.assertRaisesRegex(ValueError, "owner-owned single-link"):
                stage_cross_workspace_symlink(workspace_b, workspace_b / "fee.py")

    def test_signed_workspace_trial_pair_rejects_reused_authority_and_missing_scope_refusal(self):
        def trial(suffix: str, *, built: bool, fixture_case: str, refused: bool) -> dict[str, object]:
            runtime_trial_id = str(uuid.uuid4())
            task_id = str(uuid.uuid4())
            session_id = str(uuid.uuid4())
            request_id = f"request-{uuid.uuid4()}"
            approval = hashlib.sha256(f"approval-{suffix}".encode()).hexdigest()
            result_digest = hashlib.sha256(f"result-{suffix}".encode()).hexdigest()
            return {
                "result": "PASS",
                "app_build_occurred": built,
                "build_record_sha256": "a" * 64,
                "app_tree_sha256_before_after": ["b" * 64, "b" * 64],
                "deep_code_signature_verified": True,
                "signing_certificate_sha1": "c" * 40,
                "team_identifiers": {"app": "TEAM"},
                "model_actually_invoked": False,
                "workspace_identity_binding": {
                    "status": "PASS",
                    "runtime_trial_id": runtime_trial_id,
                    "launcher_task_id": task_id,
                    "workspace_session_ids": [session_id],
                    "workspace_path_sha256": hashlib.sha256(f"path-{suffix}".encode()).hexdigest(),
                    "workspace_device": 1,
                    "workspace_inode": 10 + (suffix == "b"),
                    "identity_marker_sha256": hashlib.sha256(f"marker-{suffix}".encode()).hexdigest(),
                    "identity_marker_inode": 20 + (suffix == "b"),
                    "request_bindings": [{
                        "launcher_request_id": request_id,
                        "approval_sha256": approval,
                        "result_sha256": result_digest,
                        "result_digest_matches_launcher_delivery": True,
                    }],
                },
                "phase31_signed_semantic_fixture": {
                    "status": "PASS",
                    "fixture_case": fixture_case,
                    "cross_workspace_scope_refused": refused,
                    "dsh_session_ids": [f"dsh-session-{suffix}"],
                },
            }

        first = trial("a", built=True, fixture_case="coding", refused=False)
        second = trial("b", built=False, fixture_case="cross-workspace-after-read", refused=True)
        first["phase31_signed_semantic_fixture"]["workspace_canary_sha256"] = "d" * 64
        second["phase31_signed_semantic_fixture"]["cross_workspace_target_canary_sha256"] = "d" * 64
        self.assertEqual(evaluate_workspace_trial_pair(first, second)["status"], "PASS")

        identical_result_content = json.loads(json.dumps(second))
        identical_result_content["workspace_identity_binding"]["request_bindings"][0][
            "result_sha256"
        ] = first["workspace_identity_binding"]["request_bindings"][0]["result_sha256"]
        identical_result_report = evaluate_workspace_trial_pair(first, identical_result_content)
        self.assertEqual(identical_result_report["status"], "PASS")
        self.assertTrue(identical_result_report["result_content_digest_overlap"])

        wrong_cross_workspace_target = json.loads(json.dumps(second))
        wrong_cross_workspace_target["phase31_signed_semantic_fixture"][
            "cross_workspace_target_canary_sha256"
        ] = "e" * 64
        report = evaluate_workspace_trial_pair(first, wrong_cross_workspace_target)
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["cross_workspace_canary_bound_to_trial_a"])
        self.assertIn("cross_workspace_canary_not_bound_to_trial_a", report["failure_reasons"])

        reused_approval = json.loads(json.dumps(second))
        reused_approval["workspace_identity_binding"]["request_bindings"][0]["approval_sha256"] = \
            first["workspace_identity_binding"]["request_bindings"][0]["approval_sha256"]
        report = evaluate_workspace_trial_pair(first, reused_approval)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("approval_sha256_replayed", report["failure_reasons"])

        missing_refusal = json.loads(json.dumps(second))
        missing_refusal["phase31_signed_semantic_fixture"]["cross_workspace_scope_refused"] = False
        self.assertIn(
            "cross_workspace_scope_refusal_not_proven",
            evaluate_workspace_trial_pair(first, missing_refusal)["failure_reasons"],
        )

    def test_prebuilt_app_signature_and_identity_mismatches_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = (Path(temporary) / "Candidate.app")
            app.mkdir()
            app = app.resolve()
            receipt_path = app / "Contents/Resources/build-inputs.json"
            receipt_path.parent.mkdir(parents=True)
            receipt_path.write_text('{"schema":1}\n', encoding="utf-8")

            with patch("tools.run_dsh_xpc_attack_acceptance.seed_builder._require_signing_identity", return_value="c" * 40), \
                    patch("tools.run_dsh_xpc_attack_acceptance.run", side_effect=RuntimeError("codesign rejected")):
                with self.assertRaisesRegex(RuntimeError, "codesign rejected"):
                    validate_prebuilt_dsh_app(app, signing_identity="Developer ID", source_sha="d" * 40)

            with patch("tools.run_dsh_xpc_attack_acceptance.seed_builder._require_signing_identity", return_value="c" * 40), \
                    patch("tools.run_dsh_xpc_attack_acceptance.run", return_value=""), \
                    patch("tools.run_dsh_xpc_attack_acceptance.seed_builder.verify_app"):
                with self.assertRaisesRegex(ValueError, "receipt does not match"):
                    validate_prebuilt_dsh_app(app, signing_identity="Developer ID", source_sha="d" * 40)


if __name__ == "__main__":
    unittest.main()
