"""One-shot Kernel Broker operations for a spawned workspace Runner."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Sequence
from dataclasses import dataclass
import errno
import hashlib
import os
from pathlib import Path
import selectors
import stat
import struct
import sys
import threading
from typing import TYPE_CHECKING

from ..ipc import (
    FrameReader,
    IPCProtocolError,
    MAX_WORKSPACE_FILESYSTEM_OPERATIONS,
    MAX_WORKSPACE_WRITE_BYTES,
    PROTOCOL_VERSION,
    is_valid_token,
    receive_frame,
    send_frame,
)

from .workspace_changes import (
    WorkspaceCommitError,
    WorkspaceCommitOutcomeUncertain,
    commit_snapshot,
)
from .workspace_snapshot import (
    WorkspaceReadLimitError,
    WorkspaceReadScope,
    WorkspaceSnapshot,
    WorkspaceSnapshotError,
    WorkspaceWriteScope,
    list_snapshot_directory,
    read_snapshot_file,
    write_snapshot_file,
)

if TYPE_CHECKING:
    from .macos_seatbelt import SandboxedProcessResult


_COMMIT_OPERATION = "workspace.commit"
_EXEC_OPERATION = "process.exec"
_CANCEL_OPERATION = "process.cancel"
_READ_OPERATION = "fs.read"
_LIST_OPERATION = "fs.list"
_WRITE_OPERATION = "fs.write"
_REQUEST_FIELDS = {"version", "request_id", "operation", "payload"}
_COMMIT_RESULT = struct.Struct("!BBQQQ")
_COMMIT_APPLIED = 0
_COMMIT_REJECTED = 1
_COMMIT_OUTCOME_UNCERTAIN = 2
_COMMIT_READY = b"\x01"
_COMMIT_ACCEPT = b"\x01"
_COMMIT_ABORT = b"\x00"


@dataclass(frozen=True, slots=True)
class WorkspaceCommitSummary:
    """Bounded counts returned by the trusted commit operation."""

    added: int
    modified: int
    deleted: int


def serve_workspace_commit(
    request_read_fd: int,
    response_write_fd: int,
    snapshot: WorkspaceSnapshot,
    *,
    workspace_write_scope: WorkspaceWriteScope | Sequence[str] = (),
    timeout_seconds: float = 5.0,
    cancel_requested: Callable[[], bool] | None = None,
) -> WorkspaceCommitSummary:
    """Serve one commit request after the active process operation has ended.

    The caller retains the snapshot and pipe ownership; the Runner supplies no
    workspace path, capability, or approval. This is one operation handler, not
    a general broker or proof that its caller runs in a separate process. One
    delayed process.cancel frame is rejected as inactive before the commit.
    """
    cancelled_requests = 0
    while True:
        request_id, operation, payload = _receive_request(
            request_read_fd, response_write_fd, timeout_seconds
        )
        if operation != _CANCEL_OPERATION:
            break
        cancel_payload = payload
        if (
            type(cancel_payload) is not dict
            or set(cancel_payload) != {"process_request_id"}
            or not is_valid_token(cancel_payload.get("process_request_id"))
            or request_id == cancel_payload.get("process_request_id")
            or cancelled_requests
        ):
            _send_error(response_write_fd, request_id, "invalid_request", timeout_seconds)
            raise IPCProtocolError("inactive process cancel request is invalid")
        cancelled_requests += 1
        _send_error(response_write_fd, request_id, "process_not_active", timeout_seconds)

    if operation != _COMMIT_OPERATION:
        _send_error(
            response_write_fd,
            request_id,
            "operation_not_supported",
            timeout_seconds,
        )
        raise IPCProtocolError("workspace commit operation is not supported")
    if type(payload) is not dict or payload:
        _send_error(
            response_write_fd, request_id, "invalid_request", timeout_seconds
        )
        raise IPCProtocolError("workspace commit request payload must be empty")

    if cancel_requested is not None and cancel_requested():
        raise IPCProtocolError("workspace commit was cancelled before application")

    try:
        write_scope = WorkspaceWriteScope.from_paths(
            workspace_write_scope,
            max_depth=snapshot.max_depth,
        )
    except WorkspaceSnapshotError as exc:
        _send_error(
            response_write_fd, request_id, "commit_rejected", timeout_seconds
        )
        raise WorkspaceCommitError("workspace write scope is invalid") from exc

    try:
        changes = _commit_snapshot_in_sandbox(
            snapshot,
            write_scope,
            cancel_requested=cancel_requested,
        )
    except WorkspaceCommitOutcomeUncertain:
        _send_error(
            response_write_fd,
            request_id,
            "commit_outcome_uncertain",
            timeout_seconds,
        )
        raise
    except WorkspaceCommitError:
        _send_error(response_write_fd, request_id, "commit_rejected", timeout_seconds)
        raise

    send_frame(
        response_write_fd,
        {
            "version": PROTOCOL_VERSION,
            "request_id": request_id,
            "ok": True,
            "result": {
                "added": changes.added,
                "modified": changes.modified,
                "deleted": changes.deleted,
            },
        },
        timeout_seconds=timeout_seconds,
    )
    return changes


def _commit_snapshot_in_sandbox(
    snapshot: WorkspaceSnapshot,
    workspace_write_scope: WorkspaceWriteScope,
    *,
    cancel_requested: Callable[[], bool] | None,
) -> WorkspaceCommitSummary:
    """Fork a one-shot trusted committer and restrict it before live writes."""
    if sys.platform != "darwin":
        raise WorkspaceCommitError("workspace commit sandbox is unavailable")
    if threading.active_count() != 1:
        raise WorkspaceCommitError("workspace commit isolation is unavailable")
    source_root_fd = snapshot._source_root_fd
    if type(source_root_fd) is not int or source_root_fd < 0:
        raise WorkspaceCommitError("workspace root descriptor is unavailable")
    try:
        if not stat.S_ISDIR(os.fstat(source_root_fd).st_mode):
            raise WorkspaceCommitError("workspace root descriptor is invalid")
    except OSError as exc:
        raise WorkspaceCommitError(
            "workspace root descriptor is unavailable"
        ) from exc

    result_read_fd = -1
    result_write_fd = -1
    ready_read_fd = -1
    ready_write_fd = -1
    decision_read_fd = -1
    decision_write_fd = -1
    descriptors: list[int] = []
    try:
        result_read_fd, result_write_fd = os.pipe()
        descriptors.extend((result_read_fd, result_write_fd))
        ready_read_fd, ready_write_fd = os.pipe()
        descriptors.extend((ready_read_fd, ready_write_fd))
        decision_read_fd, decision_write_fd = os.pipe()
        descriptors.extend((decision_read_fd, decision_write_fd))
        for descriptor in descriptors:
            os.set_inheritable(descriptor, False)
        child_pid = os.fork()
    except OSError as exc:
        for descriptor in descriptors:
            os.close(descriptor)
        raise WorkspaceCommitError(
            "workspace commit isolation is unavailable"
        ) from exc

    if child_pid == 0:
        status = _COMMIT_REJECTED
        counts = (0, 0, 0)
        try:
            os.close(result_read_fd)
            os.close(ready_read_fd)
            os.close(decision_write_fd)
            _close_child_descriptors_except(
                (
                    result_write_fd,
                    ready_write_fd,
                    decision_read_fd,
                    source_root_fd,
                )
            )
            from .macos_seatbelt import apply_workspace_commit_sandbox

            def restrict_before_mutations(
                staging_path: Path,
                file_write_paths: tuple[tuple[str, ...], ...],
                create_unlink_paths: tuple[tuple[str, ...], ...],
            ) -> None:
                apply_workspace_commit_sandbox(
                    snapshot,
                    staging_path,
                    file_write_paths,
                    create_unlink_paths,
                )
                _write_all(ready_write_fd, _COMMIT_READY)
                if _read_one(decision_read_fd) != _COMMIT_ACCEPT:
                    raise WorkspaceCommitError(
                        "workspace commit cancelled before mutation"
                    )

            changes = commit_snapshot(
                snapshot,
                workspace_write_scope=workspace_write_scope,
                before_live_mutations=restrict_before_mutations,
            )
            status = _COMMIT_APPLIED
            counts = (
                len(changes.added),
                len(changes.modified),
                len(changes.deleted),
            )
        except WorkspaceCommitOutcomeUncertain:
            status = _COMMIT_OUTCOME_UNCERTAIN
        except WorkspaceCommitError:
            status = _COMMIT_REJECTED
        except BaseException:
            status = _COMMIT_OUTCOME_UNCERTAIN
        try:
            _write_all(
                result_write_fd,
                _COMMIT_RESULT.pack(1, status, *counts),
            )
        except OSError:
            os._exit(1)
        os._exit(0)

    os.close(result_write_fd)
    os.close(ready_write_fd)
    os.close(decision_read_fd)
    cancelled = False
    authorized: bool | None = None
    authorization_error: BaseException | None = None
    try:
        try:
            authorized = _await_commit_authorization(
                ready_read_fd,
                decision_write_fd,
                cancel_requested,
            )
            cancelled = authorized is False
        except BaseException as exc:
            authorization_error = exc
            try:
                _write_all(decision_write_fd, _COMMIT_ABORT)
            except OSError:
                pass
        result = _read_child_commit_result(result_read_fd)
        child_status = _wait_for_child(child_pid)
    finally:
        os.close(result_read_fd)
        os.close(ready_read_fd)
        os.close(decision_write_fd)
    if authorization_error is not None:
        raise authorization_error
    if cancelled:
        raise WorkspaceCommitError("workspace commit cancelled before mutation")
    if child_status != 0 or result is None:
        if authorized is True:
            raise WorkspaceCommitOutcomeUncertain(
                "commit child failed after live mutation was authorized"
            )
        raise WorkspaceCommitError("isolated workspace commit failed")
    version, status, added, modified, deleted = result
    if version != 1:
        if authorized is True:
            raise WorkspaceCommitOutcomeUncertain(
                "commit child returned an invalid result after authorization"
            )
        raise WorkspaceCommitError("isolated workspace commit failed")
    if status == _COMMIT_OUTCOME_UNCERTAIN:
        raise WorkspaceCommitOutcomeUncertain(
            "workspace commit may have partially applied"
        )
    if status == _COMMIT_REJECTED:
        raise WorkspaceCommitError("isolated workspace commit failed")
    if status != _COMMIT_APPLIED:
        if authorized is True:
            raise WorkspaceCommitOutcomeUncertain(
                "commit child failed after live mutation was authorized"
            )
        raise WorkspaceCommitError("isolated workspace commit failed")
    return WorkspaceCommitSummary(added, modified, deleted)


def _close_child_descriptors_except(kept_fds: tuple[int, ...]) -> None:
    kept = set(kept_fds)
    for value in os.listdir("/dev/fd"):
        try:
            descriptor = int(value)
        except ValueError:
            continue
        if descriptor in kept:
            continue
        try:
            os.close(descriptor)
        except OSError as exc:
            if exc.errno != errno.EBADF:
                raise


def _await_commit_authorization(
    ready_read_fd: int,
    decision_write_fd: int,
    cancel_requested: Callable[[], bool] | None,
) -> bool | None:
    """Gate live mutation after validation and observe cancellation until then."""
    with selectors.DefaultSelector() as selector:
        selector.register(ready_read_fd, selectors.EVENT_READ)
        while True:
            if cancel_requested is not None and cancel_requested():
                _write_all(decision_write_fd, _COMMIT_ABORT)
                return False
            if not selector.select(timeout=0.05):
                continue
            message = _read_one(ready_read_fd)
            if not message:
                return None
            if message != _COMMIT_READY:
                raise WorkspaceCommitError("workspace commit gate is invalid")
            if cancel_requested is not None and cancel_requested():
                _write_all(decision_write_fd, _COMMIT_ABORT)
                return False
            _write_all(decision_write_fd, _COMMIT_ACCEPT)
            return True


def _read_one(descriptor: int) -> bytes:
    while True:
        try:
            return os.read(descriptor, 1)
        except InterruptedError:
            continue


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        try:
            written = os.write(descriptor, view)
        except InterruptedError:
            continue
        if written <= 0:
            raise OSError("commit result pipe closed")
        view = view[written:]


def _read_child_commit_result(
    descriptor: int,
) -> tuple[int, int, int, int, int] | None:
    data = bytearray()
    while len(data) <= _COMMIT_RESULT.size:
        try:
            chunk = os.read(descriptor, _COMMIT_RESULT.size + 1 - len(data))
        except InterruptedError:
            continue
        except OSError:
            return None
        if not chunk:
            break
        data.extend(chunk)
    if len(data) != _COMMIT_RESULT.size:
        return None
    try:
        return _COMMIT_RESULT.unpack(data)
    except struct.error:
        return None


def _wait_for_child(child_pid: int) -> int:
    while True:
        try:
            waited_pid, status = os.waitpid(child_pid, 0)
        except InterruptedError:
            continue
        if waited_pid != child_pid or not os.WIFEXITED(status):
            return -1
        return os.WEXITSTATUS(status)


def serve_runner_execution(
    request_read_fd: int,
    response_write_fd: int,
    snapshot: WorkspaceSnapshot,
    *,
    authorized_timeout_seconds: float,
    timeout_seconds: float = 5.0,
    cancel_requested: Callable[[], bool] | None = None,
    process_started_fd: int | None = None,
    workspace_request_id: str | None = None,
    process_finished: Callable[[int], None] | None = None,
    workspace_read_scope: WorkspaceReadScope | Sequence[str] = (),
    workspace_write_scope: WorkspaceWriteScope | Sequence[str] = (),
) -> SandboxedProcessResult:
    """Serve scoped workspace access and one untrusted command request."""
    read_scope = WorkspaceReadScope.from_paths(
        workspace_read_scope,
        max_depth=snapshot.max_depth,
    )
    write_scope = WorkspaceWriteScope.from_paths(
        workspace_write_scope,
        max_depth=snapshot.max_depth,
    )
    filesystem_requests = 0
    while True:
        if cancel_requested is not None and cancel_requested():
            raise IPCProtocolError("Runner execution was cancelled before process.exec")
        request_id, operation, payload = _receive_request(
            request_read_fd, response_write_fd, timeout_seconds
        )
        if operation in {_READ_OPERATION, _LIST_OPERATION, _WRITE_OPERATION}:
            if filesystem_requests >= MAX_WORKSPACE_FILESYSTEM_OPERATIONS:
                _send_error(
                    response_write_fd,
                    request_id,
                    "operation_limit_exceeded",
                    timeout_seconds,
                )
                raise IPCProtocolError("Runner filesystem request limit exceeded")
            filesystem_requests += 1
            if operation == _READ_OPERATION:
                _serve_workspace_read(
                    request_id,
                    payload,
                    response_write_fd,
                    snapshot,
                    read_scope,
                    timeout_seconds,
                )
            elif operation == _LIST_OPERATION:
                _serve_workspace_list(
                    request_id,
                    payload,
                    response_write_fd,
                    snapshot,
                    read_scope,
                    timeout_seconds,
                )
            else:
                _serve_workspace_write(
                    request_id,
                    payload,
                    response_write_fd,
                    snapshot,
                    write_scope,
                    timeout_seconds,
                )
            continue
        if operation != _EXEC_OPERATION:
            _send_error(
                response_write_fd,
                request_id,
                "operation_not_supported",
                timeout_seconds,
            )
            raise IPCProtocolError("Runner operation is not supported")
        return _serve_process_exec(
            request_id,
            payload,
            request_read_fd,
            response_write_fd,
            snapshot,
            read_scope,
            write_scope,
            authorized_timeout_seconds,
            timeout_seconds=timeout_seconds,
            cancel_requested=cancel_requested,
            process_started_fd=process_started_fd,
            workspace_request_id=workspace_request_id,
            process_finished=process_finished,
        )


def _serve_process_exec(
    request_id: str,
    payload: object,
    request_read_fd: int,
    response_write_fd: int,
    snapshot: WorkspaceSnapshot,
    workspace_read_scope: WorkspaceReadScope,
    workspace_write_scope: WorkspaceWriteScope,
    authorized_timeout_seconds: float,
    *,
    timeout_seconds: float,
    cancel_requested: Callable[[], bool] | None,
    process_started_fd: int | None,
    workspace_request_id: str | None,
    process_finished: Callable[[int], None] | None,
) -> SandboxedProcessResult:
    if (
        type(payload) is not dict
        or set(payload) != {"argv"}
        or type(payload["argv"]) is not list
        or any(type(argument) is not str for argument in payload["argv"])
    ):
        _send_error(response_write_fd, request_id, "invalid_request", timeout_seconds)
        raise IPCProtocolError("process exec payload must contain only argv")

    from .macos_seatbelt import SandboxedProcessError, run_sandboxed_process

    cancel_reader = FrameReader(request_read_fd)
    cancel_request_id: str | None = None
    control_frame_received = False

    def check_cancel(active: bool) -> bool:
        nonlocal cancel_request_id, control_frame_received
        caller_cancelled = (
            cancel_requested is not None and cancel_requested()
        )
        message = cancel_reader.receive_ready()
        if message is None:
            return caller_cancelled
        if control_frame_received:
            raise IPCProtocolError(
                "only one control frame is allowed during process.exec"
            )
        control_frame_received = True

        cancel_id = message.get("request_id")
        if not is_valid_token(cancel_id):
            raise IPCProtocolError("process cancel request id is invalid")
        if (
            set(message) != _REQUEST_FIELDS
            or type(message.get("version")) is not int
            or message["version"] != PROTOCOL_VERSION
            or type(message.get("operation")) is not str
            or cancel_id == request_id
        ):
            _send_error(
                response_write_fd, cancel_id, "invalid_request", timeout_seconds
            )
            raise IPCProtocolError("process cancel request schema is invalid")
        if message["operation"] != _CANCEL_OPERATION:
            _send_error(
                response_write_fd,
                cancel_id,
                "operation_not_supported",
                timeout_seconds,
            )
            return caller_cancelled

        cancel_payload = message["payload"]
        if (
            type(cancel_payload) is not dict
            or set(cancel_payload) != {"process_request_id"}
            or not is_valid_token(cancel_payload.get("process_request_id"))
        ):
            _send_error(
                response_write_fd, cancel_id, "invalid_request", timeout_seconds
            )
            raise IPCProtocolError("process cancel payload is invalid")
        if not active or cancel_payload["process_request_id"] != request_id:
            _send_error(
                response_write_fd, cancel_id, "process_not_active", timeout_seconds
            )
            return caller_cancelled

        cancel_request_id = cancel_id
        return True

    try:
        result = run_sandboxed_process(
            snapshot,
            payload["argv"],
            timeout_seconds=authorized_timeout_seconds,
            workspace_read_scope=workspace_read_scope,
            workspace_write_scope=workspace_write_scope,
            cancel_requested=check_cancel,
            process_started_fd=process_started_fd,
            workspace_request_id=workspace_request_id,
            process_finished=process_finished,
        )
    except SandboxedProcessError as exc:
        if exc.code == "process_cancelled" and cancel_request_id is not None:
            send_frame(
                response_write_fd,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": cancel_request_id,
                    "ok": True,
                    "result": {
                        "cancelled": True,
                        "process_request_id": request_id,
                    },
                },
                timeout_seconds=timeout_seconds,
            )
        _send_error(response_write_fd, request_id, exc.code, timeout_seconds)
        raise IPCProtocolError("sandboxed process execution failed") from exc
    except IPCProtocolError:
        _send_error(
            response_write_fd,
            request_id,
            "invalid_process_control",
            timeout_seconds,
        )
        raise

    send_frame(
        response_write_fd,
        {
            "version": PROTOCOL_VERSION,
            "request_id": request_id,
            "ok": True,
            "result": {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        },
        timeout_seconds=timeout_seconds,
    )
    return result


def _serve_workspace_read(
    request_id: str,
    payload: object,
    response_write_fd: int,
    snapshot: WorkspaceSnapshot,
    read_scope: WorkspaceReadScope,
    timeout_seconds: float,
) -> None:
    path = _filesystem_request_path(
        _READ_OPERATION, request_id, payload, response_write_fd, timeout_seconds
    )
    if not read_scope.permits_read(path, max_depth=snapshot.max_depth):
        _send_error(response_write_fd, request_id, "path_not_readable", timeout_seconds)
        return
    try:
        content = read_snapshot_file(snapshot, path)
    except WorkspaceReadLimitError:
        _send_error(response_write_fd, request_id, "file_too_large", timeout_seconds)
        return
    except WorkspaceSnapshotError:
        _send_error(response_write_fd, request_id, "path_not_readable", timeout_seconds)
        return
    send_frame(
        response_write_fd,
        {
            "version": PROTOCOL_VERSION,
            "request_id": request_id,
            "ok": True,
            "result": {"data_base64": base64.b64encode(content).decode("ascii")},
        },
        timeout_seconds=timeout_seconds,
    )


def _serve_workspace_list(
    request_id: str,
    payload: object,
    response_write_fd: int,
    snapshot: WorkspaceSnapshot,
    read_scope: WorkspaceReadScope,
    timeout_seconds: float,
) -> None:
    path = _filesystem_request_path(
        _LIST_OPERATION, request_id, payload, response_write_fd, timeout_seconds
    )
    if not read_scope.permits_list(path, max_depth=snapshot.max_depth):
        _send_error(response_write_fd, request_id, "path_not_listable", timeout_seconds)
        return
    try:
        entries = read_scope.visible_entries(
            path,
            list_snapshot_directory(snapshot, path),
            max_depth=snapshot.max_depth,
        )
    except WorkspaceReadLimitError:
        _send_error(
            response_write_fd, request_id, "directory_too_large", timeout_seconds
        )
        return
    except WorkspaceSnapshotError:
        _send_error(response_write_fd, request_id, "path_not_listable", timeout_seconds)
        return
    send_frame(
        response_write_fd,
        {
            "version": PROTOCOL_VERSION,
            "request_id": request_id,
            "ok": True,
            "result": {
                "entries": [
                    {"name": entry.name, "kind": entry.kind, "size": entry.size}
                    for entry in entries
                ]
            },
        },
        timeout_seconds=timeout_seconds,
    )


def _serve_workspace_write(
    request_id: str,
    payload: object,
    response_write_fd: int,
    snapshot: WorkspaceSnapshot,
    write_scope: WorkspaceWriteScope,
    timeout_seconds: float,
) -> None:
    path = _filesystem_request_path(
        _WRITE_OPERATION,
        request_id,
        payload,
        response_write_fd,
        timeout_seconds,
        fields={"path", "data_base64"},
    )
    if not write_scope.permits_write(path, max_depth=snapshot.max_depth):
        _send_error(response_write_fd, request_id, "path_not_writable", timeout_seconds)
        return
    encoded = payload["data_base64"]
    if type(encoded) is not str:
        _send_error(response_write_fd, request_id, "invalid_request", timeout_seconds)
        raise IPCProtocolError("fs.write content is invalid")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        _send_error(response_write_fd, request_id, "invalid_request", timeout_seconds)
        raise IPCProtocolError("fs.write content is not valid base64")
    if (
        len(content) > MAX_WORKSPACE_WRITE_BYTES
        or base64.b64encode(content).decode("ascii") != encoded
    ):
        _send_error(response_write_fd, request_id, "invalid_request", timeout_seconds)
        raise IPCProtocolError("fs.write content is not canonical or bounded")
    try:
        digest = write_snapshot_file(snapshot, path, content)
    except WorkspaceSnapshotError:
        _send_error(response_write_fd, request_id, "path_not_writable", timeout_seconds)
        return
    send_frame(
        response_write_fd,
        {
            "version": PROTOCOL_VERSION,
            "request_id": request_id,
            "ok": True,
            "result": {
                "written_bytes": len(content),
                "sha256": digest,
            },
        },
        timeout_seconds=timeout_seconds,
    )


def _filesystem_request_path(
    operation: str,
    request_id: str,
    payload: object,
    response_write_fd: int,
    timeout_seconds: float,
    *,
    fields: set[str] | None = None,
) -> str:
    expected_fields = fields or {"path"}
    if (
        type(payload) is not dict
        or set(payload) != expected_fields
        or type(payload.get("path")) is not str
    ):
        _send_error(response_write_fd, request_id, "invalid_request", timeout_seconds)
        raise IPCProtocolError(f"{operation} request payload is invalid")
    return payload["path"]


def _receive_request(
    request_read_fd: int,
    response_write_fd: int,
    timeout_seconds: float,
) -> tuple[str, object, object]:
    request = receive_frame(request_read_fd, timeout_seconds=timeout_seconds)
    request_id = request.get("request_id")
    if not is_valid_token(request_id):
        raise IPCProtocolError("request id is invalid")
    if (
        set(request) != _REQUEST_FIELDS
        or type(request.get("version")) is not int
        or request["version"] != PROTOCOL_VERSION
        or type(request.get("operation")) is not str
    ):
        _send_error(response_write_fd, request_id, "invalid_request", timeout_seconds)
        raise IPCProtocolError("request schema is invalid")
    return request_id, request["operation"], request["payload"]


def _send_error(
    response_write_fd: int,
    request_id: str,
    code: str,
    timeout_seconds: float,
) -> None:
    send_frame(
        response_write_fd,
        {
            "version": PROTOCOL_VERSION,
            "request_id": request_id,
            "ok": False,
            "error": {"code": code},
        },
        timeout_seconds=timeout_seconds,
    )
