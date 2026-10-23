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
    candidate_b_fixed_script,
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


if __name__ == "__main__":
    unittest.main()
