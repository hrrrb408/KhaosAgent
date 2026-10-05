from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from khaos.ipc import (
    IPCProtocolError,
    MAX_RUNNER_SOURCE_BYTES,
    PROTOCOL_VERSION,
    send_frame,
)
from khaos.kernel.macos_seatbelt import SandboxUnavailable, SandboxedProcessError
from khaos.kernel.worker import (
    _WorkspaceAncestryIOError,
    _WorkspaceCancellation,
    _run_workspace_command,
    _sandbox_unavailable_error_code,
    _workspace_io_error_code,
)
from khaos.kernel.workspace_snapshot import (
    WorkspaceSnapshotCancelled,
    WorkspaceSnapshotError,
)


_RUNNER_SOURCE = "def run():\n    pass\n"


class KernelWorkerTests(unittest.TestCase):
    def test_sandbox_unavailable_diagnostics_are_bounded_and_path_free(self) -> None:
        for stage, expected in (
            ("probe-child", "sandbox_unavailable_probe_child"),
            ("probe-readiness", "sandbox_unavailable_probe_readiness"),
            ("probe-snapshot", "sandbox_unavailable_probe_snapshot"),
            (
                "probe-verification",
                "sandbox_unavailable_probe_verification",
            ),
            (None, "sandbox_unavailable"),
        ):
            with self.subTest(stage=stage):
                error = SandboxUnavailable(
                    "/private/secret/workspace",
                    diagnostic_stage=stage,
                )
                code = _sandbox_unavailable_error_code(error)
                self.assertEqual(code, expected)
                self.assertNotIn("/private/secret/workspace", code)

    def test_worker_labels_unclassified_readiness_probe_failure(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value).resolve()
            probe_failure = SandboxUnavailable("private path")
            with (
                patch(
                    "khaos.kernel.worker._path_for_directory_descriptor",
                    return_value=workspace,
                ),
                patch(
                    "khaos.kernel.worker._path_is_within",
                    side_effect=(False, False),
                ),
                patch(
                    "khaos.kernel.worker.probe_macos_seatbelt",
                    side_effect=probe_failure,
                ),
            ):
                with self.assertRaises(SandboxUnavailable) as raised:
                    _run_workspace_command(
                        str(workspace),
                        5,
                        _RUNNER_SOURCE,
                        workspace_root_fd=123,
                    )

        self.assertEqual(raised.exception.diagnostic_stage, "probe-readiness")
        self.assertNotIn("private path", str(raised.exception))

    def test_seatbelt_probe_uses_the_request_snapshot_broker_lease(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value).resolve()
            probe_failure = RuntimeError("stop after checking probe arguments")
            with (
                patch(
                    "khaos.kernel.worker._path_for_directory_descriptor",
                    return_value=workspace,
                ),
                patch(
                    "khaos.kernel.worker._path_is_within",
                    side_effect=(False, False),
                ),
                patch(
                    "khaos.kernel.worker.probe_macos_seatbelt",
                    side_effect=probe_failure,
                ) as probe,
            ):
                with self.assertRaisesRegex(RuntimeError, "stop after"):
                    _run_workspace_command(
                        str(workspace),
                        5,
                        _RUNNER_SOURCE,
                        workspace_root_fd=123,
                        brokered_snapshot_mount_path="/private/tmp/lease/volume",
                        brokered_snapshot_storage_bytes=2_415_919_104,
                    )

        probe.assert_called_once_with(
            cancel_requested=None,
            brokered_snapshot_mount_path="/private/tmp/lease/volume",
            brokered_snapshot_storage_bytes=2_415_919_104,
        )

    def test_workspace_io_diagnostics_are_stage_only_and_path_free(self) -> None:
        def _path_is_within() -> None:
            raise OSError("/private/secret/workspace")

        try:
            _path_is_within()
        except OSError as error:
            code = _workspace_io_error_code(error)
        else:
            self.fail("the staged I/O failure was not raised")

        self.assertEqual(code, "workspace_rejected_io_ancestry")
        self.assertNotIn("/private/secret/workspace", code)

    def test_workspace_ancestry_io_diagnostics_identify_the_checked_direction(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value).resolve()
            workspace_fd = os.open(
                workspace,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                for results, expected in (
                    ([PermissionError("/private/workspace")], "kernel_in_workspace"),
                    ([False, PermissionError("/private/workspace")], "workspace_in_kernel"),
                ):
                    with self.subTest(stage=expected):
                        with (
                            patch("khaos.kernel.worker.probe_macos_seatbelt") as probe,
                            patch(
                                "khaos.kernel.worker._path_is_within",
                                side_effect=results,
                            ),
                        ):
                            with self.assertRaises(_WorkspaceAncestryIOError) as raised:
                                _run_workspace_command(
                                    workspace,
                                    5,
                                    _RUNNER_SOURCE,
                                    workspace_root_fd=workspace_fd,
                                )
                        self.assertEqual(
                            raised.exception.code,
                            f"workspace_rejected_io_{expected}",
                        )
                        probe.assert_not_called()
            finally:
                os.close(workspace_fd)

    def test_workspace_cancel_is_bound_to_the_active_request(self) -> None:
        read_fd, write_fd = os.pipe()
        cancellation = _WorkspaceCancellation("a" * 32, read_fd=read_fd)
        try:
            self.assertFalse(cancellation())
            send_frame(
                write_fd,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "b" * 32,
                    "operation": "workspace.cancel",
                    "payload": {"workspace_request_id": "a" * 32},
                },
            )
            self.assertTrue(cancellation())
            self.assertTrue(cancellation())
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_workspace_cancel_rejects_a_different_request(self) -> None:
        read_fd, write_fd = os.pipe()
        cancellation = _WorkspaceCancellation("a" * 32, read_fd=read_fd)
        try:
            send_frame(
                write_fd,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "b" * 32,
                    "operation": "workspace.cancel",
                    "payload": {"workspace_request_id": "c" * 32},
                },
            )
            with self.assertRaisesRegex(IPCProtocolError, "invalid"):
                cancellation()
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_rejects_invalid_kernel_execution_policy_before_probe_or_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            with (
                patch("khaos.kernel.worker.probe_macos_seatbelt") as probe,
                patch("khaos.kernel.worker.workspace_snapshot") as snapshot,
            ):
                with self.assertRaisesRegex(
                    SandboxedProcessError, "invalid_timeout"
                ):
                    _run_workspace_command(value, float("inf"), _RUNNER_SOURCE)
                with self.assertRaisesRegex(
                    WorkspaceSnapshotError, "workspace read scope"
                ):
                    _run_workspace_command(
                        value,
                        5,
                        _RUNNER_SOURCE,
                        workspace_read_scope=("../outside.txt",),
                    )
                with self.assertRaisesRegex(
                    WorkspaceSnapshotError, "trusted workspace root descriptor"
                ):
                    _run_workspace_command(value, 5, _RUNNER_SOURCE)

            probe.assert_not_called()
            snapshot.assert_not_called()

    def test_rejects_oversized_runner_source_before_probe_or_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            with (
                patch("khaos.kernel.worker.probe_macos_seatbelt") as probe,
                patch("khaos.kernel.worker.workspace_snapshot") as snapshot,
            ):
                with self.assertRaisesRegex(IPCProtocolError, "runner source"):
                    _run_workspace_command(
                        value,
                        5,
                        "#" * (MAX_RUNNER_SOURCE_BYTES + 1),
                    )

            probe.assert_not_called()
            snapshot.assert_not_called()

    def test_cancellation_before_preflight_skips_probe_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value).resolve()
            workspace_fd = os.open(
                workspace,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                with (
                    patch("khaos.kernel.worker.probe_macos_seatbelt") as probe,
                    patch("khaos.kernel.worker.workspace_snapshot") as snapshot,
                ):
                    with self.assertRaises(WorkspaceSnapshotCancelled):
                        _run_workspace_command(
                            workspace,
                            5,
                            _RUNNER_SOURCE,
                            workspace_root_fd=workspace_fd,
                            cancel_requested=lambda: True,
                        )

                probe.assert_not_called()
                snapshot.assert_not_called()
            finally:
                os.close(workspace_fd)

    def test_rejects_workspace_overlapping_kernel_installation(self) -> None:
        installation = Path(__file__).resolve().parents[1]
        with patch("khaos.kernel.worker.probe_macos_seatbelt") as probe:
            for workspace in (installation, installation / "khaos" / "kernel"):
                with self.subTest(workspace=workspace):
                    workspace_fd = os.open(
                        workspace,
                        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                    )
                    try:
                        with self.assertRaisesRegex(
                            WorkspaceSnapshotError, "overlaps the Kernel installation"
                        ):
                            _run_workspace_command(
                                workspace,
                                5,
                                _RUNNER_SOURCE,
                                workspace_root_fd=workspace_fd,
                            )
                    finally:
                        os.close(workspace_fd)
        probe.assert_not_called()

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS firmlinks")
    def test_rejects_workspace_mount_containing_kernel_through_firmlink(self) -> None:
        with patch("khaos.kernel.worker.probe_macos_seatbelt") as probe:
            workspace = Path("/System/Volumes/Data")
            workspace_fd = os.open(
                workspace,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                with self.assertRaisesRegex(
                    WorkspaceSnapshotError, "overlaps the Kernel installation"
                ):
                    _run_workspace_command(
                        workspace,
                        5,
                        _RUNNER_SOURCE,
                        workspace_root_fd=workspace_fd,
                    )
            finally:
                os.close(workspace_fd)
        probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
