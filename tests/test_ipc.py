from __future__ import annotations

import json
import os
import socket
import struct
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from collections.abc import Iterator

from khaos.ipc import (
    MAX_OPERATION_SECONDS,
    MAX_RUNNER_SOURCE_BYTES,
    FrameReader,
    IPCProtocolError,
    MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    ping_peer,
    receive_frame,
    send_frame,
    validate_runner_source,
)


class IPCProtocolTests(unittest.TestCase):
    def test_runner_source_is_bounded_utf8_and_nonempty(self) -> None:
        source = "#" * MAX_RUNNER_SOURCE_BYTES
        self.assertEqual(validate_runner_source(source), source)
        for invalid in ("", "\x00", "#" * (MAX_RUNNER_SOURCE_BYTES + 1), "\ud800"):
            with self.subTest(invalid_length=len(invalid)):
                with self.assertRaisesRegex(IPCProtocolError, "runner source"):
                    validate_runner_source(invalid)

    def test_frame_reader_handles_partial_and_back_to_back_frames(self) -> None:
        with _pipe() as (receiver, sender):
            frame_reader = FrameReader(receiver)
            messages = (
                {"version": PROTOCOL_VERSION, "request_id": "a" * 32},
                {"version": PROTOCOL_VERSION, "request_id": "b" * 32},
            )
            encoded = []
            for message in messages:
                payload = json.dumps(message, separators=(",", ":")).encode()
                encoded.append(struct.pack("!I", len(payload)) + payload)

            os.write(sender, encoded[0][:2])
            self.assertIsNone(frame_reader.receive_ready())
            os.write(sender, encoded[0][2:] + encoded[1])
            self.assertEqual(frame_reader.receive_ready(), messages[0])
            self.assertEqual(frame_reader.receive_ready(), messages[1])
            self.assertIsNone(frame_reader.receive_ready())

    def test_frame_reader_rejects_oversized_header(self) -> None:
        with _pipe() as (receiver, sender):
            frame_reader = FrameReader(receiver)
            os.write(sender, struct.pack("!I", MAX_FRAME_BYTES + 1))
            with self.assertRaisesRegex(IPCProtocolError, "size"):
                frame_reader.receive_ready()

    def test_ping_is_bound_to_request_id_and_nonce(self) -> None:
        with _duplex_pipes() as (broker_read, broker_write, runner_read, runner_write):
            server_errors: list[BaseException] = []

            def serve_ping() -> None:
                try:
                    request = receive_frame(runner_read)
                    self.assertEqual(
                        set(request), {"version", "request_id", "operation", "payload"}
                    )
                    self.assertEqual(request["version"], PROTOCOL_VERSION)
                    self.assertEqual(request["operation"], "ping")
                    send_frame(
                        runner_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": request["request_id"],
                            "ok": True,
                            "result": {"nonce": request["payload"]["nonce"]},
                        },
                    )
                except BaseException as exc:
                    server_errors.append(exc)

            server = threading.Thread(target=serve_ping)
            server.start()
            ping_peer(broker_read, broker_write, timeout_seconds=2)
            server.join(timeout=2)
            self.assertFalse(server.is_alive())
            self.assertEqual(server_errors, [])

    def test_ping_rejects_response_with_wrong_nonce(self) -> None:
        with _duplex_pipes() as (broker_read, broker_write, runner_read, runner_write):
            def serve_wrong_ping() -> None:
                request = receive_frame(runner_read)
                send_frame(
                    runner_write,
                    {
                        "version": PROTOCOL_VERSION,
                        "request_id": request["request_id"],
                        "ok": True,
                        "result": {"nonce": "0" * 32},
                    },
                )

            server = threading.Thread(target=serve_wrong_ping)
            server.start()
            with self.assertRaisesRegex(IPCProtocolError, "did not match"):
                ping_peer(broker_read, broker_write, timeout_seconds=2)
            server.join(timeout=2)
            self.assertFalse(server.is_alive())

    def test_ping_rejects_non_ascii_nonce_without_parser_escape(self) -> None:
        with _duplex_pipes() as (broker_read, broker_write, runner_read, runner_write):
            def serve_wrong_ping() -> None:
                request = receive_frame(runner_read)
                send_frame(
                    runner_write,
                    {
                        "version": PROTOCOL_VERSION,
                        "request_id": request["request_id"],
                        "ok": True,
                        "result": {"nonce": "é" * 32},
                    },
                )

            server = threading.Thread(target=serve_wrong_ping)
            server.start()
            with self.assertRaisesRegex(IPCProtocolError, "did not match"):
                ping_peer(broker_read, broker_write, timeout_seconds=2)
            server.join(timeout=2)
            self.assertFalse(server.is_alive())

    def test_rejects_oversized_frame_before_reading_body(self) -> None:
        with _pipe() as (receiver, sender):
            os.write(sender, struct.pack("!I", MAX_FRAME_BYTES + 1))
            with self.assertRaisesRegex(IPCProtocolError, "size"):
                receive_frame(receiver)

    def test_rejects_socket_transport(self) -> None:
        receiver, sender = socket.socketpair()
        try:
            with self.assertRaisesRegex(IPCProtocolError, "pipe"):
                receive_frame(receiver.fileno())
        finally:
            receiver.close()
            sender.close()

    def test_rejects_named_fifo_transport(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "ipc")
            os.mkfifo(path)
            read_fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            try:
                with self.assertRaisesRegex(IPCProtocolError, "anonymous pipe"):
                    receive_frame(read_fd)
            finally:
                os.close(read_fd)

    def test_rejects_pipe_used_in_the_wrong_direction(self) -> None:
        with _pipe() as (read_fd, write_fd):
            with self.assertRaisesRegex(IPCProtocolError, "directed"):
                receive_frame(write_fd)
            with self.assertRaisesRegex(IPCProtocolError, "directed"):
                send_frame(read_fd, {"invalid": True})

    def test_rejects_duplicate_json_fields(self) -> None:
        with _pipe() as (receiver, sender):
            _write_json_payload(sender, b'{"version":1,"version":1}')
            with self.assertRaisesRegex(IPCProtocolError, "strict JSON"):
                receive_frame(receiver)

    def test_rejects_non_object_json(self) -> None:
        with _pipe() as (receiver, sender):
            payload = json.dumps([1, 2, 3]).encode()
            _write_json_payload(sender, payload)
            with self.assertRaisesRegex(IPCProtocolError, "JSON object"):
                receive_frame(receiver)

    def test_rejects_excessive_json_nesting(self) -> None:
        with _pipe() as (receiver, sender):
            payload = b'{"nested":' + (b"[" * 10000) + b"0" + (b"]" * 10000) + b"}"
            sender_errors: list[BaseException] = []

            def send_nested_frame() -> None:
                try:
                    _write_json_payload(sender, payload)
                except BaseException as exc:
                    sender_errors.append(exc)

            sender_thread = threading.Thread(target=send_nested_frame)
            sender_thread.start()
            with self.assertRaisesRegex(IPCProtocolError, "strict JSON"):
                receive_frame(receiver)
            sender_thread.join(timeout=2)
            self.assertFalse(sender_thread.is_alive())
            self.assertEqual(sender_errors, [])

    def test_json_nesting_ignores_brackets_inside_strings(self) -> None:
        text = "]" * 40 + r'\"' + "{" * 40 + "[" * 40
        with _pipe() as (receiver, sender):
            send_frame(sender, {"text": text})
            self.assertEqual(receive_frame(receiver), {"text": text})

    def test_send_rejects_oversized_and_nonfinite_values(self) -> None:
        with _pipe() as (_, writer):
            with self.assertRaisesRegex(IPCProtocolError, "size"):
                send_frame(writer, {"value": "x" * MAX_FRAME_BYTES})
            with self.assertRaisesRegex(IPCProtocolError, "canonical JSON"):
                send_frame(writer, {"value": float("nan")})

    def test_receive_timeout_is_bounded(self) -> None:
        with _pipe() as (receiver, _):
            with self.assertRaisesRegex(IPCProtocolError, "deadline"):
                receive_frame(receiver, timeout_seconds=0.01)

    def test_send_timeout_is_bounded_when_peer_does_not_read(self) -> None:
        with _pipe() as (_, writer):
            message = {"value": "x" * (MAX_FRAME_BYTES - 32)}
            for _ in range(256):
                try:
                    send_frame(writer, message, timeout_seconds=0.01)
                except IPCProtocolError as exc:
                    self.assertIn("deadline", str(exc))
                    break
            else:
                self.fail("pipe never filled while the peer was not reading")

    def test_send_reports_closed_peer_as_protocol_error(self) -> None:
        read_fd, write_fd = os.pipe()
        os.close(read_fd)
        try:
            with self.assertRaisesRegex(IPCProtocolError, "pipe write failed"):
                send_frame(write_fd, {"request": "ping"})
        finally:
            os.close(write_fd)

    def test_rejects_invalid_timeout_limits(self) -> None:
        with _pipe() as (receiver, _):
            for timeout in (
                True,
                0,
                -1,
                float("inf"),
                MAX_OPERATION_SECONDS + 1,
                10**1000,
            ):
                with self.subTest(timeout=type(timeout).__name__):
                    with self.assertRaises(ValueError):
                        receive_frame(receiver, timeout_seconds=timeout)


@contextmanager
def _pipe() -> Iterator[tuple[int, int]]:
    read_fd, write_fd = os.pipe()
    try:
        yield read_fd, write_fd
    finally:
        os.close(read_fd)
        os.close(write_fd)


@contextmanager
def _duplex_pipes() -> Iterator[tuple[int, int, int, int]]:
    runner_read, broker_write = os.pipe()
    broker_read, runner_write = os.pipe()
    descriptors = (broker_read, broker_write, runner_read, runner_write)
    try:
        yield descriptors
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


def _write_json_payload(write_fd: int, payload: bytes) -> None:
    os.write(write_fd, struct.pack("!I", len(payload)) + payload)


if __name__ == "__main__":
    unittest.main()
