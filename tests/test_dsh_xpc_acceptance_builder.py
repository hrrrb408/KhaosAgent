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
    apply_experimental_tool_trace_protocol,
    apply_experimental_telemetry_transport_client,
    apply_experimental_workspace_runtime_binding,
    candidate_b_fixed_script,
)
from tools.run_dsh_xpc_attack_acceptance import (
    create_workspace_identity_manifest,
    load_workspace_identity_evidence,
)

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
            self.assertIn('"AGENT_TERMINATED"', source)
            self.assertIn('"TURN_END_OBSERVED"', source)
            self.assertIn('record["tool_name"] as? String == "run_tests"', source)
            self.assertIn('maximum: 10_000', source)
            for field in ("tests_run", "failures", "errors", "skipped"):
                self.assertIn(f'"{field}"', source)
            for field in (
                "turn_end_sequence",
                "assistant_message_count",
                "tool_result_count",
                "turn_end_reason",
                "last_message_role",
                "last_message_text_only",
                "unresolved_kernel_result",
            ):
                self.assertIn(f'"{field}"', source)

        host_telemetry = host_source.split("private func acceptTelemetry", 1)[1].split("func exchange", 1)[0]
        self.assertIn('"runtime_trial_id"', host_telemetry)
        self.assertIn('event == "LAUNCHER_TERMINAL_RESULT_DELIVERED"', host_telemetry)
        self.assertIn('record["runtime_trial_id"] as? String', host_telemetry)
        client_telemetry = launcher_source.split("private func acceptExperimentalTelemetry", 1)[1]
        self.assertIn('"runtime_trial_id"', client_telemetry)
        self.assertIn('event == "LAUNCHER_TERMINAL_RESULT_DELIVERED"', client_telemetry)
        self.assertIn('record["runtime_trial_id"] as? String', client_telemetry)

    def test_experimental_tool_result_trace_requires_runtime_trial_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source_root = Path(temporary)
            target = source_root / "khaos/macos/AgentHostProtocol.swift"
            target.parent.mkdir(parents=True)
            shutil.copy2(ROOT / "khaos/macos/AgentHostProtocol.swift", target)
            overlay = apply_experimental_tool_trace_protocol(source_root)
            source = target.read_text(encoding="utf-8")

        self.assertEqual(overlay["path"], "khaos/macos/AgentHostProtocol.swift")
        self.assertIn('"runtime_trial_id"', source)
        self.assertIn('"trial_id", "dsh_session_id", "runtime_trial_id", "tool_call_id"', source)

    def test_workspace_identity_manifest_is_owner_only_and_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "main.py").write_text("value = 1\n", encoding="utf-8")
            manifest_path, generated = create_workspace_identity_manifest(workspace, "trial-a", root)

            loaded = load_workspace_identity_evidence(manifest_path, workspace)
            self.assertEqual(loaded, generated)
            self.assertEqual(manifest_path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("workspace_path", loaded)

            (workspace / "main.py").write_text("value = 2\n", encoding="utf-8")
            self.assertEqual(
                load_workspace_identity_evidence(manifest_path, workspace),
                loaded,
                "fixture contents may change after the runtime identity marker is established",
            )

    def test_workspace_identity_marker_replay_and_directory_inode_replacement_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "fee.py").write_text("value = 1\n", encoding="utf-8")
            old_manifest, _ = create_workspace_identity_manifest(workspace, "trial-old", root)
            marker = workspace / ".khaos-phase322-identity.json"
            old_marker = root / "old-marker.json"
            marker.rename(old_marker)
            new_manifest, _ = create_workspace_identity_manifest(workspace, "trial-new", root)
            self.assertEqual(load_workspace_identity_evidence(new_manifest, workspace)["trial_id"], "trial-new")
            with self.assertRaisesRegex(ValueError, "marker digest mismatch|marker contents"):
                load_workspace_identity_evidence(old_manifest, workspace)

            other = root / "replace-directory"
            other.mkdir()
            (other / "fee.py").write_text("value = 2\n", encoding="utf-8")
            replaced_manifest, _ = create_workspace_identity_manifest(other, "trial-directory", root)
            moved = root / "replace-directory-old"
            other.rename(moved)
            other.mkdir()
            (other / "fee.py").write_text("value = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "directory identity changed"):
                load_workspace_identity_evidence(replaced_manifest, other)

    def test_workspace_runtime_overlay_is_path_independent_and_experimental_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "sources"
            target = source_root / "khaos/macos/TrustedWorkspaceLauncherMain.swift"
            target.parent.mkdir(parents=True)
            shutil.copy2(ROOT / "khaos/macos/TrustedWorkspaceLauncherMain.swift", target)

            apply_experimental_launcher_semantic_trace(source_root)
            overlay = apply_experimental_workspace_runtime_binding(source_root)
            source = target.read_text(encoding="utf-8")

            second_root = root / "second-sources"
            second_target = second_root / "khaos/macos/TrustedWorkspaceLauncherMain.swift"
            second_target.parent.mkdir(parents=True)
            shutil.copy2(ROOT / "khaos/macos/TrustedWorkspaceLauncherMain.swift", second_target)
            apply_experimental_launcher_semantic_trace(second_root)
            second_overlay = apply_experimental_workspace_runtime_binding(second_root)

        self.assertEqual(overlay["path"], "khaos/macos/TrustedWorkspaceLauncherMain.swift")
        self.assertEqual(overlay["experimental_sha256"], second_overlay["experimental_sha256"])
        self.assertLess(
            source.index("@main\nenum TrustedWorkspaceLauncherMain {"),
            source.index("private struct Phase322MarkerSnapshot"),
            "runtime binding support types must remain nested under the original Launcher entry point",
        )
        self.assertIn("let trialID = UUID()", source)
        self.assertIn("phase322BeginTrial(taskID: taskID)", source)
        self.assertIn("phase322EndTrial(taskID: taskID)", source)
        self.assertIn("resolvingBookmarkData: selection.bookmark", source)
        self.assertIn("workspaceURL.startAccessingSecurityScopedResource()", source)
        self.assertIn("workspaceURL.stopAccessingSecurityScopedResource()", source)
        self.assertIn("Darwin.realpath(source, &resolvedPath)", source)
        self.assertIn("O_NOFOLLOW", source)
        self.assertIn('checkpoint: "before_approval"', source)
        self.assertIn('checkpoint: "after_approval"', source)
        self.assertIn('checkpoint: "after_kernel_result"', source)
        self.assertIn("phase322ReadMarker(directoryFD: directoryFD)", source)
        self.assertIn("Darwin.fstatat(AT_FDCWD, $0, &namedDirectoryInfo, 0)", source)
        self.assertIn("selection.identity", source)
        self.assertIn("bookmarkSHA256", source)
        self.assertNotIn("phase322ExpectedWorkspacePath", source)
        self.assertNotIn("phase322ExpectedWorkspaceSHA256", source)
        self.assertNotIn('private static let phase322TrialID =', source)


if __name__ == "__main__":
    unittest.main()
