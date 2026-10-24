from __future__ import annotations

import subprocess
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.build_dsh_xpc_acceptance_app import (
    apply_experimental_candidate_approval_identity,
    apply_experimental_launcher_semantic_trace,
    apply_experimental_telemetry_transport_client,
    apply_experimental_workspace_identity_binding,
    candidate_b_fixed_script,
    load_workspace_identity_manifest,
)
from tools.run_dsh_xpc_attack_acceptance import create_workspace_identity_manifest

ROOT = Path(__file__).resolve().parents[1]


class DSHXPCAcceptanceBuilderTests(unittest.TestCase):
    def test_candidate_b_probe_decodes_completed_process_stdout(self) -> None:
        probe = Path("TrustedEditApprovalProbe")
        completed = subprocess.CompletedProcess(
            [str(probe), "--fixed-script-json"], 0, '{"fixed_script":"print(1)"}', ""
        )

        with patch("tools.build_dsh_xpc_acceptance_app.run", return_value=completed) as run:
            self.assertEqual(candidate_b_fixed_script(probe), "print(1)")

        run.assert_called_once_with([str(probe), "--fixed-script-json"])

    def test_candidate_b_probe_rejects_missing_fixed_script(self) -> None:
        completed = subprocess.CompletedProcess(
            ["TrustedEditApprovalProbe", "--fixed-script-json"], 0, "{}", ""
        )

        with patch("tools.build_dsh_xpc_acceptance_app.run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "no fixed script"):
                candidate_b_fixed_script(Path("TrustedEditApprovalProbe"))

    def test_semantic_approval_overlays_show_the_active_task_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source_root = Path(temporary)
            for relative_path in (
                "khaos/macos/TrustedWorkspaceLauncherMain.swift",
                "khaos/macos/TrustedEditApproval.swift",
            ):
                target = source_root / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative_path, target)

            launcher = apply_experimental_launcher_semantic_trace(source_root)
            candidate = apply_experimental_candidate_approval_identity(source_root)
            launcher_source = (source_root / launcher["path"]).read_text(encoding="utf-8")
            candidate_source = (source_root / candidate["path"]).read_text(encoding="utf-8")

        self.assertIn('details: "Task ID: \\(taskID.uuidString.lowercased())', launcher_source)
        self.assertIn("taskID: taskID,", launcher_source)
        self.assertIn('Task ID: \\(taskID.uuidString.lowercased())', candidate_source)
        self.assertEqual(candidate_source.count("scrollableText(operationIdentity + summary)"), 1)
        self.assertEqual(candidate_source.count("scrollableText(operationIdentity + details)"), 1)

    def test_test_result_telemetry_contract_matches_both_experimental_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source_root = Path(temporary)
            target = source_root / "khaos/macos/AgentHostClient.swift"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "khaos/macos/AgentHostClient.swift", target)
            apply_experimental_telemetry_transport_client(source_root)
            launcher_source = target.read_text(encoding="utf-8")
            host_source = (
                ROOT / "experiments/dsh-feasibility/DSHAgentHostAcceptance.swift"
            ).read_text(encoding="utf-8")

        for source in (host_source, launcher_source):
            self.assertIn('"PUBLIC_TEST_RESULT_VERIFIED"', source)
            self.assertIn('record["tool_name"] as? String == "run_tests"', source)
            self.assertIn('maximum: 10_000', source)
            for field in ("tests_run", "failures", "errors", "skipped"):
                self.assertIn(f'"{field}"', source)

    def test_workspace_identity_manifest_is_owner_only_and_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "main.py").write_text("value = 1\n", encoding="utf-8")
            manifest_path, generated = create_workspace_identity_manifest(workspace, "trial-a", root)

            loaded, selected_path = load_workspace_identity_manifest(manifest_path)
            self.assertEqual(loaded, generated)
            self.assertEqual(selected_path, workspace.resolve())
            self.assertEqual(manifest_path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("workspace_path", loaded)

            (workspace / "main.py").write_text("value = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "fixture does not match"):
                load_workspace_identity_manifest(manifest_path)

    def test_workspace_identity_overlay_is_trial_bound_and_experimental_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "main.py").write_text("value = 1\n", encoding="utf-8")
            manifest_path, identity = create_workspace_identity_manifest(workspace, "trial-overlay", root)
            loaded, selected_path = load_workspace_identity_manifest(manifest_path)
            source_root = root / "sources"
            target = source_root / "khaos/macos/TrustedWorkspaceLauncherMain.swift"
            target.parent.mkdir(parents=True)
            shutil.copy2(ROOT / "khaos/macos/TrustedWorkspaceLauncherMain.swift", target)

            apply_experimental_launcher_semantic_trace(source_root)
            overlay = apply_experimental_workspace_identity_binding(source_root, loaded, selected_path)
            source = target.read_text(encoding="utf-8")

        self.assertEqual(overlay["path"], "khaos/macos/TrustedWorkspaceLauncherMain.swift")
        self.assertIn('private static let phase322TrialID = "trial-overlay"', source)
        self.assertIn(identity["workspace_path_sha256"], source)
        self.assertIn(str(workspace), source)
        self.assertIn("initialDirectory: URL(fileURLWithPath: phase322ExpectedWorkspacePath", source)
        self.assertIn("canonicalPath == phase322ExpectedWorkspacePath", source)
        self.assertIn("Darwin.realpath(source, &resolvedPath)", source)
        self.assertIn("Data(canonicalPath.utf8)", source)
        self.assertIn('"directory_identity_matches": directoryIdentityMatches', source)
        self.assertIn("approvalSHA256: approvalDigest", source)
        self.assertIn("no Kernel request was submitted", source)
        self.assertEqual(source.count('checkpoint: "after_approval"'), 1)


if __name__ == "__main__":
    unittest.main()
