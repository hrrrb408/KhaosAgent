"""Bounded process bridge from the authenticated macOS XPC Kernel to its Worker."""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
import struct
import sys
import time
from collections.abc import Iterator

from ..ipc import _read_exact, is_valid_token, receive_frame, send_frame
from ..launcher import KernelLaunchError, run_workspace_command
from .workspace_snapshot import WorkspaceSnapshotError


_REQUEST_FIELDS = {"version", "request_id", "operation", "payload"}
_WORKSPACE_XPC_OPERATION_VERSION = 8
_MAXIMUM_WORKSPACE_BOOKMARK_BYTES = 64 * 1024
_BOOKMARK_TRANSFER_LENGTH = struct.Struct("!I")
_CFURL_BOOKMARK_RESOLUTION_DEFAULT = 0
_PAYLOAD_FIELDS = {
    "timeout_seconds",
    "runner_source",
    "runner_source_sha256",
    "workspace_read_scope",
    "workspace_write_scope",
}
_REPORTED_ERRORS = {
    "commit_outcome_uncertain",
    "commit_rejected",
    "kernel_child_cleanup_failed",
    "kernel_cleanup_failed",
    "kernel_ipc_failed",
    "kernel_ipc_unavailable",
    "kernel_process_failed",
    "kernel_timeout",
    "process_cancelled",
    "runner_failed",
    "sandbox_unavailable",
    "sandbox_unavailable_probe_child",
    "sandbox_unavailable_probe_readiness",
    "sandbox_unavailable_probe_snapshot",
    "sandbox_unavailable_probe_verification",
    "snapshot_broker_unavailable",
    "workspace_rejected",
    "workspace_rejected_bookmark",
    "workspace_rejected_bookmark_access",
    "workspace_rejected_bookmark_resolve",
    "workspace_rejected_bookmark_stale",
    "workspace_rejected_bridge_execution",
    "workspace_rejected_bridge_execution_io",
    "workspace_rejected_bridge_execution_key",
    "workspace_rejected_bridge_execution_root_identity",
    "workspace_rejected_bridge_execution_root_io",
    "workspace_rejected_bridge_execution_root_open",
    "workspace_rejected_bridge_execution_root_resolve",
    "workspace_rejected_bridge_execution_root",
    "workspace_rejected_bridge_execution_type",
    "workspace_rejected_bridge_execution_value",
    "workspace_rejected_bridge_bookmark",
    "workspace_rejected_bridge_request",
    "workspace_rejected_bridge_result",
    "workspace_rejected_input",
    "workspace_rejected_io",
    "workspace_rejected_io_ancestry",
    "workspace_rejected_io_directory_mountpoint",
    "workspace_rejected_io_directory_resolve",
    "workspace_rejected_io_kernel_in_workspace",
    "workspace_rejected_io_path_mountpoint",
    "workspace_rejected_io_path_resolve",
    "workspace_rejected_io_preflight",
    "workspace_rejected_io_runner_profile",
    "workspace_rejected_io_runner_scratch",
    "workspace_rejected_io_runtime_paths",
    "workspace_rejected_io_sandbox_probe",
    "workspace_rejected_io_sandbox_probe_fixture_files",
    "workspace_rejected_io_sandbox_probe_fixture_root",
    "workspace_rejected_io_sandbox_probe_runtime",
    "workspace_rejected_io_sandbox_probe_temporary_cleanup",
    "workspace_rejected_io_sandbox_probe_temporary_create",
    "workspace_rejected_io_sandbox_probe_verification",
    "workspace_rejected_io_worker",
    "workspace_rejected_io_workspace_in_kernel",
    "workspace_rejected_snapshot",
    "workspace_rejected_worker",
}


