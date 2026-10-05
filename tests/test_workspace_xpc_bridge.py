from __future__ import annotations

from contextlib import nullcontext
import hashlib
import os
from pathlib import Path
import re
import struct
import unittest
from unittest.mock import patch

from khaos.kernel import workspace_xpc_bridge
from khaos.kernel.workspace_xpc_bridge import (
    _WORKSPACE_XPC_OPERATION_VERSION,
    _decode_request,
    _read_workspace_bookmark,
    _scoped_workspace_bookmark,
)


class WorkspaceXPCBridgeTests(unittest.TestCase):
    def test_swift_executor_classifies_every_reported_bridge_error(self) -> None:
        swift = (
            Path(__file__).resolve().parents[1]
            / "khaos/macos/KernelWorkspacePythonExecutor.swift"
        ).read_text(encoding="utf-8")
        exact = set(re.findall(r'case "([a-z_]+)":', swift))
        exact.update(re.findall(r'code == "([a-z_]+)"', swift))
        prefixes = re.findall(r'code\.hasPrefix\("([a-z_]+)"\)', swift)
        self.assertFalse({
            code for code in workspace_xpc_bridge._REPORTED_ERRORS
            if code not in exact and not any(code.startswith(p) for p in prefixes)
        })
        self.assertTrue(any("kernel_failed".startswith(p) for p in prefixes))

    def test_reports_only_allowlisted_sandbox_readiness_stages(self) -> None:
        for error_code in (
            "sandbox_unavailable_probe_child",
            "sandbox_unavailable_probe_readiness",
            "sandbox_unavailable_probe_snapshot",
            "sandbox_unavailable_probe_verification",
        ):
            with self.subTest(error_code=error_code):
                self.assertIn(error_code, workspace_xpc_bridge._REPORTED_ERRORS)

    def test_reports_only_allowlisted_probe_io_stages(self) -> None:
        for stage in (
            "fixture_files",
            "fixture_root",
            "runtime",
            "temporary_cleanup",
            "temporary_create",
            "verification",
        ):
            with self.subTest(stage=stage):
                error_code = f"workspace_rejected_io_sandbox_probe_{stage}"
                self.assertIn(error_code, workspace_xpc_bridge._REPORTED_ERRORS)

    def test_accepts_runner_source_bound_to_its_sha256(self) -> None:
        source = "def run():\n    return 0\n"
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        request_id, payload = _decode_request(self._request(source, digest))

        self.assertEqual(request_id, "a" * 32)
        self.assertEqual(payload["runner_source"], source)
        self.assertEqual(payload["runner_source_sha256"], digest)

    def test_rejects_runner_source_with_a_different_sha256(self) -> None:
        source = "def run():\n    return 0\n"

        with self.assertRaisesRegex(ValueError, "invalid workspace payload"):
            _decode_request(self._request(source, "0" * 64))

    def test_reports_execution_rejection_without_exception_text(self) -> None:
        source = "def run():\n    return 0\n"
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        request = self._request(source, digest)
        with (
            patch.object(workspace_xpc_bridge.sys, "argv", ["bridge", "", "/workspace", "3", "4"]),
            patch.object(workspace_xpc_bridge.os, "fstat"),
            patch.object(workspace_xpc_bridge, "receive_frame", return_value=request),
            patch.object(workspace_xpc_bridge, "_read_workspace_bookmark", return_value=b"bookmark"),
            patch.object(workspace_xpc_bridge, "_scoped_workspace_bookmark", return_value=nullcontext()),
            patch.object(
                workspace_xpc_bridge,
                "run_workspace_command",
                side_effect=ValueError("private path detail"),
            ),
            patch.object(workspace_xpc_bridge, "send_frame") as send_frame,
            patch.dict(
                workspace_xpc_bridge.os.environ,
                {
                    "KHAOS_SNAPSHOT_MOUNT_PATH": "/private/snapshot",
                    "KHAOS_SNAPSHOT_STORAGE_BYTES": "2621440000",
                },
            ),
        ):
            self.assertEqual(workspace_xpc_bridge.main(), 0)

        response = send_frame.call_args.args[1]
        self.assertEqual(
            response["error"],
            {"code": "workspace_rejected_bridge_execution_value"},
        )
        self.assertNotIn("private path detail", repr(response))

    def test_classifies_workspace_root_rejection_without_path(self) -> None:
        error_code = workspace_xpc_bridge._execution_failure_code(
            ValueError("workspace is unavailable or changed")
        )

        self.assertEqual(error_code, "workspace_rejected_bridge_execution_root")

    def test_classifies_workspace_root_binding_stages_without_path(self) -> None:
        failures = (
            (ValueError("workspace root could not be resolved"), "resolve"),
            (ValueError("workspace root could not be opened"), "open"),
            (workspace_xpc_bridge.WorkspaceSnapshotError("private path"), "identity"),
            (PermissionError("private path"), "io"),
        )
        for cause, stage in failures:
            with self.subTest(stage=stage):
                try:
                    raise ValueError("workspace is unavailable or changed") from cause
                except ValueError as error:
                    error_code = workspace_xpc_bridge._execution_failure_code(error)
                self.assertEqual(
                    error_code,
                    f"workspace_rejected_bridge_execution_root_{stage}",
                )

    def test_reads_one_bounded_workspace_bookmark_transfer(self) -> None:
        read_fd, write_fd = os.pipe()
        bookmark = b"bounded-bookmark-data"
        try:
            os.write(write_fd, struct.pack("!I", len(bookmark)) + bookmark)
        finally:
            os.close(write_fd)
        try:
            self.assertEqual(_read_workspace_bookmark(read_fd), bookmark)
        finally:
            os.close(read_fd)

    def test_rejects_oversized_workspace_bookmark_transfer(self) -> None:
        read_fd, write_fd = os.pipe()
        try:
            os.write(
                write_fd,
                struct.pack("!I", workspace_xpc_bridge._MAXIMUM_WORKSPACE_BOOKMARK_BYTES + 1),
            )
        finally:
            os.close(write_fd)
        try:
            with self.assertRaisesRegex(ValueError, "workspace bookmark length"):
                _read_workspace_bookmark(read_fd)
        finally:
            os.close(read_fd)

    @unittest.skipUnless(
        workspace_xpc_bridge.sys.platform == "darwin",
        "Core Foundation is macOS-only",
    )
    def test_rejects_invalid_bookmark_without_opening_a_scope(self) -> None:
        with self.assertRaisesRegex(
            workspace_xpc_bridge.KernelLaunchError,
            "workspace_rejected_bookmark_resolve",
        ):
            with _scoped_workspace_bookmark(b"invalid"):
                self.fail("invalid bookmark unexpectedly opened a scope")

    @staticmethod
    def _request(source: str, digest: str) -> dict[str, object]:
        return {
            "version": _WORKSPACE_XPC_OPERATION_VERSION,
            "request_id": "a" * 32,
            "operation": "workspace.run",
            "payload": {
                "timeout_seconds": 5,
                "runner_source": source,
                "runner_source_sha256": digest,
                "workspace_read_scope": [],
                "workspace_write_scope": [],
            },
        }


if __name__ == "__main__":
    unittest.main()
