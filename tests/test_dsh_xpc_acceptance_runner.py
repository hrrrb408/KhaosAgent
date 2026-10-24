import json
import unittest

from tools.run_dsh_xpc_attack_acceptance import (
    evaluate_workspace_identity_binding,
    launcher_task_records,
    semantic_agent_completion_evidence,
    semantic_result_observation,
    signed_ui_evidence,
    validate_operator,
)


class DSHXPCAcceptanceEvidenceTests(unittest.TestCase):
    def test_semantic_fixture_completion_requires_committed_final_and_completed_turn(self):
        telemetry = [
            {"event": "DSH_ASSISTANT_MESSAGE_COMMITTED", "status": "session_committed", "dsh_event_seq": 8},
            {"event": "TURN_END_OBSERVED", "status": "completed", "dsh_event_seq": 9},
            {"event": "AGENT_TERMINATED", "status": "completed"},
        ]
        diagnostics = [{
            "terminal_status": "completed",
            "turn_end_reason": "completed",
            "turn_end_sequence": 9,
            "last_message_role": "assistant",
            "last_message_block_types": ["text"],
        }]

        self.assertTrue(semantic_agent_completion_evidence(telemetry, diagnostics)["completed"])
        self.assertFalse(semantic_agent_completion_evidence(
            [*telemetry[:-1], {"event": "AGENT_TERMINATED", "status": "incomplete"}], diagnostics
        )["completed"])
        self.assertFalse(semantic_agent_completion_evidence(telemetry, [
            {**diagnostics[0], "turn_end_sequence": 8},
        ])["completed"])
        self.assertFalse(semantic_agent_completion_evidence(telemetry, [
            {**diagnostics[0], "last_message_block_types": ["tool-call"]},
        ])["completed"])
        self.assertFalse(semantic_agent_completion_evidence(telemetry, [
            {**diagnostics[0], "terminal_status": "incomplete", "incomplete_reason": "no_progress_limit"},
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

    def test_workspace_identity_evidence_joins_pre_and_post_approval_events(self):
        identity = {
            "trial_id": "trial-identity",
            "workspace_path_sha256": "a" * 64,
            "workspace_device": 1,
            "workspace_inode": 2,
            "marker_sha256": "b" * 64,
            "manifest_sha256": "c" * 64,
            "fixture_files": {"main.py": {"sha256": "d" * 64, "bytes": 12}},
        }
        request = {
            "request_id": "request-1",
            "workspace_session_id": "session-1",
            "invocation_sha256": "e" * 64,
            "kernel_result": "output",
        }
        common = {
            "trial_id": "trial-identity",
            "launcher_task_id": "task-1",
            "launcher_request_id": "request-1",
            "workspace_session_id": "session-1",
            "selected_path_sha256": "a" * 64,
            "marker_sha256": "b" * 64,
            "fixture_files_verified": True,
            "snapshot_identity": "NOT_AVAILABLE",
            "status": "verified",
        }
        events = [
            {**common, "checkpoint": "before_approval"},
            {**common, "checkpoint": "after_approval", "approval_sha256": "e" * 64},
            {**common, "checkpoint": "after_kernel_result", "approval_sha256": "e" * 64},
        ]
        stderr = "\n".join(
            "dsh-workspace-identity=" + json.dumps(event) for event in events
        )
        report = evaluate_workspace_identity_binding(
            identity=identity,
            task_records=[{"task_id": "task-1", "workspace_requests": [request]}],
            stderr=stderr,
        )

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["verified_request_count"], 1)
        self.assertEqual(report["workspace_session_ids"], ["session-1"])
        self.assertTrue(report["request_bindings"][0]["post_kernel_result_verified"])
        self.assertNotIn("workspace_path", report)

        tampered = {**events[1], "workspace_session_id": "other-session"}
        rejected = evaluate_workspace_identity_binding(
            identity=identity,
            task_records=[{"task_id": "task-1", "workspace_requests": [request]}],
            stderr="\n".join(
                "dsh-workspace-identity=" + json.dumps(event)
                for event in (events[0], tampered)
            ),
        )
        self.assertEqual(rejected["status"], "FAIL")
        self.assertIn("launcher_request_identity_mismatch", rejected["failure_reasons"])


if __name__ == "__main__":
    unittest.main()
