"""Fail-closed macOS Seatbelt backend and diagnostic capability probe."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import ctypes
import errno
import json
import math
import os
from pathlib import Path
import selectors
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from typing import ContextManager

try:
    import resource
except ImportError:  # pragma: no cover - resource is unavailable on Windows
    resource = None

from ..ipc import (
    IPCProtocolError,
    PROTOCOL_VERSION,
    _encode,
    _require_pipe,
    is_valid_token,
    ping_peer,
)
from .workspace_changes import WorkspaceCommitError
from .workspace_snapshot import (
    SnapshotEntry,
    WorkspaceReadScope,
    WorkspaceWriteScope,
    WorkspaceSnapshot,
    WorkspaceSnapshotCancelled,
    WorkspaceSnapshotError,
    _validate_component,
    _open_absolute_directory,
    _volume_mountpoint,
    workspace_snapshot,
)


SANDBOX_EXECUTABLE = Path("/usr/bin/sandbox-exec")
_SYSTEM_READ_ROOTS = (
    Path("/System/Library"),
    Path("/usr/lib"),
    Path("/bin"),
    Path("/usr/bin"),
)
_MAX_COMMAND_ARGUMENTS = 128
_MAX_COMMAND_ARGUMENT_BYTES = 32 * 1024
_MAX_COMMAND_OUTPUT_BYTES = 8 * 1024
_MAX_COMMAND_TIMEOUT_SECONDS = 30.0
_COMMAND_FILE_SIZE_LIMIT = 536_870_912
_COMMAND_OPEN_FILE_LIMIT = 128
_COMMAND_PROCESS_COUNT_LIMIT_PER_UID = 1024
_MAX_SEATBELT_SCOPE_RULES = 8_192
_MAX_SEATBELT_SCOPE_RULE_BYTES = 1024 * 1024
_COMMAND_BOOTSTRAP = f"""\
import os
import resource
import sys

cpu_seconds = int(sys.argv[1])
limits = (
    (resource.RLIMIT_CORE, 0),
    (resource.RLIMIT_CPU, cpu_seconds),
    (resource.RLIMIT_FSIZE, {_COMMAND_FILE_SIZE_LIMIT}),
    (resource.RLIMIT_NOFILE, {_COMMAND_OPEN_FILE_LIMIT}),
    (resource.RLIMIT_NPROC, {_COMMAND_PROCESS_COUNT_LIMIT_PER_UID}),
)
for resource_id, value in limits:
    resource.setrlimit(resource_id, (value, value))
argv = sys.argv[2:]
os.execvpe(argv[0], argv, os.environ)
"""
_PROBE_SCRIPT = """\
import os
import sys

unpassed_fd = int(sys.argv[5])
try:
    os.fstat(unpassed_fd)
except OSError:
    pass
else:
    raise SystemExit(20)

import errno
import ctypes
import json
from pathlib import Path
import socket
import struct
import subprocess
import sys

workspace = Path(sys.argv[1])
outside = Path(sys.argv[2])
outside_write = Path(sys.argv[3])
port = int(sys.argv[4])
hardlink_target = Path(sys.argv[6])
kernel_file = Path(sys.argv[7])
protocol_version = int(sys.argv[8])
process_argv = json.loads(sys.argv[9])

def must_be_denied(action, exit_code):
    try:
        action()
    except OSError as exc:
        if exc.errno in (errno.EPERM, errno.EACCES):
            return
    raise SystemExit(exit_code)

def fork_must_be_denied():
    try:
        child_pid = os.fork()
    except OSError as exc:
        if exc.errno in (errno.EPERM, errno.EACCES):
            return
        raise SystemExit(28)
    if child_pid == 0:
        os._exit(0)
    os.waitpid(child_pid, 0)
    raise SystemExit(28)

def setxattr_must_be_denied():
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
    value = b"runner-metadata"
    if setxattr(
        os.fsencode(workspace / "visible.txt"),
        b"com.khaos.runner",
        value,
        len(value),
        0,
        0,
    ) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))

def receive_exact(size):
    data = bytearray()
    while len(data) < size:
        chunk = sys.stdin.buffer.read(size - len(data))
        if not chunk:
            raise SystemExit(17)
        data.extend(chunk)
    return bytes(data)

