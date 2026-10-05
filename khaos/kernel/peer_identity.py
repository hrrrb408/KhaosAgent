"""One-time macOS peer PID checks for trusted parent/Runner launches."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import struct
import sys

from ..ipc import IPCProtocolError


_SOL_LOCAL = 0
_LOCAL_PEERPID = 0x002
_PEER_HANDSHAKE_TIMEOUT_SECONDS = 3.0


@contextmanager
def local_peer_pid_listener(
    directory: Path,
) -> Iterator[tuple[socket.socket, Path]]:
    """Bind a short-lived local socket below a private writable directory."""
    if sys.platform != "darwin":
        raise IPCProtocolError("OS peer PID checks require macOS")
    directory = directory.resolve(strict=True)
    path = directory / "p"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        # sockaddr_un bounds the supplied name, not the resolved filesystem
        # path. Bind relative to the pinned private directory so long Broker
        # lease paths cannot disable the mandatory OS peer-PID handshake.
        previous_fd = os.open(".", os.O_RDONLY | os.O_DIRECTORY)
        try:
            directory_fd = os.open(
                directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            try:
                os.fchdir(directory_fd)
                try:
                    listener.bind("p")
                finally:
                    os.fchdir(previous_fd)
            finally:
                os.close(directory_fd)
        finally:
            os.close(previous_fd)
        listener.listen(1)
    except OSError as exc:
        listener.close()
        raise IPCProtocolError("OS peer PID listener is unavailable") from exc
    try:
        yield listener, path
    finally:
        listener.close()
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise IPCProtocolError("OS peer PID listener could not be removed") from exc


def accept_local_peer_pid(listener: socket.socket, expected_pid: int) -> None:
    """Accept exactly one connection and require the spawned child's PID."""
    _validate_pid(expected_pid)
    listener.settimeout(_PEER_HANDSHAKE_TIMEOUT_SECONDS)
    try:
        connection, _ = listener.accept()
    except (OSError, TimeoutError) as exc:
        raise IPCProtocolError("OS peer PID connection timed out") from exc
    with connection:
        peer_pid = _local_peer_pid(connection)
    if peer_pid != expected_pid:
        raise IPCProtocolError("OS peer PID did not match the spawned Runner")


def verify_local_parent_pid(path: Path, expected_pid: int) -> None:
    """Connect once and require the OS-reported peer to be the direct parent."""
    _validate_pid(expected_pid)
    if sys.platform != "darwin":
        raise IPCProtocolError("OS peer PID checks require macOS")
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(_PEER_HANDSHAKE_TIMEOUT_SECONDS)
    try:
        connection.connect(os.fspath(path))
        peer_pid = _local_peer_pid(connection)
        if connection.recv(1):
            raise IPCProtocolError("OS peer PID handshake carried unexpected data")
    except OSError as exc:
        raise IPCProtocolError("OS parent PID could not be verified") from exc
    finally:
        connection.close()
    if peer_pid != expected_pid:
        raise IPCProtocolError("OS peer PID did not match the Kernel parent")


def _local_peer_pid(connection: socket.socket) -> int:
    if sys.platform != "darwin":
        raise IPCProtocolError("OS peer PID checks require macOS")
    try:
        value = connection.getsockopt(
            _SOL_LOCAL, _LOCAL_PEERPID, struct.calcsize("=i")
        )
    except OSError as exc:
        raise IPCProtocolError("OS peer PID is unavailable") from exc
    if not isinstance(value, bytes) or len(value) != struct.calcsize("=i"):
        raise IPCProtocolError("OS peer PID response is malformed")
    peer_pid = struct.unpack("=i", value)[0]
    _validate_pid(peer_pid)
    return peer_pid


def _validate_pid(value: object) -> None:
    if type(value) is not int or value <= 0:
        raise IPCProtocolError("OS peer PID is invalid")
