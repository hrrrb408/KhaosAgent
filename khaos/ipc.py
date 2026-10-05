"""Small, bounded frames for kernel-created local IPC pipes."""

from __future__ import annotations

import fcntl
import json
import math
import os
import selectors
import secrets
import stat
import struct
import time
from collections.abc import Mapping
from typing import Any


PROTOCOL_VERSION = 6
MAX_FRAME_BYTES = 64 * 1024
MAX_OPERATION_SECONDS = 60.0
MAX_RUNNER_SOURCE_BYTES = 10 * 1024
MAX_WORKSPACE_READ_BYTES = 32 * 1024
MAX_WORKSPACE_WRITE_BYTES = 32 * 1024
MAX_WORKSPACE_LIST_ENTRIES = 128
MAX_WORKSPACE_LIST_NAME_BYTES = 4 * 1024
MAX_WORKSPACE_FILESYSTEM_OPERATIONS = 128
_LENGTH = struct.Struct("!I")


class IPCProtocolError(RuntimeError):
    """The local peer sent an invalid, oversized, or late message."""


class FrameReader:
    """Incrementally decode bounded frames from one anonymous pipe."""

    def __init__(self, read_fd: int) -> None:
        _require_pipe(read_fd, os.O_RDONLY)
        self._read_fd = read_fd
        self._buffer = bytearray()
        self._frame_size: int | None = None

    def receive_ready(self) -> dict[str, Any] | None:
        """Return one complete frame, or None while the next frame is partial."""
        while True:
            if self._frame_size is None and len(self._buffer) >= _LENGTH.size:
                (self._frame_size,) = _LENGTH.unpack_from(self._buffer)
                if self._frame_size == 0 or self._frame_size > MAX_FRAME_BYTES:
                    raise IPCProtocolError("IPC frame size is invalid")

            frame_end = (
                _LENGTH.size + self._frame_size
                if self._frame_size is not None
                else _LENGTH.size
            )
            if len(self._buffer) >= frame_end:
                payload = bytes(self._buffer[_LENGTH.size : frame_end])
                del self._buffer[:frame_end]
                self._frame_size = None
                return _decode_payload(payload)

            try:
                chunk = os.read(self._read_fd, frame_end - len(self._buffer))
            except InterruptedError:
                continue
            except BlockingIOError:
                return None
            except OSError as exc:
                raise IPCProtocolError("IPC pipe read failed") from exc
            if not chunk:
                message = (
                    "IPC peer closed an incomplete frame"
                    if self._buffer
                    else "IPC peer closed its input pipe"
                )
                raise IPCProtocolError(message)
            self._buffer.extend(chunk)


def send_frame(
    write_fd: int,
    message: Mapping[str, Any],
    *,
    timeout_seconds: float = 5.0,
) -> None:
    """Send one canonical JSON object; the pipe endpoint becomes nonblocking."""
    deadline = _deadline(timeout_seconds)
    _require_pipe(write_fd, os.O_WRONLY)
    _write_bytes_until(write_fd, _encode(message), deadline)


