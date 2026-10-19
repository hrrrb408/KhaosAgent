"""Deterministic checks for test-only source overlays; no UI action is simulated."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

from signed_cancellation_fixture import CASES, MARKER, overlay, replace_once
from tools.build_macos_seed import ROOT, _snapshot_sources


class SignedCancellationFixtureTests(unittest.TestCase):
    def test_private_overlay_is_explicit_and_fails_on_anchor_drift(self):
        paths = [ROOT / "khaos/kernel/broker.py", ROOT / "khaos/kernel/worker.py",
                 ROOT / "khaos/macos/KernelWorkspaceClient.swift",
                 ROOT / "khaos/macos/KernelWorkspaceService.swift"]
        before = {path: path.read_bytes() for path in paths}
        for case in CASES:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as value:
                snapshot = Path(value) / "sources"
                _snapshot_sources(snapshot, None)
                changed = overlay(snapshot, Path(value), case)
                self.assertEqual(len(changed), 5 if case == "b32" else 4)
                for relative in ("khaos/kernel/broker.py", "khaos/kernel/worker.py"):
                    compile((snapshot / relative).read_text(), relative, "exec")
                self.assertIn(MARKER, (snapshot / "khaos/kernel/broker.py").read_text())
                with self.assertRaisesRegex(ValueError, "anchor must occur once"):
                    overlay(snapshot, Path(value), case)
        self.assertEqual(before, {path: path.read_bytes() for path in paths})
        for source in ("missing", "double double"):
            with self.assertRaises(ValueError):
                replace_once(source, "double", "replacement")

    def test_pre_accept_barrier_observes_cancel_before_authorizing_live_mutation(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            snapshot = root / "sources"
            _snapshot_sources(snapshot, None)
            overlay(snapshot, root, "pre-commit")
            name = "khaos.kernel._signed_acceptance_broker_probe"
            spec = importlib.util.spec_from_file_location(name, snapshot / "khaos/kernel/broker.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            self.addCleanup(sys.modules.pop, name, None)
            spec.loader.exec_module(module)
            ready_read, ready_write = os.pipe()
            decision_read, decision_write = os.pipe()
            self.addCleanup(lambda: [os.close(fd) for fd in (ready_read, ready_write, decision_read, decision_write)])
            cancelled = threading.Event()
            answer = []
            errors = []
            def run():
                try:
                    answer.append(module._await_commit_authorization(ready_read, decision_write, cancelled.is_set))
                except BaseException as error:
                    errors.append(error)
            thread = threading.Thread(target=run)
            thread.start()
            os.write(ready_write, module._COMMIT_READY)
            try:
                deadline = time.monotonic() + 3
                event = root / "kernel-events.jsonl"
                while not event.exists() and time.monotonic() < deadline:
                    time.sleep(0.005)
                self.assertTrue(event.exists(), errors)
                self.assertIn("KERNEL_READY_PRE_ACCEPT", event.read_text())
                self.assertTrue(thread.is_alive(), "READY must not automatically authorize ACCEPT")
                cancelled.set()
            finally:
                (root / "release").touch()
                thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
            self.assertFalse(errors)
            self.assertEqual(answer, [False])
            self.assertEqual(os.read(decision_read, 1), module._COMMIT_ABORT)
