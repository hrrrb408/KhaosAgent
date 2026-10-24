import json
import unittest

from tools.run_dsh_xpc_attack_acceptance import (
    launcher_task_records,
    semantic_result_observation,
    signed_ui_evidence,
    validate_operator,
)


class DSHXPCAcceptanceEvidenceTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
