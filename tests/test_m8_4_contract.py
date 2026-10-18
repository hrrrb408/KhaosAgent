from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / "reports/experiments/m8-4-coding-reliability/experiment_support.py"
SPEC = importlib.util.spec_from_file_location("m8_4_support", SUPPORT)
assert SPEC and SPEC.loader
support = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(support)


class M84ContractTests(unittest.TestCase):
    def test_frozen_benchmark_inputs_are_unchanged(self) -> None:
        self.assertEqual(support.verify_inputs()["status"], "PASS")

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
