"""Deterministic checks for test-only source overlays; no UI action is simulated."""
import base64
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

from signed_cancellation_fixture import CASES, MARKER, host_receipt_contains_terminal, overlay, replace_once
from tools.build_macos_seed import ROOT, _snapshot_sources


class SignedCancellationFixtureTests(unittest.TestCase):
    def test_host_receipt_must_start_with_exact_terminal_bytes(self):
        terminal = b"cancelled before submission"
        receipt = terminal + b"\nfixed model-probe instructions"
        self.assertTrue(host_receipt_contains_terminal(
            base64.b64encode(terminal).decode(), base64.b64encode(receipt).decode()))
        self.assertFalse(host_receipt_contains_terminal(
            base64.b64encode(terminal).decode(),
            base64.b64encode(b"different terminal" + receipt).decode()))

    def test_private_overlay_is_explicit_and_fails_on_anchor_drift(self):
        paths = [ROOT / "khaos/kernel/broker.py", ROOT / "khaos/kernel/worker.py",
                 ROOT / "khaos/kernel/workspace_xpc_bridge.py", ROOT / "khaos/launcher.py",
                 ROOT / "khaos/macos/KernelWorkspaceClient.swift",
                 ROOT / "khaos/macos/KernelWorkspaceService.swift"]
        before = {path: path.read_bytes() for path in paths}
        for case in CASES:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as value:
                snapshot = Path(value) / "sources"
                _snapshot_sources(snapshot, None)
                changed = overlay(snapshot, Path(value), case)
                self.assertEqual(len(changed), 7 if case == "b32" else 6)
                for relative in (
                    "khaos/kernel/broker.py",
                    "khaos/kernel/worker.py",
                    "khaos/kernel/workspace_xpc_bridge.py",
                    "khaos/launcher.py",
                ):
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
                    answer.append(module._await_commit_authorization(
                        ready_read,
                        decision_write,
                        cancelled.is_set,
                        workspace_request_id="headless-request",
                    ))
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
                self.assertIn("headless-request", event.read_text())
                self.assertTrue(thread.is_alive(), "READY must not automatically authorize ACCEPT")
                cancelled.set()
            finally:
                (root / "release").touch()
                thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
            self.assertFalse(errors)
            self.assertEqual(answer, [False])
            self.assertEqual(os.read(decision_read, 1), module._COMMIT_ABORT)

            (root / "release").unlink()
            probe_ready_read, probe_ready_write = os.pipe()
            probe_decision_read, probe_decision_write = os.pipe()
            probe_answer = []
            probe_errors = []
            def run_probe():
                try:
                    probe_answer.append(module._await_commit_authorization(
                        probe_ready_read,
                        probe_decision_write,
                        None,
                    ))
                except BaseException as error:
                    probe_errors.append(error)
            try:
                os.write(probe_ready_write, module._COMMIT_READY)
                probe_thread = threading.Thread(target=run_probe)
                probe_thread.start()
                probe_thread.join(timeout=0.5)
                self.assertFalse(
                    probe_thread.is_alive(),
                    "Seatbelt readiness checks must not wait at the signed test barrier",
                )
                self.assertFalse(probe_errors)
                self.assertEqual(probe_answer, [True])
                self.assertEqual(os.read(probe_decision_read, 1), module._COMMIT_ACCEPT)
                events = event.read_text().splitlines()
                self.assertEqual(
                    sum('"stage": "KERNEL_READY_PRE_ACCEPT"' in line for line in events),
                    1,
                    "Seatbelt readiness checks must not enter the signed test barrier",
                )
            finally:
                (root / "release").touch()
                if "probe_thread" in locals():
                    probe_thread.join(timeout=3)
                for descriptor in (
                    probe_ready_read,
                    probe_ready_write,
                    probe_decision_read,
                    probe_decision_write,
                ):
                    os.close(descriptor)