def main() -> int:
    if len(sys.argv) != 5:
        return 2
    _, _, workspace, root_fd_text, cancel_fd_text = sys.argv
    phase = "request"
    try:
        root_fd = int(root_fd_text)
        cancel_fd = int(cancel_fd_text)
        if root_fd < 3 or cancel_fd < 3 or root_fd == cancel_fd:
            return 2
        os.fstat(root_fd)
        os.fstat(cancel_fd)
        request = receive_frame(0, timeout_seconds=5)
        request_id, payload = _decode_request(request)
        phase = "bookmark"
        bookmark = _read_workspace_bookmark(0)
        snapshot_mount_path = os.environ.get("KHAOS_SNAPSHOT_MOUNT_PATH")
        snapshot_storage_text = os.environ.get("KHAOS_SNAPSHOT_STORAGE_BYTES")
        if snapshot_mount_path is None or snapshot_storage_text is None:
            raise KernelLaunchError("sandbox_unavailable")
        if not snapshot_storage_text.isdecimal():
            raise KernelLaunchError("sandbox_unavailable")
        phase = "execution"
        with _scoped_workspace_bookmark(bookmark):
            result = run_workspace_command(
                workspace,
                runner_source=payload["runner_source"],
                workspace_read_scope=payload["workspace_read_scope"],
                workspace_write_scope=payload["workspace_write_scope"],
                timeout_seconds=payload["timeout_seconds"],
                cancel_requested=_cancellation_reader(cancel_fd),
                workspace_root_fd=root_fd,
                brokered_snapshot_mount_path=snapshot_mount_path,
                brokered_snapshot_storage_bytes=int(snapshot_storage_text),
            )
        phase = "result"
        output = json.dumps(
            {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "added": result.added,
                "modified": result.modified,
                "deleted": result.deleted,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        response = {
            "version": _WORKSPACE_XPC_OPERATION_VERSION,
            "request_id": request_id,
            "ok": True,
            "output": output,
        }
    except KernelLaunchError as error:
        request_id = request.get("request_id") if "request" in locals() else None
        if not is_valid_token(request_id):
            return 2
        code = str(error)
        if code == "workspace_rejected":
            code = "workspace_rejected_worker"
        response = _error_response(
            request_id,
            code if code in _REPORTED_ERRORS else "kernel_failed",
        )
    except Exception as error:
        request_id = request.get("request_id") if "request" in locals() else None
        if not is_valid_token(request_id):
            return 2
        bridge_code = {
            "request": "workspace_rejected_bridge_request",
            "bookmark": "workspace_rejected_bridge_bookmark",
            "execution": _execution_failure_code(error),
            "result": "workspace_rejected_bridge_result",
        }.get(phase, "workspace_rejected")
        response = _error_response(
            request_id,
            bridge_code,
        )

    try:
        send_frame(1, response, timeout_seconds=5)
    except (OSError, ValueError):
        return 2
    return 0


def _read_workspace_bookmark(descriptor: int) -> bytes:
    deadline = time.monotonic() + 5
    (length,) = _BOOKMARK_TRANSFER_LENGTH.unpack(
        _read_exact(descriptor, _BOOKMARK_TRANSFER_LENGTH.size, deadline)
    )
    if not 0 < length <= _MAXIMUM_WORKSPACE_BOOKMARK_BYTES:
        raise ValueError("workspace bookmark length is invalid")
    return _read_exact(descriptor, length, deadline)


@contextmanager
def _scoped_workspace_bookmark(bookmark: bytes) -> Iterator[None]:
    """Resolve the selected folder's temporary scope in the fixed Kernel child."""
    if sys.platform != "darwin" or type(bookmark) is not bytes or not bookmark:
        raise KernelLaunchError("workspace_rejected_bookmark")

    # App Sandbox PowerBox access is process-local and does not reach spawned helpers.
    core_foundation = None
    data_ref = None
    url_ref = None
    try:
        core_foundation = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        core_foundation.CFDataCreate.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_long,
        )
        core_foundation.CFDataCreate.restype = ctypes.c_void_p
        core_foundation.CFURLCreateByResolvingBookmarkData.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_void_p,
        )
        core_foundation.CFURLCreateByResolvingBookmarkData.restype = ctypes.c_void_p
        core_foundation.CFURLStartAccessingSecurityScopedResource.argtypes = (
            ctypes.c_void_p,
        )
        core_foundation.CFURLStartAccessingSecurityScopedResource.restype = (
            ctypes.c_ubyte
        )
        core_foundation.CFURLStopAccessingSecurityScopedResource.argtypes = (
            ctypes.c_void_p,
        )
        core_foundation.CFURLStopAccessingSecurityScopedResource.restype = None
        core_foundation.CFRelease.argtypes = (ctypes.c_void_p,)
        core_foundation.CFRelease.restype = None

        bookmark_buffer = (ctypes.c_ubyte * len(bookmark)).from_buffer_copy(bookmark)
        data_ref = core_foundation.CFDataCreate(
            None, bookmark_buffer, len(bookmark)
        )
        if not data_ref:
            raise KernelLaunchError("workspace_rejected_bookmark")
        stale = ctypes.c_ubyte(0)
        url_ref = core_foundation.CFURLCreateByResolvingBookmarkData(
            None,
            data_ref,
            _CFURL_BOOKMARK_RESOLUTION_DEFAULT,
            None,
            None,
            ctypes.byref(stale),
            None,
        )
        if not url_ref:
            raise KernelLaunchError("workspace_rejected_bookmark_resolve")
        if stale.value:
            raise KernelLaunchError("workspace_rejected_bookmark_stale")
        if not core_foundation.CFURLStartAccessingSecurityScopedResource(url_ref):
            raise KernelLaunchError("workspace_rejected_bookmark_access")
    except KernelLaunchError:
        if url_ref and core_foundation is not None:
            core_foundation.CFRelease(url_ref)
        if data_ref and core_foundation is not None:
            core_foundation.CFRelease(data_ref)
        raise
    except Exception as error:
        if url_ref and core_foundation is not None:
            core_foundation.CFRelease(url_ref)
        if data_ref and core_foundation is not None:
            core_foundation.CFRelease(data_ref)
        raise KernelLaunchError("workspace_rejected_bookmark") from error

    try:
        yield
    finally:
        core_foundation.CFURLStopAccessingSecurityScopedResource(url_ref)
        core_foundation.CFRelease(url_ref)
        core_foundation.CFRelease(data_ref)


