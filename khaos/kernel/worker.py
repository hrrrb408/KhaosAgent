"""One-shot Kernel process for a private-workspace command session."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import ctypes
import os
from pathlib import Path
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
import traceback

from ..ipc import (
    FrameReader,
    IPCProtocolError,
    PROTOCOL_VERSION,
    is_valid_token,
    ping_peer,
    receive_frame,
    send_error_frame,
    send_frame,
    validate_runner_source,
)
from .broker import serve_runner_execution, serve_workspace_commit
from .macos_seatbelt import (
    SANDBOX_EXECUTABLE,
    SandboxProbeIOError,
    SandboxedProcessError,
    SandboxUnavailable,
    _python_runtime_paths,
    _snapshot_profile,
    probe_macos_seatbelt,
    validate_command_timeout,
)
from .peer_identity import (
    accept_local_peer_pid,
    local_peer_pid_listener,
    verify_local_parent_pid,
)
from .workspace_changes import (
    WorkspaceCommitError,
    WorkspaceCommitOutcomeUncertain,
)
from .workspace_snapshot import (
    WorkspaceReadScope,
    WorkspaceSnapshotCancelled,
    WorkspaceSnapshotError,
    WorkspacePathIOError,
    WorkspaceWriteScope,
    _path_for_directory_descriptor,
    _path_is_within,
    workspace_snapshot,
)


_REQUEST_FIELDS = {"version", "request_id", "operation", "payload"}
_PT_DENY_ATTACH = 31  # macOS sys/ptrace.h
_WORKER_IO_STAGES = {
    "_path_is_within": "ancestry",
    "probe_macos_seatbelt": "sandbox_probe",
    "_python_runtime_paths": "runtime_paths",
    "_snapshot_profile": "runner_profile",
    "TemporaryDirectory": "runner_scratch",
    "_run_workspace_command": "preflight",
}
_SANDBOX_UNAVAILABLE_DIAGNOSTICS = {
    "probe-child": "sandbox_unavailable_probe_child",
    "probe-readiness": "sandbox_unavailable_probe_readiness",
    "probe-snapshot": "sandbox_unavailable_probe_snapshot",
    "probe-verification": "sandbox_unavailable_probe_verification",
}


def _deny_debugger_attach() -> bool:
    """Prevent same-user processes from tracing this Kernel Worker."""
    try:
        ptrace = ctypes.CDLL(None, use_errno=True).ptrace
    except (AttributeError, OSError):
        return False
    ptrace.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_int,
    )
    ptrace.restype = ctypes.c_int
    return ptrace(_PT_DENY_ATTACH, 0, None, 0) == 0


def main() -> int:
    """Serve exactly one trusted-launcher request, then exit."""
    if sys.platform != "darwin" or not SANDBOX_EXECUTABLE.is_file() or not os.access(
        SANDBOX_EXECUTABLE, os.X_OK
    ):
        return 2
    # PT_ATTACHEXC can control unrelated same-UID processes. Lock this worker
    # before it accepts IPC or starts any untrusted Runner code.
    if not _deny_debugger_attach():
        return 2
    if len(sys.argv) != 4:
        return 2
    try:
        workspace_root_fd = int(sys.argv[3])
        brokered_snapshot_mount_path = os.environ.get(
            "KHAOS_SNAPSHOT_MOUNT_PATH"
        )
        brokered_storage_text = os.environ.get("KHAOS_SNAPSHOT_STORAGE_BYTES")
        if (brokered_snapshot_mount_path is None) != (brokered_storage_text is None):
            return 2
        brokered_snapshot_storage_bytes = (
            int(brokered_storage_text)
            if brokered_storage_text is not None
            and brokered_storage_text.isdecimal()
            else None
        )
        if brokered_storage_text is not None and brokered_snapshot_storage_bytes is None:
            return 2
        if workspace_root_fd < 3 or not stat.S_ISDIR(
            os.fstat(workspace_root_fd).st_mode
        ):
            return 2
    except (OSError, ValueError):
        return 2

    try:
        verify_local_parent_pid(Path(sys.argv[2]), os.getppid())
        ping_peer(0, 1, timeout_seconds=3)
        request = receive_frame(0, timeout_seconds=5)
        request_id = request.get("request_id")
        if not is_valid_token(request_id):
            return 2
        if (
            set(request) != _REQUEST_FIELDS
            or type(request.get("version")) is not int
            or request["version"] != PROTOCOL_VERSION
            or request.get("operation") != "workspace.run"
            or type(request.get("payload")) is not dict
            or set(request["payload"])
            != {
                "timeout_seconds",
                "runner_source",
                "workspace_read_scope",
                "workspace_write_scope",
            }
            or type(request["payload"].get("workspace_read_scope")) is not list
            or type(request["payload"].get("workspace_write_scope")) is not list
        ):
            _send_error(request_id, "invalid_request")
            return 0

        try:
            runner_source = validate_runner_source(
                request["payload"]["runner_source"]
            )
        except IPCProtocolError:
            _send_error(request_id, "invalid_request")
            return 0
        try:
            workspace_read_scope = WorkspaceReadScope.from_paths(
                request["payload"]["workspace_read_scope"]
            )
        except WorkspaceSnapshotError:
            _send_error(request_id, "invalid_request")
            return 0
        try:
            workspace_write_scope = WorkspaceWriteScope.from_paths(
                request["payload"]["workspace_write_scope"]
            )
        except WorkspaceSnapshotError:
            _send_error(request_id, "invalid_request")
            return 0

        cancellation = _WorkspaceCancellation(request_id)
        process_started_fd = os.dup(1)
        try:
            def report_process_finished(process_group_id: int) -> None:
                _send_process_event(request_id, "process_finished", process_group_id)

            try:
                try:
                    result, changes = _run_workspace_command(
                        sys.argv[1],
                        request["payload"]["timeout_seconds"],
                        runner_source,
                        workspace_root_fd=workspace_root_fd,
                        workspace_read_scope=workspace_read_scope,
                        workspace_write_scope=workspace_write_scope,
                        cancel_requested=cancellation,
                        process_started_fd=process_started_fd,
                        workspace_request_id=request_id,
                        process_finished=report_process_finished,
                        brokered_snapshot_mount_path=brokered_snapshot_mount_path,
                        brokered_snapshot_storage_bytes=brokered_snapshot_storage_bytes,
                    )
                finally:
                    os.close(workspace_root_fd)
            finally:
                os.close(process_started_fd)
        except SandboxProbeIOError as exc:
            _send_error(
                request_id,
                f"workspace_rejected_io_sandbox_probe_{exc.stage}",
            )
        except SandboxUnavailable as exc:
            _send_error(request_id, _sandbox_unavailable_error_code(exc))
        except WorkspaceCommitOutcomeUncertain:
            _send_error(request_id, "commit_outcome_uncertain")
        except WorkspaceCommitError:
            _send_error(
                request_id,
                "process_cancelled" if cancellation.requested else "commit_rejected",
            )
        except SandboxedProcessError as exc:
            _send_error(
                request_id,
                "process_cancelled" if cancellation.requested else exc.code,
            )
        except WorkspaceSnapshotCancelled:
            _send_error(request_id, "process_cancelled")
        except WorkspacePathIOError as exc:
            _send_error(request_id, f"workspace_rejected_io_{exc.stage}")
        except _WorkspaceAncestryIOError as exc:
            _send_error(request_id, exc.code)
        except WorkspaceSnapshotError:
            _send_error(request_id, "workspace_rejected_snapshot")
        except OSError as exc:
            _send_error(request_id, _workspace_io_error_code(exc))
        except (ValueError, TypeError):
            _send_error(request_id, "workspace_rejected_input")
        except (IPCProtocolError, subprocess.SubprocessError):
            _send_error(
                request_id,
                "process_cancelled" if cancellation.requested else "runner_failed",
            )
        else:
            send_frame(
                1,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": request_id,
                    "ok": True,
                    "result": {
                        "returncode": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "added": changes.added,
                        "modified": changes.modified,
                        "deleted": changes.deleted,
                    },
                },
                timeout_seconds=5,
            )
        return 0
    except IPCProtocolError:
        return 2


def _kernel_installation_roots(package_root: Path) -> tuple[Path, ...]:
    """Protect the Kernel package and every enclosing signed macOS bundle."""
    bundle_suffixes = {".app", ".xpc"}
    enclosing_bundles = tuple(
        parent
        for parent in package_root.parents
        if parent.suffix.lower() in bundle_suffixes
    )
    return (package_root, *enclosing_bundles)


def _run_workspace_command(
    workspace_value: str,
    timeout_seconds: object,
    runner_source: object,
    *,
    workspace_root_fd: int | None = None,
    workspace_read_scope: WorkspaceReadScope | Sequence[str] = (),
    workspace_write_scope: WorkspaceWriteScope | Sequence[str] = (),
    cancel_requested: Callable[[], bool] | None = None,
    process_started_fd: int | None = None,
    workspace_request_id: str | None = None,
    process_finished: Callable[[int], None] | None = None,
    brokered_snapshot_mount_path: str | None = None,
    brokered_snapshot_storage_bytes: int | None = None,
):
    package_root = Path(__file__).resolve().parents[2]
    timeout = validate_command_timeout(timeout_seconds)
    source = validate_runner_source(runner_source)
    read_scope = WorkspaceReadScope.from_paths(workspace_read_scope)
    write_scope = WorkspaceWriteScope.from_paths(workspace_write_scope)
    if type(workspace_root_fd) is not int or workspace_root_fd < 0:
        raise WorkspaceSnapshotError("trusted workspace root descriptor is required")
    workspace = Path(workspace_value).expanduser()
    if not workspace.is_absolute() or workspace != _path_for_directory_descriptor(
        workspace_root_fd
    ):
        raise WorkspaceSnapshotError("workspace path does not match its pinned descriptor")
    if workspace == Path("/"):
        raise WorkspaceSnapshotError("workspace overlaps the Kernel installation")
    for protected_root in _kernel_installation_roots(package_root):
        try:
            kernel_is_inside_workspace = _path_is_within(
                protected_root,
                workspace,
                directory_descriptor=workspace_root_fd,
            )
        except OSError as exc:
            raise _WorkspaceAncestryIOError("kernel_in_workspace") from exc
        if kernel_is_inside_workspace:
            raise WorkspaceSnapshotError("workspace overlaps the Kernel installation")
        try:
            workspace_is_inside_kernel = _path_is_within(
                workspace,
                protected_root,
                path_descriptor=workspace_root_fd,
            )
        except OSError as exc:
            raise _WorkspaceAncestryIOError("workspace_in_kernel") from exc
        if workspace_is_inside_kernel:
            raise WorkspaceSnapshotError("workspace overlaps the Kernel installation")
    if cancel_requested is not None and cancel_requested():
        raise WorkspaceSnapshotCancelled("workspace operation was cancelled")

    try:
        probe_macos_seatbelt(
            cancel_requested=cancel_requested,
            brokered_snapshot_mount_path=brokered_snapshot_mount_path,
            brokered_snapshot_storage_bytes=brokered_snapshot_storage_bytes,
        )
    except SandboxUnavailable as exc:
        if exc.diagnostic_stage is not None:
            raise
        # Keep diagnostics bounded; exception messages may include private paths.
        raise SandboxUnavailable(
            "macOS Seatbelt readiness probe is unavailable",
            diagnostic_stage="probe-readiness",
        ) from exc

    executable = Path(sys.executable).resolve(strict=True)
    runtime_paths = _python_runtime_paths()
    if not any(executable.is_relative_to(path) for path in runtime_paths):
        raise SandboxUnavailable("Python runtime is outside the approved roots")

    runner_package = package_root / "khaos"
    readable_paths = (
        runner_package,
        runner_package / "__init__.py",
        runner_package / "ipc.py",
        runner_package / "runner.py",
        runner_package / "runner_sdk.py",
        runner_package / "kernel",
        runner_package / "kernel" / "__init__.py",
        runner_package / "kernel" / "peer_identity.py",
    )
    with workspace_snapshot(
        workspace,
        source_root_fd=workspace_root_fd,
        brokered_mount_path=brokered_snapshot_mount_path,
        brokered_storage_bytes=brokered_snapshot_storage_bytes,
        owner_pid=os.getpid(),
        cancel_requested=cancel_requested,
    ) as snapshot:
        with tempfile.TemporaryDirectory(prefix="r-", dir=snapshot.path.parent) as scratch_value:
            scratch = Path(scratch_value).resolve(strict=True)
            # Keep Python's import search below the checkout root.
            bootstrap = (
                "import importlib.util, sys\n"
                "package_spec = importlib.util.spec_from_file_location("
                f"'khaos', {str(runner_package / '__init__.py')!r}, "
                f"submodule_search_locations=[{str(runner_package)!r}])\n"
                "if package_spec is None or package_spec.loader is None:\n"
                "    raise ImportError('Khaos Runner package is unavailable')\n"
                "package = importlib.util.module_from_spec(package_spec)\n"
                "sys.modules['khaos'] = package\n"
                "package_spec.loader.exec_module(package)\n"
                "from khaos.runner import main\n"
                "raise SystemExit(main())\n"
            )
            process: subprocess.Popen[bytes] | None = None
            try:
                with local_peer_pid_listener(scratch) as (listener, peer_socket_path):
                    # Keep the IPC Runner in scratch; only the Broker handles the snapshot.
                    profile = _snapshot_profile(
                        scratch,
                        runtime_paths,
                        executable=executable,
                        allow_workspace_write=False,
                        allow_same_sandbox_signals=False,
                        additional_unix_socket_paths=(peer_socket_path,),
                        readable_paths=readable_paths,
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
                            bootstrap,
                            peer_socket_path.name,
                        ),
                        cwd=scratch,
                        env={
                            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                            "HOME": str(scratch),
                            "TMPDIR": str(scratch),
                            "LC_ALL": "C",
                            "PYTHONDONTWRITEBYTECODE": "1",
                        },
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        close_fds=True,
                    )
                    accept_local_peer_pid(listener, process.pid)
                if process.stdin is None or process.stdout is None:
                    raise IPCProtocolError("Runner IPC pipes are unavailable")
                ping_peer(
                    process.stdout.fileno(), process.stdin.fileno(), timeout_seconds=3
                )
                send_frame(
                    process.stdin.fileno(),
                    {
                        "version": PROTOCOL_VERSION,
                        "request_id": secrets.token_hex(16),
                        "operation": "plugin.start",
                        "payload": {"source": source},
                    },
                    timeout_seconds=5,
                )
                result = serve_runner_execution(
                    process.stdout.fileno(),
                    process.stdin.fileno(),
                    snapshot,
                    authorized_timeout_seconds=timeout,
                    workspace_read_scope=read_scope,
                    workspace_write_scope=write_scope,
                    timeout_seconds=5,
                    cancel_requested=cancel_requested,
                    process_started_fd=process_started_fd,
                    workspace_request_id=workspace_request_id,
                    process_finished=process_finished,
                )
                changes = serve_workspace_commit(
                    process.stdout.fileno(),
                    process.stdin.fileno(),
                    snapshot,
                    workspace_write_scope=write_scope,
                    timeout_seconds=5,
                    cancel_requested=cancel_requested,
                )
                for stream in (process.stdin, process.stdout):
                    stream.close()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # The validated commit result is authoritative; Runner code
                    # after its final IPC request cannot revoke it.
                    _kill_runner(process)
                return result, changes
            except BaseException:
                if process is not None:
                    _kill_runner(process)
                raise


def _kill_runner(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.send_signal(signal.SIGKILL)
        process.wait()
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None and not stream.closed:
            stream.close()


def _send_process_event(
    request_id: str,
    event: str,
    process_group_id: int,
) -> None:
    if event != "process_finished":
        raise ValueError("Kernel process event is invalid")
    send_frame(
        1,
        {
            "version": PROTOCOL_VERSION,
            "request_id": request_id,
            "event": event,
            "payload": {"process_group_id": f"{process_group_id:08x}"},
        },
        timeout_seconds=3,
    )


class _WorkspaceCancellation:
    """Accept at most one caller cancellation bound to the active request."""

    def __init__(self, workspace_request_id: str, *, read_fd: int = 0) -> None:
        self._workspace_request_id = workspace_request_id
        self._reader = FrameReader(read_fd)
        self._requested = False

    @property
    def requested(self) -> bool:
        return self._requested

    def __call__(self) -> bool:
        if self._requested:
            return True
        message = self._reader.receive_ready()
        if message is None:
            return False
        request_id = message.get("request_id")
        payload = message.get("payload")
        if (
            set(message) != {"version", "request_id", "operation", "payload"}
            or type(message.get("version")) is not int
            or message["version"] != PROTOCOL_VERSION
            or not is_valid_token(request_id)
            or request_id == self._workspace_request_id
            or message.get("operation") != "workspace.cancel"
            or type(payload) is not dict
            or set(payload) != {"workspace_request_id"}
            or payload.get("workspace_request_id") != self._workspace_request_id
        ):
            raise IPCProtocolError("workspace cancellation request is invalid")
        self._requested = True
        return True


class _WorkspaceAncestryIOError(RuntimeError):
    def __init__(self, stage: str) -> None:
        if stage not in {"kernel_in_workspace", "workspace_in_kernel"}:
            raise ValueError("workspace ancestry stage is invalid")
        self.code = f"workspace_rejected_io_{stage}"
        super().__init__(stage)


def _send_error(request_id: str, code: str) -> None:
    send_error_frame(
        1,
        request_id,
        code,
        timeout_seconds=5,
    )


def _sandbox_unavailable_error_code(error: SandboxUnavailable) -> str:
    # The XPC service maps these internal tags back to its generic public error.
    return _SANDBOX_UNAVAILABLE_DIAGNOSTICS.get(
        error.diagnostic_stage,
        "sandbox_unavailable",
    )


def _workspace_io_error_code(error: OSError) -> str:
    for frame in reversed(traceback.extract_tb(error.__traceback__)):
        stage = _WORKER_IO_STAGES.get(frame.name)
        if stage is not None:
            return f"workspace_rejected_io_{stage}"
    return "workspace_rejected_io_worker"


if __name__ == "__main__":
    raise SystemExit(main())
