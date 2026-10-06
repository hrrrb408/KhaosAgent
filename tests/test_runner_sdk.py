from __future__ import annotations

import base64
import hashlib
import os
import threading
import unittest
from contextlib import contextmanager
from collections.abc import Iterator

from khaos.ipc import PROTOCOL_VERSION, receive_frame, send_frame
from khaos.runner_sdk import (
    fs_list,
    fs_read,
    fs_write,
    plugin_output,
    process_exec,
    state_read,
    state_replace,
)


class RunnerSDKTests(unittest.TestCase):
    def test_workspace_read_and_list_use_bounded_schemas(self) -> None:
        with _duplex_pipes() as (kernel_read, kernel_write):
            read_results: list[bytes] = []
            reader = threading.Thread(
                target=lambda: read_results.append(fs_read("src/main.py"))
            )
            reader.start()
            read_request = receive_frame(kernel_read, timeout_seconds=3)
            self.assertEqual(read_request["operation"], "fs.read")
            self.assertEqual(read_request["payload"], {"path": "src/main.py"})
            send_frame(
                kernel_write,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": read_request["request_id"],
                    "ok": True,
                    "result": {"data_base64": base64.b64encode(b"print('ok')").decode()},
                },
            )
            reader.join(timeout=3)
            self.assertFalse(reader.is_alive())
            self.assertEqual(read_results, [b"print('ok')"])

            list_results: list[list[dict[str, str | int | None]]] = []
            lister = threading.Thread(
                target=lambda: list_results.append(fs_list("src"))
            )
            lister.start()
            list_request = receive_frame(kernel_read, timeout_seconds=3)
            self.assertEqual(list_request["operation"], "fs.list")
            self.assertEqual(list_request["payload"], {"path": "src"})
            entries = [
                {"name": "main.py", "kind": "file", "size": 11},
                {"name": "tests", "kind": "directory", "size": None},
            ]
            send_frame(
                kernel_write,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": list_request["request_id"],
                    "ok": True,
                    "result": {"entries": entries},
                },
            )
            lister.join(timeout=3)
            self.assertFalse(lister.is_alive())
            self.assertEqual(list_results, [entries])

    def test_workspace_write_uses_exact_bounded_request_and_digest_reply(self) -> None:
        content = b"approved edit"
        with _duplex_pipes() as (kernel_read, kernel_write):
            results: list[dict[str, int | str]] = []
            writer = threading.Thread(
                target=lambda: results.append(
                    fs_write("src/main.py", content)
                )
            )
            writer.start()
            request = receive_frame(kernel_read, timeout_seconds=3)
            self.assertEqual(request["operation"], "fs.write")
            self.assertEqual(request["payload"]["path"], "src/main.py")
            self.assertEqual(
                base64.b64decode(request["payload"]["data_base64"], validate=True),
                content,
            )
            send_frame(
                kernel_write,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": request["request_id"],
                    "ok": True,
                    "result": {
                        "written_bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    },
                },
            )
            writer.join(timeout=3)

        self.assertFalse(writer.is_alive())
        self.assertEqual(
            results,
            [{"written_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}],
        )

    def test_workspace_write_rejects_oversized_bytes_before_ipc(self) -> None:
        from khaos.ipc import MAX_WORKSPACE_WRITE_BYTES

        with _duplex_pipes() as _:
            with self.assertRaisesRegex(ValueError, "exceeds its limit"):
                fs_write("large.txt", b"x" * (MAX_WORKSPACE_WRITE_BYTES + 1))

    def test_plugin_state_and_output_use_namespace_free_bounded_schemas(self) -> None:
        state = b'{"format":"khaos-memory-v1","items":{}}'
        with _duplex_pipes() as (kernel_read, kernel_write):
            results: list[bytes | None] = []
            reader = threading.Thread(target=lambda: results.append(state_read()))
            reader.start()
            read_request = receive_frame(kernel_read, timeout_seconds=3)
            self.assertEqual(read_request["operation"], "state.read")
            self.assertEqual(read_request["payload"], {})
            send_frame(
                kernel_write,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": read_request["request_id"],
                    "ok": True,
                    "result": {
                        "present": True,
                        "data_base64": base64.b64encode(state).decode(),
                    },
                },
            )
            reader.join(timeout=3)
            self.assertFalse(reader.is_alive())
            self.assertEqual(results, [state])

            writer = threading.Thread(target=lambda: state_replace(state))
            writer.start()
            write_request = receive_frame(kernel_read, timeout_seconds=3)
            self.assertEqual(write_request["operation"], "state.replace")
            self.assertEqual(set(write_request["payload"]), {"data_base64"})
            self.assertEqual(
                base64.b64decode(write_request["payload"]["data_base64"]), state
            )
            send_frame(
                kernel_write,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": write_request["request_id"],
                    "ok": True,
                    "result": {"written_bytes": len(state)},
                },
            )
            writer.join(timeout=3)
            self.assertFalse(writer.is_alive())

            output_value = {"operation": "recall", "value": "Project K"}
            output_bytes = b'{"operation":"recall","value":"Project K"}'
            emitter = threading.Thread(target=lambda: plugin_output(output_value))
            emitter.start()
            output_request = receive_frame(kernel_read, timeout_seconds=3)
            self.assertEqual(output_request["operation"], "plugin.output")
            self.assertEqual(set(output_request["payload"]), {"data_base64"})
            self.assertEqual(
                base64.b64decode(output_request["payload"]["data_base64"]),
                output_bytes,
            )
            send_frame(
                kernel_write,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": output_request["request_id"],
                    "ok": True,
                    "result": {},
                },
            )
            emitter.join(timeout=3)
            self.assertFalse(emitter.is_alive())

    def test_plugin_state_and_output_reject_oversized_values_before_ipc(self) -> None:
        from khaos.ipc import (
            MAX_PLUGIN_OUTPUT_BYTES,
            MAX_PLUGIN_STATE_BYTES,
        )

        with _duplex_pipes() as (kernel_read, _):
            for operation in (
                lambda: state_replace(b"x" * (MAX_PLUGIN_STATE_BYTES + 1)),
                lambda: plugin_output({"value": "x" * MAX_PLUGIN_OUTPUT_BYTES}),
            ):
                with self.subTest(operation=operation):
                    with self.assertRaisesRegex(ValueError, "exceeds"):
                        operation()
            import select

            self.assertEqual(select.select([kernel_read], [], [], 0.02)[0], [])

    def test_late_cancel_rejection_can_follow_process_result(self) -> None:
        with _duplex_pipes() as (kernel_read, kernel_write):
            results: list[dict[str, object]] = []
            errors: list[BaseException] = []

            def request_execution() -> None:
                try:
                    results.append(
                        process_exec(
                            ["/usr/bin/true"],
                            cancel_requested=lambda: True,
                        )
                    )
                except BaseException as exc:
                    errors.append(exc)

            client = threading.Thread(target=request_execution)
            client.start()
            execution = receive_frame(kernel_read, timeout_seconds=3)
            self.assertEqual(execution["payload"], {"argv": ["/usr/bin/true"]})
            cancellation = receive_frame(kernel_read, timeout_seconds=3)
            send_frame(
                kernel_write,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": execution["request_id"],
                    "ok": True,
                    "result": {"returncode": 0, "stdout": "", "stderr": ""},
                },
            )
            send_frame(
                kernel_write,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": cancellation["request_id"],
                    "ok": False,
                    "error": {"code": "process_not_active"},
                },
            )
            client.join(timeout=3)

            self.assertFalse(client.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(
                results,
                [{"returncode": 0, "stdout": "", "stderr": ""}],
            )
            self.assertEqual(
                cancellation["payload"],
                {"process_request_id": execution["request_id"]},
            )


@contextmanager
def _duplex_pipes() -> Iterator[tuple[int, int]]:
    runner_read, kernel_write = os.pipe()
    kernel_read, runner_write = os.pipe()
    saved_stdin = os.dup(0)
    saved_stdout = os.dup(1)
    try:
        os.dup2(runner_read, 0)
        os.dup2(runner_write, 1)
        yield kernel_read, kernel_write
    finally:
        os.dup2(saved_stdin, 0)
        os.dup2(saved_stdout, 1)
        for descriptor in (
            saved_stdin,
            saved_stdout,
            runner_read,
            runner_write,
            kernel_read,
            kernel_write,
        ):
            os.close(descriptor)


if __name__ == "__main__":
    unittest.main()
