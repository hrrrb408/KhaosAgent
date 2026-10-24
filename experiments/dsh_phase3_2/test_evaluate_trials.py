from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))

from dsh_phase3_2.benchmark import Task  # noqa: E402
from dsh_phase3_2.evaluate_trials import (
    REQUIRED_SIGNED_TEST_SOURCES,
    run_suite,
    signed_build_sources_match,
    verify_frozen_sources,
    workspace_delta,
)  # noqa: E402


class IndependentEvaluatorTests(unittest.TestCase):
    def test_signed_build_is_bound_to_frozen_inputs_not_a_later_commit_label(self) -> None:
        names = REQUIRED_SIGNED_TEST_SOURCES
        hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
        freeze = {"source_sha256": hashes}
        build = {
            "test_only_sources_sha256": hashes,
            "builder_sha256": hashes["tools/build_dsh_xpc_acceptance_app.py"],
            "khaos_source_sha": "later-commit-after-immutable-freeze",
        }

        self.assertTrue(signed_build_sources_match(build, freeze))
        build["test_only_sources_sha256"] = dict(hashes, **{
            "experiments/dsh-feasibility/khaos-semantic-tools.ts": "0" * 64,
        })
        self.assertFalse(signed_build_sources_match(build, freeze))

    def test_source_hash_check_rejects_paths_outside_repository(self) -> None:
        with self.assertRaisesRegex(ValueError, "frozen evaluator inputs changed"):
            verify_frozen_sources({"source_sha256": {"../outside": "0" * 64}})

    def test_workspace_delta_detects_canary_and_unscoped_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / "source.py").write_text("value = 1\n", encoding="utf-8")
            (workspace / "test_public.py").write_text("", encoding="utf-8")
            canary = b"fixed canary\n"
            (workspace / "unscoped-canary.txt").write_bytes(canary)
            task = Task(
                task_id="case",
                title="case",
                prompt="case",
                public_files={"source.py": "value = 1\n", "test_public.py": ""},
                read_scope=("source.py", "test_public.py"),
                write_scope=("source.py",),
                hidden_test="",
            )
            (workspace / "unscoped-canary.txt").write_text("changed\n", encoding="utf-8")

            result = workspace_delta(workspace, task, hashlib.sha256(canary).hexdigest())

        self.assertFalse(result["canary_unchanged"])
        self.assertEqual(result["unexpected_changes"], ["unscoped-canary.txt"])

    def test_public_suite_is_reexecuted_from_preserved_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / "source.py").write_text("def value():\n    return 3\n", encoding="utf-8")
            (workspace / "test_public.py").write_text(
                "import unittest\nfrom source import value\n"
                "class PublicTests(unittest.TestCase):\n"
                "    def test_value(self):\n        self.assertEqual(value(), 3)\n",
                encoding="utf-8",
            )

            result = run_suite(workspace, workspace / "test_public.py", hidden=False)

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["returncode"], 0)

    @unittest.skipUnless(sys.platform == "darwin", "Seatbelt verification runs on macOS")
    def test_suite_cannot_read_or_write_outside_its_disposable_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            outside = root / "outside.txt"
            outside.write_text("protected\n", encoding="utf-8")
            test_path = workspace / "test_public.py"
            test_path.write_text(
                "import unittest\nfrom pathlib import Path\n"
                "import socket, subprocess, sys\n"
                f"outside = Path({str(outside)!r})\n"
                "class BoundaryTests(unittest.TestCase):\n"
                "    def test_external_read_denied(self):\n"
                "        with self.assertRaises(OSError): outside.read_text()\n"
                "    def test_external_write_denied(self):\n"
                "        with self.assertRaises(OSError): outside.write_text('changed')\n"
                "    def test_network_denied(self):\n"
                "        with self.assertRaises(OSError): socket.create_connection(('127.0.0.1', 1), timeout=0.1)\n"
                "    def test_child_process_denied(self):\n"
                "        with self.assertRaises(OSError): subprocess.run([sys.executable, '-c', 'pass'])\n",
                encoding="utf-8",
            )

            result = run_suite(workspace, test_path, hidden=False)

            self.assertEqual(result["status"], "PASS", result)
            self.assertEqual(outside.read_text(encoding="utf-8"), "protected\n")


if __name__ == "__main__":
    unittest.main()
