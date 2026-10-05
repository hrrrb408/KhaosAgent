"""Trusted local launcher for a one-shot Kernel workspace command."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import selectors
import secrets
import signal
import subprocess
import sys
import tempfile
import time

from .ipc import (
    FrameReader,
    IPCProtocolError,
    MAX_OPERATION_SECONDS,
    PROTOCOL_VERSION,
    answer_ping,
    send_frame,
    validate_runner_source,
)
from .kernel.macos_seatbelt import (
    SandboxedProcessError,
    validate_command_request,
    validate_command_timeout,
)
from .kernel.peer_identity import accept_local_peer_pid, local_peer_pid_listener
from .kernel.workspace_snapshot import (
    WorkspaceReadScope,
    WorkspaceSnapshotError,
    WorkspaceWriteScope,
    _path_for_directory_descriptor,
    _open_absolute_directory,
)


class KernelLaunchError(RuntimeError):
    """The isolated Kernel could not complete its bounded workspace session."""


@dataclass(frozen=True, slots=True)
class WorkspaceCommandResult:
    returncode: int
    stdout: str
    stderr: str
    added: int
    modified: int
    deleted: int


_DEFAULT_RUNNER_SOURCE = """\
from khaos.runner_sdk import process_exec, workspace_commit

def run():
    result = process_exec({argv!r})
    workspace_commit()
    return result["returncode"]
