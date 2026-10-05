from __future__ import annotations

import ctypes
import errno
import fcntl
import hashlib
import os
import plistlib
import re
import selectors
import secrets
import signal
import socket
import subprocess
import sys
import sysconfig
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from khaos.ipc import PROTOCOL_VERSION, receive_frame, send_frame
from khaos.kernel.macos_disk_image import (
    _DISKUTIL,
    _HDIUTIL,
    _attached_image_info,
    _run_tool,
    _validated_entities,
    _whole_image_device,
    mounted_apfs_volume,
)
from khaos.kernel.macos_seatbelt import (
    _COMMAND_FILE_SIZE_LIMIT,
    _COMMAND_OPEN_FILE_LIMIT,
    _COMMAND_PROCESS_COUNT_LIMIT_PER_UID,
    _MAX_SEATBELT_SCOPE_RULES,
    SANDBOX_EXECUTABLE,
    SandboxProbeIOError,
    SandboxedProcessError,
    SandboxUnavailable,
    _loopback_listener,
    _prove_host_loopback,
    _python_runtime_exclusions,
    _python_runtime_paths,
    _process_started_notification,
    _snapshot_profile,
    _sandbox_probe_io_stage,
    _seatbelt_probe_directory,
    _seatbelt_probe_snapshot,
    probe_macos_seatbelt,
    run_sandboxed_process,
)
from khaos.kernel.peer_identity import local_peer_pid_listener
from khaos.kernel.workspace_changes import commit_snapshot
from khaos.kernel.workspace_snapshot import (
    SnapshotEntry,
    WorkspaceReadScope,
    WorkspaceSnapshotCancelled,
    WorkspaceSnapshotError,
    WorkspaceSnapshot,
    WorkspaceWriteScope,
    workspace_snapshot,
)
from khaos.kernel.worker import _run_workspace_command
from khaos.launcher import _DEFAULT_RUNNER_SOURCE


def _direct_unmount(mount_point: Path) -> tuple[int, int]:
    libc = ctypes.CDLL(None, use_errno=True)
    unmount = libc.unmount
    unmount.argtypes = (ctypes.c_char_p, ctypes.c_int)
    unmount.restype = ctypes.c_int
    result = unmount(os.fsencode(mount_point), 0)
    return result, ctypes.get_errno()