def receive_frame(
    read_fd: int,
    *,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Receive one bounded JSON object; the pipe endpoint becomes nonblocking."""
    deadline = _deadline(timeout_seconds)
    _require_pipe(read_fd, os.O_RDONLY)
    return _receive_frame_until(read_fd, deadline)


def ping_peer(
    read_fd: int,
    write_fd: int,
    *,
    timeout_seconds: float = 5.0,
) -> None:
    """Nonce-check the peer already bound to these anonymous pipe ends."""
    deadline = _deadline(timeout_seconds)
    _require_pipe(read_fd, os.O_RDONLY)
    _require_pipe(write_fd, os.O_WRONLY)
    request_id = secrets.token_hex(16)
    nonce = secrets.token_hex(16)
    _write_bytes_until(
        write_fd,
        _encode(
            {
                "version": PROTOCOL_VERSION,
                "request_id": request_id,
                "operation": "ping",
                "payload": {"nonce": nonce},
            }
        ),
        deadline,
    )
    response = _receive_frame_until(read_fd, deadline)
    if set(response) != {"version", "request_id", "ok", "result"}:
        raise IPCProtocolError("IPC ping response fields are invalid")
    if (
        type(response["version"]) is not int
        or response["version"] != PROTOCOL_VERSION
        or response["request_id"] != request_id
        or response["ok"] is not True
        or not isinstance(response["result"], dict)
        or set(response["result"]) != {"nonce"}
        or not is_valid_token(response["result"]["nonce"])
        or not secrets.compare_digest(response["result"]["nonce"], nonce)
    ):
        raise IPCProtocolError("IPC ping response did not match its request")


def answer_ping(
    read_fd: int = 0,
    write_fd: int = 1,
    *,
    timeout_seconds: float = 5.0,
) -> None:
    """Echo a valid one-time ping challenge from the peer on these pipes."""
    request = receive_frame(read_fd, timeout_seconds=timeout_seconds)
    request_id = request.get("request_id")
    payload = request.get("payload")
    if (
        set(request) != {"version", "request_id", "operation", "payload"}
        or type(request.get("version")) is not int
        or request["version"] != PROTOCOL_VERSION
        or not is_valid_token(request_id)
        or request.get("operation") != "ping"
        or type(payload) is not dict
        or set(payload) != {"nonce"}
        or not is_valid_token(payload.get("nonce"))
    ):
        raise IPCProtocolError("IPC ping challenge is invalid")
    send_frame(
        write_fd,
        {
            "version": PROTOCOL_VERSION,
            "request_id": request_id,
            "ok": True,
            "result": {"nonce": payload["nonce"]},
        },
        timeout_seconds=timeout_seconds,
    )


def is_valid_token(value: object) -> bool:
    """Check the fixed lowercase-hex form used for request IDs and nonces."""
    return (
        type(value) is str
        and len(value) == 32
        and value.isascii()
        and all(character in "0123456789abcdef" for character in value)
    )


def validate_runner_source(value: object) -> str:
    """Bound the one-shot untrusted source handed to an isolated Runner."""
    if type(value) is not str or not value or "\x00" in value:
        raise IPCProtocolError("runner source is invalid")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise IPCProtocolError("runner source is invalid") from exc
    if len(encoded) > MAX_RUNNER_SOURCE_BYTES:
        raise IPCProtocolError("runner source exceeds its limit")
    return value


def _require_pipe(descriptor: int, access_mode: int) -> None:
    if isinstance(descriptor, bool) or not isinstance(descriptor, int):
        raise IPCProtocolError("IPC endpoint must be an anonymous pipe")
    try:
        metadata = os.fstat(descriptor)
        actual_mode = fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE
    except OSError as exc:
        raise IPCProtocolError("IPC pipe descriptor is unavailable") from exc
    if (
        not stat.S_ISFIFO(metadata.st_mode)
        or metadata.st_nlink != 0
        or actual_mode != access_mode
    ):
        raise IPCProtocolError(
            "IPC endpoint must be a correctly directed anonymous pipe"
        )
    try:
        # Readiness alone cannot bound a large blocking pipe write.
        os.set_blocking(descriptor, False)
    except OSError as exc:
        raise IPCProtocolError("IPC pipe cannot use bounded nonblocking I/O") from exc


def _encode(message: Mapping[str, Any]) -> bytes:
    try:
        payload = json.dumps(
            dict(message),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise IPCProtocolError("IPC message is not canonical JSON") from exc
    if not payload or len(payload) > MAX_FRAME_BYTES:
        raise IPCProtocolError("IPC frame size is invalid")
    return _LENGTH.pack(len(payload)) + payload


def _write_bytes_until(write_fd: int, data: bytes, deadline: float) -> None:
    offset = 0
    while offset < len(data):
        try:
            _wait_until(write_fd, selectors.EVENT_WRITE, deadline)
            written = os.write(write_fd, data[offset:])
        except (InterruptedError, BlockingIOError):
            continue
        except OSError as exc:
            raise IPCProtocolError("IPC pipe write failed") from exc
        if written <= 0:
            raise IPCProtocolError("IPC peer closed its input pipe")
        offset += written


def _receive_frame_until(read_fd: int, deadline: float) -> dict[str, Any]:
    header = _read_exact(read_fd, _LENGTH.size, deadline)
    (length,) = _LENGTH.unpack(header)
    if length == 0 or length > MAX_FRAME_BYTES:
        raise IPCProtocolError("IPC frame size is invalid")
    payload = _read_exact(read_fd, length, deadline)

    return _decode_payload(payload)


def _decode_payload(payload: bytes) -> dict[str, Any]:
    try:
        message = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        IPCProtocolError,
        ValueError,
        RecursionError,
    ) as exc:
        raise IPCProtocolError("IPC frame is not valid strict JSON") from exc
    if not isinstance(message, dict):
        raise IPCProtocolError("IPC frame must contain a JSON object")
    return message


def _read_exact(read_fd: int, size: int, deadline: float) -> bytes:
    result = bytearray()
    while len(result) < size:
        try:
            _wait_until(read_fd, selectors.EVENT_READ, deadline)
            chunk = os.read(read_fd, size - len(result))
        except (InterruptedError, BlockingIOError):
            continue
        except OSError as exc:
            raise IPCProtocolError("IPC pipe read failed") from exc
        if not chunk:
            raise IPCProtocolError("IPC peer closed an incomplete frame")
        result.extend(chunk)
    return bytes(result)


def _wait_until(descriptor: int, event: int, deadline: float) -> None:
    while True:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(descriptor, event)
                ready = selector.select(_remaining(deadline))
        except InterruptedError:
            continue
        except OSError as exc:
            raise IPCProtocolError("IPC readiness check failed") from exc
        if ready:
            return
        raise IPCProtocolError("IPC deadline expired")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IPCProtocolError("IPC JSON contains a duplicate field")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise IPCProtocolError(f"IPC JSON contains unsupported constant {value}")


def _deadline(timeout_seconds: float) -> float:
    if isinstance(timeout_seconds, bool) or not isinstance(
        timeout_seconds, (int, float)
    ):
        raise ValueError("IPC timeout must be finite and within the supported range")
    try:
        timeout = float(timeout_seconds)
    except OverflowError as exc:
        raise ValueError(
            "IPC timeout must be finite and within the supported range"
        ) from exc
    if (
        not math.isfinite(timeout)
        or timeout <= 0
        or timeout > MAX_OPERATION_SECONDS
    ):
        raise ValueError("IPC timeout must be finite and within the supported range")
    return time.monotonic() + timeout


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise IPCProtocolError("IPC deadline expired")
    return remaining
