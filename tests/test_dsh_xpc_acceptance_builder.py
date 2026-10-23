from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.build_dsh_xpc_acceptance_app import candidate_b_fixed_script


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


if __name__ == "__main__":
    unittest.main()