class MacOSSeatbeltTests(unittest.TestCase):
    def test_loopback_os_permission_denials_are_tolerated_only(self) -> None:
        listener = MagicMock()
        listener.bind.side_effect = PermissionError(errno.EPERM, "denied")
        with patch(
            "khaos.kernel.macos_seatbelt.socket.socket",
            return_value=listener,
        ):
            self.assertIsNone(_loopback_listener())
        listener.close.assert_called_once_with()

        with patch(
            "khaos.kernel.macos_seatbelt.socket.create_connection",
            side_effect=PermissionError(errno.EACCES, "denied"),
        ):
            _prove_host_loopback(MagicMock())

        with patch(
            "khaos.kernel.macos_seatbelt.socket.socket",
            return_value=MagicMock(bind=Mock(side_effect=OSError(errno.EIO, "failed"))),
        ):
            with self.assertRaises(SandboxUnavailable):
                _loopback_listener()

    def test_probe_io_diagnostics_keep_only_a_fixed_stage(self) -> None:
        with self.assertRaises(SandboxProbeIOError) as raised:
            with _sandbox_probe_io_stage("fixture_files"):
                raise OSError("/private/secret/path")

        self.assertEqual(raised.exception.stage, "fixture_files")
        self.assertEqual(str(raised.exception), "fixture_files")
        self.assertNotIn("/private/secret/path", str(raised.exception))

        with self.assertRaisesRegex(ValueError, "I/O stage"):
            SandboxProbeIOError("secret-path")

    def test_probe_temporary_directory_errors_have_a_fixed_stage(self) -> None:
        with patch(
            "khaos.kernel.macos_seatbelt.tempfile.TemporaryDirectory",
            side_effect=PermissionError("/private/secret/temp"),
        ):
            with self.assertRaises(SandboxProbeIOError) as raised:
                with _seatbelt_probe_directory():
                    self.fail("temporary directory creation unexpectedly succeeded")

        self.assertEqual(raised.exception.stage, "temporary_create")
        self.assertNotIn("/private/secret/temp", str(raised.exception))

    def test_probe_temporary_directory_uses_kernel_temporary_storage(self) -> None:
        temporary = MagicMock()
        temporary.__enter__.return_value = "/private/kernel-container/tmp/probe"
        with patch(
            "khaos.kernel.macos_seatbelt.tempfile.TemporaryDirectory",
            return_value=temporary,
        ) as create_temporary_directory:
            with _seatbelt_probe_directory():
                pass

        create_temporary_directory.assert_called_once_with(
            prefix="khaos-seatbelt-probe-",
            dir=None,
        )

    def test_probe_temporary_directory_uses_broker_lease_parent(self) -> None:
        parent = Path("/private/kernel-container/tmp/khaos-snapshot-broker-lease")
        temporary = MagicMock()
        temporary.__enter__.return_value = str(parent / "probe")
        with patch(
            "khaos.kernel.macos_seatbelt.tempfile.TemporaryDirectory",
            return_value=temporary,
        ) as create_temporary_directory:
            with _seatbelt_probe_directory(parent):
                pass

        create_temporary_directory.assert_called_once_with(
            prefix="khaos-seatbelt-probe-",
            dir=parent,
        )

    def test_probe_snapshot_failure_is_sanitized_but_cancellation_is_preserved(
        self,
    ) -> None:
        failed_snapshot = MagicMock()
        failed_snapshot.__enter__.side_effect = WorkspaceSnapshotError(
            "/private/secret/workspace"
        )
        with self.assertRaises(SandboxUnavailable) as raised:
            with _seatbelt_probe_snapshot(failed_snapshot):
                self.fail("failed snapshot unexpectedly succeeded")
        self.assertNotIn("/private/secret/workspace", str(raised.exception))
        self.assertEqual(raised.exception.diagnostic_stage, "probe-snapshot")

        cancelled_snapshot = MagicMock()
        cancelled_snapshot.__enter__.side_effect = WorkspaceSnapshotCancelled()
        with self.assertRaises(WorkspaceSnapshotCancelled):
            with _seatbelt_probe_snapshot(cancelled_snapshot):
                self.fail("cancelled snapshot unexpectedly succeeded")

        entered_snapshot = MagicMock()
        entered_snapshot.__enter__.return_value = object()
        with self.assertRaisesRegex(
            WorkspaceSnapshotError, "commit failed inside probe"
        ):
            with _seatbelt_probe_snapshot(entered_snapshot):
                raise WorkspaceSnapshotError("commit failed inside probe")

    def test_probe_temporary_cleanup_errors_have_a_fixed_stage(self) -> None:
        temporary = Mock()
        temporary.__enter__ = Mock(return_value="/private/secret/temp")
        temporary.cleanup.side_effect = PermissionError("/private/secret/temp")
        with patch(
            "khaos.kernel.macos_seatbelt.tempfile.TemporaryDirectory",
            return_value=temporary,
        ):
            with self.assertRaises(SandboxProbeIOError) as raised:
                with _seatbelt_probe_directory():
                    pass

        self.assertEqual(raised.exception.stage, "temporary_cleanup")
        self.assertNotIn("/private/secret/temp", str(raised.exception))

    def test_probe_honors_cancellation_before_host_setup(self) -> None:
        with self.assertRaises(SandboxedProcessError) as raised:
            probe_macos_seatbelt(cancel_requested=lambda: True)
        self.assertEqual(raised.exception.code, "process_cancelled")

    def test_python_runtime_scope_excludes_prefix_and_installed_packages(self) -> None:
        runtime_paths = _python_runtime_paths()
        executable = Path(sys.executable).resolve(strict=True)
        prefix = Path(sys.prefix).resolve(strict=True)
        stdlib = Path(sysconfig.get_path("stdlib")).resolve(strict=True)

        self.assertIn(executable, runtime_paths)
        self.assertIn(stdlib, runtime_paths)
        self.assertNotIn(prefix, runtime_paths)
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value).resolve()
            profile = _snapshot_profile(
                workspace,
                runtime_paths,
                executable=executable,
            )
        for excluded in _python_runtime_exclusions():
            self.assertIn(
                f'(deny file-read* (subpath "{excluded}"))', profile
            )

    def test_process_read_scope_blocks_moves_of_unreadable_baseline_entries(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value).resolve() / "workspace"
            (workspace / "nested").mkdir(parents=True)
            (workspace / "private-tree").mkdir()
            executable = Path(sys.executable).resolve(strict=True)
            baseline = {
                (): SnapshotEntry("directory", 0o700, ()),
                ("nested",): SnapshotEntry("directory", 0o700, ()),
                ("nested", "allowed.txt"): SnapshotEntry("file", 0o600, ()),
                ("nested", "private.txt"): SnapshotEntry("file", 0o600, ()),
                ("private-tree",): SnapshotEntry("directory", 0o700, ()),
                ("private-tree", "child.txt"): SnapshotEntry("file", 0o600, ()),
            }
            profile = _snapshot_profile(
                workspace,
                _python_runtime_paths(),
                executable=executable,
                allow_process_exec=True,
                workspace_read_scope=WorkspaceReadScope.from_paths(
                    ("nested/allowed.txt",)
                ),
                workspace_baseline=baseline,
            )
            empty_scope_profile = _snapshot_profile(
                workspace,
                _python_runtime_paths(),
                executable=executable,
                allow_process_exec=True,
            )

        allowed = workspace / "nested" / "allowed.txt"
        private = workspace / "nested" / "private.txt"
        nested = workspace / "nested"
        private_tree = workspace / "private-tree"
        self.assertIn(f'(allow file-read* (literal "{allowed}"))', profile)
        self.assertIn(
            f'(deny file-write-unlink (literal "{nested}"))',
            profile,
        )
        self.assertIn(
            f'(deny file-write-unlink (literal "{private}"))', profile
        )
        self.assertIn(
            f'(deny file-write-unlink (subpath "{private_tree}"))', profile
        )
        self.assertNotIn(
            f'(deny file-write-unlink (subpath "{workspace}"))', profile
        )
        broad_write = (
            f'(allow file-write-data file-write-create file-write-unlink '
            f'(subpath "{workspace}"))'
        )
        nested_guard = f'(deny file-write-unlink (literal "{nested}"))'
        self.assertLess(profile.index(broad_write), profile.rindex(nested_guard))
        self.assertIn(
            f'(deny file-write-unlink (subpath "{workspace}"))',
            empty_scope_profile,
        )

    def test_python_framework_library_is_scoped_without_its_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            prefix = root / "Python.framework" / "Versions" / "3.13"
            executable = prefix / "bin" / "python3.13"
            executable.parent.mkdir(parents=True)
            executable.touch()
            framework_library = prefix / "Python"
            framework_library.touch()
            stdlib = root / "stdlib"
            stdlib.mkdir()
            config = {
                "DESTSHARED": None,
                "LDLIBRARY": None,
                "LIBDIR": None,
                "PYTHONFRAMEWORKPREFIX": str(root / "system-frameworks"),
                "PYTHONFRAMEWORKDIR": "Python.framework",
                "PYTHONFRAMEWORK": "Python",
                "VERSION": "3.13",
            }
            with (
                patch("sys.executable", str(executable)),
                patch("sys.prefix", str(prefix)),
                patch("sys.base_prefix", str(prefix)),
                patch("sysconfig.get_path", return_value=str(stdlib)),
                patch("sysconfig.get_config_var", side_effect=config.get),
            ):
                runtime_paths = _python_runtime_paths()

        self.assertIn(framework_library.resolve(), runtime_paths)
        self.assertNotIn(prefix.resolve(), runtime_paths)

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_runner_cannot_read_python_installation_siblings(self) -> None:
        executable = Path(sys.executable).resolve(strict=True)
        runtime_paths = _python_runtime_paths()
        stdlib = Path(sysconfig.get_path("stdlib")).resolve(strict=True)
        denied_paths = []

        include_path = sysconfig.get_config_var("INCLUDEPY")
        if isinstance(include_path, str) and include_path:
            header = Path(include_path) / "pyconfig.h"
            if header.is_file():
                denied_paths.append(header.resolve(strict=True))

        site_packages_alias = stdlib / "site-packages"
        if site_packages_alias.is_dir():
            denied_paths.append(site_packages_alias)

        if not denied_paths:
            self.skipTest("this Python installation has no sibling read fixture")
        for path in denied_paths:
            if path.is_dir():
                tuple(path.iterdir())
            else:
                path.read_bytes()

        with tempfile.TemporaryDirectory() as value:
            scratch = Path(value).resolve()
            profile = _snapshot_profile(
                scratch,
                runtime_paths,
                executable=executable,
                allow_workspace_write=False,
            )
            script = """\
import errno
from pathlib import Path
import sys

for value in sys.argv[1:]:
    path = Path(value)
    try:
        tuple(path.iterdir()) if path.is_dir() else path.read_bytes()
    except OSError as exc:
        if exc.errno not in (errno.EPERM, errno.EACCES):
            raise SystemExit(f"unexpected error: {exc.errno}")
    else:
        raise SystemExit(f"read unexpectedly allowed: {path}")
"""
            result = subprocess.run(
                (
                    str(SANDBOX_EXECUTABLE),
                    "-p",
                    profile,
                    str(executable),
                    "-I",
                    "-S",
                    "-c",
                    script,
                    *(str(path) for path in denied_paths),
                ),
                cwd=scratch,
                env={
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                    "HOME": str(scratch),
                    "TMPDIR": str(scratch),
                    "LC_ALL": "C",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS process semantics")
    def test_process_start_event_precedes_exec_and_popen_return(self) -> None:
        read_fd, write_fd = os.pipe()
        request_id = "a" * 32
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                ("/bin/sleep", "10"),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                pass_fds=(write_fd,),
                start_new_session=True,
                preexec_fn=_process_started_notification(write_fd, request_id),
            )
            send_frame(
                write_fd,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": request_id,
                    "event": "popen_returned",
                    "payload": {},
                },
            )

            started = receive_frame(read_fd, timeout_seconds=2)
            returned = receive_frame(read_fd, timeout_seconds=2)
            self.assertEqual(started["event"], "process_started")
            self.assertEqual(started["request_id"], request_id)
            group_id = int(started["payload"]["process_group_id"], 16)
            self.assertEqual(group_id, process.pid)
            self.assertEqual(os.getpgid(process.pid), group_id)
            self.assertEqual(returned["event"], "popen_returned")
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            os.close(read_fd)
            os.close(write_fd)

    def test_process_lifecycle_reporting_rejects_partial_configuration(self) -> None:
        snapshot = WorkspaceSnapshot(
            source_root=Path("/source"),
            path=Path("/snapshot"),
            source_mount_point="/source",
            snapshot_mount_point="/snapshot",
            storage_limit_bytes=1,
            baseline={},
            max_entries=1,
            max_bytes=1,
            max_depth=1,
        )
        read_fd, write_fd = os.pipe()
        request_id = "a" * 32
        finished_process_groups: list[int] = []
        finish = finished_process_groups.append
        incomplete_options = (
            {"workspace_request_id": request_id},
            {"process_started_fd": write_fd},
            {"process_finished": finish},
            {"process_started_fd": write_fd, "workspace_request_id": request_id},
            {
                "process_started_fd": write_fd,
                "workspace_request_id": request_id,
                "process_finished": object(),
            },
        )
        try:
            with patch("khaos.kernel.macos_seatbelt.sys.platform", "darwin"):
                for options in incomplete_options:
                    with self.subTest(options=tuple(options)):
                        with self.assertRaisesRegex(
                            SandboxedProcessError, "sandbox_execution_failed"
                        ):
                            run_sandboxed_process(
                                snapshot,
                                ["/usr/bin/true"],
                                timeout_seconds=1,
                                **options,
                            )
            self.assertEqual(finished_process_groups, [])
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_profile_scopes_snapshot_writes_and_denies_network(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value).resolve()
            runtime_roots = (SANDBOX_EXECUTABLE.parent,)
            executable = Path(sys.executable).resolve(strict=True)
            profile = _snapshot_profile(
                workspace, runtime_roots, executable=executable
            )

        self.assertIn("(deny file-write*)", profile)
        self.assertNotIn("(allow signal", profile)
        self.assertIn("(deny process-info*)", profile)
        self.assertIn("(allow process-info* (target self))", profile)
        self.assertNotIn("(allow sysctl-read)", profile)
        self.assertIn(
            "(deny syscall-unix (syscall-number SYS_mount))", profile
        )
        self.assertIn(
            "(deny syscall-unix (syscall-number SYS_unmount))", profile
        )
        self.assertIn(
            "(deny syscall-unix (syscall-number SYS_setsid))", profile
        )
        self.assertIn(
            "(deny syscall-unix (syscall-number SYS_setpgid))", profile
        )
        self.assertIn(
            f'(allow process-exec (literal "{executable}"))', profile
        )
        framework_executable = (
            Path(sys.prefix).resolve(strict=True)
            / "Resources"
            / "Python.app"
            / "Contents"
            / "MacOS"
            / "Python"
        )
        if framework_executable.is_file():
            self.assertIn(
                "(allow process-exec (literal \""
                f"{framework_executable.resolve(strict=True)}\"))",
                profile,
            )
        self.assertNotIn("(allow process-exec)", profile)
        self.assertNotIn("(allow process-fork", profile)
        self.assertIn(
            f'(allow file-write-data file-write-create file-write-unlink '
            f'(subpath "{workspace}"))',
            profile,
        )
        self.assertNotIn("(allow file-write*", profile)
        self.assertIn("(deny network*)", profile)

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_runner_profile_denies_kern_procargs2_for_known_command_pid(self) -> None:
        marker = "--khaos-argv-boundary-probe"
        secret = secrets.token_hex(24)
        expected_digest = hashlib.sha256(secret.encode()).hexdigest()
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            workspace = root / "workspace"
            workspace.mkdir()
            executable = Path(sys.executable).resolve(strict=True)
            runtime_paths = _python_runtime_paths()
            command_profile = _snapshot_profile(
                workspace,
                runtime_paths,
                executable=executable,
                allow_same_sandbox_signals=True,
                allow_process_fork=True,
                allow_process_exec=True,
            )
            runner_profile = _snapshot_profile(
                workspace,
                runtime_paths,
                executable=executable,
                allow_workspace_write=False,
            )
            environment = {
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "HOME": str(root),
                "TMPDIR": str(root),
                "LC_ALL": "C",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            command = subprocess.Popen(
                (
                    str(SANDBOX_EXECUTABLE),
                    "-p",
                    command_profile,
                    str(executable),
                    "-I",
                    "-S",
                    "-c",
                    "import time; time.sleep(10)",
                    marker,
                    secret,
                ),
                cwd=workspace,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
            try:
                libc = ctypes.CDLL(None, use_errno=True)
                sysctl = libc.sysctl
                sysctl.argtypes = (
                    ctypes.POINTER(ctypes.c_int),
                    ctypes.c_uint,
                    ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_size_t),
                    ctypes.c_void_p,
                    ctypes.c_size_t,
                )
                sysctl.restype = ctypes.c_int
                mib = (ctypes.c_int * 3)(1, 49, command.pid)
                size = ctypes.c_size_t(0)
                self.assertEqual(
                    sysctl(mib, 3, None, ctypes.byref(size), None, 0), 0
                )
                self.assertGreater(size.value, 0)
                host_args = ctypes.create_string_buffer(size.value)
                self.assertEqual(
                    sysctl(
                        mib,
                        3,
                        host_args,
                        ctypes.byref(size),
                        None,
                        0,
                    ),
                    0,
                )
                host_argv = host_args.raw[:size.value].split(bytes([0]))
                marker_index = host_argv.index(marker.encode())
                self.assertEqual(
                    hashlib.sha256(host_argv[marker_index + 1]).hexdigest(),
                    expected_digest,
                )

                runner_probe = f'''\\
import ctypes
import errno
import hashlib
import sys

pid = int(sys.argv[1])
marker = sys.argv[2].encode()
expected_digest = sys.argv[3]
libc = ctypes.CDLL(None, use_errno=True)
sysctl = libc.sysctl
sysctl.argtypes = (
    ctypes.POINTER(ctypes.c_int), ctypes.c_uint, ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t,
)
sysctl.restype = ctypes.c_int
mib = (ctypes.c_int * 3)(1, 49, pid)
size = ctypes.c_size_t(0)
if sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0:
    raise SystemExit(0 if ctypes.get_errno() in (errno.EPERM, errno.EACCES) else 91)
if size.value <= 0:
    raise SystemExit(92)
data = ctypes.create_string_buffer(size.value)
if sysctl(mib, 3, data, ctypes.byref(size), None, 0) != 0:
    raise SystemExit(0 if ctypes.get_errno() in (errno.EPERM, errno.EACCES) else 93)
arguments = data.raw[:size.value].split(bytes([0]))
for index, argument in enumerate(arguments[:-1]):
    if argument == marker:
        if hashlib.sha256(arguments[index + 1]).hexdigest() == expected_digest:
            raise SystemExit(94)
        raise SystemExit(95)
raise SystemExit(96)
'''
                probe = subprocess.run(
                    (
                        str(SANDBOX_EXECUTABLE),
                        "-p",
                        runner_profile,
                        str(executable),
                        "-I",
                        "-S",
                        "-c",
                        runner_probe,
                        str(command.pid),
                        marker,
                        expected_digest,
                    ),
                    cwd=workspace,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=5,
                    text=True,
                )
            finally:
                if command.poll() is None:
                    command.send_signal(signal.SIGKILL)
                command.wait(timeout=5)

        self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)
        self.assertEqual(probe.stdout, "")
        self.assertEqual(probe.stderr, "")

    def test_command_profile_allows_exec_only_with_snapshot_and_scratch_scope(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            workspace = root / "workspace"
            scratch = root / "scratch"
            workspace.mkdir()
            scratch.mkdir()
            executable = Path(sys.executable).resolve(strict=True)
            profile = _snapshot_profile(
                workspace,
                _python_runtime_paths(),
                executable=executable,
                allow_same_sandbox_signals=True,
                allow_process_fork=True,
                allow_process_exec=True,
                additional_writable_roots=(scratch,),
            )

        self.assertIn("(allow process-fork)", profile)
        self.assertIn("(allow process-exec)", profile)
        self.assertIn("(allow signal (target same-sandbox))", profile)
        self.assertIn(f'(subpath "{workspace}")', profile)
        self.assertIn(f'(subpath "{scratch}")', profile)
        self.assertIn(
            f'(allow file-write-data file-write-create file-write-unlink '
            f'(subpath "{scratch}"))',
            profile,
        )
        self.assertNotIn(
            f'(allow file-write* (subpath "{scratch}"))', profile
        )
        self.assertIn("(deny network*)", profile)
        self.assertIn(
            "(deny syscall-unix (syscall-number SYS_setsid))", profile
        )
        self.assertIn(
            "(deny syscall-unix (syscall-number SYS_setpgid))", profile
        )
        self.assertIn(
            "(deny syscall-unix (syscall-number SYS_mount))", profile
        )
        self.assertIn(
            "(deny syscall-unix (syscall-number SYS_unmount))", profile
        )

    def test_profile_rejects_invalid_signal_policy(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            with self.assertRaisesRegex(
                SandboxUnavailable, "sandbox signal policy is invalid"
            ):
                _snapshot_profile(
                    Path(value).resolve(),
                    (),
                    executable=Path(sys.executable).resolve(strict=True),
                    allow_same_sandbox_signals=1,
                )

    def test_workspace_commit_profile_scopes_writes_to_entries_and_staging(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            workspace = root / "workspace"
            staging = root / "staging"
            changed = workspace / "changed.txt"
            workspace.mkdir()
            staging.mkdir(mode=0o700)
            profile = _snapshot_profile(
                workspace,
                _python_runtime_paths(),
                executable=Path(sys.executable).resolve(strict=True),
                allow_workspace_write=False,
                workspace_write_paths=(("changed.txt",),),
                workspace_create_unlink_paths=((),),
                allow_additional_full_write=True,
                additional_writable_roots=(staging,),
            )

        self.assertIn(
            f'(allow file-write* (literal "{changed}"))',
            profile,
        )
        self.assertNotIn(
            f'(allow file-write* (subpath "{workspace}"))', profile
        )
        self.assertIn(
            f'(allow file-write-create file-write-unlink (literal "{workspace}"))',
            profile,
        )
        self.assertIn(
            f'(allow file-write* (subpath "{staging}"))', profile
        )
        self.assertIn(
            f'(allow file-read-data (literal "{workspace.parent}"))', profile
        )
        self.assertIn(
            f'(allow file-write-flags (literal "{staging}"))', profile
        )
        self.assertNotIn(
            f'(allow file-write* (subpath "{root}"))', profile
        )

    def test_workspace_commit_profile_scopes_reads_and_writes_to_changeset(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            workspace = root / "workspace"
            workspace.mkdir()
            file_write_paths = (
                ("nested", "changed.txt"),
                ("nested", ".khaos-random.tmp"),
            )
            create_unlink_paths = ((), ("nested",))
            profile = _snapshot_profile(
                workspace,
                _python_runtime_paths(),
                executable=Path(sys.executable).resolve(strict=True),
                allow_workspace_write=False,
                workspace_write_paths=file_write_paths,
                workspace_create_unlink_paths=create_unlink_paths,
            )

        for path in file_write_paths:
            literal = workspace.joinpath(*path)
            self.assertIn(
                f'(allow file-write* (literal "{literal}"))', profile
            )
            self.assertIn(
                f'(allow file-read* (literal "{literal}"))', profile
            )
        for path in create_unlink_paths:
            literal = workspace.joinpath(*path)
            self.assertIn(
                f'(allow file-write-create file-write-unlink '
                f'(literal "{literal}"))',
                profile,
            )
            self.assertIn(
                f'(allow file-read* (literal "{literal}"))', profile
            )
        for directory in (workspace, workspace / "nested"):
            self.assertIn(
                f'(allow file-read-data (literal "{directory}"))', profile
            )
        self.assertNotIn(
            f'(allow file-read* (subpath "{workspace}"))', profile
        )
        self.assertNotIn(
            f'(allow file-write* (subpath "{workspace}"))', profile
        )
        self.assertIn("(deny file-write*)", profile)

    def test_workspace_commit_profile_rejects_oversized_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value).resolve()
            executable = Path(sys.executable).resolve(strict=True)
            oversized_scopes = (
                tuple(
                    (f"file-{index}",)
                    for index in range(_MAX_SEATBELT_SCOPE_RULES + 1)
                ),
                tuple((f"x" * 2048 + str(index),) for index in range(600)),
            )
            for paths in oversized_scopes:
                with self.subTest(path_count=len(paths)):
                    with self.assertRaisesRegex(
                        SandboxUnavailable, "scope exceeds limit"
                    ):
                        _snapshot_profile(
                            workspace,
                            _python_runtime_paths(),
                            executable=executable,
                            allow_workspace_write=False,
                            workspace_write_paths=paths,
                        )

    def test_profile_rejects_writable_roots_overlapping_readable_kernel_paths(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            workspace = root / "workspace"
            package = root / "khaos"
            nested_scratch = package / "scratch"
            workspace.mkdir()
            nested_scratch.mkdir(parents=True)
            kernel_file = package / "kernel.py"
            kernel_file.write_text("kernel", encoding="utf-8")
            executable = Path(sys.executable).resolve(strict=True)

            with self.subTest("writable child of a readable package"):
                with self.assertRaisesRegex(
                    SandboxUnavailable, "overlaps a read-only path"
                ):
                    _snapshot_profile(
                        workspace,
                        _python_runtime_paths(),
                        executable=executable,
                        additional_writable_roots=(nested_scratch,),
                        readable_paths=(package,),
                    )

            with self.subTest("writable parent of a readable module"):
                with self.assertRaisesRegex(
                    SandboxUnavailable, "overlaps a read-only path"
                ):
                    _snapshot_profile(
                        workspace,
                        _python_runtime_paths(),
                        executable=executable,
                        additional_writable_roots=(package,),
                        readable_paths=(kernel_file,),
                    )

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_runner_sandbox_cannot_access_workspace_snapshot_or_user_home(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            home_fixture = tempfile.TemporaryDirectory(
                prefix="khaos-runner-home-", dir=Path.home()
            )
            self.addCleanup(home_fixture.cleanup)
            snapshot = root / "snapshot"
            scratch = root / "runner-scratch"
            live_workspace = root / "live-workspace"
            user_home = Path(home_fixture.name)
            kernel_package = root / "khaos"
            kernel_directory = kernel_package / "kernel"
            snapshot.mkdir()
            scratch.mkdir()
            live_workspace.mkdir()
            kernel_directory.mkdir(parents=True)
            secret = snapshot / "workspace-secret.txt"
            secret.write_text("snapshot data", encoding="utf-8")
            live_workspace_secret = live_workspace / "workspace-secret.txt"
            live_workspace_secret.write_text("live workspace data", encoding="utf-8")
            home_secret = user_home / "secret.txt"
            home_secret.write_text("home secret", encoding="utf-8")
            kernel_module = kernel_directory / "worker.py"
            kernel_module.write_text("trusted module", encoding="utf-8")
            snapshot_canary = snapshot / "runner-canary.txt"
            live_workspace_canary = live_workspace / "runner-canary.txt"
            home_canary = user_home / "runner-canary.txt"
            outside_canary = root / "outside-canary"
            scratch_canary = scratch / "runner-canary.txt"
            control = root / "outside-control.txt"
            scratch_control = scratch / "outside-control.txt"
            control.write_text("writable", encoding="utf-8")
            scratch_control.write_text("writable", encoding="utf-8")
            self.assertEqual(secret.read_text(encoding="utf-8"), "snapshot data")
            self.assertEqual(
                live_workspace_secret.read_text(encoding="utf-8"),
                "live workspace data",
            )
            control.unlink()
            scratch_control.unlink()

            executable = Path(sys.executable).resolve(strict=True)
            script = """\
from pathlib import Path
import sys

try:
    Path(sys.argv[1]).read_text(encoding="utf-8")
except OSError:
    print("snapshot read denied")
else:
    print("snapshot read allowed")

try:
    Path(sys.argv[2]).write_text("escaped", encoding="utf-8")
except OSError:
    print("snapshot write denied")
else:
    print("snapshot write allowed")

try:
    Path(sys.argv[3]).write_text("escaped", encoding="utf-8")
except OSError:
    print("runner scratch write denied")
else:
    print("runner scratch write allowed")

try:
    Path(sys.argv[4]).write_text("escaped", encoding="utf-8")
except OSError:
    print("outside write denied")
else:
    print("outside write allowed")

try:
    Path(sys.argv[5]).write_text("attacker", encoding="utf-8")
except OSError:
    print("readable Kernel path write denied")
else:
    print("readable Kernel path write allowed")

try:
    Path(sys.argv[6]).read_text(encoding="utf-8")
except OSError:
    print("live workspace read denied")
else:
    print("live workspace read allowed")

try:
    Path(sys.argv[7]).write_text("escaped", encoding="utf-8")
except OSError:
    print("live workspace write denied")
else:
    print("live workspace write allowed")

try:
    Path(sys.argv[8]).read_text(encoding="utf-8")
except OSError:
    print("user home read denied")
else:
    print("user home read allowed")

try:
    Path(sys.argv[9]).write_text("escaped", encoding="utf-8")
except OSError:
    print("user home write denied")
else:
    print("user home write allowed")
"""
            with local_peer_pid_listener(scratch) as (_, peer_socket_path):
                profile = _snapshot_profile(
                    scratch,
                    _python_runtime_paths(),
                    executable=executable,
                    allow_workspace_write=False,
                    additional_unix_socket_paths=(peer_socket_path,),
                    readable_paths=(kernel_package, kernel_directory, kernel_module),
                )
                result = subprocess.run(
                    (
                        str(SANDBOX_EXECUTABLE),
                        "-p",
                        profile,
                        str(executable),
                        "-I",
                        "-S",
                        "-c",
                        script,
                        str(secret),
                        str(snapshot_canary),
                        str(scratch_canary),
                        str(outside_canary),
                        str(kernel_module),
                        str(live_workspace_secret),
                        str(live_workspace_canary),
                        str(home_secret),
                        str(home_canary),
                    ),
                    cwd=scratch,
                    env={
                        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                        "HOME": str(scratch),
                        "TMPDIR": str(scratch),
                        "LC_ALL": "C",
                        "PYTHONDONTWRITEBYTECODE": "1",
                    },
                    close_fds=True,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout,
                "snapshot read denied\nsnapshot write denied\n"
                "runner scratch write denied\noutside write denied\n"
                "readable Kernel path write denied\n"
                "live workspace read denied\nlive workspace write denied\n"
                "user home read denied\nuser home write denied\n",
            )
            self.assertFalse(snapshot_canary.exists())
            self.assertFalse(live_workspace_canary.exists())
            self.assertFalse(home_canary.exists())
            self.assertFalse(scratch_canary.exists())
            self.assertFalse(outside_canary.exists())
            self.assertEqual(
                live_workspace_secret.read_text(encoding="utf-8"),
                "live workspace data",
            )
            self.assertEqual(home_secret.read_text(encoding="utf-8"), "home secret")
            self.assertEqual(
                kernel_module.read_text(encoding="utf-8"), "trusted module"
            )

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_forked_children_cannot_escape_the_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value).resolve()
            executable = Path(sys.executable).resolve(strict=True)
            profile = _snapshot_profile(
                workspace,
                _python_runtime_paths(),
                executable=executable,
                allow_process_fork=True,
            )

            script = """\
import errno
import os

def require_denied(action, failure):
    pid = os.fork()
    if pid == 0:
        try:
            action()
        except OSError as exc:
            os._exit(0 if exc.errno in (errno.EPERM, errno.EACCES) else failure)
        os._exit(failure)
    _, status = os.waitpid(pid, 0)
    if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
        raise SystemExit(failure)

require_denied(os.setsid, 41)
require_denied(lambda: os.setpgid(0, 0), 42)
"""
            result = subprocess.run(
                (
                    str(SANDBOX_EXECUTABLE),
                    "-p",
                    profile,
                    str(executable),
                    "-I",
                    "-S",
                    "-c",
                    script,
                ),
                cwd=workspace,
                env={
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                capture_output=True,
                timeout=5,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_killing_sandbox_process_group_closes_descendant_pipe(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value).resolve()
            executable = Path(sys.executable).resolve(strict=True)
            profile = _snapshot_profile(
                workspace,
                _python_runtime_paths(),
                executable=executable,
                allow_process_fork=True,
            )
            script = """\
import os
import sys
import time

pid = os.fork()
if pid == 0:
    while True:
        time.sleep(1)
sys.stdout.write("READY\\n")
sys.stdout.flush()
while True:
    time.sleep(1)
"""
            process = subprocess.Popen(
                (
                    str(SANDBOX_EXECUTABLE),
                    "-p",
                    profile,
                    str(executable),
                    "-I",
                    "-S",
                    "-c",
                    script,
                ),
                cwd=workspace,
                env={
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
            try:
                self.assertIsNotNone(process.stdout)
                self.assertEqual(os.getpgid(process.pid), process.pid)
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    self.assertTrue(selector.select(5), "Runner did not become ready")
                    self.assertEqual(process.stdout.readline(), b"READY\n")
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                    self.assertTrue(
                        selector.select(1),
                        "a sandbox descendant retained the output pipe after group kill",
                    )
                    self.assertEqual(process.stdout.read(), b"")
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                if process.poll() is None:
                    process.wait(timeout=5)
                if process.stdout is not None:
                    process.stdout.close()

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_sandboxed_command_writes_only_the_trusted_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            original = source / "original.txt"
            original.write_text("unchanged", encoding="utf-8")
            outside = root / "outside.txt"
            outside.write_text("protected", encoding="utf-8")
            (source / "escape.txt").symlink_to(outside)
            script = """\
import errno
import os
import sys
from pathlib import Path

Path("command-output.txt").write_text("snapshot-only")
for path in (Path(sys.argv[1]), Path("escape.txt")):
    for action in (path.read_text, lambda: path.write_text("escaped")):
        try:
            action()
        except OSError as exc:
            if exc.errno not in (errno.EPERM, errno.EACCES):
                raise
        else:
            raise SystemExit(22)
print(os.environ.get("KHAOS_SECRET", "missing"))
"""
            with workspace_snapshot(source) as snapshot:
                with patch.dict(os.environ, {"KHAOS_SECRET": "host-secret"}):
                    result = run_sandboxed_process(
                        snapshot,
                        [
                            str(Path(sys.executable).resolve()),
                            "-I",
                            "-S",
                            "-c",
                            script,
                            str(outside),
                        ],
                        timeout_seconds=5,
                    )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "missing\n")
                self.assertEqual(
                    (snapshot.path / "command-output.txt").read_text(),
                    "snapshot-only",
                )

            self.assertEqual(original.read_text(encoding="utf-8"), "unchanged")
            self.assertEqual(outside.read_text(encoding="utf-8"), "protected")

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_sandboxed_command_and_runner_cannot_relax_their_sandboxes(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            outside = root / "outside-canary"
            permissive_profile = "(version 1)(allow default)"
            python = str(Path(sys.executable).resolve(strict=True))
            sandbox_init_script = """\
import ctypes
import sys
from pathlib import Path

library = ctypes.CDLL("/usr/lib/libsandbox.dylib")
apply = library.sandbox_init
apply.argtypes = (ctypes.c_char_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_char_p))
apply.restype = ctypes.c_int
free_error = library.sandbox_free_error
free_error.argtypes = (ctypes.c_void_p,)
free_error.restype = None
error = ctypes.c_char_p()
status = apply(sys.argv[1].encode("utf-8"), 0, ctypes.byref(error))
if status != 0:
    message = error.value.decode("utf-8", "replace") if error.value else "sandbox_init failed"
    print(message)
    if error.value is not None:
        free_error(ctypes.cast(error, ctypes.c_void_p))
    raise SystemExit(0)
Path(sys.argv[2]).write_text("escaped", encoding="utf-8")
print("sandbox applied")
"""
            subprocess.run(
                [
                    str(SANDBOX_EXECUTABLE),
                    "-p",
                    permissive_profile,
                    "/usr/bin/true",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            direct_api_control = root / "sandbox-init-control"
            control_result = subprocess.run(
                [
                    python,
                    "-I",
                    "-S",
                    "-c",
                    sandbox_init_script,
                    permissive_profile,
                    str(direct_api_control),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(control_result.stdout, "sandbox applied\n")
            self.assertEqual(direct_api_control.read_text(encoding="utf-8"), "escaped")

            with workspace_snapshot(source) as snapshot:
                result = run_sandboxed_process(
                    snapshot,
                    [
                        str(SANDBOX_EXECUTABLE),
                        "-p",
                        permissive_profile,
                        "/usr/bin/touch",
                        str(outside),
                    ],
                    timeout_seconds=5,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("sandbox_apply", result.stderr)
                self.assertIn("Operation not permitted", result.stderr)
                self.assertFalse(outside.exists())
                direct_api_result = run_sandboxed_process(
                    snapshot,
                    [
                        python,
                        "-I",
                        "-S",
                        "-c",
                        sandbox_init_script,
                        permissive_profile,
                        str(outside),
                    ],
                    timeout_seconds=5,
                )
                self.assertEqual(
                    direct_api_result.returncode,
                    0,
                    direct_api_result.stderr,
                )
                self.assertIn("Operation not permitted", direct_api_result.stdout)
                self.assertFalse(outside.exists())

            runner_scratch = root / "runner-scratch"
            runner_scratch.mkdir()
            runner_outside = root / "runner-outside-canary"
            with local_peer_pid_listener(runner_scratch) as (_, peer_socket_path):
                runner_profile = _snapshot_profile(
                    runner_scratch,
                    _python_runtime_paths(),
                    executable=Path(python),
                    allow_workspace_write=False,
                    additional_unix_socket_paths=(peer_socket_path,),
                )
                runner_result = subprocess.run(
                    [
                        str(SANDBOX_EXECUTABLE),
                        "-p",
                        runner_profile,
                        python,
                        "-I",
                        "-S",
                        "-c",
                        sandbox_init_script,
                        permissive_profile,
                        str(runner_outside),
                    ],
                    cwd=runner_scratch,
                    env={
                        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                        "HOME": str(runner_scratch),
                        "TMPDIR": str(runner_scratch),
                        "LC_ALL": "C",
                        "PYTHONDONTWRITEBYTECODE": "1",
                    },
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            self.assertIn("Operation not permitted", runner_result.stdout)
            self.assertFalse(runner_outside.exists())
            self.assertFalse(outside.exists())

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_commit_sandbox_denies_dirfd_write_after_parent_moves_out(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            workspace = root / "workspace"
            nested = workspace / "nested"
            staging = root / "staging"
            workspace.mkdir()
            nested.mkdir()
            staging.mkdir(mode=0o700)
            escaped = root / "escaped"
            executable = Path(sys.executable).resolve(strict=True)
            profile = _snapshot_profile(
                workspace,
                _python_runtime_paths(),
                executable=executable,
                allow_workspace_write=False,
                workspace_write_paths=(("nested", "escaped-write.txt"),),
                workspace_create_unlink_paths=(("nested",),),
                allow_additional_full_write=True,
                additional_writable_roots=(staging,),
            )
            script = """\
import errno
import os
import sys
import time
from pathlib import Path

workspace = Path(sys.argv[1])
staging = Path(sys.argv[2])
parent_fd = os.open(
    workspace / "nested", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
)
(staging / "ready").write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 5
while (workspace / "nested").exists() and time.monotonic() < deadline:
    time.sleep(0.01)
if (workspace / "nested").exists():
    raise SystemExit(31)
try:
    os.open(
        "escaped-write.txt",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
        dir_fd=parent_fd,
    )
except OSError as exc:
    if exc.errno in (errno.EPERM, errno.EACCES):
        print("denied")
        raise SystemExit(0)
    raise SystemExit(32)
raise SystemExit(33)
"""
            process = subprocess.Popen(
                (
                    str(SANDBOX_EXECUTABLE),
                    "-p",
                    profile,
                    str(executable),
                    "-I",
                    "-S",
                    "-c",
                    script,
                    str(workspace),
                    str(staging),
                ),
                cwd=workspace,
                env={
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                    "HOME": str(staging),
                    "TMPDIR": str(staging),
                    "LC_ALL": "C",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
            )
            ready = staging / "ready"
            deadline = time.monotonic() + 5
            while not ready.exists() and process.poll() is None:
                if time.monotonic() >= deadline:
                    process.kill()
                    self.fail("commit sandbox did not open the workspace directory")
                time.sleep(0.01)
            self.assertTrue(ready.exists(), "commit sandbox exited before opening dirfd")
            nested.rename(escaped)
            stdout, stderr = process.communicate(timeout=5)

        self.assertEqual(process.returncode, 0, stderr.decode("utf-8", "replace"))
        self.assertEqual(stdout.decode("utf-8", "replace"), "denied\n")
        self.assertFalse((escaped / "escaped-write.txt").exists())

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_commit_sandbox_denies_unplanned_sibling_writes(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            workspace = root / "workspace"
            nested = workspace / "nested"
            workspace.mkdir()
            nested.mkdir()
            changed = nested / "changed.txt"
            untouched = nested / "untouched.txt"
            outside = root / "outside-canary.txt"
            changed.write_text("before", encoding="utf-8")
            untouched.write_text("protected", encoding="utf-8")
            outside.write_text("outside", encoding="utf-8")
            injection_component = 'quote\\") (literal "'
            injected_path = (injection_component, *outside.parts[1:])
            file_write_paths = (
                ("nested", "changed.txt"),
                ("nested", "added.txt"),
                ("nested", ".khaos-prepared.tmp"),
                injected_path,
            )
            create_unlink_paths = (
                ("nested",),
                *(injected_path[:index] for index in range(1, len(injected_path))),
            )
            profile = _snapshot_profile(
                workspace,
                _python_runtime_paths(),
                executable=Path(sys.executable).resolve(strict=True),
                allow_workspace_write=False,
                workspace_write_paths=file_write_paths,
                workspace_create_unlink_paths=create_unlink_paths,
            )
            script = """\
import errno
import os
from pathlib import Path
import sys

nested = Path(sys.argv[1])
outside = Path(sys.argv[2])
(nested / "changed.txt").write_text("after", encoding="utf-8")
(nested / "added.txt").write_text("added", encoding="utf-8")
directory_fd = os.open(nested, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    try:
        os.open(
            "untouched.txt",
            os.O_WRONLY | os.O_TRUNC,
            dir_fd=directory_fd,
        )
    except OSError as exc:
        if exc.errno not in (errno.EPERM, errno.EACCES):
            raise SystemExit(31)
    else:
        raise SystemExit(32)
    try:
        os.open(
            "unplanned.txt",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=directory_fd,
        )
    except OSError as exc:
        if exc.errno not in (errno.EPERM, errno.EACCES):
            raise SystemExit(33)
    else:
        raise SystemExit(34)
    try:
        os.chmod(nested, 0o700)
    except OSError as exc:
        if exc.errno not in (errno.EPERM, errno.EACCES):
            raise SystemExit(35)
    else:
        raise SystemExit(36)
    try:
        outside.write_text("escaped", encoding="utf-8")
    except OSError as exc:
        if exc.errno not in (errno.EPERM, errno.EACCES):
            raise SystemExit(37)
    else:
        raise SystemExit(38)
finally:
    os.close(directory_fd)
print("planned writes allowed; sibling, metadata, and injected outside writes denied")
"""
            result = subprocess.run(
                (
                    str(SANDBOX_EXECUTABLE),
                    "-p",
                    profile,
                    str(Path(sys.executable).resolve(strict=True)),
                    "-I",
                    "-S",
                    "-c",
                    script,
                    str(nested),
                    str(outside),
                ),
                cwd=workspace,
                env={
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                    "HOME": str(workspace),
                    "TMPDIR": str(workspace),
                    "LC_ALL": "C",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                capture_output=True,
                text=True,
                timeout=5,
            )

            self.assertEqual(
                result.returncode,
                0,
                result.stdout + result.stderr,
            )
            self.assertEqual(
                result.stdout,
                "planned writes allowed; sibling, metadata, and injected outside writes denied\n",
            )
            self.assertEqual(changed.read_text(encoding="utf-8"), "after")
            self.assertEqual(untouched.read_text(encoding="utf-8"), "protected")
            self.assertEqual(outside.read_text(encoding="utf-8"), "outside")
            self.assertFalse((nested / "unplanned.txt").exists())

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_sandboxed_command_does_not_inherit_an_open_pipe(self) -> None:
        read_fd, write_fd = os.pipe()
        status_read_fd, status_write_fd = os.pipe()
        secret_fd = -1
        status_fd = -1
        try:
            os.write(write_fd, b"khaos-fd-secret")
            os.close(write_fd)
            write_fd = -1
            secret_fd = fcntl.fcntl(read_fd, fcntl.F_DUPFD, 64)
            os.close(read_fd)
            read_fd = -1
            os.set_inheritable(secret_fd, True)
            status_fd = fcntl.fcntl(status_write_fd, fcntl.F_DUPFD, 65)
            os.close(status_write_fd)
            status_write_fd = -1

            with tempfile.TemporaryDirectory() as value:
                source = Path(value) / "workspace"
                source.mkdir()
                finished_process_groups: list[int] = []
                script = """\
import errno
import os
import sys

descriptor = int(sys.argv[1])
status_descriptor = int(sys.argv[2])
try:
    os.set_blocking(descriptor, False)
    inherited = os.read(descriptor, 64) == b"khaos-fd-secret"
except OSError as exc:
    if exc.errno != errno.EBADF:
        raise
    inherited = False
print(f"descriptor={inherited}")
if inherited:
    raise SystemExit(30)
try:
    os.write(status_descriptor, b"forged")
except OSError as exc:
    if exc.errno != errno.EBADF:
        raise
else:
    raise SystemExit(31)
"""
                with workspace_snapshot(source) as snapshot:
                    result = run_sandboxed_process(
                        snapshot,
                        [
                            str(Path(sys.executable).resolve(strict=True)),
                            "-I",
                            "-S",
                            "-c",
                            script,
                            str(secret_fd),
                            str(status_fd),
                        ],
                        timeout_seconds=5,
                        process_started_fd=status_fd,
                        workspace_request_id="b" * 32,
                        process_finished=finished_process_groups.append,
                    )
            start_event = receive_frame(status_read_fd, timeout_seconds=2)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "descriptor=False\n")
            self.assertEqual(start_event["event"], "process_started")
            self.assertEqual(start_event["request_id"], "b" * 32)
            self.assertEqual(
                finished_process_groups,
                [int(start_event["payload"]["process_group_id"], 16)],
            )
        finally:
            for descriptor in (
                read_fd,
                write_fd,
                secret_fd,
                status_read_fd,
                status_write_fd,
                status_fd,
            ):
                if descriptor >= 0:
                    os.close(descriptor)

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_sandboxed_command_cannot_connect_to_host_loopback(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        dns_listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        dns_listener.bind(("127.0.0.1", 0))
        dns_listener.settimeout(0.1)
        try:
            with tempfile.TemporaryDirectory() as value:
                source = Path(value) / "workspace"
                source.mkdir()
                child_script = """\
import errno
import socket
import sys

try:
    socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=1)
except OSError as exc:
    if exc.errno not in (errno.EPERM, errno.EACCES):
        raise
else:
    raise SystemExit(24)
print("child-network-denied")
"""
                script = """\
import errno
import socket
import sys
import subprocess
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

try:
    socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=1)
except OSError as exc:
    if exc.errno not in (errno.EPERM, errno.EACCES):
        raise
else:
    raise SystemExit(23)

child_script = CHILD_SCRIPT
child = subprocess.run(
    (sys.executable, "-I", "-S", "-c", child_script, str(sys.argv[1])),
    capture_output=True,
    text=True,
    timeout=2,
)
if child.returncode != 0 or child.stdout != "child-network-denied\\n":
    raise SystemExit(25)

udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    query = (
        b"\\x12\\x34\\x01\\x00\\x00\\x01\\x00\\x00\\x00\\x00\\x00\\x00"
        b"\\x05khaos\\x04test\\x00\\x00\\x01\\x00\\x01"
    )
    udp.sendto(query, ("127.0.0.1", int(sys.argv[2])))
except OSError as exc:
    if exc.errno not in (errno.EPERM, errno.EACCES):
        raise
else:
    raise SystemExit(26)

proxy = f"http://127.0.0.1:{int(sys.argv[1])}"
try:
    build_opener(ProxyHandler({"http": proxy})).open(
        "http://example.invalid/", timeout=1
    )
except URLError as exc:
    if not isinstance(exc.reason, OSError) or exc.reason.errno not in (
        errno.EPERM,
        errno.EACCES,
    ):
        raise
else:
    raise SystemExit(27)

print("ipv4-child-dns-proxy-denied")
""".replace("CHILD_SCRIPT", repr(child_script))
                with workspace_snapshot(source) as snapshot:
                    result = run_sandboxed_process(
                        snapshot,
                        [
                            str(Path(sys.executable).resolve()),
                            "-I",
                            "-S",
                            "-c",
                            script,
                            str(listener.getsockname()[1]),
                            str(dns_listener.getsockname()[1]),
                        ],
                        timeout_seconds=5,
                    )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "ipv4-child-dns-proxy-denied\n")
            with self.assertRaises(socket.timeout):
                dns_listener.recvfrom(512)
        finally:
            listener.close()
            dns_listener.close()

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_sandboxed_command_cannot_connect_to_ipv6_loopback(self) -> None:
        listener = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            listener.bind(("::1", 0))
            listener.listen(1)
        except OSError as exc:
            listener.close()
            self.skipTest(f"IPv6 loopback is unavailable: {exc}")

        try:
            with tempfile.TemporaryDirectory() as value:
                source = Path(value) / "workspace"
                source.mkdir()
                script = """\
import errno
import socket
import sys

try:
    socket.create_connection(("::1", int(sys.argv[1])), timeout=1)
except OSError as exc:
    if exc.errno not in (errno.EPERM, errno.EACCES):
        raise
else:
    raise SystemExit(28)
print("ipv6-denied")
"""
                with workspace_snapshot(source) as snapshot:
                    result = run_sandboxed_process(
                        snapshot,
                        [
                            str(Path(sys.executable).resolve(strict=True)),
                            "-I",
                            "-S",
                            "-c",
                            script,
                            str(listener.getsockname()[1]),
                        ],
                        timeout_seconds=5,
                    )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "ipv6-denied\n")
        finally:
            listener.close()

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_sandboxed_command_cannot_contact_macos_dns_resolver(self) -> None:
        resolver = Path("/var/run/mDNSResponder")
        if not resolver.is_socket():
            self.skipTest("macOS DNS resolver socket is unavailable")

        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            script = """\
import errno
import socket
import sys

for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
    peer = socket.socket(socket.AF_UNIX, kind)
    try:
        peer.connect(sys.argv[1])
    except OSError as exc:
        if exc.errno not in (errno.EPERM, errno.EACCES):
            raise
    else:
        raise SystemExit(29)
    finally:
        peer.close()
print("dns-resolver-ipc-denied")
"""
            with workspace_snapshot(source) as snapshot:
                result = run_sandboxed_process(
                    snapshot,
                    [
                        str(Path(sys.executable).resolve(strict=True)),
                        "-I",
                        "-S",
                        "-c",
                        script,
                        str(resolver),
                    ],
                    timeout_seconds=5,
                )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "dns-resolver-ipc-denied\n")

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_sandboxed_getaddrinfo_is_denied_by_the_system_resolver_boundary(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            script = """\
import os
import socket

pid = os.getpid()
print(f"resolver-pid:{pid}", flush=True)
try:
    socket.getaddrinfo(
        f"khaos-resolver-{pid}.example.com", 443, type=socket.SOCK_STREAM
    )
except socket.gaierror:
    print("resolver-request-failed")
else:
    raise SystemExit(37)
"""
            with workspace_snapshot(source) as snapshot:
                result = run_sandboxed_process(
                    snapshot,
                    [
                        str(Path(sys.executable).resolve(strict=True)),
                        "-I",
                        "-S",
                        "-c",
                        script,
                    ],
                    timeout_seconds=5,
                )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"^resolver-pid:\d+\nresolver-request-failed\n$")
        child_pid = int(result.stdout.splitlines()[0].partition(":")[2])
        predicate = (
            f'eventMessage CONTAINS[c] "({child_pid})" '
            'AND eventMessage CONTAINS[c] "deny(1)"'
        )
        log_result = subprocess.run(
            (
                "/usr/bin/log",
                "show",
                "--last",
                "1m",
                "--style",
                "compact",
                "--predicate",
                predicate,
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"},
            close_fds=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(log_result.returncode, 0, log_result.stderr.decode("utf-8", "replace"))
        records = log_result.stdout.decode("utf-8", "replace").splitlines()
        self.assertTrue(
            any(
                "com.apple.system.opendirectoryd.libinfo" in line
                or "/var/run/mDNSResponder" in line
                or "deny(1) network-outbound" in line
                for line in records
            ),
            "macOS did not report a resolver or network denial for the sandbox PID",
        )

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_sandboxed_command_timeout_kills_forked_descendants(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            script = """\
import os
import time

pid = os.fork()
if pid == 0:
    while True:
        time.sleep(1)
while True:
    time.sleep(1)
"""
            with workspace_snapshot(source) as snapshot:
                started = time.monotonic()
                with self.assertRaisesRegex(
                    SandboxedProcessError, "process_timeout"
                ):
                    run_sandboxed_process(
                        snapshot,
                        [
                            str(Path(sys.executable).resolve()),
                            "-I",
                            "-S",
                            "-c",
                            script,
                        ],
                        timeout_seconds=0.25,
                )
                self.assertLess(time.monotonic() - started, 5)

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_command_exit_kills_snapshot_writer_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            state = source / "state"
            state.mkdir()
            command = """\
import os
import time
from pathlib import Path

state = Path("state")
pid = os.fork()
if pid == 0:
    os.close(1)
    os.close(2)
    (state / "child-ready.txt").write_text("ready")
    while not (state / "release-child.txt").exists():
        time.sleep(0.01)
    (state / "survived.txt").write_text("late write")
    os._exit(0)

deadline = time.monotonic() + 2
while not (state / "child-ready.txt").exists() and time.monotonic() < deadline:
    time.sleep(0.01)
if not (state / "child-ready.txt").exists():
    raise SystemExit(31)
(state / "parent-result.txt").write_text("completed")
"""
            executable = Path(sys.executable).resolve(strict=True)
            with workspace_snapshot(source) as snapshot:
                result = run_sandboxed_process(
                    snapshot,
                    [str(executable), "-I", "-S", "-c", command],
                    workspace_read_scope=("state",),
                    timeout_seconds=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(
                    (snapshot.path / "state" / "child-ready.txt").exists()
                )
                self.assertTrue(
                    (snapshot.path / "state" / "parent-result.txt").exists()
                )

                release = snapshot.path / "state" / "release-child.txt"
                time.sleep(0.1)
                release.touch()
                survived = snapshot.path / "state" / "survived.txt"
                deadline = time.monotonic() + 1
                while not survived.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                release.unlink()
                self.assertFalse(survived.exists())
                (snapshot.path / "state" / "child-ready.txt").unlink()

                changes = commit_snapshot(
                    snapshot,
                    workspace_write_scope=WorkspaceWriteScope.from_paths(
                        ("state/parent-result.txt",)
                    ),
                )
                self.assertIn(("state", "parent-result.txt"), changes.added)
                self.assertNotIn(("state", "survived.txt"), changes.added)

            self.assertTrue((source / "state" / "parent-result.txt").exists())
            self.assertFalse((source / "state" / "child-ready.txt").exists())
            self.assertFalse((source / "state" / "survived.txt").exists())

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_write_scope_metadata_cannot_follow_unreadable_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "secret.txt").write_text("private", encoding="utf-8")
            outside = root / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            (workspace / "dirlink").symlink_to(root, target_is_directory=True)
            script = """\
import errno
import os
import sys

try:
    os.link("secret.txt", "hardlink.txt")
except OSError as error:
    if error.errno not in (errno.EPERM, errno.EACCES):
        raise
else:
    try:
        os.stat("hardlink.txt")
    except OSError as error:
        if error.errno not in (errno.EPERM, errno.EACCES):
            raise
    else:
        raise SystemExit("unreadable baseline metadata escaped")

os.symlink(sys.argv[1], "symlink.txt")
try:
    os.stat("symlink.txt")
except OSError as error:
    if error.errno not in (errno.EPERM, errno.EACCES):
        raise
else:
    raise SystemExit("outside metadata escaped")
try:
    os.stat("dirlink/outside.txt")
except OSError as error:
    if error.errno not in (errno.EPERM, errno.EACCES):
        raise
else:
    raise SystemExit("symlink ancestor metadata escaped")
print("metadata-aliases=denied")
"""
            with workspace_snapshot(workspace) as snapshot:
                result = run_sandboxed_process(
                    snapshot,
                    (
                        str(Path(sys.executable).resolve(strict=True)),
                        "-I", "-S", "-c", script, str(outside),
                    ),
                    workspace_write_scope=(
                        "hardlink.txt", "symlink.txt", "dirlink/outside.txt"
                    ),
                    timeout_seconds=5,
                )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "metadata-aliases=denied\n")
            self.assertEqual((workspace / "secret.txt").read_text(), "private")
            self.assertEqual(outside.read_text(), "outside")

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_double_fork_cannot_daemonize_past_command_exit(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            state = source / "state"
            state.mkdir()
            command = """\
import errno
import os
import time
from pathlib import Path

state = Path("state")
first_child = os.fork()
if first_child == 0:
    os.close(1)
    os.close(2)
    daemon_pid = os.fork()
    if daemon_pid:
        os._exit(0)

    (state / "daemon-pid.txt").write_text(str(os.getpid()))
    try:
        os.setsid()
    except OSError as exc:
        if exc.errno not in (errno.EPERM, errno.EACCES):
            raise
        (state / "setsid-denied.txt").write_text("denied")
    else:
        (state / "setsid-allowed.txt").write_text("escaped")

    while not (state / "release-daemon.txt").exists():
        time.sleep(0.01)
    (state / "survived.txt").write_text("late write")
    os._exit(0)

deadline = time.monotonic() + 2
while (
    not (state / "setsid-denied.txt").exists()
    and not (state / "setsid-allowed.txt").exists()
    and time.monotonic() < deadline
):
    time.sleep(0.01)
if not (state / "setsid-denied.txt").exists() and not (state / "setsid-allowed.txt").exists():
    raise SystemExit(32)
(state / "leader-result.txt").write_text("completed")
"""
            daemon_pid_file: Path | None = None
            daemon_pid: int | None = None
            with workspace_snapshot(source) as snapshot:
                daemon_pid_file = snapshot.path / "state" / "daemon-pid.txt"
                try:
                    result = run_sandboxed_process(
                        snapshot,
                        [
                            str(Path(sys.executable).resolve(strict=True)),
                            "-I",
                            "-S",
                            "-c",
                            command,
                        ],
                        workspace_read_scope=("state",),
                        timeout_seconds=5,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue(
                        (snapshot.path / "state" / "setsid-denied.txt").exists()
                    )
                    self.assertFalse(
                        (snapshot.path / "state" / "setsid-allowed.txt").exists()
                    )
                    self.assertTrue(
                        (snapshot.path / "state" / "leader-result.txt").exists()
                    )

                    release = snapshot.path / "state" / "release-daemon.txt"
                    release.touch()
                    survived = snapshot.path / "state" / "survived.txt"
                    deadline = time.monotonic() + 1
                    while not survived.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertFalse(survived.exists())
                    daemon_pid = int(daemon_pid_file.read_text())
                    daemon_pid_file.unlink()
                    release.unlink()

                    changes = commit_snapshot(
                        snapshot,
                        workspace_write_scope=WorkspaceWriteScope.from_paths(
                            ("state/setsid-denied.txt", "state/leader-result.txt")
                        ),
                    )
                    self.assertIn(("state", "setsid-denied.txt"), changes.added)
                    self.assertNotIn(("state", "survived.txt"), changes.added)
                finally:
                    if daemon_pid is not None:
                        try:
                            os.kill(daemon_pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_sandboxed_command_output_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            with workspace_snapshot(source) as snapshot:
                with self.assertRaisesRegex(SandboxedProcessError, "output_limit"):
                    run_sandboxed_process(
                        snapshot,
                        [
                            str(Path(sys.executable).resolve()),
                            "-I",
                            "-S",
                            "-c",
                            "print('x' * 9000)",
                    ],
                    timeout_seconds=5,
                )

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_sandboxed_command_enforces_file_and_descriptor_limits(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            (source / "state").mkdir()
            script = """\
import errno
import os
import resource
import signal

file_limit = int(os.sys.argv[1])
descriptor_limit = int(os.sys.argv[2])
if resource.getrlimit(resource.RLIMIT_FSIZE) != (file_limit, file_limit):
    raise SystemExit(31)
if resource.getrlimit(resource.RLIMIT_NOFILE) != (
    descriptor_limit,
    descriptor_limit,
):
    raise SystemExit(32)

for resource_id, limit in (
    (resource.RLIMIT_FSIZE, file_limit),
    (resource.RLIMIT_NOFILE, descriptor_limit),
):
    try:
        resource.setrlimit(resource_id, (limit + 1, limit + 1))
    except (OSError, ValueError):
        pass
    else:
        raise SystemExit(33)

signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
fd = os.open("state/file-limit-probe", os.O_CREAT | os.O_RDWR, 0o600)
try:
    try:
        os.ftruncate(fd, file_limit + 1)
    except OSError as exc:
        if exc.errno != errno.EFBIG:
            raise
    else:
        raise SystemExit(34)
finally:
    os.close(fd)
if os.stat("state/file-limit-probe").st_size > file_limit:
    raise SystemExit(35)

pipes = []
try:
    for _ in range(descriptor_limit):
        try:
            pipes.append(os.pipe())
        except OSError as exc:
            if exc.errno != errno.EMFILE:
                raise
            break
    else:
        raise SystemExit(36)
finally:
    for pair in pipes:
        for pipe_fd in pair:
            os.close(pipe_fd)

print("resource-limits-enforced")
"""
            with workspace_snapshot(source) as snapshot:
                result = run_sandboxed_process(
                    snapshot,
                    [
                        str(Path(sys.executable).resolve()),
                        "-I",
                        "-S",
                        "-c",
                        script,
                        str(_COMMAND_FILE_SIZE_LIMIT),
                        str(_COMMAND_OPEN_FILE_LIMIT),
                    ],
                    workspace_read_scope=("state",),
                    timeout_seconds=10,
                )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "resource-limits-enforced\n")

    @unittest.skipUnless(
        sys.platform == "darwin"
        and os.getuid() != 0
        and SANDBOX_EXECUTABLE.is_file(),
        "requires non-root macOS Seatbelt process limits",
    )
    def test_sandboxed_command_rlimit_nproc_denies_fork_over_limit(self) -> None:
        script = """\
import errno
import os
import resource
import sys

expected_limit = int(sys.argv[1])
if resource.getrlimit(resource.RLIMIT_NPROC) != (expected_limit, expected_limit):
    raise SystemExit(31)

# Prove the Seatbelt profile permits fork before exercising the OS quota.
pid = os.fork()
if pid == 0:
    os._exit(0)
_, status = os.waitpid(pid, 0)
if status != 0:
    raise SystemExit(32)

# RLIMIT_NPROC is per real UID on macOS, so lowering it below the current
# process count must make the kernel reject a subsequent fork.
resource.setrlimit(resource.RLIMIT_NPROC, (2, 2))
try:
    pid = os.fork()
except OSError as exc:
    if exc.errno != errno.EAGAIN:
        raise
else:
    if pid == 0:
        os._exit(0)
    os.waitpid(pid, 0)
    raise SystemExit(33)

print("per-user-process-limit-enforced")
"""
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            with workspace_snapshot(source) as snapshot:
                result = run_sandboxed_process(
                    snapshot,
                    [
                        str(Path(sys.executable).resolve()),
                        "-I",
                        "-S",
                        "-c",
                        script,
                        str(_COMMAND_PROCESS_COUNT_LIMIT_PER_UID),
                    ],
                    timeout_seconds=10,
                )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "per-user-process-limit-enforced\n")

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend and APFS",
    )
    def test_real_sandbox_enforces_aggregate_apfs_limit_and_blocks_unmount(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            (source / "state").mkdir()
            canary = root / "outside-canary.txt"
            canary.write_text("unchanged", encoding="utf-8")
            detached_parent: Path | None = None
            with mounted_apfs_volume(
                root, size_bytes=128_000_000, case_sensitive=False
            ) as control_mount:
                control_result, control_errno = _direct_unmount(control_mount)
                self.assertEqual(
                    control_result,
                    0,
                    f"unconfined same-user unmount failed with errno {control_errno}",
                )
                self.assertFalse(Path(control_mount).is_mount())

            with workspace_snapshot(
                source, max_storage_bytes=128_000_000
            ) as snapshot:
                detached_parent = snapshot.path.parent.parent
                self.assertNotEqual(
                    snapshot.source_mount_point,
                    snapshot.snapshot_mount_point,
                )
                self.assertEqual(snapshot.storage_limit_bytes, 128_000_000)
                script = """\
import ctypes
import errno
import os
from pathlib import Path
import sys

workspace = sys.argv[1]
mount_point = os.fsencode(sys.argv[2])
os.chdir("/")
libc = ctypes.CDLL(None, use_errno=True)
unmount = libc.unmount
unmount.argtypes = (ctypes.c_char_p, ctypes.c_int)
unmount.restype = ctypes.c_int
if unmount(mount_point, 0) != -1:
    raise SystemExit(41)
if ctypes.get_errno() not in (errno.EPERM, errno.EACCES):
    raise SystemExit(42)
os.chdir(os.path.join(workspace, "state"))
Path("quota-output.txt").write_text("before ENOSPC")

payload = b"x" * (1024 * 1024)
complete_bytes = 0
disk_full = False
for index in range(256):
    try:
        with Path(f"fill-{index}").open("wb") as output:
            for _ in range(8):
                output.write(payload)
        complete_bytes += 8 * len(payload)
    except OSError as exc:
        if exc.errno != errno.ENOSPC:
            raise
        disk_full = True
        break
if not disk_full or complete_bytes < 64 * 1024 * 1024:
    raise SystemExit(43)
for path in Path(".").glob("fill-*"):
    path.unlink()
Path("quota-output.txt").write_text("validated after ENOSPC")
print("aggregate-quota-enforced")
"""
                result = run_sandboxed_process(
                    snapshot,
                    [
                        str(Path(sys.executable).resolve()),
                        "-I",
                        "-S",
                        "-c",
                        script,
                        str(snapshot.path),
                        str(snapshot.path.parent),
                    ],
                    workspace_read_scope=("state",),
                    timeout_seconds=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "aggregate-quota-enforced\n")
                changes = commit_snapshot(
                    snapshot,
                    workspace_write_scope=WorkspaceWriteScope.from_paths(
                        ("state/quota-output.txt",)
                    ),
                )
                self.assertEqual(changes.added, (("state", "quota-output.txt"),))
                self.assertEqual(
                    (source / "state" / "quota-output.txt").read_text(
                        encoding="utf-8"
                    ),
                    "validated after ENOSPC",
                )
                self.assertFalse(any((source / "state").glob("fill-*")))
            self.assertEqual(canary.read_text(encoding="utf-8"), "unchanged")
            self.assertIsNotNone(detached_parent)
            self.assertFalse(detached_parent.exists())

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend and APFS",
    )
    def test_real_sandbox_blocks_disk_image_mount_over_live_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            mount_target = source / "mount-target"
            mount_target.mkdir()
            image = source / "attach-probe.sparsebundle"
            _run_tool(
                _HDIUTIL,
                (
                    "create",
                    "-type",
                    "SPARSEBUNDLE",
                    "-sectors",
                    "131072",
                    "-layout",
                    "NONE",
                    "-fs",
                    "APFS",
                    "-volname",
                    "KhaosProbe",
                    "-nospotlight",
                    str(image),
                ),
            )

            with workspace_snapshot(
                source, max_storage_bytes=128_000_000
            ) as snapshot:
                snapshot_image = snapshot.path / image.name
                resolved_target = mount_target.resolve(strict=True)
                attach_commands = (
                    (
                        "hdiutil",
                        (
                            _HDIUTIL,
                            "attach",
                            "-plist",
                            "-nobrowse",
                            "-mountpoint",
                            str(resolved_target),
                            str(snapshot_image),
                        ),
                    ),
                    (
                        "diskutil",
                        (
                            _DISKUTIL,
                            "image",
                            "attach",
                            "--plist",
                            "--nobrowse",
                            "--mountPoint",
                            str(resolved_target),
                            str(snapshot_image),
                        ),
                    ),
                )

                def detach_probe_image() -> None:
                    if resolved_target.is_mount():
                        result, error = _direct_unmount(resolved_target)
                        if result != 0:
                            raise AssertionError(
                                f"mount probe cleanup failed with errno {error}"
                            )
                    info = _attached_image_info(snapshot_image)
                    if info is not None:
                        device = _whole_image_device(
                            _validated_entities(info.get("system-entities"))
                        )
                        _run_tool(_HDIUTIL, ("detach", device))

                script = """\
import subprocess
import sys

result = subprocess.run(
    sys.argv[1:],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    timeout=20,
    check=False,
)
print(f"attach-returncode={result.returncode}")
print(result.stderr.decode("utf-8", errors="replace"), end="")
"""

                mount_apfs_script = """\
import ctypes
import os
import subprocess
import sys

libc = ctypes.CDLL(None, use_errno=True)
mount = libc.mount
mount.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
mount.restype = ctypes.c_int
raw_result = mount(b"apfs", os.fsencode(sys.argv[-1]), 0, None)
print(f"raw-mount-return={raw_result};errno={ctypes.get_errno()}")

try:
    result = subprocess.run(
        sys.argv[1:],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
except OSError as exc:
    print(f"mount-apfs-launch-error={exc.errno}")
else:
    print(f"mount-apfs-returncode={result.returncode}")
    print(result.stderr.decode("utf-8", errors="replace"), end="")
"""

                try:
                    attachment = _run_tool(
                        _DISKUTIL,
                        (
                            "image",
                            "attach",
                            "--plist",
                            "--noMount",
                            str(snapshot_image),
                        ),
                    )
                    attachment_info = plistlib.loads(attachment.stdout)
                    attachment_entities = _validated_entities(
                        attachment_info.get("system-entities")
                    )
                    volume_devices = [
                        entity["dev-entry"]
                        for entity in attachment_entities
                        if entity.get("content-hint") == "Apple_APFS_Volume"
                        and isinstance(entity.get("dev-entry"), str)
                        and re.fullmatch(
                            r"disk[0-9]+s[0-9]+", entity["dev-entry"]
                        )
                    ]
                    self.assertEqual(len(volume_devices), 1, attachment_entities)
                    direct_mount_command = (
                        "/sbin/mount_apfs",
                        "-o",
                        "rdonly",
                        f"/dev/{volume_devices[0]}",
                        str(resolved_target),
                    )
                    host_control = subprocess.run(
                        direct_mount_command,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=30,
                        check=False,
                    )
                    self.assertEqual(
                        host_control.returncode,
                        0,
                        host_control.stderr.decode("utf-8", errors="replace"),
                    )
                    self.assertTrue(resolved_target.is_mount())
                    host_unmount, host_unmount_errno = _direct_unmount(
                        resolved_target
                    )
                    self.assertEqual(
                        host_unmount,
                        0,
                        f"host mount control cleanup failed with errno "
                        f"{host_unmount_errno}",
                    )
                    self.assertFalse(resolved_target.is_mount())
                    libc = ctypes.CDLL(None, use_errno=True)
                    host_mount = libc.mount
                    host_mount.argtypes = (
                        ctypes.c_char_p,
                        ctypes.c_char_p,
                        ctypes.c_int,
                        ctypes.c_void_p,
                    )
                    host_mount.restype = ctypes.c_int
                    raw_host_result = host_mount(
                        b"apfs", os.fsencode(resolved_target), 0, None
                    )
                    raw_host_errno = ctypes.get_errno()
                    self.assertEqual(raw_host_result, -1)
                    self.assertEqual(
                        raw_host_errno,
                        errno.EFAULT,
                        "host mount syscall did not reach APFS argument validation",
                    )

                    direct_result = run_sandboxed_process(
                        snapshot,
                        [
                            str(Path(sys.executable).resolve(strict=True)),
                            "-I",
                            "-S",
                            "-c",
                            mount_apfs_script,
                            *direct_mount_command,
                        ],
                        timeout_seconds=30,
                    )
                finally:
                    detach_probe_image()

                self.assertEqual(direct_result.returncode, 0, direct_result.stderr)
                self.assertFalse(resolved_target.is_mount())
                self.assertEqual(
                    resolved_target.stat().st_dev,
                    resolved_target.parent.stat().st_dev,
                )
                raw_mount_outcome = next(
                    (
                        line
                        for line in direct_result.stdout.splitlines()
                        if line.startswith("raw-mount-return=")
                    ),
                    None,
                )
                self.assertIn(
                    raw_mount_outcome,
                    {
                        f"raw-mount-return=-1;errno={errno.EPERM}",
                        f"raw-mount-return=-1;errno={errno.EACCES}",
                    },
                    direct_result.stdout,
                )
                mount_outcome = next(
                    (
                        line
                        for line in direct_result.stdout.splitlines()
                        if line.startswith(
                            ("mount-apfs-launch-error=", "mount-apfs-returncode=")
                        )
                    ),
                    None,
                )
                self.assertIsNotNone(mount_outcome, direct_result.stdout)
                if mount_outcome.startswith("mount-apfs-launch-error="):
                    launch_error = mount_outcome.removeprefix(
                        "mount-apfs-launch-error="
                    )
                    self.assertIn(
                        launch_error, {str(errno.EPERM), str(errno.EACCES)}
                    )
                else:
                    mount_status = mount_outcome.removeprefix(
                        "mount-apfs-returncode="
                    )
                    self.assertNotEqual(mount_status, "0", direct_result.stdout)
                    self.assertRegex(
                        direct_result.stdout,
                        r"Operation not permitted|Permission denied",
                    )
                self.assertIsNone(_attached_image_info(snapshot_image))

                for tool, attach_command in attach_commands:
                    control = subprocess.run(
                        attach_command,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=30,
                        check=False,
                    )
                    try:
                        self.assertEqual(
                            control.returncode,
                            0,
                            control.stderr.decode("utf-8", errors="replace"),
                        )
                        self.assertTrue(resolved_target.is_mount())
                        info = _attached_image_info(snapshot_image)
                        self.assertIsNotNone(info)
                        mounted_targets = {
                            Path(entity["mount-point"]).resolve()
                            for entity in _validated_entities(
                                info.get("system-entities")
                            )
                            if isinstance(entity.get("mount-point"), str)
                        }
                        self.assertIn(resolved_target, mounted_targets)
                    finally:
                        detach_probe_image()
                    self.assertFalse(resolved_target.is_mount())
                    self.assertIsNone(_attached_image_info(snapshot_image))

                    try:
                        result = run_sandboxed_process(
                            snapshot,
                            [
                                str(Path(sys.executable).resolve(strict=True)),
                                "-I",
                                "-S",
                                "-c",
                                script,
                                *attach_command,
                            ],
                            timeout_seconds=30,
                        )
                    finally:
                        # Clean up if a future regression lets the request through.
                        detach_probe_image()

                    self.assertEqual(result.returncode, 0, result.stderr)
                    attach_status = next(
                        (
                            line.removeprefix("attach-returncode=")
                            for line in result.stdout.splitlines()
                            if line.startswith("attach-returncode=")
                        ),
                        None,
                    )
                    self.assertIsNotNone(attach_status, result.stdout)
                    self.assertNotEqual(
                        attach_status,
                        "0",
                        f"{tool} unexpectedly attached the snapshot image",
                    )
                    self.assertFalse(resolved_target.is_mount())
                    self.assertEqual(
                        resolved_target.stat().st_dev,
                        resolved_target.parent.stat().st_dev,
                    )
                    self.assertIsNone(_attached_image_info(snapshot_image))

    def test_unsupported_platform_fails_closed(self) -> None:
        with patch("khaos.kernel.macos_seatbelt.sys.platform", "linux"):
            with self.assertRaisesRegex(SandboxUnavailable, "unsupported"):
                probe_macos_seatbelt()

    @unittest.skipUnless(sys.platform == "darwin", "requires the macOS Seed path")
    def test_missing_backend_fails_closed_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "input.txt").write_text("snapshot input", encoding="utf-8")
            positive_control = root / "host-positive-control.txt"
            fallback_marker = root / "host-fallback-ran.txt"
            missing_backend = root / "missing-sandbox-exec"
            marker_command = (
                sys.executable,
                "-S",
                "-c",
                "from pathlib import Path; import sys; "
                "Path(sys.argv[1]).write_text('ran', encoding='utf-8')",
            )
            subprocess.run(
                (*marker_command, str(positive_control)),
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(positive_control.read_text(encoding="utf-8"), "ran")

            with workspace_snapshot(workspace) as snapshot:
                with patch(
                    "khaos.kernel.macos_seatbelt.SANDBOX_EXECUTABLE",
                    missing_backend,
                ), patch(
                    "khaos.kernel.worker.SANDBOX_EXECUTABLE",
                    missing_backend,
                ):
                    with self.assertRaisesRegex(SandboxUnavailable, "unavailable"):
                        probe_macos_seatbelt()
                    with self.assertRaisesRegex(
                        SandboxedProcessError, "sandbox_unavailable"
                    ):
                        run_sandboxed_process(
                            snapshot,
                            (*marker_command, str(fallback_marker)),
                            timeout_seconds=1,
                        )
                    workspace_root_fd = os.open(
                        workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
                    )
                    try:
                        with self.assertRaisesRegex(
                            SandboxUnavailable, "unavailable"
                        ) as raised:
                            _run_workspace_command(
                                str(workspace.resolve(strict=True)),
                                1,
                                _DEFAULT_RUNNER_SOURCE,
                                workspace_root_fd=workspace_root_fd,
                            )
                        self.assertEqual(
                            raised.exception.diagnostic_stage,
                            "probe-readiness",
                        )
                    finally:
                        os.close(workspace_root_fd)

            self.assertFalse(fallback_marker.exists())

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS Seatbelt")
    def test_real_seatbelt_confines_writable_snapshot_and_denies_loopback(self) -> None:
        probe_macos_seatbelt()


if __name__ == "__main__":
    unittest.main()
