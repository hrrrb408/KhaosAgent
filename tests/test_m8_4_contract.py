from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / "reports/experiments/m8-4-coding-reliability/experiment_support.py"
SPEC = importlib.util.spec_from_file_location("m8_4_support", SUPPORT)
assert SPEC and SPEC.loader
support = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(support)
DRIVER_SPEC = importlib.util.spec_from_file_location("m8_4_driver", SUPPORT.with_name("run_attempt.py"))
assert DRIVER_SPEC and DRIVER_SPEC.loader
driver = importlib.util.module_from_spec(DRIVER_SPEC)
with patch.dict(sys.modules, {"experiment_support": support}):
    DRIVER_SPEC.loader.exec_module(driver)


class M84ContractTests(unittest.TestCase):
    def test_frozen_benchmark_inputs_are_unchanged(self) -> None:
        self.assertEqual(support.verify_inputs()["status"], "PASS")

    def test_copied_dataset_integrity_is_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dataset = Path(temporary)
            for relative in support.FROZEN_SHA256:
                target = dataset / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(support.DATASET / relative, target)
            self.assertEqual(support.verify_inputs(dataset)["status"], "PASS")
            (dataset / "grade_attempt.py").write_text("changed")
            with self.assertRaisesRegex(ValueError, "grade_attempt.py"):
                support.verify_inputs(dataset)

    def test_candidate_snapshot_keeps_new_files_without_reading_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            git = ["git", "-C", str(workspace)]
            subprocess.run(git + ["init", "-q"], check=True)
            (workspace / "existing.py").write_text("old = True\n")
            subprocess.run(git + ["add", "existing.py"], check=True)
            subprocess.run(git + ["-c", "user.name=Probe", "-c", "user.email=probe@example.invalid",
                                  "commit", "-qm", "baseline"], check=True)
            (workspace / "existing.py").write_text("old = False\n")
            (workspace / "new.py").write_text("new = True\n")
            secret = root / "outside"
            secret.write_text("EXTERNAL_SECRET_SENTINEL")
            (workspace / "link").symlink_to(secret)
            snapshot, paths = driver.candidate_snapshot(workspace)
            self.assertEqual(paths, ["existing.py", "link", "new.py"])
            self.assertIn(b"+new = True", snapshot)
            self.assertIn(b"120000", snapshot)
            self.assertNotIn(b"EXTERNAL_SECRET_SENTINEL", snapshot)
            self.assertEqual(subprocess.check_output(git + ["diff", "--cached"]), b"")

    def test_grader_error_keeps_output_private_and_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "grade_attempt.py").write_text("import sys\nprint('PRIVATE_SENTINEL')\nsys.exit(7)\n")
            summary = driver.independent_grade(root, root, "probe")
            self.assertEqual(summary["grade_status"], "GRADER_ERROR")
            self.assertEqual(summary["grader_exit_code"], 7)
            self.assertEqual(summary["all_test_commands_passed"], "NOT_CAPTURED")
            self.assertNotIn("PRIVATE_SENTINEL", str(summary))
            self.assertIn("PRIVATE_SENTINEL", (root / "grader.stdout").read_text())

    def test_strict_derivation_changes_only_reviewed_normalization(self) -> None:
        source = (ROOT / "khaos/macos/AgentHostActionOutput.swift").read_text()
        strict = support.strict_source(source)
        self.assertEqual(len(source) - len(strict), len(support.NORMALIZATION))
        with self.assertRaises(ValueError):
            support.strict_source(strict)

    @unittest.skipUnless(sys.platform == "darwin", "real Swift macOS parser probe")
    def test_both_production_parsers_and_diagnostics_preserve_acceptance(self) -> None:
        source = (ROOT / "khaos/macos/AgentHostActionOutput.swift").read_text()
        swiftc = subprocess.check_output(["xcrun", "--find", "swiftc"], text=True).strip()
        sdk = subprocess.check_output(["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True).strip()
        with tempfile.TemporaryDirectory(prefix="khaos-m84-contract-") as temporary:
            root = Path(temporary)
            for group, content in [("A", support.strict_source(source)), ("C", source)]:
                parser = root / "AgentHostActionOutput.swift"
                parser.write_text(content)
                probe = root / f"ACProbe{group}"
                subprocess.run([swiftc, "-sdk", sdk, "-target", f"{platform.machine()}-apple-macosx26.0",
                    str(ROOT / "khaos/macos/AgentHostProtocol.swift"), str(parser),
                    str(ROOT / "tests/macos_xpc_probe/AgentHostACContractProbe.swift"),
                    "-o", str(probe)], check=True, capture_output=True, timeout=60)
                outputs = []
                for enabled in [False, True]:
                    env = os.environ.copy()
                    env.pop("KHAOS_AGENT_ACTION_DIAGNOSTICS", None)
                    if enabled:
                        env["KHAOS_AGENT_ACTION_DIAGNOSTICS"] = "1"
                    run = subprocess.run([str(probe), group], env=env, capture_output=True,
                                         text=True, timeout=10)
                    self.assertEqual(run.returncode, 0, run.stderr)
                    outputs.append((run.stdout, run.stderr))
                self.assertEqual(outputs[0], outputs[1])
                self.assertIn(f"ac-contract=passed group={group}", outputs[0][0])


if __name__ == "__main__":
    unittest.main()
