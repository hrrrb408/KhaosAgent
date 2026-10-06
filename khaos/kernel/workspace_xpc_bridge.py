"""Bounded process bridge from the authenticated macOS XPC Kernel to its Worker."""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
import re
import struct
import sys
import tempfile
import time
from collections.abc import Iterator

from ..ipc import (
    MAX_PLUGIN_INPUT_BYTES,
    MAX_PLUGIN_INPUT_NESTING,
    _json_nesting_within_limit,
    _read_exact,
    is_valid_token,
    receive_frame,
    send_frame,
)
from ..launcher import KernelLaunchError, run_workspace_command
from .plugin_lifecycle import (
    ACTIVATION_APPROVAL_SECONDS,
    PluginLifecycleError,
    PluginCandidate,
    Activation,
    activation_details,
    activate_candidate,
    active_candidate,
    admit_candidate,
    rollback,
)
from .workspace_snapshot import WorkspaceSnapshotError


_REQUEST_FIELDS = {"version", "request_id", "operation", "payload"}
_WORKSPACE_XPC_OPERATION_VERSION = 10
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
    "capability_denied",
    "commit_outcome_uncertain",
    "commit_rejected",
    "activation_outcome_uncertain",
    "activation_state_corrupt",
    "activation_state_unavailable",
    "approval_binding_mismatch",
    "approval_expired",
    "candidate_corrupt",
    "candidate_missing",
    "candidate_store_failed",
    "invalid_rollback_target",
    "invalid_time",
    "kernel_child_cleanup_failed",
    "kernel_cleanup_failed",
    "kernel_ipc_failed",
    "kernel_ipc_unavailable",
    "kernel_process_failed",
    "kernel_timeout",
    "process_cancelled",
    "plugin_source_rejected",
    "plugin_input_too_large",
    "plugin_invocation_unsupported",
    "plugin_output_too_large",
    "plugin_state_corrupt",
    "plugin_state_outcome_uncertain",
    "plugin_state_too_large",
    "plugin_state_unavailable",
    "plugin_lifecycle_failed",
    "manifest_rejected",
    "no_active_candidate",
    "runner_failed",
    "sandbox_unavailable",
    "sandbox_unavailable_probe_child",
    "sandbox_unavailable_probe_readiness",
    "sandbox_unavailable_probe_snapshot",
    "sandbox_unavailable_probe_verification",
    "snapshot_broker_unavailable",
    "stale_approval",
    "store_unavailable",
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
        request_id, operation, payload = _decode_invocation_request(request)
        if operation == "workspace.run":
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
            output = _workspace_result_json(result)
        elif operation == "plugin.run":
            phase = "execution"
            candidate, _ = active_candidate(
                _plugin_store_root(),
                candidate_digest=payload["candidate_digest"],
                manifest_digest=payload["manifest_digest"],
                scope_digest=payload["scope_digest"],
                expected_generation=payload["expected_generation"],
            )
            if candidate.manifest.plugin_id != payload["plugin_id"]:
                raise PluginLifecycleError("approval_binding_mismatch")
            needs_workspace = bool(
                candidate.manifest.process_exec
                or candidate.manifest.read_scope
                or candidate.manifest.write_scope
            )
            if needs_workspace != payload["workspace_required"]:
                raise PluginLifecycleError("approval_binding_mismatch")
            invocation_input = payload["input"]
            if needs_workspace and invocation_input is not None:
                raise PluginLifecycleError("plugin_invocation_unsupported")
            runner_source = candidate.source.decode("utf-8", errors="strict")
            snapshot_mount_path = os.environ.get("KHAOS_SNAPSHOT_MOUNT_PATH")
            snapshot_storage_text = os.environ.get("KHAOS_SNAPSHOT_STORAGE_BYTES")
            if snapshot_mount_path is None or snapshot_storage_text is None:
                raise KernelLaunchError("sandbox_unavailable")
            if not snapshot_storage_text.isdecimal():
                raise KernelLaunchError("sandbox_unavailable")
            runner_options = {
                "runner_source": runner_source,
                "workspace_read_scope": candidate.manifest.read_scope,
                "workspace_write_scope": candidate.manifest.write_scope,
                "timeout_seconds": 30,
                "cancel_requested": _cancellation_reader(cancel_fd),
                "brokered_snapshot_mount_path": snapshot_mount_path,
                "brokered_snapshot_storage_bytes": int(snapshot_storage_text),
                "process_exec_allowed": candidate.manifest.process_exec,
                "plugin_id": candidate.manifest.plugin_id,
                "plugin_state_root": _plugin_state_root(),
            }
            if needs_workspace:
                phase = "bookmark"
                bookmark = _read_workspace_bookmark(0)
                with _scoped_workspace_bookmark(bookmark):
                    result = run_workspace_command(
                        workspace,
                        workspace_root_fd=root_fd,
                        **runner_options,
                    )
            else:
                if invocation_input is None:
                    raise PluginLifecycleError("plugin_invocation_unsupported")
                with tempfile.TemporaryDirectory(prefix="khaos-plugin-session-") as value:
                    result = run_workspace_command(
                        value,
                        plugin_input=invocation_input,
                        **runner_options,
                    )
            phase = "result"
            output = _workspace_result_json(result)
        else:
            phase = "lifecycle"
            if os.read(0, 1):
                raise ValueError("unexpected lifecycle transfer data")
            output = _handle_plugin_lifecycle(operation, payload)
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
    except PluginLifecycleError as error:
        request_id = request.get("request_id") if "request" in locals() else None
        if not is_valid_token(request_id):
            return 2
        response = _error_response(
            request_id,
            error.code if error.code in _REPORTED_ERRORS else "kernel_failed",
        )
    except Exception as error:
        request_id = request.get("request_id") if "request" in locals() else None
        if not is_valid_token(request_id):
            return 2
        bridge_code = {
            "request": "workspace_rejected_bridge_request",
            "bookmark": "workspace_rejected_bridge_bookmark",
            "execution": _execution_failure_code(error),
            "lifecycle": "plugin_lifecycle_failed",
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


def _workspace_result_json(result: object) -> str:
    return json.dumps(
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


def _plugin_store_root() -> str:
    value = os.environ.get("KHAOS_PLUGIN_STORE_PATH")
    if not value or not os.path.isabs(value):
        raise PluginLifecycleError("store_unavailable")
    return value


def _plugin_state_root() -> str:
    value = os.environ.get("KHAOS_PLUGIN_STATE_PATH")
    if not value or not os.path.isabs(value):
        raise PluginLifecycleError("plugin_state_unavailable")
    return value


def _handle_plugin_lifecycle(operation: str, payload: dict[str, object]) -> str:
    store_root = _plugin_store_root()
    if operation == "plugin.admit":
        manifest = _decode_bounded_base64(payload["manifest_base64"], 4_096)
        source = _decode_bounded_base64(payload["source_base64"], 10_240)
        candidate = admit_candidate(store_root, manifest, source)
        _, _, generation = activation_details(store_root)
        result = {"candidate": _candidate_summary(candidate), "generation": generation}
    elif operation == "plugin.activate":
        activate_candidate(
            store_root,
            str(payload["candidate_digest"]),
            str(payload["manifest_digest"]),
            str(payload["scope_digest"]),
            expected_generation=int(payload["expected_generation"]),
        )
        result = _state_summary(store_root)
    elif operation == "plugin.state":
        result = _state_summary(store_root)
    elif operation == "plugin.rollback":
        rollback(
            store_root,
            expected_generation=int(payload["expected_generation"]),
            candidate_digest=str(payload["candidate_digest"]),
            manifest_digest=str(payload["manifest_digest"]),
            scope_digest=str(payload["scope_digest"]),
        )
        result = _state_summary(store_root)
    else:
        raise PluginLifecycleError("invalid_request")
    return json.dumps(result, sort_keys=True, separators=(",", ":"))


def _decode_bounded_base64(value: object, maximum: int) -> bytes:
    if type(value) is not str:
        raise PluginLifecycleError("invalid_request")
    import base64
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise PluginLifecycleError("invalid_request") from error
    if not data or len(data) > maximum or base64.b64encode(data).decode("ascii") != value:
        raise PluginLifecycleError("invalid_request")
    return data


def _candidate_summary(candidate: PluginCandidate) -> dict[str, object]:
    return {
        "plugin_id": candidate.manifest.plugin_id,
        "candidate_digest": candidate.candidate_digest,
        "manifest_digest": candidate.manifest_digest,
        "scope_digest": candidate.scope_digest,
        "process_exec": candidate.manifest.process_exec,
        "read_scope": list(candidate.manifest.read_scope),
        "write_scope": list(candidate.manifest.write_scope),
    }


def _activation_summary(
    slot: tuple[PluginCandidate, Activation] | None,
) -> dict[str, object] | None:
    if slot is None:
        return None
    candidate, activation = slot
    return {
        **_candidate_summary(candidate),
        "slot": activation.slot,
        "approved_at": activation.approved_at,
        "expires_at": activation.expires_at,
        "approval_validity_seconds": ACTIVATION_APPROVAL_SECONDS,
    }


def _state_summary(store_root: str) -> dict[str, object]:
    active, previous, generation = activation_details(store_root)
    return {
        "active": _activation_summary(active),
        "previous": _activation_summary(previous),
        "generation": generation,
    }


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
    request_id, operation, payload = _decode_invocation_request(request)
    if operation != "workspace.run":
        raise ValueError("invalid workspace request")
    return request_id, payload


def _decode_invocation_request(
    request: object,
) -> tuple[str, str, dict[str, object]]:
    if (
        type(request) is not dict
        or set(request) != _REQUEST_FIELDS
        or type(request.get("version")) is not int
        or request["version"] != _WORKSPACE_XPC_OPERATION_VERSION
        or not is_valid_token(request.get("request_id"))
        or type(request.get("operation")) is not str
        or type(request.get("payload")) is not dict
    ):
        raise ValueError("invalid operation request")
    operation = request["operation"]
    payload = request["payload"]
    if operation == "workspace.run":
        if set(payload) != _PAYLOAD_FIELDS:
            raise ValueError("invalid workspace request")
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
    elif operation == "plugin.admit":
        if set(payload) != {"manifest_base64", "source_base64"}:
            raise ValueError("invalid lifecycle request")
        _validate_base64_field(payload.get("manifest_base64"), 4_096)
        _validate_base64_field(payload.get("source_base64"), 10_240)
    elif operation in ("plugin.activate", "plugin.rollback"):
        if set(payload) != {
            "candidate_digest", "manifest_digest", "scope_digest",
            "expected_generation",
        }:
            raise ValueError("invalid lifecycle request")
        if (
            any(
                type(payload.get(field)) is not str
                or re.fullmatch(r"[0-9a-f]{64}", payload[field]) is None
                for field in ("candidate_digest", "manifest_digest", "scope_digest")
            )
            or type(payload.get("expected_generation")) is not int
            or payload["expected_generation"] < 0
        ):
            raise ValueError("invalid lifecycle approval")
    elif operation == "plugin.run":
        if set(payload) != {
            "plugin_id", "candidate_digest", "manifest_digest", "scope_digest",
            "expected_generation", "input", "workspace_required",
        }:
            raise ValueError("invalid lifecycle request")
        if (
            type(payload.get("plugin_id")) is not str
            or re.fullmatch(r"[a-z][a-z0-9-]{0,63}", payload["plugin_id"]) is None
            or any(
                type(payload.get(field)) is not str
                or re.fullmatch(r"[0-9a-f]{64}", payload[field]) is None
                for field in ("candidate_digest", "manifest_digest", "scope_digest")
            )
            or type(payload.get("expected_generation")) is not int
            or payload["expected_generation"] < 0
            or type(payload.get("workspace_required")) is not bool
            or payload.get("input") is not None and type(payload.get("input")) is not dict
        ):
            raise ValueError("invalid lifecycle approval")
        _validate_plugin_input(payload["input"])
    elif operation == "plugin.state":
        if payload:
            raise ValueError("invalid lifecycle request")
    else:
        raise ValueError("unknown operation")
    return request["request_id"], operation, payload


def _validate_plugin_input(value: object) -> None:
    if value is None:
        return
    if type(value) is not dict:
        raise ValueError("invalid Plugin input")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise ValueError("invalid Plugin input") from error
    if (
        len(encoded) > MAX_PLUGIN_INPUT_BYTES
        or not _json_nesting_within_limit(
            encoded,
            maximum_depth=MAX_PLUGIN_INPUT_NESTING,
        )
    ):
        raise ValueError("Plugin input exceeds its bound")


def _validate_base64_field(value: object, maximum: int) -> None:
    import base64
    import binascii
    if type(value) is not str:
        raise ValueError("invalid lifecycle package")
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("invalid lifecycle package") from error
    if (
        not data
        or len(data) > maximum
        or base64.b64encode(data).decode("ascii") != value
    ):
        raise ValueError("invalid lifecycle package")
    if not data.decode("utf-8", errors="strict"):
        raise ValueError("invalid lifecycle package")


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