def exchange(operation, payload):
    request_id = os.urandom(16).hex()
    request = {
        "version": protocol_version,
        "request_id": request_id,
        "operation": operation,
        "payload": payload,
    }
    encoded = json.dumps(request, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(encoded) > 65536:
        raise SystemExit(29)
    sys.stdout.buffer.write(struct.pack("!I", len(encoded)) + encoded)
    sys.stdout.buffer.flush()
    response_size = struct.unpack("!I", receive_exact(4))[0]
    if response_size < 1 or response_size > 65536:
        raise SystemExit(30)
    response = json.loads(receive_exact(response_size).decode("utf-8"))
    if (
        not isinstance(response, dict)
        or set(response) != {"version", "request_id", "ok", "result"}
        or type(response["version"]) is not int
        or response["version"] != protocol_version
        or response["request_id"] != request_id
        or response["ok"] is not True
        or not isinstance(response["result"], dict)
    ):
        raise SystemExit(31)
    return response

frame_size = struct.unpack("!I", receive_exact(4))[0]
if frame_size < 1 or frame_size > 65536:
    raise SystemExit(18)
request = json.loads(receive_exact(frame_size).decode("utf-8"))
if (
    set(request) != {"version", "request_id", "operation", "payload"}
    or type(request["version"]) is not int
    or request["version"] != protocol_version
    or request["operation"] != "ping"
    or not isinstance(request["payload"], dict)
):
    raise SystemExit(19)
response = {
    "version": protocol_version,
    "request_id": request["request_id"],
    "ok": True,
    "result": {"nonce": request["payload"].get("nonce")},
}
payload = json.dumps(response, separators=(",", ":"), sort_keys=True).encode("utf-8")
sys.stdout.buffer.write(struct.pack("!I", len(payload)) + payload)
sys.stdout.buffer.flush()

try:
    if (workspace / "visible.txt").read_text() != "workspace-data":
        raise SystemExit(10)
except OSError as exc:
    print("workspace-read-error", type(exc).__name__, exc.errno, file=sys.stderr)
    raise SystemExit(11)

for path in (outside, workspace / "escape.txt"):
    must_be_denied(path.read_text, 12)

def open_kernel_for_writing():
    descriptor = os.open(kernel_file, os.O_WRONLY)
    os.close(descriptor)

must_be_denied(open_kernel_for_writing, 36)

try:
    if hardlink_target.read_text() != "hardlink-canary":
        raise SystemExit(25)
except OSError:
    raise SystemExit(26)

try:
    (workspace / "visible.txt").write_text("updated-in-snapshot")
    (workspace / "write-allowed.txt").write_text("new-snapshot-file")
    operations_dir = workspace / "operations"
    operations_dir.mkdir()
    first_name = operations_dir / "first.txt"
    second_name = operations_dir / "second.txt"
    first_name.write_text("rename-test")
    os.rename(first_name, second_name)
    second_name.unlink()
    operations_dir.rmdir()
except OSError:
    raise SystemExit(13)

must_be_denied(lambda: os.chmod(workspace / "visible.txt", 0o777), 21)
must_be_denied(setxattr_must_be_denied, 37)
must_be_denied(lambda: os.chmod(workspace, 0o777), 24)
fork_must_be_denied()
must_be_denied(
    lambda: subprocess.run((sys.executable, "-I", "-S", "-B", "-c", "pass")),
    27,
)
must_be_denied(lambda: os.execve("/usr/bin/true", ["true"], {}), 32)

try:
    os.link(hardlink_target, workspace / "outside-hardlink.txt")
except OSError as exc:
    if exc.errno not in (errno.EPERM, errno.EACCES):
        raise SystemExit(22)
else:
    try:
        (workspace / "outside-hardlink.txt").write_text("changed-outside")
    except OSError:
        pass
    raise SystemExit(22)

must_be_denied(
    lambda: (workspace / "escape.txt").write_text("changed-outside"),
    23,
)
must_be_denied(lambda: outside_write.write_text("modified"), 14)

try:
    socket.create_connection(("127.0.0.1", port), timeout=1)
except OSError as exc:
    if exc.errno not in (errno.EPERM, errno.EACCES):
        raise SystemExit(15)
else:
    raise SystemExit(16)

exec_response = exchange(
    "process.exec",
    {"argv": process_argv},
)
if exec_response["result"] != {
    "returncode": 0,
    "stdout": "exec-output\\n",
    "stderr": "",
}:
    raise SystemExit(32)

commit_response = exchange("workspace.commit", {})
if commit_response["result"] != {"added": 2, "modified": 1, "deleted": 0}:
    raise SystemExit(31)
"""


class SandboxUnavailable(RuntimeError):
    """The required real OS sandbox could not be proven on this host."""

    _DIAGNOSTIC_STAGES = frozenset(
        {
            "probe-child",
            "probe-readiness",
            "probe-snapshot",
            "probe-verification",
        }
    )

    def __init__(
        self,
        message: str,
        *,
        diagnostic_stage: str | None = None,
    ) -> None:
        if diagnostic_stage is not None and diagnostic_stage not in self._DIAGNOSTIC_STAGES:
            raise ValueError("sandbox diagnostic stage is invalid")
        self.diagnostic_stage = diagnostic_stage
        super().__init__(message)


class SandboxProbeIOError(OSError):
    """A path-free I/O stage from the real Seatbelt readiness probe."""

    _STAGES = frozenset(
        {
            "fixture_files",
            "fixture_root",
            "runtime",
            "temporary_cleanup",
            "temporary_create",
            "verification",
        }
    )

    def __init__(self, stage: str) -> None:
        if stage not in self._STAGES:
            raise ValueError("Seatbelt probe I/O stage is invalid")
        self.stage = stage
        super().__init__(stage)


@contextmanager
def _sandbox_probe_io_stage(stage: str) -> Iterator[None]:
    try:
        yield
    except SandboxProbeIOError:
        raise
    except OSError as exc:
        raise SandboxProbeIOError(stage) from exc


@contextmanager
def _seatbelt_probe_directory(parent: Path | None = None) -> Iterator[str]:
    temporary = None
    try:
        with _sandbox_probe_io_stage("temporary_create"):
            temporary = tempfile.TemporaryDirectory(
                prefix="khaos-seatbelt-probe-",
                dir=parent,
            )
            value = temporary.__enter__()
        yield value
    finally:
        if temporary is not None:
            with _sandbox_probe_io_stage("temporary_cleanup"):
                temporary.cleanup()


@contextmanager
def _seatbelt_probe_snapshot(
    snapshot_context: ContextManager[WorkspaceSnapshot],
) -> Iterator[WorkspaceSnapshot]:
    with ExitStack() as stack:
        try:
            snapshot = stack.enter_context(snapshot_context)
        except WorkspaceSnapshotCancelled:
            raise
        except WorkspaceSnapshotError as exc:
            raise SandboxUnavailable(
                "macOS Seatbelt snapshot readiness could not be verified",
                diagnostic_stage="probe-snapshot",
            ) from exc
        yield snapshot


def apply_workspace_commit_sandbox(
    snapshot: WorkspaceSnapshot,
    staging_path: Path,
    file_write_paths: tuple[tuple[str, ...], ...],
    create_unlink_paths: tuple[tuple[str, ...], ...],
) -> None:
    """Constrain the committer to validated live paths and private staging."""
    if sys.platform != "darwin":
        raise SandboxUnavailable("macOS Seatbelt is unsupported on this platform")
    if not isinstance(snapshot, WorkspaceSnapshot):
        raise SandboxUnavailable("workspace commit snapshot is unavailable")
    try:
        workspace = snapshot.source_root.resolve(strict=True)
        staging = staging_path.resolve(strict=True)
        staging_stat = staging.stat()
    except OSError as exc:
        raise SandboxUnavailable("workspace commit roots are unavailable") from exc
    if (
        not workspace.is_dir()
        or not staging.is_dir()
        or not stat.S_ISDIR(staging_stat.st_mode)
        or staging_stat.st_uid != os.geteuid()
        or stat.S_IMODE(staging_stat.st_mode) & 0o077
    ):
        raise SandboxUnavailable("workspace commit staging root is not private")

    executable = Path(sys.executable).resolve(strict=True)
    runtime_paths = _python_runtime_paths()
    if not any(executable.is_relative_to(path) for path in runtime_paths):
        raise SandboxUnavailable("Python runtime is outside the approved roots")
    profile = _snapshot_profile(
        workspace,
        runtime_paths,
        executable=executable,
        allow_workspace_write=False,
        workspace_write_paths=file_write_paths,
        workspace_create_unlink_paths=create_unlink_paths,
        allow_additional_full_write=True,
        additional_writable_roots=(staging,),
    )
    _apply_sandbox_profile(profile)


def _apply_sandbox_profile(profile: str) -> None:
    """Apply a Seatbelt profile to the current trusted one-shot process."""
    try:
        library = ctypes.CDLL("/usr/lib/libsandbox.dylib")
        apply = library.sandbox_init
        apply.argtypes = (
            ctypes.c_char_p,
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_char_p),
        )
        apply.restype = ctypes.c_int
        free_error = library.sandbox_free_error
        free_error.argtypes = (ctypes.c_void_p,)
        free_error.restype = None
        error = ctypes.c_char_p()
        status = apply(profile.encode("utf-8"), 0, ctypes.byref(error))
    except (AttributeError, OSError) as exc:
        raise SandboxUnavailable("macOS Seatbelt could not be applied") from exc
    if status != 0:
        try:
            raise SandboxUnavailable("macOS Seatbelt could not be applied")
        finally:
            if error.value is not None:
                free_error(ctypes.cast(error, ctypes.c_void_p))
    if error.value is not None:
        free_error(ctypes.cast(error, ctypes.c_void_p))


def probe_macos_seatbelt(
    *,
    cancel_requested: Callable[[], bool] | None = None,
    brokered_snapshot_mount_path: str | None = None,
    brokered_snapshot_storage_bytes: int | None = None,
) -> None:
    """Prove private snapshot writes and Kernel/outside-path denial in a child.

    This diagnostic is not a general command launcher. It must succeed before
    any later Seed execution path may rely on the macOS Seatbelt backend. The
    one-shot caller may cancel the probe through its workspace request.
    """
    if cancel_requested is not None and not callable(cancel_requested):
        raise ValueError("sandbox probe cancellation check must be callable")
    _raise_if_cancelled(cancel_requested)
    if sys.platform != "darwin":
        raise SandboxUnavailable("macOS Seatbelt is unsupported on this platform")
    if not SANDBOX_EXECUTABLE.is_file() or not os.access(
        SANDBOX_EXECUTABLE, os.X_OK
    ):
        raise SandboxUnavailable("macOS Seatbelt executable is unavailable")

    from .broker import serve_runner_execution, serve_workspace_commit

    with _sandbox_probe_io_stage("runtime"):
        executable = Path(sys.executable).resolve(strict=True)
        runtime_paths = _python_runtime_paths()
    if not any(executable.is_relative_to(path) for path in runtime_paths):
        raise SandboxUnavailable("Python runtime is outside the approved roots")

    # Place fixtures beside the mounted volume, not in its APFS filesystem. The
    # Broker lease also owns cleanup if the Kernel request is interrupted.
    probe_parent = None
    if brokered_snapshot_mount_path is not None:
        with _sandbox_probe_io_stage("temporary_create"):
            probe_parent = Path(brokered_snapshot_mount_path).resolve(
                strict=True
            ).parent
    with _seatbelt_probe_directory(probe_parent) as value:
        with _sandbox_probe_io_stage("fixture_root"):
            root = Path(value).resolve(strict=True)
            source = root / "source"
            source.mkdir(mode=0o700)
        with _sandbox_probe_io_stage("fixture_files"):
            (source / "visible.txt").write_text("workspace-data", encoding="utf-8")
            outside = root / "outside.txt"
            outside.write_text("outside-canary", encoding="utf-8")
            outside_write = root / "outside-write.txt"
            outside_write.write_text("outside-write-canary", encoding="utf-8")
            hardlink_target = root / "hardlink-target.txt"
            hardlink_target.write_text("hardlink-canary", encoding="utf-8")
            (source / "escape.txt").symlink_to(outside)

        # The product App Sandbox may itself deny local networking. The Runner's
        # connect attempt below must still be rejected by an OS sandbox layer.
        listener = _loopback_listener()
        try:
            _raise_if_cancelled(cancel_requested)
            if listener is not None:
                _prove_host_loopback(listener)
            _raise_if_cancelled(cancel_requested)
            unpassed_read_fd = -1
            unpassed_write_fd = -1
            try:
                unpassed_read_fd, unpassed_write_fd = os.pipe()
            except OSError as exc:
                if unpassed_read_fd >= 0:
                    os.close(unpassed_read_fd)
                if unpassed_write_fd >= 0:
                    os.close(unpassed_write_fd)
                raise SandboxUnavailable(
                    "macOS Seatbelt IPC channel is unavailable"
                ) from exc
            try:
                with _seatbelt_probe_snapshot(
                    workspace_snapshot(
                        source,
                        brokered_mount_path=brokered_snapshot_mount_path,
                        brokered_storage_bytes=brokered_snapshot_storage_bytes,
                        max_storage_bytes=(
                            brokered_snapshot_storage_bytes
                            if brokered_snapshot_storage_bytes is not None
                            else 128_000_000
                        ),
                        snapshot_name="seatbelt-probe",
                        cancel_requested=cancel_requested,
                    )
                ) as snapshot:
                    workspace = snapshot.path
                    snapshot_mode = workspace.stat().st_mode & 0o7777
                    visible_mode = (workspace / "visible.txt").stat().st_mode & 0o7777
                    profile = _snapshot_profile(
                        workspace,
                        runtime_paths,
                        executable=executable,
                        readable_paths=(hardlink_target,),
                    )
                    process_argv = (
                        str(executable),
                        "-I",
                        "-S",
                        "-B",
                        "-c",
                        "from pathlib import Path; "
                        "Path('command-output.txt').write_text('command-output'); "
                        "print('exec-output')",
                    )
                    process: subprocess.Popen[bytes] | None = None
                    try:
                        process = subprocess.Popen(
                            (
                                str(SANDBOX_EXECUTABLE),
                                "-p",
                                profile,
                                str(executable),
                                "-I",
                                "-S",
                                "-B",
                                "-c",
                                _PROBE_SCRIPT,
                                str(workspace),
                                str(outside),
                                str(outside_write),
                                str(
                                    listener.getsockname()[1]
                                    if listener is not None
                                    else 0
                                ),
                                str(unpassed_read_fd),
                                str(hardlink_target),
                                str(Path(__file__).resolve(strict=True)),
                                str(PROTOCOL_VERSION),
                                json.dumps(process_argv),
                            ),
                            cwd=workspace,
                            env={
                                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                                "PYTHONDONTWRITEBYTECODE": "1",
                            },
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL,
                            close_fds=True,
                            start_new_session=True,
                        )
                        os.close(unpassed_read_fd)
                        unpassed_read_fd = -1
                        os.close(unpassed_write_fd)
                        unpassed_write_fd = -1
                        if process.stdin is None or process.stdout is None:
                            raise IPCProtocolError(
                                "macOS Seatbelt IPC pipes are unavailable"
                            )
                        ping_peer(
                            process.stdout.fileno(),
                            process.stdin.fileno(),
                            timeout_seconds=3,
                        )
                        serve_runner_execution(
                            process.stdout.fileno(),
                            process.stdin.fileno(),
                            snapshot,
                            authorized_timeout_seconds=5,
                            timeout_seconds=3,
                            cancel_requested=cancel_requested,
                        )
                        changes = serve_workspace_commit(
                            process.stdout.fileno(),
                            process.stdin.fileno(),
                            snapshot,
                            workspace_write_scope=(
                                "visible.txt",
                                "write-allowed.txt",
                                "command-output.txt",
                            ),
                            timeout_seconds=3,
                            cancel_requested=cancel_requested,
                        )
                        process.stdin.close()
                        process.stdin = None
                        process.stdout.close()
                        process.stdout = None
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired as exc:
                        _kill_and_reap(process)
                        raise SandboxUnavailable(
                            "macOS Seatbelt IPC probe timed out",
                            diagnostic_stage="probe-child",
                        ) from exc
                    except (
                        IPCProtocolError,
                        OSError,
                        subprocess.SubprocessError,
                        WorkspaceCommitError,
                    ) as exc:
                        _kill_and_reap(process)
                        if cancel_requested is not None and cancel_requested():
                            raise SandboxedProcessError("process_cancelled") from None
                        raise SandboxUnavailable(
                            "macOS Seatbelt IPC probe could not execute",
                            diagnostic_stage="probe-child",
                        ) from exc
                    if process.returncode != 0:
                        raise SandboxUnavailable(
                            "macOS Seatbelt probe failed "
                            f"(exit {process.returncode}); execution must be refused",
                            diagnostic_stage="probe-child",
                        )
                    with _sandbox_probe_io_stage("verification"):
                        if (
                            (workspace / "visible.txt").read_text(encoding="utf-8")
                            != "updated-in-snapshot"
                            or (workspace / "write-allowed.txt").read_text(encoding="utf-8")
                            != "new-snapshot-file"
                            or (workspace / "command-output.txt").read_text(encoding="utf-8")
                            != "command-output"
                        ):
                            raise SandboxUnavailable(
                                "macOS Seatbelt probe could not write its private snapshot",
                                diagnostic_stage="probe-verification",
                            )
                        if (
                            workspace.stat().st_mode & 0o7777 != snapshot_mode
                            or (workspace / "visible.txt").stat().st_mode & 0o7777
                            != visible_mode
                        ):
                            raise SandboxUnavailable(
                                "macOS Seatbelt probe changed snapshot permissions",
                                diagnostic_stage="probe-verification",
                            )
                        if (
                            changes.added != 2
                            or changes.modified != 1
                            or changes.deleted != 0
                            or (source / "visible.txt").read_text(encoding="utf-8")
                            != "updated-in-snapshot"
                            or (source / "write-allowed.txt").read_text(encoding="utf-8")
                            != "new-snapshot-file"
                            or (source / "command-output.txt").read_text(encoding="utf-8")
                            != "command-output"
                        ):
                            raise SandboxUnavailable(
                                "trusted changeset commit did not apply the validated output",
                                diagnostic_stage="probe-verification",
                            )
                        if outside.read_text(encoding="utf-8") != "outside-canary":
                            raise SandboxUnavailable(
                                "Seatbelt or changeset commit changed an outside file",
                                diagnostic_stage="probe-verification",
                            )
                        if (
                            outside_write.read_text(encoding="utf-8")
                            != "outside-write-canary"
                            or hardlink_target.read_text(encoding="utf-8")
                            != "hardlink-canary"
                        ):
                            raise SandboxUnavailable(
                                "Seatbelt or changeset commit changed an outside canary",
                                diagnostic_stage="probe-verification",
                            )
            finally:
                if unpassed_read_fd >= 0:
                    os.close(unpassed_read_fd)
                if unpassed_write_fd >= 0:
                    os.close(unpassed_write_fd)
        finally:
            if listener is not None:
                listener.close()


def _kill_and_reap(process: subprocess.Popen[bytes] | None) -> None:
    """Stop the sandbox child without buffering attacker-controlled output."""
    if process is None:
        return
    for stream in (process.stdin, process.stdout):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
    process.stdin = None
    process.stdout = None
    if process.poll() is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    process.wait()


def _python_runtime_paths() -> tuple[Path, ...]:
    """Return only the interpreter files needed by isolated Python startup."""
    import sysconfig

    executable = Path(sys.executable).resolve(strict=True)
    stdlib_value = sysconfig.get_path("stdlib")
    if (
        not isinstance(stdlib_value, str)
        or not stdlib_value
        or not Path(stdlib_value).is_absolute()
    ):
        raise SandboxUnavailable("Python standard library path is unavailable")
    try:
        stdlib = Path(stdlib_value).resolve(strict=True)
    except OSError as exc:
        raise SandboxUnavailable("Python standard library path is unavailable") from exc
    if not stdlib.is_dir():
        raise SandboxUnavailable("Python standard library path is not a directory")

    required = [executable, stdlib]
    optional: list[Path] = []

    zip_library = stdlib.parent / (
        f"python{sys.version_info.major}{sys.version_info.minor}.zip"
    )
    if zip_library.is_file():
        optional.append(zip_library)

    shared_modules = sysconfig.get_config_var("DESTSHARED")
    if isinstance(shared_modules, str) and Path(shared_modules).is_absolute():
        optional.append(Path(shared_modules))

    library = sysconfig.get_config_var("LDLIBRARY")
    library_directory = sysconfig.get_config_var("LIBDIR")
    if isinstance(library, str) and library:
        library_path = Path(library)
        if not library_path.is_absolute() and isinstance(library_directory, str):
            library_path = Path(library_directory) / library_path
        if library_path.is_absolute():
            optional.append(library_path)

    framework_prefix = sysconfig.get_config_var("PYTHONFRAMEWORKPREFIX")
    framework_directory = sysconfig.get_config_var("PYTHONFRAMEWORKDIR")
    framework_name = sysconfig.get_config_var("PYTHONFRAMEWORK")
    framework_version = sysconfig.get_config_var("VERSION")
    if all(
        isinstance(value, str) and value
        for value in (
            framework_prefix,
            framework_directory,
            framework_name,
            framework_version,
        )
    ) and Path(framework_prefix).is_absolute():
        optional.append(
            Path(framework_prefix)
            / framework_directory
            / "Versions"
            / framework_version
            / framework_name
        )

    for prefix in {Path(sys.prefix), Path(sys.base_prefix)}:
        if prefix.is_absolute():
            if isinstance(framework_name, str) and framework_name:
                optional.append(prefix / framework_name)
            optional.append(
                prefix
                / "Resources"
                / "Python.app"
                / "Contents"
                / "MacOS"
                / "Python"
            )

    paths: list[Path] = []
    for value in (*required, *optional):
        try:
            path = value.resolve(strict=True)
        except OSError:
            if value in required:
                raise SandboxUnavailable("Python runtime path is unavailable")
            continue
        if (path.is_file() or path.is_dir()) and path not in paths:
            paths.append(path)
    if executable not in paths:
        raise SandboxUnavailable("Python executable path is unavailable")
    return tuple(paths)


def _python_runtime_exclusions() -> tuple[Path, ...]:
    """Exclude installed package trees, including symlinks inside stdlib."""
    import sysconfig

    stdlib_value = sysconfig.get_path("stdlib")
    if not isinstance(stdlib_value, str) or not stdlib_value:
        raise SandboxUnavailable("Python standard library path is unavailable")
    try:
        stdlib = Path(stdlib_value).resolve(strict=True)
        exclusions: list[Path] = []
        for key in ("purelib", "platlib"):
            value = sysconfig.get_path(key)
            if isinstance(value, str) and value:
                path = Path(value)
                if not path.is_absolute():
                    raise SandboxUnavailable("Python package path is not absolute")
                exclusions.append(path)
        exclusions.extend(
            child.absolute()
            for child in stdlib.iterdir()
            if child.name in {"site-packages", "dist-packages"}
        )
        exclusions.extend(
            path.resolve(strict=False)
            for path in tuple(exclusions)
        )
    except OSError as exc:
        raise SandboxUnavailable("Python runtime exclusions are unavailable") from exc
    return tuple(dict.fromkeys(exclusions))


def _snapshot_profile(
    workspace: Path,
    runtime_paths: tuple[Path, ...],
    *,
    executable: Path,
    allow_workspace_write: bool = True,
    workspace_write_paths: tuple[tuple[str, ...], ...] | None = None,
    workspace_create_unlink_paths: tuple[tuple[str, ...], ...] | None = None,
    allow_additional_full_write: bool = False,
    allow_same_sandbox_signals: bool = False,
    allow_process_fork: bool = False,
    allow_process_exec: bool = False,
    workspace_read_scope: WorkspaceReadScope = WorkspaceReadScope(()),
    workspace_write_scope: WorkspaceWriteScope = WorkspaceWriteScope(()),
    workspace_baseline: Mapping[tuple[str, ...], SnapshotEntry] | None = None,
    additional_writable_roots: tuple[Path, ...] = (),
    additional_unix_socket_paths: tuple[Path, ...] = (),
    readable_paths: tuple[Path, ...] = (),
) -> str:
    if type(allow_workspace_write) is not bool:
        raise SandboxUnavailable("sandbox workspace write policy is invalid")
    has_workspace_commit_scope = (
        workspace_write_paths is not None
        or workspace_create_unlink_paths is not None
    )
    workspace_entry_read_paths: tuple[tuple[str, ...], ...] = ()
    workspace_directory_read_paths: tuple[tuple[str, ...], ...] = ()
    if has_workspace_commit_scope:
        if allow_workspace_write:
            raise SandboxUnavailable("sandbox workspace write paths are invalid")
        try:
            for paths in (
                workspace_write_paths,
                workspace_create_unlink_paths,
            ):
                if paths is None:
                    continue
                if not isinstance(paths, tuple):
                    raise WorkspaceSnapshotError("invalid workspace paths")
                for path in paths:
                    if not isinstance(path, tuple):
                        raise WorkspaceSnapshotError("invalid workspace path")
                    for component in path:
                        _validate_component(component)
        except WorkspaceSnapshotError as exc:
            raise SandboxUnavailable("sandbox workspace write paths are invalid") from exc
        workspace_entry_read_paths = tuple(
            sorted(
                set(workspace_write_paths or ())
                | set(workspace_create_unlink_paths or ()),
                key=lambda value: (len(value), value),
            )
        )
        directory_paths = {()}
        for path in workspace_entry_read_paths:
            directory_paths.update(path[:index] for index in range(len(path)))
        workspace_directory_read_paths = tuple(
            sorted(directory_paths, key=lambda value: (len(value), value))
        )
        scope_rule_count = (
            len(workspace_write_paths or ())
            + len(workspace_create_unlink_paths or ())
            + len(workspace_entry_read_paths)
            + len(workspace_directory_read_paths)
        )
        if scope_rule_count > _MAX_SEATBELT_SCOPE_RULES:
            raise SandboxUnavailable("sandbox workspace commit scope exceeds limit")
    if type(allow_additional_full_write) is not bool:
        raise SandboxUnavailable("sandbox additional write policy is invalid")
    if type(allow_same_sandbox_signals) is not bool:
        raise SandboxUnavailable("sandbox signal policy is invalid")
    roots = [workspace.resolve(strict=True)]
    roots.extend(path.resolve(strict=True) for path in runtime_paths)
    roots.extend(
        root.resolve(strict=True) for root in _SYSTEM_READ_ROOTS if root.exists()
    )
    roots = list(dict.fromkeys(roots))
    runtime_exclusions = _python_runtime_exclusions()
    extra_writable_roots = tuple(
        dict.fromkeys(path.resolve(strict=True) for path in additional_writable_roots)
    )
    sandbox_roots = (roots[0], *extra_writable_roots)
    unix_socket_paths = tuple(
        dict.fromkeys(path.resolve(strict=True) for path in additional_unix_socket_paths)
    )
    readable_paths = tuple(
        dict.fromkeys(path.resolve(strict=True) for path in readable_paths)
    )
    if any(
        _paths_overlap(writable_root, read_root)
        for writable_root in extra_writable_roots
        for read_root in (*roots, *readable_paths)
    ):
        raise SandboxUnavailable(
            "sandbox writable root overlaps a read-only path"
        )
    if any(
        not any(path.is_relative_to(root) for root in sandbox_roots)
        for path in unix_socket_paths
    ):
        raise SandboxUnavailable(
            "local peer PID sockets must stay inside sandbox roots"
        )

    metadata_roots: set[Path] = {Path("/")}
    for root in (*roots, *extra_writable_roots, *readable_paths):
        metadata_roots.add(root)
        metadata_roots.update(root.parents)

    process_exec_paths = [executable.resolve(strict=True)]
    framework_executable = (
        Path(sys.prefix).resolve(strict=True)
        / "Resources"
        / "Python.app"
        / "Contents"
        / "MacOS"
        / "Python"
    )
    if framework_executable.is_file():
        resolved_framework_executable = framework_executable.resolve(strict=True)
        if resolved_framework_executable not in process_exec_paths:
            process_exec_paths.append(resolved_framework_executable)

    # Peer process-info can expose another process's argv through KERN_PROCARGS2.
    # Keep inspection self-only and allow only named runtime metadata sysctls.
    # Session syscalls stay denied if a future sandbox profile enables process-fork.
    rules = [
        "(version 1)",
        "(deny default)",
        "(deny process-info*)",
        "(deny syscall-unix (syscall-number SYS_mount))",
        "(deny syscall-unix (syscall-number SYS_unmount))",
        "(deny syscall-unix (syscall-number SYS_setsid))",
        "(deny syscall-unix (syscall-number SYS_setpgid))",
        "(allow process-info* (target self))",
        '(allow sysctl-read (sysctl-name '
        '"kern.bootargs" "kern.osproductversion" "kern.iossupportversion" '
        '"kern.osvariant_status" "hw.ephemeral_storage" "hw.pagesize_compat" '
        '"security.mac.lockdown_mode_state" "kern.ostype" "kern.hostname" '
        '"kern.osrelease" "kern.version" "hw.machine"))',
        '(allow file-read* file-write-data (literal "/dev/null"))',
        '(allow file-read* (literal "/dev/random"))',
        '(allow file-read* (literal "/dev/urandom"))',
        '(allow file-read-data (literal "/"))',
        '(allow file-read-metadata (literal "/"))',
    ]
    scoped_path_rule_count = scope_rule_count if has_workspace_commit_scope else 0
    scoped_path_rule_bytes = 0

    def append_scoped_path_rule(rule: str) -> None:
        nonlocal scoped_path_rule_count, scoped_path_rule_bytes
        scoped_path_rule_count += 1
        scoped_path_rule_bytes += len(rule.encode("utf-8")) + 1
        if (
            scoped_path_rule_count > _MAX_SEATBELT_SCOPE_RULES
            or scoped_path_rule_bytes > _MAX_SEATBELT_SCOPE_RULE_BYTES
        ):
            raise SandboxUnavailable("sandbox workspace path scope exceeds limit")
        rules.append(rule)

    if allow_same_sandbox_signals:
        rules.append("(allow signal (target same-sandbox))")
    if allow_process_fork:
        rules.append("(allow process-fork)")
    if allow_process_exec:
        rules.append("(allow process-exec)")
    else:
        rules.extend(
            f'(allow process-exec (literal "{_seatbelt_path(path)}"))'
            for path in process_exec_paths
        )
    rules.extend(
        f'(allow file-read-metadata (literal "{_seatbelt_path(path)}"))'
        for path in sorted(metadata_roots, key=str)
        if path != Path("/")
    )
    for root in roots:
        if root == roots[0] and (
            has_workspace_commit_scope or allow_process_exec
        ):
            # A committer can read only validated changeset entries. Commands
            # receive only the Kernel-retained workspace read scope below.
            continue
        escaped = _seatbelt_path(root)
        rules.extend(
            (
                f'(allow file-read* (subpath "{escaped}"))',
                f'(allow file-map-executable (subpath "{escaped}"))',
            )
        )
    if has_workspace_commit_scope:
        # The trusted committer reopens the named root to detect detached dirfds.
        # Exact ancestor directory reads permit path traversal to the workspace.
        for root in (roots[0], *extra_writable_roots):
            rules.extend(
                f'(allow file-read-data (literal "{_seatbelt_path(parent)}"))'
                for parent in root.parents
                if parent != Path("/")
            )
        for path in workspace_directory_read_paths:
            literal = roots[0].joinpath(*path)
            rule = f'(allow file-read-data (literal "{_seatbelt_path(literal)}"))'
            append_scoped_path_rule(rule)
        for path in workspace_entry_read_paths:
            literal = roots[0].joinpath(*path)
            rule = f'(allow file-read* (literal "{_seatbelt_path(literal)}"))'
            append_scoped_path_rule(rule)
    workspace_readable_roots: Mapping[tuple[str, ...], str] = {}
    command_workspace_baseline: Mapping[
        tuple[str, ...], SnapshotEntry
    ] = {}
    if allow_process_exec:
        if workspace_baseline is None:
            if workspace_read_scope.paths:
                raise SandboxUnavailable("sandbox workspace read scope is unavailable")
            workspace_baseline = {}
        command_workspace_baseline = workspace_baseline
        read_rules, workspace_readable_roots = _workspace_read_policy(
            roots[0], workspace_read_scope, workspace_baseline
        )
        for rule in read_rules:
            append_scoped_path_rule(rule)
        # Commands need stat on newly created output files. This exposes no
        # file contents and never grants metadata on an unreadable baseline.
        for path in workspace_write_scope.paths:
            if path not in workspace_baseline:
                target = roots[0].joinpath(*path)
                append_scoped_path_rule(
                    f'(allow file-read-metadata (literal "{_seatbelt_path(target)}"))'
                )
    rules.extend(
        f'(allow file-read* (literal "{_seatbelt_path(path)}"))'
        for path in readable_paths
    )
    rules.extend(
        f'(deny file-read* (subpath "{_seatbelt_path(path)}"))'
        for path in runtime_exclusions
    )
    rules.append("(deny file-write*)")
    if has_workspace_commit_scope:
        file_paths = tuple(
            dict.fromkeys(
                roots[0].joinpath(*path) for path in workspace_write_paths or ()
            )
        )
        create_unlink_paths = tuple(
            dict.fromkeys(
                roots[0].joinpath(*path)
                for path in workspace_create_unlink_paths or ()
            )
        )
        if any(
            not path.is_relative_to(roots[0])
            for path in (*file_paths, *create_unlink_paths)
        ):
            raise SandboxUnavailable("sandbox workspace write path escapes its root")
        for path in file_paths:
            rule = f'(allow file-write* (literal "{_seatbelt_path(path)}"))'
            append_scoped_path_rule(rule)
        for path in create_unlink_paths:
            rule = (
                f'(allow file-write-create file-write-unlink '
                f'(literal "{_seatbelt_path(path)}"))'
            )
            append_scoped_path_rule(rule)
    elif allow_workspace_write:
        rules.append(
            f'(allow file-write-data file-write-create file-write-unlink '
            f'(subpath "{_seatbelt_path(roots[0])}"))'
        )
    for root in extra_writable_roots:
        escaped = _seatbelt_path(root)
        rules.append(f'(allow file-read* (subpath "{escaped}"))')
        if allow_additional_full_write:
            rules.extend(
                (
                    f'(allow file-read* (literal "{escaped}"))',
                    f'(allow file-write* (subpath "{escaped}"))',
                    f'(allow file-write* (literal "{escaped}"))',
                    f'(allow file-write-flags (subpath "{escaped}"))',
                    f'(allow file-write-flags (literal "{escaped}"))',
                )
            )
        else:
            rules.append(
                f'(allow file-write-data file-write-create file-write-unlink '
                f'(subpath "{escaped}"))'
            )
    rules.append("(deny network*)")
    rules.extend(
        f'(allow network-outbound (literal "{_seatbelt_path(path)}"))'
        for path in unix_socket_paths
    )
    # Keep these last: the broad workspace write grant above must not reopen
    # movement of unreadable snapshot entries into a path with read authority.
    if allow_process_exec:
        for rule in _workspace_read_unlink_rules(
            roots[0], workspace_readable_roots, command_workspace_baseline
        ):
            append_scoped_path_rule(rule)
    return "".join(rules)


def _paths_overlap(left: Path, right: Path) -> bool:
    return left.is_relative_to(right) or right.is_relative_to(left)


def _workspace_read_policy(
    workspace: Path,
    scope: WorkspaceReadScope,
    baseline: Mapping[tuple[str, ...], SnapshotEntry],
) -> tuple[tuple[str, ...], Mapping[tuple[str, ...], str]]:
    """Build OS read rules and retain the safe roots those rules actually cover."""
    read_rules: set[str] = set()
    readable_roots: dict[tuple[str, ...], str] = {}
    for path in scope.paths:
        if not path:
            raise SandboxUnavailable("sandbox workspace read scope is invalid")
        safe_prefix = True
        for index in range(1, len(path) + 1):
            prefix = path[:index]
            entry = baseline.get(prefix)
            if entry is None:
                safe_prefix = False
                break
            if entry.kind == "symlink" or (
                index < len(path) and entry.kind != "directory"
            ):
                safe_prefix = False
                break
        if not safe_prefix:
            continue

        entry = baseline.get(path)
        if entry is None or entry.kind not in {"file", "directory"}:
            continue
        readable_roots[path] = entry.kind

        for index in range(1, len(path)):
            parent = workspace.joinpath(*path[:index])
            read_rules.add(
                f'(allow file-read-metadata (literal "{_seatbelt_path(parent)}"))'
            )
        target = workspace.joinpath(*path)
        rule_kind = "subpath" if entry.kind == "directory" else "literal"
        read_rules.add(
            f'(allow file-read* ({rule_kind} "{_seatbelt_path(target)}"))'
        )
        read_rules.add(
            f'(allow file-map-executable ({rule_kind} "{_seatbelt_path(target)}"))'
        )
    return tuple(sorted(read_rules)), readable_roots


def _workspace_read_unlink_rules(
    workspace: Path,
    readable_roots: Mapping[tuple[str, ...], str],
    baseline: Mapping[tuple[str, ...], SnapshotEntry],
) -> Iterator[str]:
    """Stop renames from moving unreadable baseline data under allowed paths."""
    if not readable_roots:
        yield f'(deny file-write-unlink (subpath "{_seatbelt_path(workspace)}"))'
        return

    protected_ancestors = {
        root[:index]
        for root in readable_roots
        for index in range(1, len(root))
        if baseline.get(root[:index]) is not None
        and baseline[root[:index]].kind == "directory"
    }

    def is_readable(path: tuple[str, ...]) -> bool:
        return any(
            path == root
            or (
                kind == "directory"
                and len(path) > len(root)
                and path[: len(root)] == root
            )
            for root, kind in readable_roots.items()
        )

    blocked_subtrees: set[tuple[str, ...]] = set()
    entries = sorted(baseline.items(), key=lambda item: (len(item[0]), item[0]))
    for path, entry in entries:
        if not path or any(
            path[:index] in blocked_subtrees for index in range(1, len(path))
        ):
            continue

        literal = _seatbelt_path(workspace.joinpath(*path))
        if path in protected_ancestors:
            yield f'(deny file-write-unlink (literal "{literal}"))'
        elif entry.kind == "directory":
            if not is_readable(path):
                yield f'(deny file-write-unlink (subpath "{literal}"))'
                blocked_subtrees.add(path)
        elif not is_readable(path):
            yield f'(deny file-write-unlink (literal "{literal}"))'


def _seatbelt_path(path: Path) -> str:
    value = str(path)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise SandboxUnavailable("sandbox path contains unsupported characters")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _loopback_listener() -> socket.socket | None:
    """Return None only when OS policy denies opening a loopback listener."""
    listener = None
    try:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(1)
        return listener
    except OSError as exc:
        if listener is not None:
            listener.close()
        if exc.errno in (errno.EACCES, errno.EPERM):
            return None
        raise SandboxUnavailable(
            "loopback prerequisite for Seatbelt probe is unavailable"
        ) from exc


@dataclass(frozen=True, slots=True)
class SandboxedProcessResult:
    returncode: int
    stdout: str
    stderr: str


class SandboxedProcessError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _raise_if_cancelled(
    cancel_requested: Callable[[], bool] | None,
) -> None:
    if cancel_requested is not None and cancel_requested():
        raise SandboxedProcessError("process_cancelled")


def run_sandboxed_process(
    snapshot: WorkspaceSnapshot,
    argv: Sequence[str],
    *,
    timeout_seconds: float,
    workspace_read_scope: WorkspaceReadScope | Sequence[str] = (),
    workspace_write_scope: WorkspaceWriteScope | Sequence[str] = (),
    cancel_requested: Callable[[bool], bool] | None = None,
    process_started_fd: int | None = None,
    workspace_request_id: str | None = None,
    process_finished: Callable[[int], None] | None = None,
) -> SandboxedProcessResult:
    """Run one scoped command in the snapshot; output remains untrusted."""
    if sys.platform != "darwin" or resource is None:
        raise SandboxedProcessError("sandbox_unavailable")
    if not isinstance(snapshot, WorkspaceSnapshot):
        raise TypeError("sandboxed process requires a trusted workspace snapshot")
    if (
        type(snapshot.storage_limit_bytes) is not int
        or snapshot.storage_limit_bytes < 1
        or snapshot.source_mount_point is None
        or snapshot.snapshot_mount_point is None
        or snapshot.source_mount_point == snapshot.snapshot_mount_point
    ):
        raise SandboxedProcessError("sandbox_unavailable")
    command, timeout = validate_command_request(argv, timeout_seconds)
    try:
        read_scope = WorkspaceReadScope.from_paths(
            workspace_read_scope,
            max_depth=snapshot.max_depth,
        )
    except WorkspaceSnapshotError as exc:
        raise SandboxedProcessError("invalid_workspace_read_scope") from exc
    try:
        write_scope = WorkspaceWriteScope.from_paths(
            workspace_write_scope,
            max_depth=snapshot.max_depth,
        )
    except WorkspaceSnapshotError as exc:
        raise SandboxedProcessError("invalid_workspace_write_scope") from exc
    lifecycle_reporting = (
        process_started_fd is not None,
        workspace_request_id is not None,
        process_finished is not None,
    )
    if any(lifecycle_reporting) and not all(lifecycle_reporting):
        raise SandboxedProcessError("sandbox_execution_failed")
    if process_finished is not None and not callable(process_finished):
        raise SandboxedProcessError("sandbox_execution_failed")
    start_notification = None
    if process_started_fd is not None:
        if not is_valid_token(workspace_request_id):
            raise SandboxedProcessError("sandbox_execution_failed")
        import threading

        # Python's preexec_fn can deadlock after fork if other threads exist.
        if threading.active_count() != 1:
            raise SandboxedProcessError("sandbox_execution_failed")
        try:
            _require_pipe(process_started_fd, os.O_WRONLY)
            start_notification = _process_started_notification(
                process_started_fd, workspace_request_id
            )
        except IPCProtocolError as exc:
            raise SandboxedProcessError("sandbox_execution_failed") from exc
    if not SANDBOX_EXECUTABLE.is_file() or not os.access(
        SANDBOX_EXECUTABLE, os.X_OK
    ):
        raise SandboxedProcessError("sandbox_unavailable")

    executable = Path(sys.executable).resolve(strict=True)
    runtime_paths = _python_runtime_paths()
    if not any(executable.is_relative_to(path) for path in runtime_paths):
        raise SandboxedProcessError("sandbox_unavailable")

    try:
        workspace = snapshot.path.resolve(strict=True)
        if not workspace.is_dir():
            raise SandboxedProcessError("sandbox_unavailable")
        workspace_fd = -1
        source_fd = -1
        try:
            workspace_fd = _open_absolute_directory(workspace)
            source_fd = _open_absolute_directory(snapshot.source_root)
            if (
                os.fstat(workspace_fd).st_dev == os.fstat(source_fd).st_dev
                or _volume_mountpoint(workspace_fd)
                != snapshot.snapshot_mount_point
                or _volume_mountpoint(source_fd) != snapshot.source_mount_point
            ):
                raise SandboxedProcessError("sandbox_unavailable")
        finally:
            if source_fd >= 0:
                os.close(source_fd)
            if workspace_fd >= 0:
                os.close(workspace_fd)
        with tempfile.TemporaryDirectory(
            prefix="khaos-command-", dir=workspace.parent
        ) as scratch_value:
            scratch = Path(scratch_value).resolve(strict=True)
            profile = _snapshot_profile(
                workspace,
                runtime_paths,
                executable=executable,
                allow_same_sandbox_signals=True,
                allow_process_fork=True,
                allow_process_exec=True,
                workspace_read_scope=read_scope,
                workspace_write_scope=write_scope,
                workspace_baseline=snapshot.baseline,
                additional_writable_roots=(scratch,),
            )
            process = subprocess.Popen(
                (
                    str(SANDBOX_EXECUTABLE),
                    "-p",
                    profile,
                    str(executable),
                    "-I",
                    "-S",
                    "-B",
                    "-c",
                    _COMMAND_BOOTSTRAP,
                    str(max(1, math.ceil(timeout)) + 1),
                    *command,
                ),
                cwd=workspace,
                env={
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                    "HOME": str(scratch),
                    # Seatbelt intentionally hides ancestor directory entries;
                    # provide the private cwd so shells need not reconstruct it.
                    "PWD": str(workspace),
                    "TMPDIR": str(scratch),
                    "LC_ALL": "C",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
                pass_fds=(process_started_fd,) if start_notification else (),
                preexec_fn=start_notification,
            )
            try:
                returncode, stdout, stderr = _collect_sandbox_output(
                    process, timeout, cancel_requested=cancel_requested
                )
            finally:
                if process_finished is not None:
                    process_finished(process.pid)
    except SandboxedProcessError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise SandboxedProcessError("sandbox_execution_failed") from exc

    return SandboxedProcessResult(
        returncode=returncode,
        stdout=stdout.decode("utf-8", "replace"),
        stderr=stderr.decode("utf-8", "replace"),
    )


def _process_started_notification(
    write_fd: int,
    request_id: str,
) -> Callable[[], None]:
    template = _encode(
        {
            "version": PROTOCOL_VERSION,
            "request_id": request_id,
            "event": "process_started",
            "payload": {"process_group_id": "00000000"},
        }
    )
    marker = b'"00000000"'
    if template.count(marker) != 1 or len(template) > 512:
        raise IPCProtocolError("Kernel process start event is invalid")
    prefix, suffix = template.split(marker)

    def notify_before_exec() -> None:
        process_id = os.getpid()
        if not 0 < process_id <= 0xFFFFFFFF:
            raise OSError("sandbox process identity is invalid")
        frame = prefix + f'"{process_id:08x}"'.encode("ascii") + suffix
        try:
            while True:
                try:
                    written = os.write(write_fd, frame)
                    break
                except InterruptedError:
                    continue
            if written != len(frame):
                raise OSError("Kernel process start event was incomplete")
        finally:
            os.close(write_fd)

    return notify_before_exec


def validate_command_request(
    argv: Sequence[str], timeout_seconds: float
) -> tuple[tuple[str, ...], float]:
    """Apply the one canonical size and timeout policy before dispatch or spawn."""
    return _validated_argv(argv), validate_command_timeout(timeout_seconds)


def _validated_argv(argv: Sequence[str]) -> tuple[str, ...]:
    if (
        isinstance(argv, (str, bytes))
        or not isinstance(argv, Sequence)
        or not 1 <= len(argv) <= _MAX_COMMAND_ARGUMENTS
        or any(type(argument) is not str or "\0" in argument for argument in argv)
    ):
        raise SandboxedProcessError("invalid_arguments")
    try:
        total_bytes = sum(len(argument.encode("utf-8")) + 1 for argument in argv)
    except UnicodeEncodeError as exc:
        raise SandboxedProcessError("invalid_arguments") from exc
    if total_bytes > _MAX_COMMAND_ARGUMENT_BYTES:
        raise SandboxedProcessError("invalid_arguments")
    return tuple(argv)


def validate_command_timeout(timeout_seconds: float) -> float:
    """Validate the trusted per-run limit retained for Runner commands."""
    if isinstance(timeout_seconds, bool) or not isinstance(
        timeout_seconds, (int, float)
    ):
        raise SandboxedProcessError("invalid_timeout")
    try:
        timeout = float(timeout_seconds)
    except OverflowError as exc:
        raise SandboxedProcessError("invalid_timeout") from exc
    if (
        not math.isfinite(timeout)
        or timeout <= 0
        or timeout > _MAX_COMMAND_TIMEOUT_SECONDS
    ):
        raise SandboxedProcessError("invalid_timeout")
    return timeout


def _collect_sandbox_output(
    process: subprocess.Popen[bytes],
    timeout_seconds: float,
    *,
    cancel_requested: Callable[[bool], bool] | None = None,
) -> tuple[int, bytes, bytes]:
    if process.stdout is None or process.stderr is None:
        _kill_process_group(process)
        raise SandboxedProcessError("sandbox_execution_failed")

    stdout = bytearray()
    stderr = bytearray()
    outputs = {process.stdout: stdout, process.stderr: stderr}
    selector = selectors.DefaultSelector()
    try:
        for stream in outputs:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout_seconds
        leader_exited = False
        total_output = 0

        while outputs or not leader_exited:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SandboxedProcessError("process_timeout")
            if not leader_exited and _child_exit_info(process.pid) is not None:
                leader_exited = True
                _signal_process_group(process.pid, leader_exited=True)
                process.wait()
            if cancel_requested is not None and cancel_requested(not leader_exited):
                raise SandboxedProcessError("process_cancelled")

            for key, _ in selector.select(min(remaining, 0.05)):
                stream = key.fileobj
                remaining_output = _MAX_COMMAND_OUTPUT_BYTES - total_output
                chunk = os.read(
                    stream.fileno(), min(4096, remaining_output + 1)
                )
                if not chunk:
                    selector.unregister(stream)
                    stream.close()
                    del outputs[stream]
                    continue
                if len(chunk) > remaining_output:
                    raise SandboxedProcessError("output_limit")
                outputs[stream].extend(chunk)
                total_output += len(chunk)

        return (
            process.returncode if process.returncode is not None else process.wait(),
            bytes(stdout),
            bytes(stderr),
        )
    except SandboxedProcessError:
        _kill_process_group(process)
        raise
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        _kill_process_group(process)
        raise SandboxedProcessError("sandbox_execution_failed") from exc
    except BaseException:
        _kill_process_group(process)
        raise
    finally:
        selector.close()
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()


def _child_exit_info(process_id: int) -> os.waitid_result | None:
    try:
        info = os.waitid(os.P_PID, process_id, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    except (ChildProcessError, OSError) as exc:
        raise SandboxedProcessError("process_status_unavailable") from exc
    return info if info is not None and info.si_pid else None


def _signal_process_group(process_id: int, *, leader_exited: bool = False) -> None:
    try:
        os.killpg(process_id, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        # Darwin reports EPERM when the exited leader is the only remaining
        # group member because a zombie cannot receive a signal. A live
        # same-UID descendant remains signalable and keeps the group present.
        if not leader_exited:
            raise


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    leader_exited = process.returncode is not None
    if not leader_exited:
        leader_exited = _child_exit_info(process.pid) is not None
    _signal_process_group(process.pid, leader_exited=leader_exited)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _prove_host_loopback(listener: socket.socket) -> None:
    try:
        with socket.create_connection(listener.getsockname(), timeout=1):
            connection, _ = listener.accept()
            connection.close()
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EPERM):
            return
        raise SandboxUnavailable(
            "host loopback prerequisite for Seatbelt probe failed"
        ) from exc
