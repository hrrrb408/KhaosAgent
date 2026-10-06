from __future__ import annotations

import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from khaos import launcher as launcher_module
from khaos.ipc import IPCProtocolError, MAX_RUNNER_SOURCE_BYTES
from khaos.kernel.macos_disk_image import (
    _DISKUTIL,
    _HDIUTIL,
    _attached_image_info,
    _run_tool,
    _validated_entities,
    _whole_image_device,
    cleanup_abandoned_apfs_volumes,
)
from khaos.kernel.macos_seatbelt import SANDBOX_EXECUTABLE
from khaos.launcher import KernelLaunchError, _stop_kernel, run_workspace_command


def _runner_source_with_argv(source: str, argv: list[str]) -> str:
    call = "process_exec()"
    if source.count(call) != 1:
        raise AssertionError("Runner source must have exactly one process.exec call")
    return source.replace(call, f"process_exec({tuple(argv)!r})", 1)


def _matching_processes(token: str) -> list[tuple[int, int, int]]:
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,ppid=,pgid=,command="],
        check=True,
        capture_output=True,
        text=True,
    )
    matches: list[tuple[int, int, int]] = []
    for line in result.stdout.splitlines():
        fields = line.split(maxsplit=3)
        if len(fields) == 4 and token in fields[3]:
            matches.append(tuple(int(value) for value in fields[:3]))
    return matches


def _process_group_members(process_group_id: int) -> list[int]:
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,ppid=,pgid="],
        check=True,
        capture_output=True,
        text=True,
    )
    members: list[int] = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 3 and int(fields[2]) == process_group_id:
            members.append(int(fields[0]))
    return members


