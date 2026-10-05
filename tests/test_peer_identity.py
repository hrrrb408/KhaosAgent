from __future__ import annotations

import ctypes
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import unittest

from khaos.ipc import (
    PROTOCOL_VERSION,
    IPCProtocolError,
    answer_ping,
    receive_frame,
    send_frame,
)
from khaos.launcher import _open_workspace_root, _start_kernel
from khaos.kernel.macos_seatbelt import (
    SANDBOX_EXECUTABLE,
    _python_runtime_paths,
    _snapshot_profile,
)
from khaos.kernel.peer_identity import (
    accept_local_peer_pid,
    local_peer_pid_listener,
)


_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_BOOTSTRAP_NOT_PRIVILEGED = 1100  # BOOTSTRAP_NOT_PRIVILEGED from <bootstrap.h>


class PeerIdentityTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "darwin", "requires LOCAL_PEERPID")
    def test_launcher_and_kernel_check_peer_pids_before_pipe_requests(self) -> None:
        with tempfile.TemporaryDirectory(prefix="khaos-kernel-") as value:
            workspace, workspace_root_fd = _open_workspace_root(value)
            bootstrap = (
                "import sys\n"
                f"sys.path.insert(0, {str(_PACKAGE_ROOT)!r})\n"
                "from khaos.kernel.worker import main\n"
                "raise SystemExit(main())\n"
            )
            try:
                process = _start_kernel(workspace, bootstrap, workspace_root_fd)
            finally:
                os.close(workspace_root_fd)
            try:
                self.assertIsNotNone(process.stdin)
                self.assertIsNotNone(process.stdout)
                answer_ping(
                    process.stdout.fileno(), process.stdin.fileno(), timeout_seconds=5
                )
                send_frame(
                    process.stdin.fileno(),
                    {
                        "version": PROTOCOL_VERSION,
                        "request_id": "a" * 32,
                        "operation": "invalid",
                        "payload": {},
                    },
                )
                response = receive_frame(process.stdout.fileno(), timeout_seconds=5)
                self.assertEqual(response["error"], {"code": "invalid_request"})
                self.assertEqual(process.wait(timeout=5), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()

    @unittest.skipUnless(sys.platform == "darwin", "requires LOCAL_PEERPID")
    def test_parent_and_runner_validate_each_others_real_pid(self) -> None:
        with tempfile.TemporaryDirectory(prefix="khaos-peer-") as value:
            directory = Path(value).resolve(strict=True)
            with local_peer_pid_listener(directory) as (listener, socket_path):
                script = (
                    "import os,sys\n"
                    f"sys.path.insert(0, {str(_PACKAGE_ROOT)!r})\n"
                    "from pathlib import Path\n"
                    "from khaos.kernel.peer_identity import verify_local_parent_pid\n"
                    "verify_local_parent_pid(Path(sys.argv[1]), int(sys.argv[2]))\n"
                )
                runner = subprocess.Popen(
                    (
                        sys.executable,
                        "-I",
                        "-S",
                        "-c",
                        script,
                        str(socket_path),
                        str(os.getpid()),
                    ),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    start_new_session=True,
                )
                accept_local_peer_pid(listener, runner.pid)
                self.assertEqual(runner.wait(timeout=5), 0)

    @unittest.skipUnless(sys.platform == "darwin", "requires LOCAL_PEERPID")
    def test_peer_pid_handshake_works_below_a_long_private_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="khaos-peer-") as value:
            directory = Path(value) / ("long-segment-" * 8)
            directory.mkdir(mode=0o700)
            self.assertGreater(len(os.fsencode(directory / "p")), 103)
            with local_peer_pid_listener(directory) as (listener, socket_path):
                script = (
                    "import os,sys\n"
                    f"sys.path.insert(0, {str(_PACKAGE_ROOT)!r})\n"
                    "from pathlib import Path\n"
                    "from khaos.kernel.peer_identity import verify_local_parent_pid\n"
                    "verify_local_parent_pid(Path(sys.argv[1]), int(sys.argv[2]))\n"
                )
                runner = subprocess.Popen(
                    (
                        sys.executable,
                        "-I",
                        "-S",
                        "-c",
                        script,
                        socket_path.name,
                        str(os.getpid()),
                    ),
                    cwd=directory,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    start_new_session=True,
                )
                accept_local_peer_pid(listener, runner.pid)
                self.assertEqual(runner.wait(timeout=5), 0)

    @unittest.skipUnless(sys.platform == "darwin", "requires LOCAL_PEERPID")
    def test_kernel_rejects_a_different_runner_pid(self) -> None:
        with tempfile.TemporaryDirectory(prefix="khaos-peer-") as value:
            directory = Path(value).resolve(strict=True)
            with local_peer_pid_listener(directory) as (listener, socket_path):
                script = (
                    "import array,socket,sys\n"
                    "client=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)\n"
                    "client.connect(sys.argv[1])\n"
                    "client.sendmsg([b'x'], [(socket.SOL_SOCKET, "
                    "socket.SCM_RIGHTS, array.array('i', [int(sys.argv[2])]))])\n"
                    "if client.recv(1): raise SystemExit(42)\n"
                )
                read_fd, write_fd = os.pipe()
                runner = subprocess.Popen(
                    (
                        sys.executable,
                        "-I",
                        "-S",
                        "-c",
                        script,
                        str(socket_path),
                        str(write_fd),
                    ),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    pass_fds=(write_fd,),
                    start_new_session=True,
                )
                os.close(write_fd)
                try:
                    with self.assertRaisesRegex(IPCProtocolError, "spawned Runner"):
                        accept_local_peer_pid(listener, runner.pid + 1)
                    self.assertEqual(runner.wait(timeout=5), 0)
                    os.set_blocking(read_fd, False)
                    self.assertEqual(os.read(read_fd, 1), b"")
                finally:
                    os.close(read_fd)

    @unittest.skipUnless(sys.platform == "darwin", "requires LOCAL_PEERPID")
    def test_runner_rejects_a_different_kernel_pid(self) -> None:
        with tempfile.TemporaryDirectory(prefix="khaos-peer-") as value:
            directory = Path(value).resolve(strict=True)
            with local_peer_pid_listener(directory) as (listener, socket_path):
                script = (
                    "import os,sys\n"
                    f"sys.path.insert(0, {str(_PACKAGE_ROOT)!r})\n"
                    "from pathlib import Path\n"
                    "from khaos.ipc import IPCProtocolError\n"
                    "from khaos.kernel.peer_identity import verify_local_parent_pid\n"
                    "try:\n"
                    "    verify_local_parent_pid(Path(sys.argv[1]), int(sys.argv[2]))\n"
                    "except IPCProtocolError:\n"
                    "    raise SystemExit(0)\n"
                    "raise SystemExit(41)\n"
                )
                runner = subprocess.Popen(
                    (
                        sys.executable,
                        "-I",
                        "-S",
                        "-c",
                        script,
                        str(socket_path),
                        str(os.getpid() + 1),
                    ),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    start_new_session=True,
                )
                accept_local_peer_pid(listener, runner.pid)
                self.assertEqual(runner.wait(timeout=5), 0)

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires real macOS Seatbelt and LOCAL_PEERPID",
    )
    def test_seatbelt_allows_only_peer_socket_and_still_denies_loopback(self) -> None:
        service_name = b"com.apple.coreservices.launchservicesd"
        launchd = ctypes.CDLL(None)
        bootstrap_port = ctypes.c_uint32.in_dll(launchd, "bootstrap_port").value
        service_port = ctypes.c_uint32()
        lookup = launchd.bootstrap_look_up
        lookup.argtypes = (
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_uint32),
        )
        lookup.restype = ctypes.c_int
        lookup_status = lookup(
            bootstrap_port, service_name, ctypes.byref(service_port)
        )
        deallocate = launchd.mach_port_deallocate
        deallocate.argtypes = (ctypes.c_uint32, ctypes.c_uint32)
        deallocate.restype = ctypes.c_int
        if lookup_status == 0:
            task_port = ctypes.c_uint32.in_dll(launchd, "mach_task_self_").value
            self.assertEqual(deallocate(task_port, service_port.value), 0)
        self.assertEqual(
            lookup_status,
            0,
            "the control process must resolve the active Mach service",
        )

        with tempfile.TemporaryDirectory(prefix="khaos-peer-sandbox-") as value:
            root = Path(value).resolve(strict=True)
            workspace = root / "w"
            scratch = root / "r"
            workspace.mkdir()
            scratch.mkdir()
            socket_path = scratch / "p"
            peer_listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            peer_listener.bind(str(socket_path))
            peer_listener.listen(1)
            peer_listener.settimeout(3)

            denied_socket_path = scratch / "other"
            denied_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            denied_socket.bind(str(denied_socket_path))
            denied_socket.listen(1)
            denied_socket.settimeout(0.05)

            internet_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            internet_listener.bind(("127.0.0.1", 0))
            internet_listener.listen(1)
            internet_listener.settimeout(0.05)

            executable = Path(sys.executable).resolve(strict=True)
            profile = _snapshot_profile(
                workspace,
                _python_runtime_paths(),
                executable=executable,
                additional_writable_roots=(scratch,),
                additional_unix_socket_paths=(socket_path,),
                readable_paths=(
                    _PACKAGE_ROOT,
                    _PACKAGE_ROOT / "khaos",
                    _PACKAGE_ROOT / "khaos" / "__init__.py",
                    _PACKAGE_ROOT / "khaos" / "ipc.py",
                    _PACKAGE_ROOT / "khaos" / "kernel",
                    _PACKAGE_ROOT / "khaos" / "kernel" / "__init__.py",
                    _PACKAGE_ROOT / "khaos" / "kernel" / "peer_identity.py",
                ),
            )
            script = f"""\
import errno
import ctypes
import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[4])
from khaos.kernel.peer_identity import verify_local_parent_pid

verify_local_parent_pid(Path(sys.argv[1]), os.getppid())

try:
    Path(sys.argv[4], "khaos/kernel/worker.py").read_text()
except OSError as exc:
    if exc.errno not in (errno.EPERM, errno.EACCES):
        raise SystemExit(45)
else:
    raise SystemExit(44)

try:
    socket.create_connection(("127.0.0.1", int(sys.argv[2])), timeout=1)
except OSError as exc:
    if exc.errno not in (errno.EPERM, errno.EACCES):
        raise SystemExit(42)
else:
    raise SystemExit(43)

try:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.connect(sys.argv[3])
except OSError as exc:
    if exc.errno not in (errno.EPERM, errno.EACCES):
        raise SystemExit(47)
else:
    connection.close()
    raise SystemExit(48)

library = ctypes.CDLL(None)
service_port = ctypes.c_uint32()
lookup = library.bootstrap_look_up
lookup.argtypes = (ctypes.c_uint32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32))
lookup.restype = ctypes.c_int
status = lookup(
    ctypes.c_uint32.in_dll(library, "bootstrap_port").value,
    sys.argv[5].encode("ascii"),
    ctypes.byref(service_port),
)
if status == 0:
    deallocate = library.mach_port_deallocate
    deallocate.argtypes = (ctypes.c_uint32, ctypes.c_uint32)
    deallocate.restype = ctypes.c_int
    deallocate(
        ctypes.c_uint32.in_dll(library, "mach_task_self_").value,
        service_port.value,
    )
    raise SystemExit(49)
if status != {_BOOTSTRAP_NOT_PRIVILEGED}:
    raise SystemExit(50)
print(f"mach-lookup-denied status={{status}}", file=sys.stderr)
"""
            runner = subprocess.Popen(
                (
                    str(SANDBOX_EXECUTABLE),
                    "-p",
                    profile,
                    str(executable),
                    "-I",
                    "-S",
                    "-c",
                    script,
                    str(socket_path),
                    str(internet_listener.getsockname()[1]),
                    str(denied_socket_path),
                    str(_PACKAGE_ROOT),
                    service_name.decode("ascii"),
                ),
                cwd=workspace,
                env={
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                    "HOME": str(scratch),
                    "TMPDIR": str(scratch),
                    "LC_ALL": "C",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
            )
            try:
                try:
                    connection, _ = peer_listener.accept()
                except TimeoutError:
                    _, stderr = runner.communicate(timeout=5)
                    self.fail(
                        "Runner failed before peer authentication: "
                        + stderr.decode(errors="replace")
                    )
                with connection:
                    peer_pid = struct.unpack(
                        "=i", connection.getsockopt(0, 2, 4)
                    )[0]
                self.assertEqual(peer_pid, runner.pid)
                _, stderr = runner.communicate(timeout=5)
                self.assertEqual(runner.returncode, 0, stderr.decode(errors="replace"))
                self.assertIn(
                    b"mach-lookup-denied status=1100",
                    stderr,
                )
                with self.assertRaises(TimeoutError):
                    internet_listener.accept()
                with self.assertRaises(TimeoutError):
                    denied_socket.accept()
            finally:
                peer_listener.close()
                denied_socket.close()
                internet_listener.close()
                if runner.poll() is None:
                    runner.kill()
                    runner.wait()


if __name__ == "__main__":
    unittest.main()
