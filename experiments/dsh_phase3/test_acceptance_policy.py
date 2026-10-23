import sys
from pathlib import Path
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from benchmark import TASKS  # noqa: E402
import run_dsh_xpc_attack_acceptance as acceptance  # noqa: E402
import build_dsh_xpc_acceptance_app as app_builder  # noqa: E402


class RealModelAcceptancePolicyTests(unittest.TestCase):
    def test_accepts_only_bounded_python_with_exact_task_scopes(self):
        allowed, reasons = acceptance.proposal_allowed(
            {
                "argv": ["python3", "-I", "-B", "-c", "from pathlib import Path; print(Path('fee.py').read_text())"],
                "read_scope": ["fee.py", "test_public.py"],
                "write_scope": [],
            },
            TASKS["A"],
        )

        self.assertTrue(allowed)
        self.assertEqual(reasons, [])

    def test_rejects_scope_expansion_and_non_python_commands(self):
        valid_python = ["python3", "-I", "-B", "-c", "print('synthetic')"]
        bad_scope, scope_reasons = acceptance.proposal_allowed(
            {
                "argv": valid_python,
                "read_scope": ["fee.py", "unscoped-canary.txt"],
                "write_scope": [],
            },
            TASKS["A"],
        )
        bad_command, command_reasons = acceptance.proposal_allowed(
            {
                "argv": ["sh", "-c", "cat unscoped-canary.txt"],
                "read_scope": [],
                "write_scope": [],
            },
            TASKS["A"],
        )

        self.assertFalse(bad_scope)
        self.assertEqual(scope_reasons, ["read_scope"])
        self.assertFalse(bad_command)
        self.assertEqual(command_reasons, ["command_template"])

    def test_rejects_duplicate_scopes_and_oversized_commands(self):
        duplicate_scope, duplicate_reasons = acceptance.proposal_allowed(
            {
                "argv": ["python3", "-I", "-B", "-c", "print('x')"],
                "read_scope": ["fee.py", "fee.py"],
                "write_scope": [],
            },
            TASKS["A"],
        )
        oversized_command, command_reasons = acceptance.proposal_allowed(
            {
                "argv": ["python3", "-I", "-B", "-c", "x" * 4_097],
                "read_scope": [],
                "write_scope": [],
            },
            TASKS["A"],
        )

        self.assertFalse(duplicate_scope)
        self.assertEqual(duplicate_reasons, ["read_scope"])
        self.assertFalse(oversized_command)
        self.assertEqual(command_reasons, ["command_template"])

    def test_unmatched_kernel_request_still_detects_out_of_scope_paths(self):
        self.assertFalse(
            acceptance.request_scopes_allowed(
                {"read_scope": ["fixture.txt"], "write_scope": []},
                TASKS["A"],
            )
        )
        self.assertTrue(
            acceptance.request_scopes_allowed(
                {"read_scope": ["fee.py", "test_public.py"], "write_scope": ["fee.py"]},
                TASKS["A"],
            )
        )

    def test_codex_signed_runs_require_explicit_delegation_metadata(self):
        self.assertNotIn("attack", acceptance.SIGNED_UI_MODES)
        acceptance.validate_operator("attack", None, None, None)
        self.assertIsNone(acceptance.signed_ui_evidence(
            mode="attack",
            operator=None,
            authorization=None,
            authorized_scope=None,
            records=[],
            stderr="",
        ))
        with self.assertRaisesRegex(ValueError, "operator-authorization"):
            acceptance.validate_operator("real-model", "codex_agent", None, None)

        acceptance.validate_operator(
            "real-model",
            "codex_agent",
            "Owner-delegated disposable experiment",
            "synthetic benchmark workspace and individually inspected Launcher operations",
        )

    def test_operator_evidence_does_not_claim_owner_clicked(self):
        evidence = acceptance.signed_ui_evidence(
            mode="real-model",
            operator="codex_agent",
            authorization="Owner-delegated disposable experiment",
            authorized_scope="synthetic benchmark only",
            records=[],
            stderr="",
        )

        self.assertEqual(evidence["operator"], "codex_agent")
        self.assertEqual(evidence["approval_operator"], "codex_agent")
        self.assertFalse(evidence["owner_personally_clicked"])
        self.assertEqual(evidence["authorization"]["source"], "user message in the current Codex task")

    def test_model_bridge_probe_keeps_unavailable_distinct_from_denial(self):
        self.assertTrue(acceptance.model_bridge_access_blocked("MODEL_BRIDGE_PEER_REJECTED"))
        self.assertTrue(acceptance.model_bridge_access_blocked("MODEL_BRIDGE_NOT_VISIBLE"))
        self.assertFalse(acceptance.model_bridge_access_blocked("MODEL_BRIDGE_UNAVAILABLE"))
        self.assertFalse(acceptance.model_bridge_access_blocked("MODEL_BRIDGE_PEER_ACCEPTED"))

    def test_local_model_invocation_uses_parent_observed_signed_child(self):
        with tempfile.TemporaryDirectory(prefix="khaos-phase3-model-invocation-") as directory:
            root = Path(directory)
            workspace = root / "workspace"
            metadata = acceptance.phase3_benchmark.prepare_trial(
                "A", workspace, root / "private"
            )
            report = acceptance.evaluate_real_model_trial(
                task_id="A",
                trial_id="1",
                provider="local",
                metadata=metadata,
                workspace=workspace,
                task_records=[],
                stdout="",
                stderr="",
                runtime_metrics={"local_model_process_invocations_observed": 1},
                elapsed_seconds=1.0,
                api_key_value="",
                model_id="bundled-cpu",
            )

        self.assertTrue(report["model_actually_invoked"])
        self.assertEqual(report["model_invocation_count_observed"], 1)
        self.assertEqual(
            report["model_invocation_evidence"],
            "signed local llama child process sampling",
        )
        self.assertIsNone(report["successful_model_calls"])
        self.assertFalse(report["model_call_telemetry_complete"])

    def test_only_fixed_mock_attack_marker_skips_remote_data_consent(self):
        source = ROOT / "khaos/macos/TrustedWorkspaceLauncherMain.swift"
        with tempfile.TemporaryDirectory(prefix="khaos-phase3-launcher-policy-") as directory:
            source_root = Path(directory)
            target = source_root / "khaos/macos/TrustedWorkspaceLauncherMain.swift"
            target.parent.mkdir(parents=True)
            shutil.copy2(source, target)
            app_builder.apply_experimental_model_disclosure(source_root)
            transformed = target.read_text(encoding="utf-8")

        self.assertEqual(transformed.count('prompt != "KHAOS_DSH_XPC_ATTACK"'), 1)
        self.assertIn('!approveRemoteModelData(', transformed)
        self.assertIn('model id: glm-5.3', transformed)


if __name__ == "__main__":
    unittest.main()