def _process_argument_area(process_id: int) -> bytes:
    """Read Darwin's argv/environment area for an unconfined positive control."""
    sysctl = ctypes.CDLL(None, use_errno=True).sysctl
    sysctl.argtypes = (
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_void_p,
        ctypes.c_size_t,
    )
    sysctl.restype = ctypes.c_int
    mib = (ctypes.c_int * 3)(1, 49, process_id)  # CTL_KERN, KERN_PROCARGS2
    size = ctypes.c_size_t(0)
    if sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    data = ctypes.create_string_buffer(size.value)
    if sysctl(mib, 3, data, ctypes.byref(size), None, 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return data.raw[: size.value]


class KernelLauncherTests(unittest.TestCase):
    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_seed_example_plugin_commits_only_scoped_path(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "examples" / "seed-writer" / "plugin.py"
        ).read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value) / "workspace"
            workspace.mkdir()
            result = run_workspace_command(
                workspace,
                runner_source=source,
                workspace_write_scope=("seed-plugin-output.txt",),
                timeout_seconds=10,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual((result.added, result.modified, result.deleted), (1, 0, 0))
            self.assertEqual(
                (workspace / "seed-plugin-output.txt").read_bytes(),
                b"Khaos Seed plugin ran\n",
            )

            (workspace / "seed-plugin-output.txt").unlink()
            with self.assertRaisesRegex(KernelLaunchError, "runner_failed"):
                run_workspace_command(
                    workspace,
                    runner_source=source,
                    timeout_seconds=10,
                )
            self.assertEqual(list(workspace.iterdir()), [])

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_workspace_startup_retries_a_failed_pipe_ping_before_request(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value) / "workspace"
            workspace.mkdir()
            state_root = Path(value) / "plugin-state"
            state_root.mkdir(mode=0o700)
            runner_source = """\
from khaos.runner_sdk import plugin_output, state_read, state_replace

def run(request):
    count = int(state_read() or b"0") + 1
    state_replace(str(count).encode("ascii"))
    plugin_output({"count": count})
"""
            real_answer_ping = launcher_module.answer_ping
            ping_count = 0

            def fail_after_first_ping(read_fd, write_fd, *, timeout_seconds):
                nonlocal ping_count
                ping_count += 1
                real_answer_ping(
                    read_fd, write_fd, timeout_seconds=timeout_seconds
                )
                if ping_count == 1:
                    raise IPCProtocolError("forced pre-request pipe failure")

            real_start_kernel = launcher_module._start_kernel
            with (
                patch.object(
                    launcher_module, "answer_ping", side_effect=fail_after_first_ping
                ) as ping,
                patch.object(
                    launcher_module, "_start_kernel", wraps=real_start_kernel
                ) as start,
            ):
                result = run_workspace_command(
                    workspace,
                    runner_source=runner_source,
                    plugin_id="retry-probe",
                    plugin_state_root=state_root,
                    plugin_input={"operation": "count"},
                    process_exec_allowed=False,
                    timeout_seconds=5,
                )

            self.assertEqual(start.call_count, 2)
            self.assertEqual(ping.call_count, 2)
            self.assertEqual(result.returncode, 0)
            self.assertEqual((result.added, result.modified, result.deleted), (0, 0, 0))
            self.assertEqual(json.loads(result.stdout), {"count": 1})

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_scoped_command_can_copy_input_without_reading_unscoped_data(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value) / "workspace"
            workspace.mkdir()
            (workspace / "input.txt").write_text("allowed\n", encoding="utf-8")
            (workspace / "secret.txt").write_text("forbidden\n", encoding="utf-8")
            script = """\
set -eu
[ "$PWD" = "$(pwd)" ]
cat input.txt > result.txt
if cat secret.txt >/dev/null 2>/dev/null; then exit 41; fi
if cat result.txt >/dev/null 2>/dev/null; then exit 42; fi
"""
            result = run_workspace_command(
                workspace,
                ("/bin/bash", "-c", script),
                workspace_read_scope=("input.txt",),
                workspace_write_scope=("result.txt",),
                timeout_seconds=5,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stderr, "")
            self.assertEqual((result.added, result.modified, result.deleted), (1, 0, 0))
            self.assertEqual((workspace / "result.txt").read_text(), "allowed\n")
            self.assertEqual((workspace / "secret.txt").read_text(), "forbidden\n")

    @unittest.skipUnless(sys.platform == "darwin", "requires POSIX process groups")
    def test_stop_kernel_kills_helpers_after_worker_exits_on_sigint(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            ready = root / "helper-ready"
            stopping = root / "worker-stopping"
            survived = root / "helper-survived"
            script = """\
import os
import signal
import sys
import time
from pathlib import Path

ready, stopping, survived = map(Path, sys.argv[1:])
child = os.fork()
if child == 0:
    ready.write_text("ready")
    while not stopping.exists():
        time.sleep(0.01)
    time.sleep(0.3)
    survived.write_text("late helper write")
    os._exit(0)

def stop_worker(_signum, _frame):
    stopping.write_text("worker exiting")
    raise SystemExit(0)

signal.signal(signal.SIGINT, stop_worker)
while not ready.exists():
    time.sleep(0.01)
time.sleep(30)
"""
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    script,
                    str(ready),
                    str(stopping),
                    str(survived),
                ],
                cwd="/",
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and process.poll() is None:
                    if time.monotonic() >= deadline:
                        self.fail("worker helper did not start")
                    time.sleep(0.01)
                self.assertTrue(ready.exists())

                _stop_kernel(process)

                deadline = time.monotonic() + 1
                while time.monotonic() < deadline and not survived.exists():
                    time.sleep(0.01)
                self.assertFalse(
                    survived.exists(),
                    "same-group helper survived prompt Kernel worker exit",
                )
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_invalid_command_is_rejected_before_kernel_launch(self) -> None:
        with patch("khaos.launcher.subprocess.Popen") as popen:
            with self.assertRaisesRegex(ValueError, "invalid_arguments"):
                run_workspace_command("/tmp", ["x" * 33_000])
            with self.assertRaisesRegex(ValueError, "invalid_timeout"):
                run_workspace_command("/tmp", ["true"], timeout_seconds=float("inf"))
            with self.assertRaisesRegex(ValueError, "invalid_runner_source"):
                run_workspace_command(
                    "/tmp",
                    runner_source="#" * (MAX_RUNNER_SOURCE_BYTES + 1),
                )
            with self.assertRaisesRegex(ValueError, "argv must be selected"):
                run_workspace_command(
                    "/tmp",
                    ["true"],
                    runner_source="def run():\n    return 0\n",
                )
            with self.assertRaisesRegex(ValueError, "invalid_workspace_read_scope"):
                run_workspace_command(
                    "/tmp",
                    ["true"],
                    workspace_read_scope=("../outside.txt",),
                )
            with self.assertRaisesRegex(ValueError, "invalid_workspace_write_scope"):
                run_workspace_command(
                    "/tmp",
                    ["true"],
                    workspace_write_scope=("../outside.txt",),
                )
            popen.assert_not_called()

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the macOS Kernel Worker process",
    )
    def test_kernel_rejects_workspaces_inside_its_signed_bundle_roots(self) -> None:
        source_package = Path(__file__).resolve().parents[1] / "khaos"
        script = """\
import sys
sys.path.insert(0, sys.argv[1])
from khaos.launcher import KernelLaunchError, run_workspace_command

try:
    run_workspace_command(
        sys.argv[2],
        ["/bin/bash", "-c", "printf 'must-not-run' > overlap-marker.txt"],
        timeout_seconds=10,
    )
except KernelLaunchError as error:
    if str(error) not in {"workspace_rejected", "workspace_rejected_snapshot"}:
        raise
else:
    raise SystemExit("Kernel executed a command inside its installation bundle")
print("kernel-installation-overlap=denied")
"""
        with tempfile.TemporaryDirectory(prefix="khaos-install-root-") as value:
            root = Path(value)
            bundle_layouts = (
                (
                    "xpc",
                    root / "KernelProduction.xpc",
                    (
                        root
                        / "KernelProduction.xpc"
                        / "Contents"
                        / "MacOS"
                        / "workspace"
                    ),
                ),
                (
                    "app",
                    root / "KhaosSeed.app",
                    (
                        root
                        / "KhaosSeed.app"
                        / "Contents"
                        / "MacOS"
                        / "workspace"
                    ),
                ),
            )
            for kind, bundle_root, workspace in bundle_layouts:
                with self.subTest(bundle=kind):
                    resources = (
                        bundle_root
                        / "Contents"
                        / "XPCServices"
                        / "KernelProduction.xpc"
                        / "Contents"
                        / "Resources"
                        if kind == "app"
                        else bundle_root / "Contents" / "Resources"
                    )
                    package_root = resources / "khaos"
                    package_root.parent.mkdir(parents=True)
                    shutil.copytree(
                        source_package,
                        package_root,
                        ignore=shutil.ignore_patterns("__pycache__"),
                    )
                    workspace.mkdir(parents=True)
                    marker = workspace / "overlap-marker.txt"
                    result = subprocess.run(
                        [
                            sys.executable,
                            "-I",
                            "-S",
                            "-B",
                            "-c",
                            script,
                            str(resources),
                            str(workspace),
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    self.assertEqual(
                        result.returncode,
                        0,
                        result.stdout + result.stderr,
                    )
                    self.assertEqual(
                        result.stdout.strip(),
                        "kernel-installation-overlap=denied",
                    )
                    self.assertFalse(marker.exists())

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_process_exec_rejects_appended_workspace_over_wire(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            workspace = root / "workspace"
            workspace.mkdir()
            outside = root / "outside"
            outside.mkdir()
            plugin_source = f'''\
from khaos.ipc import PROTOCOL_VERSION, receive_frame, send_frame
from khaos.runner_sdk import workspace_commit

def run():
    send_frame(1, {{
        "version": PROTOCOL_VERSION,
        "request_id": "f" * 32,
        "operation": "process.exec",
        "payload": {{
            "argv": ["/bin/sh", "-c", "printf forged > wire-forged.txt"],
            "workspace": {str(outside)!r},
        }},
    }})
    reply = receive_frame(0)
    if reply.get("error") != {{"code": "invalid_request"}}:
        workspace_commit()
        raise SystemExit(61)
'''

            with self.assertRaisesRegex(KernelLaunchError, "runner_failed"):
                run_workspace_command(
                    workspace,
                    runner_source=plugin_source,
                    timeout_seconds=5,
                )

            self.assertEqual(list(workspace.iterdir()), [])
            self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_runner_cannot_expand_filesystem_scope_over_wire(self) -> None:
        attacks = (
            (
                "fs.read",
                {"path": "secret.txt", "workspace_read_scope": ["secret.txt"]},
            ),
            (
                "fs.list",
                {"path": "", "workspace_read_scope": ["secret.txt"]},
            ),
            (
                "fs.write",
                {
                    "path": "secret.txt",
                    "data_base64": "Zm9yZ2Vk",
                    "workspace_write_scope": ["secret.txt"],
                },
            ),
        )
        for operation, payload in attacks:
            with (
                self.subTest(operation=operation),
                tempfile.TemporaryDirectory() as value,
            ):
                workspace = Path(value) / "workspace"
                workspace.mkdir()
                secret = workspace / "secret.txt"
                secret.write_text("private", encoding="utf-8")
                command_marker = workspace / "scope-forgery-command.txt"
                runner_source = f'''\
from khaos.ipc import PROTOCOL_VERSION, receive_frame, send_frame
from khaos.runner_sdk import process_exec, workspace_commit

def run():
    send_frame(1, {{
        "version": PROTOCOL_VERSION,
        "request_id": "a" * 32,
        "operation": {operation!r},
        "payload": {payload!r},
    }})
    reply = receive_frame(0)
    if reply.get("ok"):
        if process_exec()["returncode"] != 0:
            raise SystemExit(71)
        workspace_commit()
        return 0
    raise SystemExit(72)
'''

                with self.assertRaisesRegex(KernelLaunchError, "runner_failed"):
                    run_workspace_command(
                        workspace,
                        runner_source=_runner_source_with_argv(
                            runner_source,
                            [
                                "/bin/sh",
                                "-c",
                                "printf reached > scope-forgery-command.txt",
                            ],
                        ),
                        timeout_seconds=5,
                    )

                self.assertEqual(secret.read_text(encoding="utf-8"), "private")
                self.assertFalse(command_marker.exists())

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_runner_cannot_select_changeset_or_commit_target_over_wire(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            workspace = root / "workspace"
            workspace.mkdir()
            outside = root / "outside"
            outside.mkdir()
            canary = outside / "canary.txt"
            canary.write_text("protected", encoding="utf-8")
            plugin_source = f'''\
from khaos.ipc import PROTOCOL_VERSION, receive_frame, send_frame
from khaos.runner_sdk import process_exec

def run():
    if process_exec()["returncode"] != 0:
        raise SystemExit(62)
    send_frame(1, {{
        "version": PROTOCOL_VERSION,
        "request_id": "e" * 32,
        "operation": "workspace.commit",
        "payload": {{
            "workspace": {str(outside)!r},
            "changeset": [{{"path": "../outside/canary.txt", "content": "forged"}}],
        }},
    }})
    reply = receive_frame(0)
    if reply.get("error") != {{"code": "invalid_request"}}:
        raise SystemExit(63)
'''

            with self.assertRaisesRegex(KernelLaunchError, "runner_failed"):
                run_workspace_command(
                    workspace,
                    runner_source=_runner_source_with_argv(
                        plugin_source,
                        ["/bin/sh", "-c", "printf trusted > pending.txt"],
                    ),
                    timeout_seconds=5,
                )

            self.assertEqual(list(workspace.iterdir()), [])
            self.assertEqual([path.name for path in outside.iterdir()], ["canary.txt"])
            self.assertEqual(canary.read_text(encoding="utf-8"), "protected")

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_separate_kernel_commits_sandbox_output_and_denies_live_write(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            workspace = root / "workspace"
            workspace.mkdir()
            live_parent = workspace / "nested"
            live_parent.mkdir()
            (live_parent / "marker.txt").write_text("live", encoding="utf-8")
            outside = root / "outside.txt"
            outside.write_text("protected", encoding="utf-8")
            moved_parent = root / "moved-workspace-parent"
            traversed_outside = "../" * 40 + str(outside).lstrip("/")
            script = """\
set -eu
printf '%s' 'private-copy' > created.txt
if printf '%s' 'escaped' > "$1"; then
    exit 41
fi
if printf '%s' 'escaped' > "$2"; then
    exit 42
fi
if mv "$3" "$4" 2>/dev/null; then
    exit 43
fi
printf '%s\\n' 'sandboxed'
"""
            runner_source = """\
from khaos.ipc import IPCProtocolError
from khaos.runner_sdk import fs_write, process_exec, workspace_commit

try:
    fs_write("runner-output.txt", b"empty scope must reject this")
except IPCProtocolError as exc:
    if "path_not_writable" not in str(exc):
        raise
else:
    raise SystemExit(44)

if process_exec()["returncode"] != 0:
    raise SystemExit(45)
workspace_commit()
"""
            result = run_workspace_command(
                workspace,
                runner_source=_runner_source_with_argv(
                    runner_source,
                    [
                        "/bin/bash",
                        "-c",
                        script,
                        "khaos",
                        str(outside),
                        traversed_outside,
                        str(live_parent),
                        str(moved_parent),
                    ],
                ),
                timeout_seconds=5,
                workspace_write_scope=("created.txt",),
            )

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "sandboxed\n")
            self.assertRegex(
                result.stderr, "Operation not permitted|Permission denied"
            )
            self.assertEqual((workspace / "created.txt").read_text(), "private-copy")
            self.assertEqual(
                (live_parent / "marker.txt").read_text(encoding="utf-8"), "live"
            )
            self.assertFalse(moved_parent.exists())
            self.assertEqual(outside.read_text(), "protected")
            self.assertFalse((workspace / "runner-output.txt").exists())
            self.assertEqual((result.added, result.modified, result.deleted), (1, 0, 0))

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend and APFS",
    )
    def test_kernel_rejects_out_of_scope_process_output_before_writeback(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value) / "workspace"
            workspace.mkdir()
            script = """\
set -eu
printf '%s' 'authorized' > allowed.txt
printf '%s' 'must-not-write-back' > unscoped.txt
"""
            runner_source = """\
from khaos.runner_sdk import process_exec, workspace_commit

def run():
    if process_exec()["returncode"] != 0:
        raise SystemExit(41)
    workspace_commit()
"""
            with self.assertRaisesRegex(KernelLaunchError, "commit_rejected"):
                run_workspace_command(
                    workspace,
                    runner_source=_runner_source_with_argv(
                        runner_source,
                        ["/bin/bash", "-c", script, "khaos"],
                    ),
                    workspace_write_scope=("allowed.txt",),
                    timeout_seconds=5,
                )

            self.assertFalse((workspace / "allowed.txt").exists())
            self.assertFalse((workspace / "unscoped.txt").exists())

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend and APFS",
    )
    def test_kernel_rejects_out_of_scope_modified_and_deleted_process_output(
        self,
    ) -> None:
        for name, command in (
            ("modified.txt", "printf changed > modified.txt"),
            ("deleted.txt", "rm deleted.txt"),
        ):
            with self.subTest(path=name), tempfile.TemporaryDirectory() as value:
                workspace = Path(value) / "workspace"
                workspace.mkdir()
                target = workspace / name
                target.write_text("original", encoding="utf-8")
                runner_source = """\
from khaos.runner_sdk import process_exec, workspace_commit

def run():
    if process_exec()["returncode"] != 0:
        raise SystemExit(41)
    workspace_commit()
"""
                with self.assertRaisesRegex(KernelLaunchError, "commit_rejected"):
                    run_workspace_command(
                        workspace,
                        runner_source=_runner_source_with_argv(
                            runner_source,
                            ["/bin/bash", "-c", command, "khaos"],
                        ),
                        workspace_read_scope=(name,),
                        workspace_write_scope=(),
                        timeout_seconds=5,
                    )

                self.assertEqual(target.read_text(encoding="utf-8"), "original")

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend and APFS",
    )
    def test_kernel_chain_blocks_disk_image_mount_and_commits_safe_output(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            workspace = root / "workspace"
            workspace.mkdir()
            mount_target = workspace / "mount-target"
            mount_target.mkdir()
            image = workspace / "attach-probe.sparsebundle"
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

            def detach_probe_image() -> None:
                info = _attached_image_info(image)
                if info is not None:
                    device = _whole_image_device(
                        _validated_entities(info.get("system-entities"))
                    )
                    _run_tool(_HDIUTIL, ("detach", device))
                elif mount_target.is_mount():
                    _run_tool(_HDIUTIL, ("detach", str(mount_target)))

            try:
                control = _run_tool(
                    _HDIUTIL,
                    (
                        "attach",
                        "-plist",
                        "-nobrowse",
                        "-mountpoint",
                        str(mount_target),
                        str(image),
                    ),
                )
                control_entities = _validated_entities(
                    plistlib.loads(control.stdout).get("system-entities")
                )
                control_device = _whole_image_device(control_entities)
                self.assertTrue(mount_target.is_mount())
                _run_tool(_HDIUTIL, ("detach", control_device))
                self.assertFalse(mount_target.is_mount())
                self.assertIsNone(_attached_image_info(image))

                try:
                    _run_tool(
                        _DISKUTIL,
                        (
                            "image",
                            "attach",
                            "--plist",
                            "--nobrowse",
                            "--mountPoint",
                            str(mount_target),
                            str(image),
                        ),
                    )
                    self.assertTrue(mount_target.is_mount())
                    diskutil_info = _attached_image_info(image)
                    self.assertIsNotNone(diskutil_info)
                    diskutil_device = _whole_image_device(
                        _validated_entities(diskutil_info.get("system-entities"))
                    )
                    _run_tool(_HDIUTIL, ("detach", diskutil_device))
                finally:
                    detach_probe_image()
                self.assertFalse(mount_target.is_mount())
                self.assertIsNone(_attached_image_info(image))

                script = """\
set -eu
test -d "$2"
printf '%s\\n' 'snapshot-image-present'
printf '%s' 'validated-output' > accepted.txt
exec /usr/bin/hdiutil attach -plist -nobrowse -mountpoint "$1" "$2"
"""
                result = run_workspace_command(
                    workspace,
                    [
                        "/bin/bash",
                        "-c",
                        script,
                        "khaos",
                        str(mount_target),
                        image.name,
                    ],
                    workspace_read_scope=(image.name,),
                    workspace_write_scope=("accepted.txt",),
                    timeout_seconds=30,
                )
            finally:
                detach_probe_image()

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "snapshot-image-present\n")
            self.assertRegex(
                result.stderr,
                "Device not configured|Operation not permitted|Permission denied",
            )
            self.assertFalse(mount_target.is_mount())
            self.assertIsNone(_attached_image_info(image))
            self.assertEqual(
                (workspace / "accepted.txt").read_text(encoding="utf-8"),
                "validated-output",
            )
            self.assertEqual((result.added, result.modified, result.deleted), (1, 0, 0))

            try:
                diskutil_result = run_workspace_command(
                    workspace,
                    [
                        _DISKUTIL,
                        "image",
                        "attach",
                        "--plist",
                        "--nobrowse",
                        "--mountPoint",
                        str(mount_target),
                        image.name,
                    ],
                    workspace_read_scope=(image.name,),
                    timeout_seconds=30,
                )
            finally:
                detach_probe_image()

            self.assertNotEqual(diskutil_result.returncode, 0)
            self.assertFalse(mount_target.is_mount())
            self.assertIsNone(_attached_image_info(image))
            self.assertEqual(
                (
                    diskutil_result.added,
                    diskutil_result.modified,
                    diskutil_result.deleted,
                ),
                (0, 0, 0),
            )

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_kernel_rejects_workspace_retargeted_after_launcher_open(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "original.txt").write_text("original", encoding="utf-8")
            moved = root / "selected-workspace"
            start_kernel = launcher_module._start_kernel

            def replace_before_kernel_start(
                selected_path: Path,
                bootstrap: str,
                workspace_root_fd: int,
                **broker_options: object,
            ) -> subprocess.Popen[bytes]:
                os.rename(selected_path, moved)
                selected_path.mkdir()
                return start_kernel(
                    selected_path,
                    bootstrap,
                    workspace_root_fd,
                    **broker_options,
                )

            with patch.object(
                launcher_module,
                "_start_kernel",
                side_effect=replace_before_kernel_start,
            ):
                with self.assertRaisesRegex(KernelLaunchError, "workspace_rejected"):
                    run_workspace_command(
                        workspace,
                        ["/bin/sh", "-c", "printf retargeted > selected.txt"],
                        timeout_seconds=5,
                    )

            self.assertEqual(
                (moved / "original.txt").read_text(encoding="utf-8"), "original"
            )
            self.assertFalse((moved / "selected.txt").exists())
            self.assertEqual(list(workspace.iterdir()), [])

    @unittest.skipUnless(sys.platform == "darwin", "requires POSIX directory descriptors")
    def test_launcher_rejects_retargeted_path_for_borrowed_workspace_descriptor(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "original.txt").write_text("original", encoding="utf-8")
            moved = root / "selected-workspace"
            descriptor = os.open(
                workspace,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_CLOEXEC,
            )
            try:
                os.rename(workspace, moved)
                workspace.mkdir()
                with patch.object(launcher_module, "_start_kernel") as start_kernel:
                    with self.assertRaisesRegex(
                        ValueError, "workspace is unavailable or changed"
                    ):
                        run_workspace_command(
                            workspace,
                            ["/bin/sh", "-c", "printf retargeted > selected.txt"],
                            workspace_root_fd=descriptor,
                        )
                    start_kernel.assert_not_called()
                self.assertGreater(os.fstat(descriptor).st_ino, 0)
            finally:
                os.close(descriptor)

            self.assertEqual(
                (moved / "original.txt").read_text(encoding="utf-8"), "original"
            )
            self.assertEqual(list(workspace.iterdir()), [])

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_runner_cannot_bypass_kernel_authority(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "allowed.txt").write_text("through kernel", encoding="utf-8")
            rename_peer = workspace / "rename-peer.txt"
            rename_peer.write_text("rename peer", encoding="utf-8")
            (workspace / "hidden.txt").write_text("not granted", encoding="utf-8")
            live_file = workspace / "allowed.txt"
            outside = root / "outside-secret.txt"
            outside.write_text("outside", encoding="utf-8")
            self.assertEqual(
                set(os.listdir(workspace)),
                {"allowed.txt", "hidden.txt", "rename-peer.txt"},
            )
            self.assertEqual(live_file.stat().st_size, len(b"through kernel"))

            clone_source = Path(sys.executable).resolve(strict=True)
            self.assertEqual(
                clone_source.stat().st_dev,
                workspace.stat().st_dev,
                "positive-control source and workspace must share a volume",
            )
            clonefileat = ctypes.CDLL(None, use_errno=True).fclonefileat
            clonefileat.argtypes = (
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint32,
            )
            clonefileat.restype = ctypes.c_int
            clone_control = root / "clone-positive-control"
            clone_source_fd = os.open(clone_source, os.O_RDONLY | os.O_CLOEXEC)
            try:
                clone_status = clonefileat(
                    clone_source_fd,
                    -2,
                    os.fsencode(clone_control),
                    0,
                )
            finally:
                os.close(clone_source_fd)
            self.assertEqual(clone_status, 0, os.strerror(ctypes.get_errno()))
            self.assertEqual(clone_control.stat().st_size, clone_source.stat().st_size)
            clone_control.unlink()

            renameatx_np = ctypes.CDLL(None, use_errno=True).renameatx_np
            renameatx_np.argtypes = (
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            )
            renameatx_np.restype = ctypes.c_int
            swap_left = root / "rename-swap-positive-left"
            swap_right = root / "rename-swap-positive-right"
            swap_left.write_text("left", encoding="utf-8")
            swap_right.write_text("right", encoding="utf-8")
            self.assertEqual(
                renameatx_np(
                    -2,
                    os.fsencode(swap_left),
                    -2,
                    os.fsencode(swap_right),
                    0x00000002,
                ),
                0,
                os.strerror(ctypes.get_errno()),
            )
            self.assertEqual(swap_left.read_text(encoding="utf-8"), "right")
            self.assertEqual(swap_right.read_text(encoding="utf-8"), "left")

            mach_library = ctypes.CDLL(None, use_errno=True)
            mach_port = ctypes.c_uint32
            bootstrap_port = mach_port.in_dll(
                mach_library, "bootstrap_port"
            ).value
            bootstrap_lookup = mach_library.bootstrap_look_up
            bootstrap_lookup.argtypes = (
                mach_port,
                ctypes.c_char_p,
                ctypes.POINTER(mach_port),
            )
            bootstrap_lookup.restype = ctypes.c_int32
            mach_service = b"com.apple.cfprefsd.agent"
            service_port = mach_port()
            self.assertEqual(
                bootstrap_lookup(
                    bootstrap_port, mach_service, ctypes.byref(service_port)
                ),
                0,
                "unconfined positive control could not resolve the Mach service",
            )
            self.assertGreater(service_port.value, 0)
            mach_library.mach_port_deallocate.argtypes = (
                mach_port,
                mach_port,
            )
            mach_library.mach_port_deallocate.restype = ctypes.c_int32
            self.assertEqual(
                mach_library.mach_port_deallocate(
                    mach_library.mach_task_self(), service_port
                ),
                0,
            )

            live_workspace_attack_helpers = """\
import ctypes

_native_renameatx_np = ctypes.CDLL(None, use_errno=True).renameatx_np
_native_renameatx_np.argtypes = (
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.c_uint,
)
_native_renameatx_np.restype = ctypes.c_int

_native_fclonefileat = ctypes.CDLL(None, use_errno=True).fclonefileat
_native_fclonefileat.argtypes = (
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.c_uint32,
)
_native_fclonefileat.restype = ctypes.c_int

def require_clone_denied(source, destination, code):
    source_fd = os.open(source, os.O_RDONLY | os.O_CLOEXEC)
    ctypes.set_errno(0)
    try:
        result = _native_fclonefileat(
            source_fd, -2, os.fsencode(destination), 0
        )
        error = ctypes.get_errno()
    finally:
        os.close(source_fd)
    if result == 0:
        raise SystemExit(code)
    if error not in (errno.EPERM, errno.EACCES):
        raise OSError(error, os.strerror(error))

def swap_error(source, destination):
    result = _native_renameatx_np(
        -2, os.fsencode(source), -2, os.fsencode(destination), 0x00000002
    )
    return 0 if result == 0 else ctypes.get_errno()

def require_swap_denied(source, destination, code):
    error = swap_error(source, destination)
    if error == 0:
        raise SystemExit(code)
    if error not in (errno.EPERM, errno.EACCES):
        raise OSError(error, os.strerror(error))
"""
            kernel_file = Path(__file__).resolve().parents[1] / "khaos" / "kernel" / "worker.py"
            kernel_contents = kernel_file.read_bytes()
            plugin_source = f"""\
import errno
import os
import signal
import threading
from pathlib import Path
import khaos
{live_workspace_attack_helpers}

from khaos.ipc import IPCProtocolError
from khaos.runner_sdk import fs_list, fs_read, process_exec, workspace_commit

package_root = Path(khaos.__file__).resolve().parents[1]

def require_denied(action):
    try:
        action()
    except OSError as exc:
        if exc.errno not in (errno.EPERM, errno.EACCES):
            raise
    else:
        raise SystemExit(51)

require_denied(lambda: os.listdir(package_root))
require_denied(
    lambda: (package_root / "AGENTS.md").read_text(encoding="utf-8")
)
require_clone_denied(
    {str(clone_source)!r}, {str(workspace / 'runner-cloned.txt')!r}, 60
)
require_denied(lambda: Path({str(live_file)!r}).write_text("runner-overwrite"))
require_denied(lambda: os.unlink({str(live_file)!r}))
require_denied(lambda: os.listdir({str(workspace)!r}))
require_denied(lambda: os.stat({str(live_file)!r}, follow_symlinks=False))
require_denied(
    lambda: os.rename(
        {str(live_file)!r}, {str(workspace / 'runner-renamed.txt')!r}
    )
)
require_swap_denied({str(live_file)!r}, {str(rename_peer)!r}, 52)
require_denied(
    lambda: Path({str(workspace / 'runner-created.txt')!r}).write_text("runner-create")
)
require_denied(lambda: Path({str(outside)!r}).write_text("runner-outside-write"))

mach_library = ctypes.CDLL(None, use_errno=True)
mach_port = ctypes.c_uint32
bootstrap_port = mach_port.in_dll(mach_library, "bootstrap_port").value
bootstrap_lookup = mach_library.bootstrap_look_up
bootstrap_lookup.argtypes = (
    mach_port, ctypes.c_char_p, ctypes.POINTER(mach_port)
)
bootstrap_lookup.restype = ctypes.c_int32
service_port = mach_port()
if bootstrap_lookup(
    bootstrap_port, b"com.apple.cfprefsd.agent", ctypes.byref(service_port)
) == 0:
    mach_library.mach_port_deallocate(mach_library.mach_task_self(), service_port)
    raise SystemExit(59)

try:
    os.kill(os.getppid(), signal.SIGKILL)
except OSError as exc:
    if exc.errno not in (errno.EPERM, errno.EACCES):
        raise
else:
    raise SystemExit(50)

if fs_read("allowed.txt") != b"through kernel":
    raise SystemExit(41)
if {{entry["name"] for entry in fs_list()}} != {{"allowed.txt"}}:
    raise SystemExit(42)
try:
    fs_read("../outside-secret.txt")
except IPCProtocolError:
    pass
else:
    raise SystemExit(43)
try:
    fs_read("hidden.txt")
except IPCProtocolError as exc:
    if "path_not_readable" not in str(exc):
        raise
else:
    raise SystemExit(48)
try:
    fs_list("hidden.txt")
except IPCProtocolError as exc:
    if "path_not_listable" not in str(exc):
        raise
else:
    raise SystemExit(49)
try:
    Path({str(live_file)!r}).read_text(encoding="utf-8")
except OSError:
    pass
else:
    raise SystemExit(44)
try:
    Path({str(outside)!r}).read_text(encoding="utf-8")
except OSError:
    pass
else:
    raise SystemExit(45)
try:
    Path({str(kernel_file)!r}).write_text("modified", encoding="utf-8")
except OSError:
    pass
else:
    raise SystemExit(46)
result = process_exec()
if result["returncode"] != 0:
    raise SystemExit(47)

swap_stop = threading.Event()
swap_ready = threading.Event()
commit_pending = threading.Event()
swap_race = {{"attempts": 0, "during_commit": 0, "error": None}}

def race_live_workspace_swap():
    while not swap_stop.is_set():
        error = swap_error({str(live_file)!r}, {str(rename_peer)!r})
        swap_race["attempts"] += 1
        if commit_pending.is_set():
            swap_race["during_commit"] += 1
        if error in (errno.EPERM, errno.EACCES):
            swap_ready.set()
            continue
        swap_race["error"] = error or "swap_succeeded"
        swap_stop.set()

swap_thread = threading.Thread(target=race_live_workspace_swap, daemon=True)
swap_thread.start()
if not swap_ready.wait(2):
    swap_stop.set()
    swap_thread.join()
    raise SystemExit(58)
commit_pending.set()
try:
    workspace_commit()
finally:
    swap_stop.set()
    swap_thread.join()
if (
    swap_race["during_commit"] == 0
    or swap_race["error"] is not None
):
    raise SystemExit(59)
"""
            command = f"""\
import errno
import os
from pathlib import Path
{live_workspace_attack_helpers}

def require_denied(action, code):
    try:
        action()
    except OSError as exc:
        if exc.errno not in (errno.EPERM, errno.EACCES):
            raise
    else:
        raise SystemExit(code)

require_denied(lambda: os.unlink({str(live_file)!r}), 55)
require_denied(lambda: os.listdir({str(workspace)!r}), 62)
require_denied(
    lambda: os.stat({str(live_file)!r}, follow_symlinks=False),
    63,
)
require_denied(
    lambda: os.rename(
        {str(live_file)!r}, {str(workspace / 'command-renamed.txt')!r}
    ),
    56,
)
require_clone_denied(
    {str(clone_source)!r}, {str(workspace / 'command-cloned.txt')!r}, 61
)
require_swap_denied({str(live_file)!r}, {str(rename_peer)!r}, 57)

Path("allowed.txt").write_text("sandbox-output", encoding="utf-8")
print("command-ran")
"""
            result = run_workspace_command(
                workspace,
                runner_source=_runner_source_with_argv(
                    plugin_source,
                    [
                        str(Path(sys.executable).resolve(strict=True)),
                        "-I",
                        "-S",
                        "-c",
                        command,
                    ],
                ),
                workspace_read_scope=("allowed.txt",),
                workspace_write_scope=("allowed.txt",),
                timeout_seconds=5,
            )

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "command-ran\n")
            self.assertEqual((result.added, result.modified, result.deleted), (0, 1, 0))
            self.assertEqual(
                live_file.read_text(encoding="utf-8"),
                "sandbox-output",
            )
            self.assertEqual(rename_peer.read_text(encoding="utf-8"), "rename peer")
            self.assertEqual(outside.read_text(encoding="utf-8"), "outside")
            self.assertFalse((workspace / "runner-created.txt").exists())
            self.assertFalse((workspace / "runner-renamed.txt").exists())
            self.assertFalse((workspace / "runner-cloned.txt").exists())
            self.assertFalse((workspace / "command-renamed.txt").exists())
            self.assertFalse((workspace / "command-cloned.txt").exists())
            self.assertEqual(kernel_file.read_bytes(), kernel_contents)

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_kernel_writes_only_explicit_files_and_runner_cannot_write_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            workspace = root / "workspace"
            workspace.mkdir()
            editable = workspace / "editable.txt"
            editable.write_bytes(b"before")
            protected = workspace / "protected.txt"
            protected.write_bytes(b"protected")
            outside = root / "outside.txt"
            outside.write_bytes(b"outside-canary")
            runner_source = f"""\\
import errno
from pathlib import Path
from khaos.ipc import IPCProtocolError
from khaos.runner_sdk import fs_write, process_exec, workspace_commit

def run():
    def require_direct_write_denied(path):
        try:
            Path(path).write_bytes(b"bypass")
        except OSError as exc:
            if exc.errno not in (errno.EPERM, errno.EACCES):
                raise
        else:
            raise SystemExit(51)

    require_direct_write_denied({str(editable)!r})
    require_direct_write_denied({str(outside)!r})
    try:
        fs_write("protected.txt", b"denied")
    except IPCProtocolError as exc:
        if "path_not_writable" not in str(exc):
            raise
    else:
        raise SystemExit(52)

    result = fs_write("editable.txt", b"after")
    if result["sha256"] != {hashlib.sha256(b"after").hexdigest()!r}:
        raise SystemExit(53)
    command = process_exec()
    if command["returncode"] != 0:
        raise SystemExit(54)
    workspace_commit()
    require_direct_write_denied({str(editable)!r})
    try:
        fs_write("editable.txt", b"late-write")
    except IPCProtocolError as error:
        if str(error) not in {
            "IPC pipe write failed",
            "IPC peer closed its input pipe",
        }:
            raise
    else:
        raise SystemExit(55)
    return 0
"""
            result = run_workspace_command(
                workspace,
                runner_source=_runner_source_with_argv(
                    runner_source, ["/usr/bin/true"]
                ),
                workspace_write_scope=("editable.txt",),
                timeout_seconds=5,
            )

            self.assertEqual(result.returncode, 0)
            self.assertEqual((result.added, result.modified, result.deleted), (0, 1, 0))
            self.assertEqual(editable.read_bytes(), b"after")
            self.assertEqual(protected.read_bytes(), b"protected")
            self.assertEqual(outside.read_bytes(), b"outside-canary")

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_runner_hang_after_commit_does_not_change_commit_result(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value) / "workspace"
            workspace.mkdir()
            committed = workspace / "committed.txt"
            runner_source = """\
from khaos.runner_sdk import fs_write, process_exec, workspace_commit

def run():
    fs_write("committed.txt", b"trusted-commit-result")
    result = process_exec()
    if result["returncode"] != 0:
        raise SystemExit(61)
    workspace_commit()
    while True:
        pass
"""
            result = run_workspace_command(
                workspace,
                runner_source=_runner_source_with_argv(
                    runner_source, ["/usr/bin/true"]
                ),
                workspace_write_scope=("committed.txt",),
                timeout_seconds=5,
            )

            self.assertEqual(result.returncode, 0)
            self.assertEqual((result.added, result.modified, result.deleted), (1, 0, 0))
            self.assertEqual(committed.read_bytes(), b"trusted-commit-result")

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_fixed_command_cannot_bypass_runner_read_scope(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value) / "workspace"
            workspace.mkdir()
            (workspace / "private-canary.txt").write_text(
                "fixed-command-read", encoding="utf-8"
            )
            runner_source = """\
from khaos.ipc import IPCProtocolError
from khaos.runner_sdk import fs_read, process_exec, workspace_commit

try:
    fs_read("private-canary.txt")
except IPCProtocolError as exc:
    if "path_not_readable" not in str(exc):
        raise
else:
    raise SystemExit(41)

result = process_exec()
if result["returncode"] != 0 or result["stdout"] != "read-denied\\n":
    raise SystemExit(42)
workspace_commit()
"""
            command = """\
import errno
import os
from pathlib import Path

try:
    Path('private-canary.txt').read_text(encoding='utf-8')
except OSError as exc:
    if exc.errno not in (errno.EPERM, errno.EACCES):
        raise
else:
    raise SystemExit(43)

try:
    os.rename('private-canary.txt', 'moved-private-canary.txt')
except OSError as exc:
    if exc.errno not in (errno.EPERM, errno.EACCES):
        raise
else:
    raise SystemExit(44)
print('read-denied')
"""
            result = run_workspace_command(
                workspace,
                runner_source=_runner_source_with_argv(
                    runner_source,
                    [
                        str(Path(sys.executable).resolve(strict=True)),
                        "-I",
                        "-S",
                        "-c",
                        command,
                    ],
                ),
                workspace_read_scope=(),
                timeout_seconds=5,
            )

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "read-denied\n")
            self.assertEqual(result.stderr, "")
            self.assertEqual((result.added, result.modified, result.deleted), (0, 0, 0))

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_fixed_command_reads_only_scoped_files_and_denies_link_escape(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value) / "workspace"
            source = workspace / "src"
            source.mkdir(parents=True)
            (source / "allowed.txt").write_text("scoped-data", encoding="utf-8")
            runnable = source / "run.sh"
            runnable.write_text("#!/bin/sh\nprintf 'script-ok\\n'\n", encoding="utf-8")
            runnable.chmod(0o755)
            (workspace / "allowed-file.txt").write_text(
                "file-scope", encoding="utf-8"
            )
            (workspace / "private-canary.txt").write_text(
                "must-not-be-read", encoding="utf-8"
            )
            case_alias_exists = (workspace / "PRIVATE-CANARY.TXT").exists()
            unicode_canary = "private-canary-\u00e9.txt"
            unicode_alias = "private-canary-e\u0301.txt"
            (workspace / unicode_canary).write_text(
                "unicode-secret", encoding="utf-8"
            )
            unicode_alias_exists = (workspace / unicode_alias).exists()
            nested = workspace / "nested"
            nested.mkdir()
            (nested / "allowed.txt").write_text(
                "nested-scope", encoding="utf-8"
            )
            (nested / "private-canary.txt").write_text(
                "nested-secret", encoding="utf-8"
            )
            (source / "alias.txt").symlink_to("../private-canary.txt")
            command = f"""\
import ctypes
import errno
import os
from pathlib import Path
import subprocess

def must_be_denied(path, code):
    try:
        Path(path).read_text(encoding='utf-8')
    except OSError as exc:
        if exc.errno not in (errno.EPERM, errno.EACCES):
            raise
        return
    raise SystemExit(code)

if Path('src/allowed.txt').read_text(encoding='utf-8') != 'scoped-data':
    raise SystemExit(41)
script = subprocess.run(
    ['src/run.sh'], check=True, capture_output=True, text=True
)
if script.stdout != 'script-ok\\n':
    raise SystemExit(46)
if Path('allowed-file.txt').read_text(encoding='utf-8') != 'file-scope':
    raise SystemExit(42)
must_be_denied('private-canary.txt', 43)
must_be_denied('src/alias.txt', 44)

try:
    os.replace('private-canary.txt', 'allowed-file.txt')
except OSError as exc:
    if exc.errno not in (errno.EPERM, errno.EACCES):
        raise
else:
    raise SystemExit(48)

if {case_alias_exists!r}:
    try:
        os.replace('PRIVATE-CANARY.TXT', 'allowed-file.txt')
    except OSError as exc:
        if exc.errno not in (errno.EPERM, errno.EACCES):
            raise
    else:
        raise SystemExit(53)

if {unicode_alias_exists!r}:
    try:
        os.replace({unicode_alias!r}, 'allowed-file.txt')
    except OSError as exc:
        if exc.errno not in (errno.EPERM, errno.EACCES):
            raise
    else:
        raise SystemExit(54)

renameatx_np = ctypes.CDLL(None, use_errno=True).renameatx_np
renameatx_np.argtypes = (
    ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint
)
renameatx_np.restype = ctypes.c_int
ctypes.set_errno(0)
if renameatx_np(
    -2, b'private-canary.txt', -2, b'allowed-file.txt', 0x00000002
) == 0:
    raise SystemExit(49)
if ctypes.get_errno() not in (errno.EPERM, errno.EACCES):
    raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()))

try:
    os.rename('nested', 'moved-nested')
except OSError as exc:
    if exc.errno not in (errno.EPERM, errno.EACCES):
        raise
else:
    Path('nested').mkdir()
    os.replace('moved-nested/private-canary.txt', 'nested/allowed.txt')
    if Path('nested/allowed.txt').read_text(encoding='utf-8') == 'nested-secret':
        raise SystemExit(50)

if Path('allowed-file.txt').read_text(encoding='utf-8') != 'file-scope':
    raise SystemExit(51)
if Path('nested/allowed.txt').read_text(encoding='utf-8') != 'nested-scope':
    raise SystemExit(52)
try:
    os.link('private-canary.txt', 'src/hardlink.txt')
except OSError as exc:
    if exc.errno not in (errno.EPERM, errno.EACCES):
        raise
else:
    must_be_denied('src/hardlink.txt', 47)
    Path('src/hardlink.txt').unlink()

allowed = Path('allowed-file.txt')
allowed.unlink()
allowed.symlink_to('private-canary.txt')
must_be_denied('allowed-file.txt', 45)
allowed.unlink()
allowed.write_text('file-scope', encoding='utf-8')
print('scoped-data:file-scope')
"""
            result = run_workspace_command(
                workspace,
                [
                    str(Path(sys.executable).resolve(strict=True)),
                    "-I",
                    "-S",
                    "-c",
                    command,
                ],
                workspace_read_scope=(
                    "src",
                    "allowed-file.txt",
                    "nested/allowed.txt",
                ),
                timeout_seconds=5,
            )

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "scoped-data:file-scope\n")
            self.assertEqual(result.stderr, "")
            self.assertEqual((result.added, result.modified, result.deleted), (0, 0, 0))

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_host_environment_sentinel_is_not_inherited_by_runner_or_command(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value) / "workspace"
            workspace.mkdir()
            secret_name = "KHAOS_TEST_HOST_ENV_SENTINEL"
            runner_source = f'''\
import os
from khaos.runner_sdk import process_exec, workspace_commit

if {secret_name!r} in os.environ:
    raise SystemExit(41)
result = process_exec()
if result["returncode"] != 0:
    raise SystemExit(42)
if result["stdout"] != "missing\\n" or result["stderr"]:
    raise SystemExit(43)
workspace_commit()
'''
            command = (
                "import os; print('present' if "
                f"{secret_name!r} in os.environ else 'missing')"
            )

            with patch.dict(os.environ, {secret_name: secrets.token_hex(24)}):
                result = run_workspace_command(
                    workspace,
                    runner_source=_runner_source_with_argv(
                        runner_source,
                        [
                            str(Path(sys.executable).resolve(strict=True)),
                            "-I",
                            "-S",
                            "-c",
                            command,
                        ],
                    ),
                    timeout_seconds=5,
                )

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "missing\n")
            self.assertEqual(result.stderr, "")
            self.assertEqual((result.added, result.modified, result.deleted), (0, 0, 0))

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_host_secret_pipe_descriptor_is_not_inherited_by_runner_or_command(
        self,
    ) -> None:
        secret = secrets.token_bytes(32)
        read_fd, write_fd = os.pipe()
        secret_fd = -1
        try:
            self.assertEqual(os.write(write_fd, secret), len(secret))
            os.close(write_fd)
            write_fd = -1
            secret_fd = fcntl.fcntl(read_fd, fcntl.F_DUPFD, 64)
            os.close(read_fd)
            read_fd = -1
            os.set_inheritable(secret_fd, True)

            with tempfile.TemporaryDirectory() as value:
                workspace = Path(value) / "workspace"
                workspace.mkdir()
                runner_source = f'''\
import errno
import os
from khaos.runner_sdk import process_exec, workspace_commit

try:
    os.fstat({secret_fd})
except OSError as error:
    if error.errno != errno.EBADF:
        raise
else:
    raise SystemExit(41)

result = process_exec()
if result["returncode"] != 0:
    raise SystemExit(42)
if result["stdout"] != "host-secret-fd=closed\\n" or result["stderr"]:
    raise SystemExit(43)
workspace_commit()
'''
                command = '''\
import errno
import os
import sys

try:
    os.fstat(int(sys.argv[1]))
except OSError as error:
    if error.errno != errno.EBADF:
        raise
else:
    raise SystemExit(51)
print("host-secret-fd=closed")
'''
                result = run_workspace_command(
                    workspace,
                    runner_source=_runner_source_with_argv(
                        runner_source,
                        [
                            str(Path(sys.executable).resolve(strict=True)),
                            "-I",
                            "-S",
                            "-c",
                            command,
                            str(secret_fd),
                        ],
                    ),
                    timeout_seconds=5,
                )

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "host-secret-fd=closed\n")
            self.assertEqual(result.stderr, "")
            self.assertEqual((result.added, result.modified, result.deleted), (0, 0, 0))
            self.assertEqual(os.read(secret_fd, len(secret)), secret)
        finally:
            for descriptor in (read_fd, write_fd, secret_fd):
                if descriptor >= 0:
                    os.close(descriptor)

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_workspace_root_descriptor_is_not_inherited_by_runner_or_command(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            workspace = root / "workspace"
            workspace.mkdir()
            fixture = workspace / "private-canary.txt"
            fixture.write_text("live workspace", encoding="utf-8")
            workspace_root_fd = -1
            low_descriptor = os.open(
                workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
            )
            try:
                workspace_root_fd = fcntl.fcntl(low_descriptor, fcntl.F_DUPFD, 200)
            finally:
                os.close(low_descriptor)
            os.set_inheritable(workspace_root_fd, True)

            runner_source = f'''\\
import errno
import os
from khaos.runner_sdk import process_exec, workspace_commit

def require_workspace_fd_closed():
    try:
        os.fstat({workspace_root_fd})
    except OSError as error:
        if error.errno != errno.EBADF:
            raise
    else:
        raise SystemExit(41)
    try:
        os.open("private-canary.txt", os.O_RDONLY, dir_fd={workspace_root_fd})
    except OSError as error:
        if error.errno != errno.EBADF:
            raise
    else:
        raise SystemExit(42)
    try:
        os.open(
            "fd-bypass.txt",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd={workspace_root_fd},
        )
    except OSError as error:
        if error.errno != errno.EBADF:
            raise
    else:
        raise SystemExit(43)

require_workspace_fd_closed()
result = process_exec()
if result["returncode"] != 0:
    raise SystemExit(44)
if result["stdout"] != "workspace-root-fd=closed\\n" or result["stderr"]:
    raise SystemExit(45)
workspace_commit()
'''
            command = f'''\\
import errno
import os
import sys

descriptor = int(sys.argv[1])
try:
    os.fstat(descriptor)
except OSError as error:
    if error.errno != errno.EBADF:
        raise
else:
    raise SystemExit(51)
try:
    os.open(
        "../fd-escape.txt",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
        dir_fd=descriptor,
    )
except OSError as error:
    if error.errno != errno.EBADF:
        raise
else:
    raise SystemExit(52)
print("workspace-root-fd=closed")
'''
            try:
                result = run_workspace_command(
                    workspace,
                    runner_source=_runner_source_with_argv(
                        runner_source,
                        [
                            str(Path(sys.executable).resolve(strict=True)),
                            "-I",
                            "-S",
                            "-c",
                            command,
                            str(workspace_root_fd),
                        ],
                    ),
                    workspace_root_fd=workspace_root_fd,
                    timeout_seconds=5,
                )
            finally:
                os.close(workspace_root_fd)

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "workspace-root-fd=closed\n")
            self.assertEqual(result.stderr, "")
            self.assertEqual((result.added, result.modified, result.deleted), (0, 0, 0))
            self.assertEqual(fixture.read_text(encoding="utf-8"), "live workspace")
            self.assertFalse((workspace / "fd-bypass.txt").exists())
            self.assertFalse((root / "fd-escape.txt").exists())

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_sandboxed_command_cannot_read_unconfined_process_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            workspace = root / "workspace"
            workspace.mkdir()
            marker = "--khaos-process-args-canary"
            argv_secret = secrets.token_hex(24)
            environment_name = "KHAOS_TEST_PROCESS_ARGS_SECRET"
            environment_secret = secrets.token_hex(24)
            canary_environment = {
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "HOME": str(root),
                "TMPDIR": str(root),
                "LC_ALL": "C",
                "PYTHONDONTWRITEBYTECODE": "1",
                environment_name: environment_secret,
            }
            canary = subprocess.Popen(
                (
                    str(Path(sys.executable).resolve(strict=True)),
                    "-I",
                    "-S",
                    "-c",
                    "import time; time.sleep(30)",
                    marker,
                    argv_secret,
                ),
                env=canary_environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            try:
                host_process_data = _process_argument_area(canary.pid)
                self.assertIn(argv_secret.encode(), host_process_data)
                self.assertIn(
                    f"{environment_name}={environment_secret}".encode(),
                    host_process_data,
                )

                command = """\
import ctypes
import errno
import sys

process_id = int(sys.argv[1])
sysctl = ctypes.CDLL(None, use_errno=True).sysctl
sysctl.argtypes = (
    ctypes.POINTER(ctypes.c_int), ctypes.c_uint, ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t,
)
sysctl.restype = ctypes.c_int
mib = (ctypes.c_int * 3)(1, 49, process_id)
size = ctypes.c_size_t(0)
if sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0:
    if ctypes.get_errno() not in (errno.EPERM, errno.EACCES):
        raise OSError(ctypes.get_errno(), "KERN_PROCARGS2 size query failed")
else:
    raise SystemExit("sandboxed command read host process metadata")
print("external-process-metadata=denied")
"""
                result = run_workspace_command(
                    workspace,
                    [
                        str(Path(sys.executable).resolve(strict=True)),
                        "-I",
                        "-S",
                        "-c",
                        command,
                        str(canary.pid),
                    ],
                    timeout_seconds=5,
                )
            finally:
                if canary.poll() is None:
                    canary.kill()
                canary.wait(timeout=5)

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "external-process-metadata=denied\n")
            self.assertEqual(result.stderr, "")
            self.assertEqual((result.added, result.modified, result.deleted), (0, 0, 0))

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_runner_cannot_obtain_kernel_task_ports(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value) / "workspace"
            workspace.mkdir()
            plugin_source = """\
import ctypes
import os
from khaos.runner_sdk import process_exec, workspace_commit

target = os.getppid()
libsystem = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
task_self = ctypes.c_uint.in_dll(libsystem, "mach_task_self_").value
deallocate = libsystem.mach_port_deallocate
deallocate.argtypes = (ctypes.c_uint, ctypes.c_uint)
deallocate.restype = ctypes.c_int
for name in ("task_for_pid", "task_read_for_pid", "task_inspect_for_pid"):
    get_task_port = getattr(libsystem, name)
    get_task_port.argtypes = (
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_uint),
    )
    get_task_port.restype = ctypes.c_int
    task_port = ctypes.c_uint(0)
    if get_task_port(task_self, target, ctypes.byref(task_port)) == 0:
        if task_port.value:
            deallocate(task_self, task_port.value)
        raise SystemExit(70)

if process_exec()["returncode"] != 0:
    workspace_commit()
    raise SystemExit(71)
workspace_commit()
"""
            result = run_workspace_command(
                workspace,
                runner_source=_runner_source_with_argv(
                    plugin_source,
                    ["/bin/sh", "-c", "printf task-port-denied > task-port.txt"],
                ),
                workspace_write_scope=("task-port.txt",),
                timeout_seconds=5,
            )

            self.assertEqual(result.returncode, 0)
            self.assertEqual((result.added, result.modified, result.deleted), (1, 0, 0))
            self.assertEqual(
                (workspace / "task-port.txt").read_text(encoding="utf-8"),
                "task-port-denied",
            )

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_runner_cannot_attach_to_kernel_process(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value) / "workspace"
            workspace.mkdir()
            plugin_source = """\
import ctypes
import os
from khaos.runner_sdk import process_exec, workspace_commit

if process_exec()["returncode"] != 0:
    workspace_commit()
    raise SystemExit(70)

target = os.getppid()
ptrace = ctypes.CDLL(None, use_errno=True).ptrace
ptrace.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int)
ptrace.restype = ctypes.c_int
if ptrace(14, target, None, 0) == 0:
    os.waitpid(target, os.WUNTRACED)
    if ptrace(11, target, ctypes.c_void_p(1), 0) == -1:
        ptrace(8, target, None, 0)
        raise SystemExit(71)
workspace_commit()
"""
            with self.assertRaisesRegex(KernelLaunchError, "runner_failed"):
                run_workspace_command(
                    workspace,
                    runner_source=_runner_source_with_argv(
                        plugin_source,
                        ["/bin/sh", "-c", "printf pending > ptrace-marker.txt"],
                    ),
                    timeout_seconds=5,
                )

            self.assertEqual(list(workspace.iterdir()), [])

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_sandboxed_output_metadata_is_denied_before_kernel_commit(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value) / "workspace"
            workspace.mkdir()
            script = """\
import ctypes
import errno
import os
from pathlib import Path

created = Path("created")
created.mkdir()
(created / "added.txt").write_text("sandbox data", encoding="utf-8")
try:
    os.chmod(created, 0o777)
except OSError as exc:
    if exc.errno not in (errno.EPERM, errno.EACCES):
        raise
else:
    raise SystemExit(41)
setxattr = ctypes.CDLL(None, use_errno=True).setxattr
setxattr.argtypes = (
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.c_uint32,
    ctypes.c_int,
)
setxattr.restype = ctypes.c_int
value = b"injected"
if setxattr(os.fsencode(created), b"com.khaos.runner", value, len(value), 0, 0) == 0:
    raise SystemExit(42)
error = ctypes.get_errno()
if error not in (errno.EPERM, errno.EACCES):
    raise OSError(error, os.strerror(error))
print("metadata-denied")
"""
            result = run_workspace_command(
                workspace,
                [
                    str(Path(sys.executable).resolve(strict=True)),
                    "-I",
                    "-S",
                    "-c",
                    script,
                ],
                workspace_write_scope=("created", "created/added.txt"),
                timeout_seconds=5,
            )

            created = workspace / "created"
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "metadata-denied\n")
            self.assertEqual(result.stderr, "")
            self.assertEqual(
                (result.added, result.modified, result.deleted), (2, 0, 0)
            )
            self.assertEqual(created.stat().st_mode & 0o777, 0o700)
            self.assertEqual((created / "added.txt").stat().st_mode & 0o777, 0o600)
            attributes = subprocess.run(
                ["/usr/bin/xattr", str(created)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            self.assertNotIn("com.khaos.runner", attributes)

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_kernel_rejects_new_symlink_from_sandbox_output(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            workspace = root / "workspace"
            workspace.mkdir()
            outside = root / "outside.txt"
            outside.write_text("protected", encoding="utf-8")
            script = """\
printf '%s' 'must-not-partially-commit' > safe-output.txt
ln -s "$1" new-link
printf '%s\\n' 'candidate-output-ready'
"""
            plugin_source = """\
from khaos.runner_sdk import process_exec, workspace_commit

def run():
    result = process_exec()
    workspace_commit()
    return result["returncode"]
"""
            with self.assertRaisesRegex(KernelLaunchError, "commit_rejected"):
                run_workspace_command(
                    workspace,
                    runner_source=_runner_source_with_argv(
                        plugin_source,
                        [
                            "/bin/bash",
                            "-c",
                            script,
                            "khaos",
                            str(outside),
                        ],
                    ),
                    timeout_seconds=5,
                )
            self.assertEqual(outside.read_text(encoding="utf-8"), "protected")
            self.assertFalse((workspace / "safe-output.txt").exists())
            self.assertFalse((workspace / "new-link").exists())

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_kernel_rejects_hardlinked_files_from_sandbox_output(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value) / "workspace"
            workspace.mkdir()
            output = workspace / "output"
            output.mkdir()
            (workspace / "baseline.txt").write_text("unchanged", encoding="utf-8")
            script = """\
set -eu
printf '%s' 'untrusted-data' > output/hardlink-source.txt
ln output/hardlink-source.txt output/hardlink-alias.txt
stat -f '%l' output/hardlink-source.txt
"""
            plugin_source = """\
from khaos.runner_sdk import process_exec, workspace_commit

def run():
    result = process_exec()
    if result["returncode"] != 0 or result["stdout"] != "2\\n":
        raise SystemExit(41)
    workspace_commit()
"""
            with self.assertRaisesRegex(KernelLaunchError, "commit_rejected"):
                run_workspace_command(
                    workspace,
                    runner_source=_runner_source_with_argv(
                        plugin_source, ["/bin/bash", "-c", script, "khaos"]
                    ),
                    workspace_read_scope=("output",),
                    timeout_seconds=5,
                )
            self.assertEqual(
                (workspace / "baseline.txt").read_text(encoding="utf-8"),
                "unchanged",
            )
            self.assertFalse((output / "hardlink-source.txt").exists())
            self.assertFalse((output / "hardlink-alias.txt").exists())

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_kernel_rejects_fifo_from_sandbox_output_without_partial_writeback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value) / "workspace"
            workspace.mkdir()
            output = workspace / "output"
            output.mkdir()
            baseline = workspace / "baseline.txt"
            baseline.write_text("unchanged", encoding="utf-8")
            script = """\
set -eu
printf '%s' 'must-not-partially-commit' > output/safe-output.txt
mkfifo output/injected-pipe
test -p output/injected-pipe
printf '%s\\n' 'special-output-ready'
"""
            plugin_source = """\
from khaos.runner_sdk import process_exec, workspace_commit

def run():
    result = process_exec()
    if result["returncode"] != 0 or result["stdout"] != "special-output-ready\\n":
        raise SystemExit(41)
    workspace_commit()
"""
            with self.assertRaisesRegex(KernelLaunchError, "commit_rejected"):
                run_workspace_command(
                    workspace,
                    runner_source=_runner_source_with_argv(
                        plugin_source, ["/bin/bash", "-c", script, "khaos"]
                    ),
                    workspace_read_scope=("output",),
                    timeout_seconds=5,
                )

            self.assertEqual(baseline.read_text(encoding="utf-8"), "unchanged")
            self.assertFalse((output / "safe-output.txt").exists())
            self.assertFalse((output / "injected-pipe").exists())

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_kernel_chain_rejects_unix_socket_output_before_partial_writeback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value) / "workspace"
            workspace.mkdir()
            output = workspace / "output"
            output.mkdir()
            baseline = workspace / "baseline.txt"
            baseline.write_text("unchanged", encoding="utf-8")
            script = """\
from pathlib import Path
import errno
import socket

endpoint = None
try:
    endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    endpoint.bind("output/injected.sock")
except OSError as error:
    if error.errno in (errno.EPERM, errno.EACCES):
        print("socket-create-denied")
    else:
        print(f"socket-create-error:{error.errno}")
else:
    Path("output/safe-output.txt").write_text("must-not-partially-commit")
    print("socket-created")
finally:
    if endpoint is not None:
        endpoint.close()
"""
            kernel_rejected_socket = False
            try:
                result = run_workspace_command(
                    workspace,
                    [
                        str(Path(sys.executable).resolve(strict=True)),
                        "-I",
                        "-S",
                        "-c",
                        script,
                    ],
                    workspace_read_scope=("output",),
                    timeout_seconds=5,
                )
            except KernelLaunchError as error:
                cause_chain = []
                cause = error.__cause__
                while cause is not None:
                    cause_chain.append(f"{type(cause).__name__}: {cause}")
                    cause = cause.__cause__
                self.assertIn(
                    "commit_rejected",
                    str(error),
                    f"unexpected Kernel launch failure cause chain: {cause_chain}",
                )
                kernel_rejected_socket = True

            if not kernel_rejected_socket:
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "socket-create-denied\n")
            self.assertEqual(baseline.read_text(encoding="utf-8"), "unchanged")
            self.assertFalse((output / "safe-output.txt").exists())
            self.assertFalse((output / "injected.sock").exists())

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_caller_cancellation_reaches_kernel_and_discards_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value) / "workspace"
            workspace.mkdir()
            cancellation = threading.Event()
            timer = threading.Timer(0.3, cancellation.set)
            timer.start()
            script = """\
import time
from pathlib import Path

Path("started.txt").write_text("started")
while True:
    time.sleep(1)
"""
            try:
                with self.assertRaisesRegex(KernelLaunchError, "process_cancelled"):
                    run_workspace_command(
                        workspace,
                        [
                            str(Path(sys.executable).resolve(strict=True)),
                            "-I",
                            "-S",
                            "-c",
                            script,
                        ],
                        timeout_seconds=10,
                        cancel_requested=cancellation.is_set,
                    )
            finally:
                timer.cancel()
                timer.join(timeout=2)

            self.assertTrue(cancellation.is_set())
            self.assertEqual(list(workspace.iterdir()), [])

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_caller_cancellation_during_snapshot_copy_reaches_kernel(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            workspace = Path(value) / "workspace"
            workspace.mkdir()
            input_name = "ipc-cancel-snapshot-input.bin"
            input_path = workspace / input_name
            input_size = 768 * 1024 * 1024
            chunk_size = 1024 * 1024
            expected_digest = hashlib.sha256()
            with input_path.open("wb") as output:
                for _ in range(input_size // chunk_size):
                    chunk = os.urandom(chunk_size)
                    output.write(chunk)
                    expected_digest.update(chunk)

            temporary_roots = {
                path.resolve(strict=True)
                for path in (
                    Path(tempfile.gettempdir()),
                    Path("/tmp"),
                    Path("/var/tmp"),
                )
                if path.exists()
            }
            existing_snapshots = {
                snapshot
                for root in temporary_roots
                for snapshot in root.glob("khaos-snapshot-*")
            }
            snapshot_copy_observed = threading.Event()
            stop_observer = threading.Event()

            def observe_partial_snapshot_copy() -> None:
                while not stop_observer.is_set():
                    for root in temporary_roots:
                        pattern = (
                            f"khaos-snapshot-*/volume/workspace/{input_name}"
                        )
                        for copied_path in root.glob(pattern):
                            try:
                                copied_size = copied_path.stat().st_size
                            except OSError:
                                continue
                            if 0 < copied_size < input_size:
                                snapshot_copy_observed.set()
                                return
                    stop_observer.wait(0.005)

            observer = threading.Thread(
                target=observe_partial_snapshot_copy,
                name="observe-private-snapshot-copy",
                daemon=True,
            )
            observer.start()
            command = [
                str(Path(sys.executable).resolve(strict=True)),
                "-I",
                "-S",
                "-c",
                "from pathlib import Path; "
                "Path('runner-started.txt').write_text('started')",
            ]
            try:
                with self.assertRaisesRegex(KernelLaunchError, "process_cancelled"):
                    run_workspace_command(
                        workspace,
                        command,
                        timeout_seconds=30,
                        cancel_requested=snapshot_copy_observed.is_set,
                    )
            finally:
                stop_observer.set()
                observer.join(timeout=2)

            self.assertFalse(observer.is_alive())
            self.assertTrue(
                snapshot_copy_observed.is_set(),
                "caller cancellation was not triggered by partial APFS snapshot progress",
            )
            actual_digest = hashlib.sha256()
            with input_path.open("rb") as source:
                while chunk := source.read(chunk_size):
                    actual_digest.update(chunk)
            self.assertEqual(actual_digest.digest(), expected_digest.digest())
            self.assertEqual(
                {entry.name for entry in workspace.iterdir()}, {input_name}
            )
            remaining_snapshots = {
                snapshot
                for root in temporary_roots
                for snapshot in root.glob("khaos-snapshot-*")
            }
            self.assertEqual(remaining_snapshots, existing_snapshots)

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_launcher_death_kills_command_descendant_and_discards_snapshot(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            workspace = root / "workspace"
            workspace.mkdir()
            token = f"khaos-disconnect-{secrets.token_hex(12)}"
            (workspace / "token.txt").write_text(token, encoding="utf-8")
            request_path = root / "request.json"
            command = [
                str(Path(sys.executable).resolve(strict=True)),
                "-I",
                "-S",
                "-c",
                "from pathlib import Path; import subprocess, sys, time; "
                "Path('uncommitted.txt').write_text('private snapshot output'); "
                "subprocess.Popen([sys.executable, '-I', '-S', '-c', "
                "'import time; time.sleep(20)', Path('token.txt').read_text()]); "
                "time.sleep(20)",
            ]
            request_path.write_text(
                json.dumps({"workspace": str(workspace), "argv": command}),
                encoding="utf-8",
            )
            package_root = Path(__file__).resolve().parents[1]
            bootstrap = (
                "import json, sys\n"
                "from pathlib import Path\n"
                f"sys.path.insert(0, {str(package_root)!r})\n"
                "from khaos.launcher import run_workspace_command\n"
                "request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
                "runner_source = (\n"
                "    'from khaos.runner_sdk import process_exec, workspace_commit\\n'\n"
                "    'def run():\\n'\n"
                "    f'    process_exec({tuple(request[\"argv\"])!r})\\n'\n"
                "    '    workspace_commit()\\n'\n"
                ")\n"
                "run_workspace_command(request['workspace'], runner_source=runner_source, "
                "workspace_read_scope=('token.txt',), timeout_seconds=25)\n"
            )
            caller = subprocess.Popen(
                (
                    str(Path(sys.executable).resolve(strict=True)),
                    "-I",
                    "-S",
                    "-c",
                    bootstrap,
                    str(request_path),
                ),
                cwd="/",
                env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
            )

            command_started = False
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if _matching_processes(token):
                        command_started = True
                        break
                    if caller.poll() is not None:
                        _, stderr = caller.communicate()
                        self.fail(
                            "launcher exited before process.exec became active: "
                            f"{stderr.decode('utf-8', 'replace')}"
                        )
                    time.sleep(0.05)
                self.assertTrue(
                    command_started,
                    "could not observe the uniquely marked sandbox command",
                )
                time.sleep(0.2)
                caller.send_signal(signal.SIGKILL)
                self.assertEqual(caller.wait(timeout=5), -signal.SIGKILL)

                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    remaining = _matching_processes(token)
                    if not remaining:
                        break
                    time.sleep(0.05)
                self.assertFalse(
                    _matching_processes(token),
                    "sandbox command descendant survived launcher pipe closure",
                )
                self.assertEqual(
                    {path.name for path in workspace.iterdir()}, {"token.txt"}
                )
                self.assertEqual(
                    (workspace / "token.txt").read_text(encoding="utf-8"), token
                )
            finally:
                if caller.poll() is None:
                    caller.kill()
                    caller.wait(timeout=5)
                if caller.stderr is not None:
                    caller.stderr.close()
                for process_id, _, process_group_id in _matching_processes(token):
                    try:
                        os.killpg(process_group_id, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_kernel_worker_death_cleans_command_group_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            workspace = root / "workspace"
            workspace.mkdir()
            token = f"khaos-worker-death-{secrets.token_hex(12)}"
            (workspace / "token.txt").write_text(token, encoding="utf-8")
            request_path = root / "request.json"
            result_path = root / "launcher-result.txt"
            command = [
                str(Path(sys.executable).resolve(strict=True)),
                "-I",
                "-S",
                "-c",
                "from pathlib import Path; import subprocess, sys, time; "
                "Path('uncommitted.txt').write_text('private snapshot output'); "
                "subprocess.Popen([sys.executable, '-I', '-S', '-c', "
                "'import time; time.sleep(40)', sys.argv[1]]); "
                "time.sleep(40)",
                token,
            ]
            request_path.write_text(
                json.dumps(
                    {
                        "workspace": str(workspace),
                        "argv": command,
                        "result": str(result_path),
                    }
                ),
                encoding="utf-8",
            )
            package_root = Path(__file__).resolve().parents[1]
            bootstrap = (
                "import json, sys\n"
                "from pathlib import Path\n"
                f"sys.path.insert(0, {str(package_root)!r})\n"
                "from khaos.launcher import KernelLaunchError, run_workspace_command\n"
                "request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
                "runner_source = (\n"
                "    'from khaos.runner_sdk import process_exec, workspace_commit\\n'\n"
                "    'def run():\\n'\n"
                "    f'    process_exec({tuple(request[\"argv\"])!r})\\n'\n"
                "    '    workspace_commit()\\n'\n"
                ")\n"
                "try:\n"
                "    run_workspace_command(request['workspace'], runner_source=runner_source, "
                "timeout_seconds=25)\n"
                "except KernelLaunchError as exc:\n"
                "    Path(request['result']).write_text(str(exc), encoding='utf-8')\n"
                "else:\n"
                "    Path(request['result']).write_text('completed', encoding='utf-8')\n"
            )
            caller = subprocess.Popen(
                (
                    str(Path(sys.executable).resolve(strict=True)),
                    "-I",
                    "-S",
                    "-c",
                    bootstrap,
                    str(request_path),
                ),
                cwd="/",
                env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
            )
            worker_pid: int | None = None
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    matches = _matching_processes(token)
                    leader = next(
                        (entry for entry in matches if entry[0] == entry[2]), None
                    )
                    if leader is not None:
                        _, worker_pid, _ = leader
                        break
                    if caller.poll() is not None:
                        _, stderr = caller.communicate()
                        self.fail(
                            "launcher exited before the sandbox command started: "
                            f"{stderr.decode('utf-8', 'replace')}"
                        )
                    time.sleep(0.05)
                self.assertIsNotNone(
                    worker_pid, "could not identify the command's Kernel worker"
                )
                assert worker_pid is not None
                self.assertEqual(os.getpgid(worker_pid), worker_pid)
                self.assertGreaterEqual(
                    len(_process_group_members(worker_pid)),
                    2,
                    "expected the isolated Runner to share the Kernel cleanup group",
                )

                os.kill(worker_pid, signal.SIGKILL)
                self.assertEqual(caller.wait(timeout=20), 0)
                self.assertEqual(result_path.read_text(encoding="utf-8"), "kernel_ipc_failed")

                deadline = time.monotonic() + 8
                while time.monotonic() < deadline and _matching_processes(token):
                    time.sleep(0.05)
                self.assertFalse(
                    _matching_processes(token),
                    "sandbox command descendant survived Kernel worker death",
                )
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline and _process_group_members(worker_pid):
                    time.sleep(0.05)
                self.assertFalse(
                    _process_group_members(worker_pid),
                    "Kernel worker process-group helper survived worker death",
                )
                self.assertEqual(
                    {path.name for path in workspace.iterdir()}, {"token.txt"}
                )
                self.assertEqual(
                    (workspace / "token.txt").read_text(encoding="utf-8"), token
                )
                temporary_parent = Path(tempfile.gettempdir()).resolve(strict=True)
                self.assertEqual(
                    list(temporary_parent.glob(f"khaos-snapshot-{worker_pid}-*")), []
                )
                image_info = subprocess.run(
                    ["/usr/bin/hdiutil", "info", "-plist"],
                    check=True,
                    capture_output=True,
                )
                inventory = plistlib.loads(image_info.stdout)
                self.assertFalse(
                    any(
                        isinstance(entry, dict)
                        and isinstance(entry.get("image-path"), str)
                        and Path(entry["image-path"]).parent.name.startswith(
                            f"khaos-snapshot-{worker_pid}-"
                        )
                        for entry in inventory.get("images", [])
                    ),
                    "Kernel worker APFS image remained attached",
                )
            finally:
                if caller.poll() is None:
                    caller.kill()
                    caller.wait(timeout=5)
                if caller.stderr is not None:
                    caller.stderr.close()
                for _, _, process_group_id in _matching_processes(token):
                    try:
                        os.killpg(process_group_id, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if worker_pid is not None:
                    try:
                        cleanup_abandoned_apfs_volumes(worker_pid)
                    except Exception:
                        pass

    def test_unsupported_platform_fails_closed_before_launch(self) -> None:
        with patch("khaos.launcher.sys.platform", "linux"):
            with self.assertRaisesRegex(KernelLaunchError, "sandbox_unavailable"):
                run_workspace_command("/tmp", ["true"])


if __name__ == "__main__":
    unittest.main()