def _decode_request(request: object) -> tuple[str, dict[str, object]]:
    if (
        type(request) is not dict
        or set(request) != _REQUEST_FIELDS
        or type(request.get("version")) is not int
        or request["version"] != _WORKSPACE_XPC_OPERATION_VERSION
        or not is_valid_token(request.get("request_id"))
        or request.get("operation") != "workspace.run"
        or type(request.get("payload")) is not dict
        or set(request["payload"]) != _PAYLOAD_FIELDS
    ):
        raise ValueError("invalid workspace request")
    payload = request["payload"]
    if (
        type(payload.get("timeout_seconds")) not in (int, float)
        or type(payload.get("runner_source")) is not str
        or type(payload.get("runner_source_sha256")) is not str
        or len(payload["runner_source_sha256"]) != 64
        or any(
            character not in "0123456789abcdef"
            for character in payload["runner_source_sha256"]
        )
        or payload["runner_source_sha256"]
        != hashlib.sha256(payload["runner_source"].encode("utf-8")).hexdigest()
        or type(payload.get("workspace_read_scope")) is not list
        or any(type(value) is not str for value in payload["workspace_read_scope"])
        or type(payload.get("workspace_write_scope")) is not list
        or any(type(value) is not str for value in payload["workspace_write_scope"])
    ):
        raise ValueError("invalid workspace payload")
    return request["request_id"], payload


def _cancellation_reader(descriptor: int):
    cancelled = False

    def is_cancelled() -> bool:
        nonlocal cancelled
        if cancelled:
            return True
        try:
            os.read(descriptor, 1)
            cancelled = True
        except BlockingIOError:
            return False
        return cancelled

    return is_cancelled


def _error_response(request_id: str, code: str) -> dict[str, object]:
    return {
        "version": _WORKSPACE_XPC_OPERATION_VERSION,
        "request_id": request_id,
        "ok": False,
        "error": {"code": code},
    }


def _execution_failure_code(error: Exception) -> str:
    if isinstance(error, OSError):
        category = "io"
    elif isinstance(error, ValueError):
        category = "value"
        if str(error) == "workspace is unavailable or changed":
            cause = error.__cause__
            if isinstance(cause, WorkspaceSnapshotError):
                category = "root_identity"
            elif isinstance(cause, ValueError):
                category = {
                    "workspace root could not be opened": "root_open",
                    "workspace root could not be resolved": "root_resolve",
                }.get(str(cause), "root")
            elif isinstance(cause, OSError):
                category = "root_io"
            else:
                category = "root"
        elif str(error) == "workspace must be a non-root directory":
            category = "root"
    elif isinstance(error, TypeError):
        category = "type"
    elif isinstance(error, KeyError):
        category = "key"
    else:
        return "workspace_rejected_bridge_execution"
    return f"workspace_rejected_bridge_execution_{category}"
