"""Narrow IPC facade for an untrusted Runner process."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
import selectors
import time
from collections.abc import Callable, Sequence
from typing import Any

from .ipc import (
    MAX_OPERATION_SECONDS,
    MAX_PLUGIN_INPUT_BYTES,
    MAX_PLUGIN_OUTPUT_BYTES,
    MAX_PLUGIN_STATE_BYTES,
    MAX_WORKSPACE_LIST_ENTRIES,
    MAX_WORKSPACE_LIST_NAME_BYTES,
    MAX_WORKSPACE_READ_BYTES,
    MAX_WORKSPACE_WRITE_BYTES,
    FrameReader,
    IPCProtocolError,
    PROTOCOL_VERSION,
    _json_nesting_within_limit,
    receive_frame,
    send_frame,
)


def fs_read(path: str) -> bytes:
    """Read one bounded regular file through the Kernel's snapshot scope."""
    if type(path) is not str:
        raise TypeError("fs.read path must be a string")
    result = _request("fs.read", {"path": path})
    if set(result) != {"data_base64"} or type(result.get("data_base64")) is not str:
        raise IPCProtocolError("Kernel fs.read result is invalid")
    encoded = result["data_base64"]
    if len(encoded) > ((MAX_WORKSPACE_READ_BYTES + 2) // 3) * 4:
        raise IPCProtocolError("Kernel fs.read result exceeds its limit")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise IPCProtocolError("Kernel fs.read result is not valid base64") from exc
    if (
        len(content) > MAX_WORKSPACE_READ_BYTES
        or base64.b64encode(content).decode("ascii") != encoded
    ):
        raise IPCProtocolError("Kernel fs.read result is not canonical or bounded")
    return content


def fs_list(path: str = "") -> list[dict[str, str | int | None]]:
    """List bounded entry metadata through the Kernel's snapshot scope."""
    if type(path) is not str:
        raise TypeError("fs.list path must be a string")
    result = _request("fs.list", {"path": path})
    if set(result) != {"entries"} or type(result.get("entries")) is not list:
        raise IPCProtocolError("Kernel fs.list result is invalid")
    entries = result["entries"]
    if len(entries) > MAX_WORKSPACE_LIST_ENTRIES:
        raise IPCProtocolError("Kernel fs.list result exceeds its entry limit")

    names: list[str] = []
    name_bytes = 0
    for entry in entries:
        if (
            type(entry) is not dict
            or set(entry) != {"name", "kind", "size"}
            or type(entry.get("name")) is not str
            or type(entry.get("kind")) is not str
            or entry.get("kind") not in {"directory", "file", "other", "symlink"}
        ):
            raise IPCProtocolError("Kernel fs.list entry is invalid")
        name = entry["name"]
        if name in ("", ".", "..") or "/" in name or "\x00" in name:
            raise IPCProtocolError("Kernel fs.list entry name is invalid")
        try:
            name_bytes += len(name.encode("utf-8", errors="strict"))
        except UnicodeEncodeError as exc:
            raise IPCProtocolError("Kernel fs.list entry name is invalid") from exc
        size = entry["size"]
        if entry["kind"] == "file":
            if type(size) is not int or size < 0:
                raise IPCProtocolError("Kernel fs.list file size is invalid")
        elif size is not None:
            raise IPCProtocolError("Kernel fs.list non-file size is invalid")
        names.append(name)

    if (
        name_bytes > MAX_WORKSPACE_LIST_NAME_BYTES
        or len(set(names)) != len(names)
        or names != sorted(names, key=lambda name: name.encode("utf-8"))
    ):
        raise IPCProtocolError("Kernel fs.list result is not canonical or bounded")
    return entries


def fs_write(path: str, data: bytes) -> dict[str, int | str]:
    """Replace one exact, pre-authorized regular file through the Kernel."""
    if type(path) is not str or type(data) is not bytes:
        raise TypeError("fs.write requires a string path and bytes")
    if len(data) > MAX_WORKSPACE_WRITE_BYTES:
        raise ValueError("fs.write data exceeds its limit")
    result = _request(
        "fs.write",
        {
            "path": path,
            "data_base64": base64.b64encode(data).decode("ascii"),
        },
    )
    expected = {
        "written_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    if result != expected:
        raise IPCProtocolError("Kernel fs.write result is invalid")
    return expected


def process_exec(
    argv: Sequence[str],
    *,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Request one Kernel-confined command and optionally cancel it while active."""
    if (
        isinstance(argv, (str, bytes))
        or not isinstance(argv, Sequence)
        or any(type(argument) is not str for argument in argv)
    ):
        raise TypeError("process.exec argv must be a sequence of strings")
    result = _request(
        "process.exec",
        {"argv": list(argv)},
        cancel_requested=cancel_requested,
    )
    if (
        set(result) != {"returncode", "stdout", "stderr"}
        or type(result.get("returncode")) is not int
        or type(result.get("stdout")) is not str
        or type(result.get("stderr")) is not str
    ):
        raise IPCProtocolError("Kernel process result is invalid")
    return result


def workspace_commit() -> dict[str, Any]:
    """Ask the Kernel to validate and commit Runner output."""
    result = _request("workspace.commit", {})
    if (
        set(result) != {"added", "modified", "deleted"}
        or any(type(result.get(key)) is not int or result[key] < 0 for key in result)
    ):
        raise IPCProtocolError("Kernel commit result is invalid")
    return result


def state_read() -> bytes | None:
    """Read this logical Plugin's bounded private state blob through the Kernel."""
    result = _request("state.read", {})
    if (
        set(result) != {"present", "data_base64"}
        or type(result.get("present")) is not bool
        or type(result.get("data_base64")) is not str
    ):
        raise IPCProtocolError("Kernel state.read result is invalid")
    encoded = result["data_base64"]
    if len(encoded) > ((MAX_PLUGIN_STATE_BYTES + 2) // 3) * 4:
        raise IPCProtocolError("Kernel state.read result exceeds its limit")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise IPCProtocolError("Kernel state.read result is not valid base64") from exc
    if (
        len(content) > MAX_PLUGIN_STATE_BYTES
        or base64.b64encode(content).decode("ascii") != encoded
        or (not result["present"] and encoded != "")
    ):
        raise IPCProtocolError("Kernel state.read result is not canonical or bounded")
    return content if result["present"] else None


def state_replace(data: bytes) -> None:
    """Atomically replace this logical Plugin's opaque, bounded state blob."""
    if type(data) is not bytes:
        raise TypeError("state.replace data must be bytes")
    if len(data) > MAX_PLUGIN_STATE_BYTES:
        raise ValueError("state.replace data exceeds its limit")
    result = _request(
        "state.replace", {"data_base64": base64.b64encode(data).decode("ascii")}
    )
    if result != {"written_bytes": len(data)}:
        raise IPCProtocolError("Kernel state.replace result is invalid")


def plugin_output(value: Any) -> None:
    """Return one generic JSON result to the untrusted Agent Host."""
    if type(value) is not dict:
        raise TypeError("Plugin output must be a JSON object")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ValueError("Plugin output is not bounded JSON data") from exc
    if (
        len(encoded) > MAX_PLUGIN_OUTPUT_BYTES
        or not _json_nesting_within_limit(encoded)
    ):
        raise ValueError("Plugin output exceeds its limit")
    result = _request(
        "plugin.output", {"data_base64": base64.b64encode(encoded).decode("ascii")}
    )
    if result:
        raise IPCProtocolError("Kernel plugin.output result is invalid")


def _request(
    operation: str,
    payload: dict[str, Any],
    *,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    if cancel_requested is not None and operation != "process.exec":
        raise ValueError("only process.exec supports cancellation")
    request_id = secrets.token_hex(16)
    send_frame(
        1,
        {
            "version": PROTOCOL_VERSION,
            "request_id": request_id,
            "operation": operation,
            "payload": payload,
        },
        timeout_seconds=3,
    )
    if cancel_requested is None:
        response = receive_frame(0, timeout_seconds=MAX_OPERATION_SECONDS)
    else:
        response = _receive_cancellable_process_result(request_id, cancel_requested)

    succeeded, result_or_error = _decode_reply(response, request_id)
    if not succeeded:
        raise IPCProtocolError(
            f"Kernel rejected {operation}: {result_or_error['code']}"
        )
    return result_or_error


def _receive_cancellable_process_result(
    process_request_id: str,
    cancel_requested: Callable[[], bool],
) -> dict[str, Any]:
    reader = FrameReader(0)
    deadline = time.monotonic() + MAX_OPERATION_SECONDS
    cancel_request_id: str | None = None
    cancellation_accepted = False
    cancellation_response_received = False
    process_response: dict[str, Any] | None = None

    with selectors.DefaultSelector() as selector:
        selector.register(0, selectors.EVENT_READ)
        while True:
            response = reader.receive_ready()
            if response is not None:
                response_id = response.get("request_id")
                if response_id == process_request_id:
                    if process_response is not None:
                        raise IPCProtocolError("Kernel repeated the process.exec response")
                    process_response = response
                    if cancel_request_id is None:
                        return process_response
                    if cancellation_response_received:
                        _validate_cancellation_outcome(
                            process_response,
                            process_request_id,
                            cancellation_accepted,
                        )
                        return process_response
                    continue

                if response_id != cancel_request_id or cancel_request_id is None:
                    raise IPCProtocolError(
                        "Kernel response did not match the process or cancel request"
                    )
                succeeded, result_or_error = _decode_reply(
                    response, cancel_request_id
                )
                if cancellation_response_received:
                    raise IPCProtocolError("Kernel repeated the process.cancel response")
                cancellation_response_received = True
                if succeeded:
                    if result_or_error != {
                        "cancelled": True,
                        "process_request_id": process_request_id,
                    }:
                        raise IPCProtocolError("Kernel cancel acknowledgment is invalid")
                    cancellation_accepted = True
                elif result_or_error["code"] != "process_not_active":
                    raise IPCProtocolError(
                        f"Kernel rejected process.cancel: {result_or_error['code']}"
                    )
                if process_response is not None:
                    _validate_cancellation_outcome(
                        process_response,
                        process_request_id,
                        cancellation_accepted,
                    )
                    return process_response
                continue

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise IPCProtocolError("IPC deadline expired")
            if cancel_request_id is None and cancel_requested():
                cancel_request_id = secrets.token_hex(16)
                while cancel_request_id == process_request_id:
                    cancel_request_id = secrets.token_hex(16)
                send_frame(
                    1,
                    {
                        "version": PROTOCOL_VERSION,
                        "request_id": cancel_request_id,
                        "operation": "process.cancel",
                        "payload": {"process_request_id": process_request_id},
                    },
                    timeout_seconds=3,
                )
            selector.select(min(remaining, 0.05))


def _validate_cancellation_outcome(
    process_response: dict[str, Any],
    process_request_id: str,
    cancellation_accepted: bool,
) -> None:
    succeeded, result_or_error = _decode_reply(process_response, process_request_id)
    process_cancelled = not succeeded and result_or_error["code"] == "process_cancelled"
    if process_cancelled != cancellation_accepted:
        raise IPCProtocolError(
            "Kernel cancellation result did not match its acknowledgment"
        )


def _decode_reply(
    response: dict[str, Any], expected_request_id: str
) -> tuple[bool, dict[str, Any]]:
    if (
        type(response.get("version")) is not int
        or response["version"] != PROTOCOL_VERSION
        or response.get("request_id") != expected_request_id
    ):
        raise IPCProtocolError("Kernel response did not match its request")
    if set(response) == {"version", "request_id", "ok", "result"}:
        if response["ok"] is not True or type(response["result"]) is not dict:
            raise IPCProtocolError("Kernel success response is invalid")
        return True, response["result"]
    if set(response) == {"version", "request_id", "ok", "error"}:
        error = response["error"]
        if (
            response["ok"] is not False
            or type(error) is not dict
            or set(error) != {"code"}
            or type(error.get("code")) is not str
        ):
            raise IPCProtocolError("Kernel error response is invalid")
        return False, error
    raise IPCProtocolError("Kernel response schema is invalid")