"""


def run_workspace_command(
    workspace: str | os.PathLike[str],
    argv: Sequence[str] | None = None,
    *,
    runner_source: str | None = None,
    workspace_read_scope: Sequence[str] = (),
    workspace_write_scope: Sequence[str] = (),
    timeout_seconds: float = 5.0,
    cancel_requested: Callable[[], bool] | None = None,
    workspace_root_fd: int | None = None,
    brokered_snapshot_mount_path: str | os.PathLike[str] | None = None,
    brokered_snapshot_storage_bytes: int | None = None,
) -> WorkspaceCommandResult:
    """Launch a separate Kernel process for one explicitly selected workspace.

    This development entrypoint has no Candidate admission, user approval, or
    Plugin identity-bound capability grant. workspace_read_scope is retained
    by the Kernel and defaults to deny all Runner and command workspace reads.
    workspace_write_scope is a trusted exact-path scope for Runner SDK writes
    and every path in the committed changeset; it defaults to deny all writes.
    Commands may write the private snapshot, but an out-of-scope change rejects
    the whole commit before live mutation.
    With no runner_source, argv builds a fixed default Runner source. A custom
    runner_source must choose its own process.exec argv. The Kernel bounds argv
    and retains the cwd, environment, timeout, workspace, and explicit scopes.
    This development path grants process.exec to the launched Runner without a
    Plugin identity-bound capability decision. Python import visibility does
    not enforce caller identity; do not expose this API to an untrusted Host
    until that authority contract is implemented. Cancellation is bound to
    this one-shot request and checked during execution and until the commit
    child crosses its pre-mutation gate. The Worker checks the same request
    cancellation during its Seatbelt probe and private snapshot construction.
    A trusted XPC caller may pass an already-open workspace root descriptor;
    the named root must still identify that directory before the Kernel starts.
    """
    if sys.platform != "darwin":
        raise KernelLaunchError("sandbox_unavailable")
    if cancel_requested is not None and not callable(cancel_requested):
        raise ValueError("cancel_requested must be callable")
    if (brokered_snapshot_mount_path is None) != (
        brokered_snapshot_storage_bytes is None
    ):
        raise ValueError("brokered snapshot configuration is incomplete")
    if brokered_snapshot_mount_path is not None:
        brokered_snapshot_mount_path = Path(brokered_snapshot_mount_path)
        if (
            not brokered_snapshot_mount_path.is_absolute()
            or type(brokered_snapshot_storage_bytes) is not int
            or brokered_snapshot_storage_bytes < 128_000_000
            or brokered_snapshot_storage_bytes > 16 * 1024 * 1024 * 1024
        ):
            raise ValueError("brokered snapshot configuration is invalid")
    brokered_snapshot = brokered_snapshot_mount_path is not None
    try:
        timeout = validate_command_timeout(timeout_seconds)
        if runner_source is not None and argv is not None:
            raise ValueError("argv must be selected by runner_source")
        command = (
            validate_command_request(argv, timeout)[0]
            if argv is not None
            else None
        )
    except SandboxedProcessError as exc:
        raise ValueError(exc.code) from exc
    if command is None and runner_source is None:
        raise ValueError("runner_source is required when no default command is set")
    try:
        source = validate_runner_source(
            _DEFAULT_RUNNER_SOURCE.format(argv=command)
            if runner_source is None
            else runner_source
        )
    except IPCProtocolError as exc:
        raise ValueError("invalid_runner_source") from exc
    try:
        read_scope = WorkspaceReadScope.from_paths(workspace_read_scope)
    except WorkspaceSnapshotError as exc:
        raise ValueError("invalid_workspace_read_scope") from exc
    try:
        write_scope = WorkspaceWriteScope.from_paths(workspace_write_scope)
    except WorkspaceSnapshotError as exc:
        raise ValueError("invalid_workspace_write_scope") from exc
    package_root = Path(__file__).resolve().parents[1]
    bootstrap = (
        "import sys\n"
        f"sys.path.insert(0, {str(package_root)!r})\n"
        "from khaos.kernel.worker import main\n"
        "raise SystemExit(main())\n"
    )
    owns_workspace_root_fd = workspace_root_fd is None
    if workspace_root_fd is None:
        workspace_path, active_workspace_root_fd = _open_workspace_root(workspace)
    else:
        try:
            workspace_path = _workspace_path_for_root_descriptor(
                workspace, workspace_root_fd
            )
        except (OSError, TypeError, ValueError, WorkspaceSnapshotError) as exc:
            raise ValueError("workspace is unavailable or changed") from exc
        active_workspace_root_fd = workspace_root_fd
    try:
        process = _start_kernel(
            workspace_path,
            bootstrap,
            active_workspace_root_fd,
            brokered_snapshot_mount_path=brokered_snapshot_mount_path,
            brokered_snapshot_storage_bytes=brokered_snapshot_storage_bytes,
        )
    finally:
        if owns_workspace_root_fd:
            os.close(active_workspace_root_fd)
    try:
        if process.stdin is None or process.stdout is None:
            raise KernelLaunchError("kernel_ipc_unavailable")
        answer_ping(
            process.stdout.fileno(),
            process.stdin.fileno(),
            timeout_seconds=3,
        )
        request_id = secrets.token_hex(16)
        send_frame(
            process.stdin.fileno(),
            {
                "version": PROTOCOL_VERSION,
                "request_id": request_id,
                "operation": "workspace.run",
                "payload": {
                    "timeout_seconds": timeout,
                    "runner_source": source,
                    "workspace_read_scope": list(read_scope.as_paths()),
                    "workspace_write_scope": list(write_scope.as_paths()),
                },
            },
            timeout_seconds=5,
        )
        response = _receive_kernel_response(
            process,
            request_id,
            cancel_requested=cancel_requested,
        )
        if (
            type(response.get("version")) is not int
            or response["version"] != PROTOCOL_VERSION
            or response.get("request_id") != request_id
        ):
            raise IPCProtocolError("Kernel response did not match its request")
        if set(response) == {"version", "request_id", "ok", "error"}:
            error = response["error"]
            if (
                response["ok"] is not False
                or type(error) is not dict
                or set(error) != {"code"}
                or type(error.get("code")) is not str
            ):
                raise IPCProtocolError("Kernel error response is invalid")
            raise KernelLaunchError(error["code"])
        if set(response) != {"version", "request_id", "ok", "result"}:
            raise IPCProtocolError("Kernel response schema is invalid")
        result = response["result"]
        if response["ok"] is not True or type(result) is not dict:
            raise IPCProtocolError("Kernel success response is invalid")
        if (
            set(result)
            != {"returncode", "stdout", "stderr", "added", "modified", "deleted"}
            or type(result.get("returncode")) is not int
            or type(result.get("stdout")) is not str
            or type(result.get("stderr")) is not str
            or any(
                type(result.get(key)) is not int or result[key] < 0
                for key in ("added", "modified", "deleted")
            )
        ):
            raise IPCProtocolError("Kernel result fields are invalid")
        if process.wait(timeout=5) != 0:
            raise KernelLaunchError("kernel_process_failed")
        return WorkspaceCommandResult(
            returncode=result["returncode"],
            stdout=result["stdout"],
            stderr=result["stderr"],
            added=result["added"],
            modified=result["modified"],
            deleted=result["deleted"],
        )
    except KernelLaunchError:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _cleanup_failed_worker(process, brokered_snapshot=brokered_snapshot)
        raise
    except subprocess.TimeoutExpired as exc:
        _cleanup_failed_worker(process, brokered_snapshot=brokered_snapshot)
        raise KernelLaunchError("kernel_timeout") from exc
    except (IPCProtocolError, OSError, subprocess.SubprocessError) as exc:
        _cleanup_failed_worker(process, brokered_snapshot=brokered_snapshot)
        raise KernelLaunchError("kernel_ipc_failed") from exc
    except BaseException:
        _cleanup_failed_worker(process, brokered_snapshot=brokered_snapshot)
        raise
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()


def _stop_kernel(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    # SIGINT targets only the Worker. A forked committer or other helper can
    # survive a prompt Worker exit, so cleanup always reaps the whole session.
    _kill_process_group(process.pid)
    if process.poll() is None:
        process.wait()
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None and not stream.closed:
            stream.close()


def _open_workspace_root(
    workspace: str | os.PathLike[str],
) -> tuple[Path, int]:
    """Pin the selected directory before crossing into the Kernel process."""
    descriptor = -1
    try:
        requested_path = Path(workspace).expanduser()
        # Allow the caller's symlink alias, then bind its canonical name below.
        descriptor = os.open(
            requested_path,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        workspace_path = _workspace_path_for_root_descriptor(
            requested_path, descriptor
        )
        return workspace_path, descriptor
    except (OSError, TypeError, ValueError, WorkspaceSnapshotError) as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise ValueError("workspace is unavailable or changed") from exc
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        raise


def _workspace_path_for_root_descriptor(
    workspace: str | os.PathLike[str], workspace_root_fd: int | None
) -> Path:
    """Bind a canonical workspace name to a trusted, already-open root."""
    if type(workspace_root_fd) is not int or workspace_root_fd < 0:
        raise WorkspaceSnapshotError("workspace root descriptor is invalid")
    try:
        workspace_path = Path(workspace).expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError("workspace root could not be resolved") from exc
    except RuntimeError as exc:
        raise ValueError("workspace root could not be resolved") from exc
    if workspace_path == Path("/"):
        raise ValueError("workspace must be a non-root directory")
    if _path_for_directory_descriptor(workspace_root_fd) != workspace_path:
        raise WorkspaceSnapshotError("workspace changed while it was opened")
    return workspace_path


def _start_kernel(
    workspace: Path,
    bootstrap: str,
    workspace_root_fd: int,
    *,
    brokered_snapshot_mount_path: Path | None = None,
    brokered_snapshot_storage_bytes: int | None = None,
) -> subprocess.Popen[bytes]:
    process: subprocess.Popen[bytes] | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="k-") as scratch_value:
            with local_peer_pid_listener(Path(scratch_value)) as (
                listener,
                socket_path,
            ):
                environment = {
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
                if brokered_snapshot_mount_path is not None:
                    if brokered_snapshot_storage_bytes is None:
                        raise KernelLaunchError("snapshot_broker_unavailable")
                    environment.update(
                        {
                            "KHAOS_SNAPSHOT_MOUNT_PATH": str(
                                brokered_snapshot_mount_path
                            ),
                            "KHAOS_SNAPSHOT_STORAGE_BYTES": str(
                                brokered_snapshot_storage_bytes
                            ),
                            "TMPDIR": str(brokered_snapshot_mount_path.parent),
                        }
                    )
                process = subprocess.Popen(
                    (
                        str(Path(sys.executable).resolve(strict=True)),
                        "-I",
                        "-S",
                        "-B",
                        "-c",
                        bootstrap,
                        str(workspace),
                        socket_path.name,
                        str(workspace_root_fd),
                    ),
                    cwd=Path(scratch_value),
                    env=environment,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    pass_fds=(workspace_root_fd,),
                    start_new_session=True,
                )
                accept_local_peer_pid(listener, process.pid)
        return process
    except (IPCProtocolError, OSError, subprocess.SubprocessError) as exc:
        if process is not None:
            _stop_kernel(process)
        raise KernelLaunchError("kernel_ipc_failed") from exc


def _receive_kernel_response(
    process: subprocess.Popen[bytes],
    request_id: str,
    *,
    cancel_requested: Callable[[], bool] | None,
) -> dict[str, object]:
    if process.stdin is None or process.stdout is None:
        raise IPCProtocolError("Kernel IPC pipes are unavailable")

    reader = FrameReader(process.stdout.fileno())
    deadline = time.monotonic() + MAX_OPERATION_SECONDS
    cancellation_sent = False
    active_process_group: int | None = None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                response = reader.receive_ready()
                if response is not None:
                    if _is_process_event(response):
                        active_process_group = _apply_process_event(
                            response,
                            request_id,
                            process.pid,
                            active_process_group,
                        )
                        continue
                    if active_process_group is not None:
                        if response.get("ok") is not False:
                            raise IPCProtocolError(
                                "Kernel returned while its command process group was active"
                            )
                        process_group_id = active_process_group
                        active_process_group = None
                        _kill_process_group(process_group_id)
                    return response

                if not cancellation_sent and cancel_requested is not None:
                    if cancel_requested():
                        cancellation_sent = True
                        try:
                            send_frame(
                                process.stdin.fileno(),
                                {
                                    "version": PROTOCOL_VERSION,
                                    "request_id": secrets.token_hex(16),
                                    "operation": "workspace.cancel",
                                    "payload": {
                                        "workspace_request_id": request_id
                                    },
                                },
                                timeout_seconds=3,
                            )
                        except IPCProtocolError:
                            # The Kernel may have completed between the response
                            # check and this write. Read its final result first.
                            pass

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(
                        process.args, MAX_OPERATION_SECONDS
                    )
                poll_interval = (
                    0.05
                    if cancel_requested is not None and not cancellation_sent
                    else remaining
                )
                selector.select(min(remaining, poll_interval))
    except BaseException:
        if active_process_group is not None:
            _kill_process_group(active_process_group)
        raise


def _is_process_event(message: dict[str, object]) -> bool:
    return "event" in message


def _apply_process_event(
    message: dict[str, object],
    request_id: str,
    worker_pid: int,
    active_process_group: int | None,
) -> int | None:
    if (
        set(message) != {"version", "request_id", "event", "payload"}
        or type(message.get("version")) is not int
        or message["version"] != PROTOCOL_VERSION
        or message.get("request_id") != request_id
        or type(message.get("event")) is not str
        or type(message.get("payload")) is not dict
        or set(message["payload"]) != {"process_group_id"}
    ):
        raise IPCProtocolError("Kernel process event is invalid")
    encoded_group_id = message["payload"]["process_group_id"]
    if (
        type(encoded_group_id) is not str
        or len(encoded_group_id) != 8
        or any(character not in "0123456789abcdef" for character in encoded_group_id)
    ):
        raise IPCProtocolError("Kernel process group identity is invalid")
    process_group_id = int(encoded_group_id, 16)
    if process_group_id < 1:
        raise IPCProtocolError("Kernel process group identity is invalid")
    if process_group_id in {worker_pid, os.getpgrp()}:
        raise IPCProtocolError("Kernel process group overlaps a trusted process")
    try:
        observed_group_id = os.getpgid(process_group_id)
    except ProcessLookupError:
        observed_group_id = None
    if observed_group_id not in (None, process_group_id):
        raise IPCProtocolError("Kernel process group identity did not match the OS")
    if message["event"] == "process_started" and active_process_group is None:
        return process_group_id
    if (
        message["event"] == "process_finished"
        and active_process_group == process_group_id
    ):
        return None
    raise IPCProtocolError("Kernel process lifecycle event is out of order")


def _kill_process_group(process_group_id: int) -> None:
    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        return
    except PermissionError as exc:
        raise KernelLaunchError("kernel_child_cleanup_failed") from exc

    deadline = time.monotonic() + 5
    while True:
        try:
            os.killpg(process_group_id, 0)
        except (ProcessLookupError, PermissionError):
            return
        if time.monotonic() >= deadline:
            raise KernelLaunchError("kernel_child_cleanup_failed")
        time.sleep(0.05)


def _cleanup_failed_worker(
    process: subprocess.Popen[bytes], *, brokered_snapshot: bool = False
) -> None:
    _stop_kernel(process)
    if brokered_snapshot:
        return
    try:
        # This direct-image cleanup backend is source-tree development support.
        # The signed Kernel bundle omits it and always supplies a Broker lease.
        from .kernel.macos_disk_image import cleanup_abandoned_apfs_volumes

        cleanup_abandoned_apfs_volumes(process.pid)
    except Exception as exc:
        raise KernelLaunchError("kernel_cleanup_failed") from exc
