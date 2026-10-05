from __future__ import annotations

import base64
import errno
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from khaos.ipc import (
    IPCProtocolError,
    MAX_WORKSPACE_FILESYSTEM_OPERATIONS,
    PROTOCOL_VERSION,
    ping_peer,
    receive_frame,
    send_frame,
)
from khaos.kernel.broker import (
    serve_runner_execution,
    serve_workspace_commit as _serve_workspace_commit,
)
from khaos.kernel import broker as broker_module
from khaos.kernel.macos_disk_image import mounted_apfs_volume
from khaos.kernel.macos_seatbelt import (
    SANDBOX_EXECUTABLE,
    _python_runtime_paths,
    _snapshot_profile,
    apply_workspace_commit_sandbox,
)
from khaos.kernel.peer_identity import accept_local_peer_pid, local_peer_pid_listener
from khaos.kernel.workspace_changes import (
    WorkspaceCommitError,
    WorkspaceCommitOutcomeUncertain,
)
from khaos.kernel import workspace_changes as workspace_changes_module
from khaos.kernel.workspace_snapshot import (
    WorkspaceReadScope,
    WorkspaceSnapshot,
    WorkspaceSnapshotError,
    list_snapshot_directory,
    read_snapshot_file,
    workspace_snapshot,
)
from workspace_test_support import fixture_workspace_write_scope


def _serve_fixture_commit(
    request_read_fd: int,
    response_write_fd: int,
    snapshot: WorkspaceSnapshot,
    **kwargs,
):
    """Authorize fixture entries so Broker tests focus on their stated case."""
    if "workspace_write_scope" not in kwargs:
        kwargs["workspace_write_scope"] = fixture_workspace_write_scope(snapshot)
    return _serve_workspace_commit(
        request_read_fd,
        response_write_fd,
        snapshot,
        **kwargs,
    )


_CANCEL_RUNNER_SCRIPT = r'''import sys
import json
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from khaos.ipc import IPCProtocolError, answer_ping
from khaos.runner_sdk import process_exec

answer_ping()
started = Path(sys.argv[2]) / "child-started.txt"
try:
    process_exec(json.loads(sys.argv[3]), cancel_requested=started.exists)
except IPCProtocolError as exc:
    if "process_cancelled" not in str(exc):
        raise
else:
    raise SystemExit(14)
'''

_FILESYSTEM_RUNNER_SCRIPT = r'''import sys
import json
import os
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from khaos.ipc import IPCProtocolError, answer_ping
from khaos.kernel.peer_identity import verify_local_parent_pid
from khaos.runner_sdk import fs_list, fs_read, process_exec, workspace_commit

verify_local_parent_pid(Path(sys.argv[2]), os.getppid())
answer_ping()
if fs_read("src/main.py") != b"print('hello')":
    raise SystemExit(20)
unicode_name, *unicode_aliases, command_json = sys.argv[3:]
if fs_read(unicode_name) != b"private":
    raise SystemExit(29)
entries = {entry["name"]: entry for entry in fs_list()}
if entries["src"]["kind"] != "directory":
    raise SystemExit(21)
if unicode_name not in entries:
    raise SystemExit(26)
if entries["escape"]["kind"] != "symlink" or entries["escape"]["size"] is not None:
    raise SystemExit(22)
if entries["secret-link"]["kind"] != "symlink":
    raise SystemExit(23)
for operation in (
    lambda: fs_read("../outside/secret.txt"),
    lambda: fs_read("escape/secret.txt"),
    lambda: fs_read("secret-link"),
    lambda: fs_list("escape"),
):
    try:
        operation()
    except IPCProtocolError:
        pass
    else:
        raise SystemExit(24)
for alias in unicode_aliases:
    try:
        fs_read(alias)
    except IPCProtocolError as exc:
        if "path_not_readable" not in str(exc):
            raise
    else:
        raise SystemExit(27)
    try:
        fs_list(alias)
    except IPCProtocolError as exc:
        if "path_not_listable" not in str(exc):
            raise
    else:
        raise SystemExit(28)

result = process_exec(json.loads(command_json))
if result["returncode"] != 0:
    raise SystemExit(25)
workspace_commit()
'''

_CRASHING_RUNNER_SCRIPT = r'''import os
import sys
import json
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from khaos.ipc import answer_ping
from khaos.kernel.peer_identity import verify_local_parent_pid
from khaos.runner_sdk import process_exec

verify_local_parent_pid(Path(sys.argv[2]), os.getppid())
answer_ping()
process_exec(json.loads(sys.argv[3]))
os._exit(73)
'''


class BrokerTests(unittest.TestCase):
    def test_rejects_nonstring_operation_as_invalid_request(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            with workspace_snapshot(source) as snapshot, _pipe_pair() as (
                request_read,
                request_write,
                response_read,
                response_write,
            ):
                send_frame(
                    request_write,
                    {
                        "version": PROTOCOL_VERSION,
                        "request_id": "a" * 32,
                        "operation": [],
                        "payload": {},
                    },
                )
                with self.assertRaisesRegex(IPCProtocolError, "schema is invalid"):
                    serve_runner_execution(
                        request_read,
                        response_write,
                        snapshot,
                        authorized_timeout_seconds=1,
                    )
                response = receive_frame(response_read)

        self.assertEqual(response["error"], {"code": "invalid_request"})

    def test_workspace_read_scope_denies_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            (source / "secret.txt").write_text("private", encoding="utf-8")
            server_errors: list[BaseException] = []
            with workspace_snapshot(source) as snapshot, _pipe_pair() as (
                request_read,
                request_write,
                response_read,
                response_write,
            ):
                def serve() -> None:
                    try:
                        serve_runner_execution(
                            request_read,
                            response_write,
                            snapshot,
                            authorized_timeout_seconds=1,
                            timeout_seconds=3,
                        )
                    except IPCProtocolError as exc:
                        server_errors.append(exc)

                server = threading.Thread(target=serve)
                server.start()
                for index, (operation, payload, denied_code) in enumerate(
                    (
                        ("fs.read", {"path": "secret.txt"}, "path_not_readable"),
                        ("fs.list", {"path": ""}, "path_not_listable"),
                    ),
                    start=1,
                ):
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": f"{index:032x}",
                            "operation": operation,
                            "payload": payload,
                        },
                    )
                    response = receive_frame(response_read, timeout_seconds=3)
                    self.assertEqual(response["error"], {"code": denied_code})

                send_frame(
                    request_write,
                    {
                        "version": PROTOCOL_VERSION,
                        "request_id": f"{3:032x}",
                        "operation": "unsupported",
                        "payload": {},
                    },
                )
                self.assertEqual(
                    receive_frame(response_read, timeout_seconds=3)["error"],
                    {"code": "operation_not_supported"},
                )
                server.join(timeout=3)

        self.assertFalse(server.is_alive())
        self.assertEqual(len(server_errors), 1)

    def test_runner_cannot_supply_filesystem_scopes_over_wire(self) -> None:
        attacks = (
            (
                "fs.read",
                {"path": "secret.txt", "workspace_read_scope": ["secret.txt"]},
            ),
            (
                "fs.list",
                {"path": "", "workspace_read_scope": ["secret.txt"]},
            ),
            (
                "fs.write",
                {
                    "path": "secret.txt",
                    "data_base64": "Zm9yZ2Vk",
                    "workspace_write_scope": ["secret.txt"],
                },
            ),
        )
        for index, (operation, payload) in enumerate(attacks, start=1):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as value:
                source = Path(value) / "workspace"
                source.mkdir()
                secret = source / "secret.txt"
                secret.write_text("private", encoding="utf-8")
                with workspace_snapshot(source) as snapshot, _pipe_pair() as (
                    request_read,
                    request_write,
                    response_read,
                    response_write,
                ):
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": f"{index:032x}",
                            "operation": operation,
                            "payload": payload,
                        },
                    )
                    with self.assertRaisesRegex(
                        IPCProtocolError, "request payload is invalid"
                    ):
                        serve_runner_execution(
                            request_read,
                            response_write,
                            snapshot,
                            authorized_timeout_seconds=1,
                            timeout_seconds=3,
                            workspace_read_scope=(),
                            workspace_write_scope=(),
                        )
                    self.assertEqual(
                        receive_frame(response_read, timeout_seconds=3)["error"],
                        {"code": "invalid_request"},
                    )
                self.assertEqual(secret.read_text(encoding="utf-8"), "private")

    def test_workspace_read_scope_limits_reads_and_filters_ancestor_lists(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            (source / "src").mkdir(parents=True)
            (source / "docs").mkdir()
            (source / "src" / "main.py").write_text("allowed", encoding="utf-8")
            (source / "src" / "private.py").write_text("hidden", encoding="utf-8")
            (source / "docs" / "secret.md").write_text("hidden", encoding="utf-8")
            server_errors: list[BaseException] = []
            with workspace_snapshot(source) as snapshot, _pipe_pair() as (
                request_read,
                request_write,
                response_read,
                response_write,
            ):
                def serve() -> None:
                    try:
                        serve_runner_execution(
                            request_read,
                            response_write,
                            snapshot,
                            authorized_timeout_seconds=1,
                            timeout_seconds=3,
                            workspace_read_scope=("src/main.py",),
                        )
                    except IPCProtocolError as exc:
                        server_errors.append(exc)

                server = threading.Thread(target=serve)
                server.start()

                def request(
                    request_id: int,
                    operation: str,
                    path: str,
                ) -> dict[str, object]:
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": f"{request_id:032x}",
                            "operation": operation,
                            "payload": {"path": path},
                        },
                    )
                    return receive_frame(response_read, timeout_seconds=3)

                allowed_read = request(1, "fs.read", "src/main.py")
                self.assertTrue(allowed_read["ok"])
                self.assertEqual(
                    base64.b64decode(allowed_read["result"]["data_base64"]),
                    b"allowed",
                )
                self.assertEqual(
                    request(2, "fs.read", "src/private.py")["error"],
                    {"code": "path_not_readable"},
                )

                root_listing = request(3, "fs.list", "")
                self.assertEqual(
                    [entry["name"] for entry in root_listing["result"]["entries"]],
                    ["src"],
                )
                source_listing = request(4, "fs.list", "src")
                self.assertEqual(
                    [entry["name"] for entry in source_listing["result"]["entries"]],
                    ["main.py"],
                )
                self.assertEqual(
                    request(5, "fs.list", "docs")["error"],
                    {"code": "path_not_listable"},
                )

                send_frame(
                    request_write,
                    {
                        "version": PROTOCOL_VERSION,
                        "request_id": f"{6:032x}",
                        "operation": "unsupported",
                        "payload": {},
                    },
                )
                self.assertEqual(
                    receive_frame(response_read, timeout_seconds=3)["error"],
                    {"code": "operation_not_supported"},
                )
                server.join(timeout=3)

        self.assertFalse(server.is_alive())
        self.assertEqual(len(server_errors), 1)

    def test_workspace_write_scope_allows_only_exact_kernel_writes(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            (source / "src").mkdir(parents=True)
            (source / "src" / "main.py").write_bytes(b"old")
            (source / "src" / "private.py").write_bytes(b"private")
            server_errors: list[BaseException] = []
            with workspace_snapshot(source) as snapshot, _pipe_pair() as (
                request_read,
                request_write,
                response_read,
                response_write,
            ):
                def serve() -> None:
                    try:
                        serve_runner_execution(
                            request_read,
                            response_write,
                            snapshot,
                            authorized_timeout_seconds=1,
                            timeout_seconds=3,
                            workspace_write_scope=("src/main.py", "new.txt"),
                        )
                    except IPCProtocolError as exc:
                        server_errors.append(exc)

                server = threading.Thread(target=serve)
                server.start()

                def write(
                    request_id: int, path: str, content: bytes
                ) -> dict[str, object]:
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": f"{request_id:032x}",
                            "operation": "fs.write",
                            "payload": {
                                "path": path,
                                "data_base64": base64.b64encode(content).decode("ascii"),
                            },
                        },
                    )
                    return receive_frame(response_read, timeout_seconds=3)

                self.assertEqual(
                    write(1, "src/private.py", b"denied")["error"],
                    {"code": "path_not_writable"},
                )
                allowed = write(2, "src/main.py", b"approved")
                self.assertTrue(allowed["ok"])
                self.assertEqual(allowed["result"]["written_bytes"], 8)
                new_file = write(3, "new.txt", b"new")
                self.assertEqual(new_file["result"]["written_bytes"], 3)

                send_frame(
                    request_write,
                    {
                        "version": PROTOCOL_VERSION,
                        "request_id": f"{4:032x}",
                        "operation": "unsupported",
                        "payload": {},
                    },
                )
                self.assertEqual(
                    receive_frame(response_read, timeout_seconds=3)["error"],
                    {"code": "operation_not_supported"},
                )
                server.join(timeout=3)
                self.assertFalse(server.is_alive())
                self.assertEqual(len(server_errors), 1)
                self.assertEqual(
                    (snapshot.path / "src" / "main.py").read_bytes(), b"approved"
                )
                self.assertEqual(
                    (snapshot.path / "src" / "private.py").read_bytes(), b"private"
                )
                self.assertEqual((snapshot.path / "new.txt").read_bytes(), b"new")

            self.assertEqual((source / "src" / "main.py").read_bytes(), b"old")

    @unittest.skipUnless(sys.platform == "darwin", "requires APFS name normalization")
    def test_workspace_read_scope_rejects_unicode_normalization_alias(self) -> None:
        with tempfile.TemporaryDirectory(prefix="khaos-read-alias-") as value:
            with mounted_apfs_volume(
                Path(value), size_bytes=256_000_000, case_sensitive=False
            ) as source_volume:
                source = source_volume / "workspace"
                source.mkdir()
                created_name = unicodedata.normalize("NFC", "é.txt")
                allowed_file = source / created_name
                allowed_file.write_text("private", encoding="utf-8")
                allowed_directory = source / "PrivateDir"
                allowed_directory.mkdir()
                (allowed_directory / "secret.txt").write_text(
                    "directory-private", encoding="utf-8"
                )
                with os.scandir(source) as entries:
                    filesystem_names = {entry.name for entry in entries}
                filesystem_name = next(
                    name for name in filesystem_names if name.endswith(".txt")
                )
                filesystem_directory_name = next(
                    name for name in filesystem_names if name != filesystem_name
                )
                alternate_name = unicodedata.normalize("NFD", filesystem_name)
                if alternate_name == filesystem_name:
                    alternate_name = unicodedata.normalize("NFC", filesystem_name)
                self.assertNotEqual(alternate_name, filesystem_name)
                self.assertTrue((source / alternate_name).samefile(allowed_file))
                alternate_directory_name = filesystem_directory_name.swapcase()
                self.assertNotEqual(alternate_directory_name, filesystem_directory_name)
                self.assertTrue(
                    (source / alternate_directory_name).samefile(allowed_directory)
                )

                server_errors: list[BaseException] = []
                with workspace_snapshot(source) as snapshot, _pipe_pair() as (
                    request_read,
                    request_write,
                    response_read,
                    response_write,
                ):
                    def serve() -> None:
                        try:
                            serve_runner_execution(
                                request_read,
                                response_write,
                                snapshot,
                                authorized_timeout_seconds=1,
                                timeout_seconds=3,
                                workspace_read_scope=(filesystem_name,),
                            )
                        except IPCProtocolError as exc:
                            server_errors.append(exc)

                    server = threading.Thread(target=serve)
                    server.start()

                    def request(
                        request_id: int, operation: str, path: str
                    ) -> dict[str, object]:
                        send_frame(
                            request_write,
                            {
                                "version": PROTOCOL_VERSION,
                                "request_id": f"{request_id:032x}",
                                "operation": operation,
                                "payload": {"path": path},
                            },
                        )
                        return receive_frame(response_read, timeout_seconds=3)

                    allowed = request(1, "fs.read", filesystem_name)
                    self.assertTrue(allowed["ok"])
                    self.assertEqual(
                        base64.b64decode(allowed["result"]["data_base64"]),
                        b"private",
                    )
                    self.assertEqual(
                        request(2, "fs.read", alternate_name)["error"],
                        {"code": "path_not_readable"},
                    )
                    alias_scope = WorkspaceReadScope.from_paths(
                        (alternate_name, alternate_directory_name)
                    )
                    self.assertTrue(
                        alias_scope.permits_read(
                            alternate_name, max_depth=snapshot.max_depth
                        )
                    )
                    self.assertTrue(
                        alias_scope.permits_list(
                            alternate_directory_name,
                            max_depth=snapshot.max_depth,
                        )
                    )
                    with self.assertRaisesRegex(
                        WorkspaceSnapshotError, "path spelling is not exact"
                    ):
                        read_snapshot_file(snapshot, alternate_name)
                    with self.assertRaisesRegex(
                        WorkspaceSnapshotError, "path spelling is not exact"
                    ):
                        list_snapshot_directory(snapshot, alternate_directory_name)
                    self.assertEqual(
                        [
                            entry["name"]
                            for entry in request(3, "fs.list", "")["result"][
                                "entries"
                            ]
                        ],
                        [filesystem_name],
                    )
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": f"{4:032x}",
                            "operation": "unsupported",
                            "payload": {},
                        },
                    )
                    self.assertEqual(
                        receive_frame(response_read, timeout_seconds=3)["error"],
                        {"code": "operation_not_supported"},
                    )
                    server.join(timeout=3)

                self.assertFalse(server.is_alive())
                self.assertEqual(len(server_errors), 1)

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires case-insensitive APFS and the real macOS Seatbelt backend",
    )
    def test_runner_reads_bounded_workspace_data_only_through_kernel(self) -> None:
        with tempfile.TemporaryDirectory() as value, mounted_apfs_volume(
            Path(value), size_bytes=256_000_000, case_sensitive=False
        ) as source_volume:
            root = Path(value)
            source = source_volume / "workspace"
            source.mkdir()
            unicode_file = source / unicodedata.normalize("NFC", "é.txt")
            unicode_file.write_bytes(b"private")
            with os.scandir(source) as entries:
                unicode_name = next(
                    entry.name for entry in entries if entry.name.endswith(".txt")
                )
            unicode_alias = unicodedata.normalize("NFD", unicode_name)
            if unicode_alias == unicode_name:
                unicode_alias = unicodedata.normalize("NFC", unicode_name)
            self.assertNotEqual(unicode_alias, unicode_name)
            case_alias = unicode_name.swapcase()
            self.assertNotEqual(case_alias, unicode_name)
            for alias in (unicode_alias, case_alias):
                self.assertTrue((source / alias).samefile(unicode_file))
            (source / "src").mkdir()
            (source / "src" / "main.py").write_text(
                "print('hello')", encoding="utf-8"
            )
            outside = root / "outside"
            outside.mkdir()
            (outside / "secret.txt").write_text("outside secret", encoding="utf-8")
            (source / "escape").symlink_to(outside, target_is_directory=True)
            (source / "secret-link").symlink_to(outside / "secret.txt")

            package_root = Path(__file__).resolve().parents[1]
            runner_package = package_root / "khaos"
            executable = Path(sys.executable).resolve(strict=True)
            authorized_command = (
                str(executable),
                "-I",
                "-S",
                "-c",
                "from pathlib import Path; Path('created.txt').write_text('committed')",
            )
            with workspace_snapshot(source) as snapshot:
                with tempfile.TemporaryDirectory(
                    prefix="r-", dir=snapshot.path.parent
                ) as scratch_value:
                    scratch = Path(scratch_value).resolve(strict=True)
                    process: subprocess.Popen[bytes] | None = None
                    try:
                        with local_peer_pid_listener(scratch) as (
                            listener,
                            peer_socket_path,
                        ):
                            profile = _snapshot_profile(
                                scratch,
                                _python_runtime_paths(),
                                executable=executable,
                                allow_workspace_write=False,
                                additional_unix_socket_paths=(peer_socket_path,),
                                readable_paths=(
                                    package_root,
                                    runner_package,
                                    runner_package / "__init__.py",
                                    runner_package / "ipc.py",
                                    runner_package / "runner_sdk.py",
                                    runner_package / "kernel",
                                    runner_package / "kernel" / "__init__.py",
                                    runner_package / "kernel" / "peer_identity.py",
                                ),
                            )
                            process = subprocess.Popen(
                                (
                                    str(SANDBOX_EXECUTABLE),
                                    "-p",
                                    profile,
                                    str(executable),
                                    "-I",
                                    "-S",
                                    "-c",
                                    _FILESYSTEM_RUNNER_SCRIPT,
                                    str(package_root),
                                    str(peer_socket_path),
                                    unicode_name,
                                    unicode_alias,
                                    case_alias,
                                    json.dumps(authorized_command),
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
                                start_new_session=True,
                            )
                            accept_local_peer_pid(listener, process.pid)
                        if process.stdin is None or process.stdout is None:
                            self.fail("Runner IPC pipes are unavailable")
                        ping_peer(
                            process.stdout.fileno(),
                            process.stdin.fileno(),
                            timeout_seconds=3,
                        )
                        result = serve_runner_execution(
                            process.stdout.fileno(),
                            process.stdin.fileno(),
                            snapshot,
                            authorized_timeout_seconds=5,
                            timeout_seconds=5,
                            workspace_read_scope=(
                                "src",
                                "escape",
                                "secret-link",
                                unicode_name,
                            ),
                        )
                        changes = _serve_fixture_commit(
                            process.stdout.fileno(),
                            process.stdin.fileno(),
                            snapshot,
                            timeout_seconds=5,
                        )
                        returncode = process.wait(timeout=5)
                    finally:
                        if process is not None and process.poll() is None:
                            process.kill()
                            process.wait(timeout=5)
                        if process is not None:
                            for stream in (process.stdin, process.stdout):
                                if stream is not None and not stream.closed:
                                    stream.close()

            self.assertEqual(returncode, 0)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(changes.added, 1)
            self.assertEqual((source / "created.txt").read_text(), "committed")
            self.assertEqual((outside / "secret.txt").read_text(), "outside secret")

    def test_runner_filesystem_request_count_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            server_errors: list[BaseException] = []
            with workspace_snapshot(source) as snapshot, _pipe_pair() as (
                request_read,
                request_write,
                response_read,
                response_write,
            ):
                def serve() -> None:
                    try:
                        serve_runner_execution(
                            request_read,
                            response_write,
                            snapshot,
                            authorized_timeout_seconds=1,
                            timeout_seconds=3,
                            workspace_write_scope=("allowed.txt",),
                        )
                    except IPCProtocolError as exc:
                        server_errors.append(exc)

                server = threading.Thread(target=serve)
                server.start()
                for index in range(MAX_WORKSPACE_FILESYSTEM_OPERATIONS - 1):
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": f"{index + 1:032x}",
                            "operation": "fs.read",
                            "payload": {"path": ".."},
                        },
                    )
                write_id = MAX_WORKSPACE_FILESYSTEM_OPERATIONS
                send_frame(
                    request_write,
                    {
                        "version": PROTOCOL_VERSION,
                        "request_id": f"{write_id:032x}",
                        "operation": "fs.write",
                        "payload": {
                            "path": "allowed.txt",
                            "data_base64": base64.b64encode(b"approved").decode(
                                "ascii"
                            ),
                        },
                    },
                )
                overflow_id = MAX_WORKSPACE_FILESYSTEM_OPERATIONS + 1
                send_frame(
                    request_write,
                    {
                        "version": PROTOCOL_VERSION,
                        "request_id": f"{overflow_id:032x}",
                        "operation": "fs.read",
                        "payload": {"path": ".."},
                    },
                )
                responses = [
                    receive_frame(response_read, timeout_seconds=3)
                    for _ in range(MAX_WORKSPACE_FILESYSTEM_OPERATIONS + 1)
                ]
                server.join(timeout=3)
                self.assertTrue(responses[-2]["ok"])
                self.assertEqual(
                    (snapshot.path / "allowed.txt").read_bytes(), b"approved"
                )

            self.assertFalse(server.is_alive())
            self.assertEqual(len(server_errors), 1)
            self.assertIn("request limit exceeded", str(server_errors[0]))
            self.assertTrue(
                all(
                    response.get("error", {}).get("code") == "path_not_readable"
                    for response in responses[:-2]
                )
            )
            self.assertEqual(
                responses[-1].get("error", {}).get("code"),
                "operation_limit_exceeded",
            )

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_runner_exit_after_exec_discards_uncommitted_snapshot_output(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            original = source / "existing.txt"
            original.write_text("live", encoding="utf-8")
            package_root = Path(__file__).resolve().parents[1]
            runner_package = package_root / "khaos"
            executable = Path(sys.executable).resolve(strict=True)
            authorized_command = (
                str(executable),
                "-I",
                "-S",
                "-c",
                "from pathlib import Path; "
                "Path('existing.txt').write_text('snapshot'); "
                "Path('uncommitted.txt').write_text('snapshot-only')",
            )
            with workspace_snapshot(source) as snapshot:
                with tempfile.TemporaryDirectory(
                    prefix="r-", dir=snapshot.path.parent
                ) as scratch_value:
                    scratch = Path(scratch_value).resolve(strict=True)
                    process: subprocess.Popen[bytes] | None = None
                    try:
                        with local_peer_pid_listener(scratch) as (
                            listener,
                            peer_socket_path,
                        ):
                            profile = _snapshot_profile(
                                scratch,
                                _python_runtime_paths(),
                                executable=executable,
                                allow_workspace_write=False,
                                additional_unix_socket_paths=(peer_socket_path,),
                                readable_paths=(
                                    package_root,
                                    runner_package,
                                    runner_package / "__init__.py",
                                    runner_package / "ipc.py",
                                    runner_package / "runner_sdk.py",
                                    runner_package / "kernel",
                                    runner_package / "kernel" / "__init__.py",
                                    runner_package / "kernel" / "peer_identity.py",
                                ),
                            )
                            process = subprocess.Popen(
                                (
                                    str(SANDBOX_EXECUTABLE),
                                    "-p",
                                    profile,
                                    str(executable),
                                    "-I",
                                    "-S",
                                    "-c",
                                    _CRASHING_RUNNER_SCRIPT,
                                    str(package_root),
                                    str(peer_socket_path),
                                    json.dumps(authorized_command),
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
                                start_new_session=True,
                            )
                            accept_local_peer_pid(listener, process.pid)
                        if process.stdin is None or process.stdout is None:
                            self.fail("Runner IPC pipes are unavailable")
                        ping_peer(
                            process.stdout.fileno(),
                            process.stdin.fileno(),
                            timeout_seconds=3,
                        )
                        result = serve_runner_execution(
                            process.stdout.fileno(),
                            process.stdin.fileno(),
                            snapshot,
                            authorized_timeout_seconds=5,
                            timeout_seconds=5,
                        )
                        self.assertEqual(result.returncode, 0)
                        self.assertEqual(
                            (snapshot.path / "existing.txt").read_text(), "snapshot"
                        )
                        self.assertTrue((snapshot.path / "uncommitted.txt").exists())
                        with self.assertRaises(IPCProtocolError):
                            _serve_fixture_commit(
                                process.stdout.fileno(),
                                process.stdin.fileno(),
                                snapshot,
                                timeout_seconds=3,
                            )
                        self.assertEqual(process.wait(timeout=5), 73)
                    finally:
                        if process is not None and process.poll() is None:
                            process.kill()
                            process.wait(timeout=5)
                        if process is not None:
                            for stream in (process.stdin, process.stdout):
                                if stream is not None and not stream.closed:
                                    stream.close()

            self.assertEqual(original.read_text(encoding="utf-8"), "live")
            self.assertFalse((source / "uncommitted.txt").exists())

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_process_cancel_kills_the_active_command_tree(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            executable = Path(sys.executable).resolve(strict=True)
            command = """\
import os
import time
from pathlib import Path

pid = os.fork()
if pid == 0:
    time.sleep(0.8)
    Path("survived.txt").write_text("bad")
    os._exit(0)
Path("child-started.txt").write_text(str(pid))
while True:
    time.sleep(1)
"""
            authorized_command = (str(executable), "-I", "-S", "-c", command)
            with workspace_snapshot(source) as snapshot:
                package_root = Path(__file__).resolve().parents[1]
                runner_package = package_root / "khaos"
                profile = _snapshot_profile(
                    snapshot.path,
                    _python_runtime_paths(),
                    executable=executable,
                    readable_paths=(
                        package_root,
                        runner_package,
                        runner_package / "__init__.py",
                        runner_package / "ipc.py",
                        runner_package / "runner_sdk.py",
                    ),
                )
                process = subprocess.Popen(
                    (
                        str(SANDBOX_EXECUTABLE),
                        "-p",
                        profile,
                        str(executable),
                        "-I",
                        "-S",
                        "-c",
                        _CANCEL_RUNNER_SCRIPT,
                        str(package_root),
                        str(snapshot.path),
                        json.dumps(authorized_command),
                    ),
                    cwd=snapshot.path,
                    env={
                        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                        "PYTHONDONTWRITEBYTECODE": "1",
                    },
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    start_new_session=True,
                )
                try:
                    self.assertIsNotNone(process.stdin)
                    self.assertIsNotNone(process.stdout)
                    ping_peer(
                        process.stdout.fileno(),
                        process.stdin.fileno(),
                        timeout_seconds=3,
                    )
                    with self.assertRaisesRegex(
                        IPCProtocolError, "sandboxed process execution failed"
                    ):
                        serve_runner_execution(
                            process.stdout.fileno(),
                            process.stdin.fileno(),
                            snapshot,
                            authorized_timeout_seconds=4,
                            timeout_seconds=5,
                        )
                    returncode = process.wait(timeout=5)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
                    for stream in (process.stdin, process.stdout):
                        if stream is not None:
                            stream.close()
                time.sleep(0.9)
                self.assertFalse((snapshot.path / "survived.txt").exists())

            self.assertEqual(returncode, 0)

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_process_cancel_rejects_a_different_exec_request_id(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            script = """\
import time
from pathlib import Path

Path("started.txt").write_text("started")
time.sleep(1)
Path("finished.txt").write_text("finished")
"""
            authorized_command = (
                str(Path(sys.executable).resolve(strict=True)),
                "-I",
                "-S",
                "-c",
                script,
            )
            server_errors: list[BaseException] = []
            with workspace_snapshot(source) as snapshot, _pipe_pair() as (
                request_read,
                request_write,
                response_read,
                response_write,
            ):
                def serve() -> None:
                    try:
                        serve_runner_execution(
                            request_read,
                            response_write,
                            snapshot,
                            authorized_timeout_seconds=4,
                        )
                    except IPCProtocolError as exc:
                        server_errors.append(exc)

                server = threading.Thread(target=serve)
                server.start()
                send_frame(
                    request_write,
                    {
                        "version": PROTOCOL_VERSION,
                        "request_id": "d" * 32,
                        "operation": "process.exec",
                        "payload": {"argv": list(authorized_command)},
                    },
                )

                started_marker = snapshot.path / "started.txt"
                deadline = time.monotonic() + 3
                while not started_marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(started_marker.exists(), "command did not start")
                send_frame(
                    request_write,
                    {
                        "version": PROTOCOL_VERSION,
                        "request_id": "f" * 32,
                        "operation": "process.cancel",
                        "payload": {"process_request_id": "a" * 32},
                    },
                )
                cancel_response = receive_frame(response_read, timeout_seconds=3)
                exec_response = receive_frame(response_read, timeout_seconds=3)
                server.join(timeout=3)
                self.assertFalse(server.is_alive())
                self.assertTrue((snapshot.path / "finished.txt").exists())

            self.assertEqual(
                cancel_response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "f" * 32,
                    "ok": False,
                    "error": {"code": "process_not_active"},
                },
            )
            self.assertEqual(
                exec_response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "d" * 32,
                    "ok": True,
                    "result": {"returncode": 0, "stdout": "", "stderr": ""},
                },
            )
            self.assertEqual(server_errors, [])

    def test_process_exec_rejects_runner_supplied_scope_and_environment(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            outside = root / "outside.txt"
            outside.write_text("protected", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                with _pipe_pair() as (
                    request_read,
                    request_write,
                    response_read,
                    response_write,
                ):
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": "e" * 32,
                            "operation": "process.exec",
                            "payload": {
                                "argv": [
                                    str(Path(sys.executable).resolve(strict=True)),
                                    "-I",
                                    "-S",
                                    "-c",
                                    "from pathlib import Path; "
                                    "Path('injected.txt').write_text('bad')",
                                ],
                                "timeout_seconds": 1,
                                "workspace": str(outside.parent),
                                "cwd": str(outside.parent),
                                "env": {"SECRET": "must-not-be-forwarded"},
                            },
                        },
                    )
                    with self.assertRaisesRegex(
                        IPCProtocolError, "only argv"
                    ):
                        serve_runner_execution(
                            request_read,
                            response_write,
                            snapshot,
                            authorized_timeout_seconds=1,
                        )
                    response = receive_frame(response_read)
                self.assertFalse((snapshot.path / "injected.txt").exists())

            self.assertEqual(response["ok"], False)
            self.assertEqual(response["error"], {"code": "invalid_request"})
            self.assertEqual(outside.read_text(encoding="utf-8"), "protected")

    def test_commit_scope_comes_from_the_trusted_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            target = source / "file.txt"
            target.write_text("before", encoding="utf-8")
            outside = root / "outside.txt"
            outside.write_text("protected", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "file.txt").write_text("runner", encoding="utf-8")
                with _pipe_pair() as (request_read, request_write, response_read, response_write):
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": "a" * 32,
                            "operation": "workspace.commit",
                            "payload": {"workspace": str(outside)},
                        },
                    )
                    with self.assertRaisesRegex(
                        IPCProtocolError, "payload must be empty"
                    ):
                        _serve_fixture_commit(request_read, response_write, snapshot)
                    response = receive_frame(response_read)

            self.assertEqual(response["ok"], False)
            self.assertEqual(response["error"], {"code": "invalid_request"})
            self.assertEqual(target.read_text(encoding="utf-8"), "before")
            self.assertEqual(outside.read_text(encoding="utf-8"), "protected")

    def test_invalid_trusted_write_scope_returns_protocol_error(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            target = source / "file.txt"
            target.write_text("unchanged", encoding="utf-8")

            with workspace_snapshot(source) as snapshot, _pipe_pair() as (
                request_read,
                request_write,
                response_read,
                response_write,
            ):
                send_frame(
                    request_write,
                    {
                        "version": PROTOCOL_VERSION,
                        "request_id": "c" * 32,
                        "operation": "workspace.commit",
                        "payload": {},
                    },
                )
                with self.assertRaisesRegex(WorkspaceCommitError, "invalid"):
                    _serve_workspace_commit(
                        request_read,
                        response_write,
                        snapshot,
                        workspace_write_scope=("../outside.txt",),
                    )
                response = receive_frame(response_read)

            self.assertEqual(response["error"], {"code": "commit_rejected"})
            self.assertEqual(target.read_text(encoding="utf-8"), "unchanged")

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS APFS snapshots")
    def test_broker_rejects_candidates_over_snapshot_limits_before_writeback(self) -> None:
        for case, limits, candidate in (
            ("entries", {"max_entries": 1}, "untrusted"),
            ("bytes", {"max_bytes": 10}, "four"),
        ):
            with self.subTest(limit=case), tempfile.TemporaryDirectory() as value:
                source = Path(value) / "workspace"
                source.mkdir()
                baseline = source / "baseline.txt"
                baseline.write_text("trusted", encoding="utf-8")

                with workspace_snapshot(source, **limits) as snapshot:
                    (snapshot.path / "candidate.txt").write_text(
                        candidate, encoding="utf-8"
                    )
                    with _pipe_pair() as (
                        request_read,
                        request_write,
                        response_read,
                        response_write,
                    ):
                        send_frame(
                            request_write,
                            {
                                "version": PROTOCOL_VERSION,
                                "request_id": "b" * 32,
                                "operation": "workspace.commit",
                                "payload": {},
                            },
                        )
                        with self.assertRaises(WorkspaceCommitError):
                            _serve_fixture_commit(
                                request_read, response_write, snapshot
                            )
                        response = receive_frame(response_read)

                self.assertEqual(response["error"], {"code": "commit_rejected"})
                self.assertEqual(baseline.read_text(encoding="utf-8"), "trusted")
                self.assertFalse((source / "candidate.txt").exists())

    def test_commit_operation_applies_only_the_bound_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            target = source / "file.txt"
            target.write_text("before", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "file.txt").write_text("runner", encoding="utf-8")
                with _pipe_pair() as (
                    request_read,
                    request_write,
                    response_read,
                    response_write,
                ):
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": "b" * 32,
                            "operation": "workspace.commit",
                            "payload": {},
                        },
                    )
                    changes = _serve_fixture_commit(
                        request_read, response_write, snapshot
                    )
                    response = receive_frame(response_read)

            self.assertEqual(target.read_text(encoding="utf-8"), "runner")
            self.assertEqual(changes.modified, 1)
            self.assertEqual(
                response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "b" * 32,
                    "ok": True,
                    "result": {"added": 0, "modified": 1, "deleted": 0},
                },
            )

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_commit_reports_uncertain_after_a_partial_live_write(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            first = source / "a.txt"
            second = source / "b.txt"
            first.write_text("before-a", encoding="utf-8")
            second.write_text("before-b", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "a.txt").write_text("after-a", encoding="utf-8")
                (snapshot.path / "b.txt").write_text("after-b", encoding="utf-8")
                original_rename_swap = workspace_changes_module._rename_swap
                swap_attempts = 0

                def fail_second_swap(
                    directory_fd: int, source_name: str, destination_name: str
                ) -> None:
                    nonlocal swap_attempts
                    swap_attempts += 1
                    if swap_attempts == 2:
                        raise OSError(errno.EIO, "injected second live swap failure")
                    original_rename_swap(directory_fd, source_name, destination_name)

                with _pipe_pair() as (
                    request_read,
                    request_write,
                    response_read,
                    response_write,
                ):
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": "c" * 32,
                            "operation": "workspace.commit",
                            "payload": {},
                        },
                    )
                    with patch.object(
                        workspace_changes_module, "_rename_swap", fail_second_swap
                    ):
                        with self.assertRaises(WorkspaceCommitOutcomeUncertain):
                            _serve_fixture_commit(
                                request_read, response_write, snapshot
                            )
                    response = receive_frame(response_read)

            self.assertEqual(first.read_text(encoding="utf-8"), "after-a")
            self.assertEqual(second.read_text(encoding="utf-8"), "before-b")
            self.assertEqual(
                response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "c" * 32,
                    "ok": False,
                    "error": {"code": "commit_outcome_uncertain"},
                },
            )

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_commit_cleanup_failure_during_preparation_reports_uncertain(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            target = source / "file.txt"
            target.write_text("before", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / target.name).write_text("after", encoding="utf-8")

                def fail_metadata_copy(source_fd: int, destination_fd: int) -> None:
                    raise OSError(errno.EIO, "injected metadata-copy failure")

                with _pipe_pair() as (
                    request_read,
                    request_write,
                    response_read,
                    response_write,
                ):
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": "f" * 32,
                            "operation": "workspace.commit",
                            "payload": {},
                        },
                    )
                    with (
                        patch.object(
                            workspace_changes_module,
                            "_copy_file_acl_and_xattrs",
                            fail_metadata_copy,
                        ),
                        _deny_khaos_temp_unlink(fail_once=True),
                    ):
                        with self.assertRaises(WorkspaceCommitOutcomeUncertain):
                            _serve_fixture_commit(
                                request_read, response_write, snapshot
                            )
                    response = receive_frame(response_read)

            self.assertEqual(target.read_text(encoding="utf-8"), "before")
            temporary_entries = list(source.glob(".khaos-*.tmp"))
            self.assertEqual(len(temporary_entries), 1)
            self.assertEqual(
                response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "f" * 32,
                    "ok": False,
                    "error": {"code": "commit_outcome_uncertain"},
                },
            )

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_delete_sentinel_cleanup_failure_reports_uncertain(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            target = source / "file.txt"
            target.write_text("before", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / target.name).unlink()

                def fail_swap(
                    directory_fd: int, source_name: str, destination_name: str
                ) -> None:
                    raise OSError(errno.EIO, "injected entry-swap failure")

                with _pipe_pair() as (
                    request_read,
                    request_write,
                    response_read,
                    response_write,
                ):
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": "2" * 32,
                            "operation": "workspace.commit",
                            "payload": {},
                        },
                    )
                    with (
                        patch.object(
                            workspace_changes_module, "_rename_swap", fail_swap
                        ),
                        _deny_khaos_temp_unlink(),
                    ):
                        with self.assertRaises(WorkspaceCommitOutcomeUncertain):
                            _serve_fixture_commit(
                                request_read, response_write, snapshot
                            )
                    response = receive_frame(response_read)

            self.assertEqual(target.read_text(encoding="utf-8"), "before")
            temporary_entries = list(source.glob(".khaos-*.tmp"))
            self.assertEqual(len(temporary_entries), 1)
            self.assertEqual(temporary_entries[0].read_bytes(), b"")
            self.assertEqual(
                response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "2" * 32,
                    "ok": False,
                    "error": {"code": "commit_outcome_uncertain"},
                },
            )

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_added_file_temp_cleanup_failure_reports_uncertain(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            target = source / "added.txt"

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / target.name).write_text("candidate", encoding="utf-8")

                def fail_clone(
                    source_fd: int,
                    destination_directory_fd: int,
                    destination_name: str,
                ) -> None:
                    raise OSError(errno.EIO, "injected clone failure")

                with _pipe_pair() as (
                    request_read,
                    request_write,
                    response_read,
                    response_write,
                ):
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": "3" * 32,
                            "operation": "workspace.commit",
                            "payload": {},
                        },
                    )
                    with (
                        patch.object(
                            workspace_changes_module,
                            "_clone_file_from_descriptor",
                            fail_clone,
                        ),
                        _deny_khaos_temp_unlink(fail_once=True),
                    ):
                        with self.assertRaises(WorkspaceCommitOutcomeUncertain):
                            _serve_fixture_commit(
                                request_read, response_write, snapshot
                            )
                    response = receive_frame(response_read)

            self.assertFalse(target.exists())
            temporary_entries = list(source.glob(".khaos-*.tmp"))
            self.assertEqual(len(temporary_entries), 1)
            self.assertEqual(
                temporary_entries[0].read_text(encoding="utf-8"), "candidate"
            )
            self.assertEqual(
                response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "3" * 32,
                    "ok": False,
                    "error": {"code": "commit_outcome_uncertain"},
                },
            )

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_commit_child_death_after_a_live_swap_reports_uncertain(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            first = source / "a.txt"
            second = source / "b.txt"
            first.write_text("before-a", encoding="utf-8")
            second.write_text("before-b", encoding="utf-8")
            staging_parent = root / "commit-staging"
            staging_parent.mkdir(mode=0o700)

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "a.txt").write_text("after-a", encoding="utf-8")
                (snapshot.path / "b.txt").write_text("after-b", encoding="utf-8")
                original_rename_swap = workspace_changes_module._rename_swap

                def kill_after_swap(
                    directory_fd: int, source_name: str, destination_name: str
                ) -> None:
                    original_rename_swap(directory_fd, source_name, destination_name)
                    os.kill(os.getpid(), signal.SIGKILL)

                with _pipe_pair() as (
                    request_read,
                    request_write,
                    response_read,
                    response_write,
                ):
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": "e" * 32,
                            "operation": "workspace.commit",
                            "payload": {},
                        },
                    )
                    with (
                        patch.object(
                            workspace_changes_module,
                            "_rename_swap",
                            kill_after_swap,
                        ),
                        patch(
                            "tempfile.gettempdir",
                            return_value=str(staging_parent),
                        ),
                    ):
                        with self.assertRaises(WorkspaceCommitOutcomeUncertain):
                            _serve_fixture_commit(
                                request_read, response_write, snapshot
                            )
                    response = receive_frame(response_read)

            self.assertEqual(first.read_text(encoding="utf-8"), "after-a")
            self.assertEqual(second.read_text(encoding="utf-8"), "before-b")
            temporary_contents = sorted(
                path.read_text(encoding="utf-8")
                for path in source.glob(".khaos-*.tmp")
            )
            self.assertEqual(temporary_contents, ["after-b", "before-a"])
            self.assertEqual(
                len(list(staging_parent.glob("khaos-changes-*"))),
                1,
            )
            self.assertEqual(
                response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "e" * 32,
                    "ok": False,
                    "error": {"code": "commit_outcome_uncertain"},
                },
            )

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_commit_child_cannot_swap_through_a_detached_parent_fd(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            source = root / "workspace"
            nested = source / "nested"
            nested.mkdir(parents=True)
            target = nested / "file.txt"
            target.write_text("before", encoding="utf-8")
            escaped = root / "escaped"
            staging_parent = root / "commit-staging"
            staging_parent.mkdir(mode=0o700)
            attacker_script = """\
import sys
import time
from pathlib import Path

staging_parent = Path(sys.argv[1])
nested = Path(sys.argv[2])
escaped = Path(sys.argv[3])
deadline = time.monotonic() + 8
while time.monotonic() < deadline:
    for staging in staging_parent.glob("khaos-changes-*"):
        if (staging / ".race-ready").exists():
            nested.rename(escaped)
            raise SystemExit(0)
    time.sleep(0.005)
raise SystemExit(21)
"""
            attacker = subprocess.Popen(
                (
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    attacker_script,
                    str(staging_parent),
                    str(nested),
                    str(escaped),
                ),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
            )
            original_commit = broker_module.commit_snapshot
            original_swap = workspace_changes_module._rename_swap
            staging_location: dict[str, Path] = {}

            def tracked_commit(
                snapshot, *, workspace_write_scope=None, before_live_mutations
            ):
                def remember_staging(path: Path, file_paths, entry_paths) -> None:
                    staging_location["path"] = path
                    before_live_mutations(path, file_paths, entry_paths)

                return original_commit(
                    snapshot,
                    workspace_write_scope=workspace_write_scope,
                    before_live_mutations=remember_staging,
                )

            def detach_parent_before_swap(
                directory_fd: int, source_name: str, destination_name: str
            ) -> None:
                staging_location["path"].joinpath(".race-ready").write_text(
                    "ready", encoding="utf-8"
                )
                deadline = time.monotonic() + 5
                while nested.exists() and time.monotonic() < deadline:
                    time.sleep(0.005)
                if nested.exists():
                    raise WorkspaceCommitError("directory detach attack timed out")
                original_swap(directory_fd, source_name, destination_name)

            try:
                with workspace_snapshot(source) as snapshot:
                    (snapshot.path / "nested" / "file.txt").write_text(
                        "after", encoding="utf-8"
                    )
                    with _pipe_pair() as (
                        request_read,
                        request_write,
                        response_read,
                        response_write,
                    ):
                        send_frame(
                            request_write,
                            {
                                "version": PROTOCOL_VERSION,
                                "request_id": "d" * 32,
                                "operation": "workspace.commit",
                                "payload": {},
                            },
                        )
                        with (
                            patch(
                                "khaos.kernel.broker.commit_snapshot",
                                tracked_commit,
                            ),
                            patch(
                                "khaos.kernel.workspace_changes._rename_swap",
                                detach_parent_before_swap,
                            ),
                            patch(
                                "tempfile.gettempdir",
                                return_value=str(staging_parent),
                            ),
                        ):
                            with self.assertRaises(WorkspaceCommitOutcomeUncertain):
                                _serve_fixture_commit(
                                    request_read, response_write, snapshot
                                )
                        response = receive_frame(response_read)
                attacker_output, attacker_error = attacker.communicate(timeout=8)
            finally:
                if attacker.poll() is None:
                    attacker.kill()
                    attacker.communicate()

            self.assertEqual(
                attacker.returncode,
                0,
                attacker_error.decode("utf-8", "replace"),
            )
            self.assertEqual(
                response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "d" * 32,
                    "ok": False,
                    "error": {"code": "commit_outcome_uncertain"},
                },
            )
            self.assertEqual(
                (escaped / "file.txt").read_text(encoding="utf-8"),
                "before",
            )
            escaped_temporary_entries = list(escaped.glob(".khaos-*.tmp"))
            self.assertEqual(len(escaped_temporary_entries), 1)
            self.assertEqual(
                escaped_temporary_entries[0].read_text(encoding="utf-8"),
                "after",
            )
            self.assertEqual(attacker_output, b"")

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_commit_child_cannot_clone_through_a_detached_parent_fd(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            source = root / "workspace"
            nested = source / "nested"
            nested.mkdir(parents=True)
            escaped = root / "escaped"
            staging_parent = root / "commit-staging"
            staging_parent.mkdir(mode=0o700)
            attacker_script = """\
import sys
import time
from pathlib import Path

staging_parent = Path(sys.argv[1])
nested = Path(sys.argv[2])
escaped = Path(sys.argv[3])
deadline = time.monotonic() + 8
while time.monotonic() < deadline:
    for staging in staging_parent.glob("khaos-changes-*"):
        if (staging / ".new-file-race-ready").exists():
            nested.rename(escaped)
            print("detached", flush=True)
            result = staging / ".new-file-clone-result"
            deadline = time.monotonic() + 5
            while not result.exists() and time.monotonic() < deadline:
                time.sleep(0.005)
            if result.exists():
                clone_result = result.read_text(encoding="utf-8")
                (staging / ".new-file-clone-result-read").write_text("read")
                print(clone_result, flush=True)
                raise SystemExit(0)
            raise SystemExit(22)
    time.sleep(0.005)
raise SystemExit(21)
"""
            attacker = subprocess.Popen(
                (
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    attacker_script,
                    str(staging_parent),
                    str(nested),
                    str(escaped),
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
            )
            original_commit = broker_module.commit_snapshot
            original_clone = workspace_changes_module._clone_file_from_descriptor
            staging_location: dict[str, Path] = {}

            def tracked_commit(
                snapshot, *, workspace_write_scope=None, before_live_mutations
            ):
                def remember_staging(path: Path, file_paths, entry_paths) -> None:
                    staging_location["path"] = path
                    before_live_mutations(path, file_paths, entry_paths)

                return original_commit(
                    snapshot,
                    workspace_write_scope=workspace_write_scope,
                    before_live_mutations=remember_staging,
                )

            def detach_parent_before_clone(
                source_fd: int,
                directory_fd: int,
                destination_name: str,
            ) -> None:
                def report_clone_result(result: str) -> None:
                    staging = staging_location["path"]
                    staging.joinpath(".new-file-clone-result").write_text(
                        result, encoding="utf-8"
                    )
                    acknowledged = staging / ".new-file-clone-result-read"
                    deadline = time.monotonic() + 5
                    while not acknowledged.exists() and time.monotonic() < deadline:
                        time.sleep(0.005)

                if destination_name == "file.txt":
                    staging_location["path"].joinpath(
                        ".new-file-race-ready"
                    ).write_text("ready", encoding="utf-8")
                    deadline = time.monotonic() + 5
                    while nested.exists() and time.monotonic() < deadline:
                        time.sleep(0.005)
                    if nested.exists():
                        raise WorkspaceCommitError(
                            "new-file parent detach attack timed out"
                        )
                try:
                    original_clone(source_fd, directory_fd, destination_name)
                except OSError as exc:
                    report_clone_result(f"denied:{exc.errno}")
                    raise
                else:
                    report_clone_result("created")

            try:
                with workspace_snapshot(source) as snapshot:
                    (snapshot.path / "nested" / "file.txt").write_text(
                        "candidate", encoding="utf-8"
                    )
                    with _pipe_pair() as (
                        request_read,
                        request_write,
                        response_read,
                        response_write,
                    ):
                        send_frame(
                            request_write,
                            {
                                "version": PROTOCOL_VERSION,
                                "request_id": "8" * 32,
                                "operation": "workspace.commit",
                                "payload": {},
                            },
                        )
                        with (
                            patch(
                                "khaos.kernel.broker.commit_snapshot",
                                tracked_commit,
                            ),
                            patch(
                                "khaos.kernel.workspace_changes._clone_file_from_descriptor",
                                detach_parent_before_clone,
                            ),
                            patch(
                                "tempfile.gettempdir",
                                return_value=str(staging_parent),
                            ),
                        ):
                            with self.assertRaises(WorkspaceCommitOutcomeUncertain):
                                _serve_fixture_commit(
                                    request_read, response_write, snapshot
                                )
                        response = receive_frame(response_read)
                attacker_output, attacker_error = attacker.communicate(timeout=8)
            finally:
                if attacker.poll() is None:
                    attacker.kill()
                    attacker.communicate()

            self.assertEqual(
                attacker.returncode,
                0,
                attacker_error.decode("utf-8", "replace"),
            )
            output_lines = attacker_output.decode("utf-8").splitlines()
            self.assertEqual(output_lines[0], "detached")
            self.assertIn(
                output_lines[1],
                {f"denied:{errno.EPERM}", f"denied:{errno.EACCES}"},
            )
            self.assertEqual(
                response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "8" * 32,
                    "ok": False,
                    "error": {"code": "commit_outcome_uncertain"},
                },
            )
            self.assertFalse((escaped / "file.txt").exists())
            self.assertFalse((nested / "file.txt").exists())

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_commit_child_preserves_post_clone_target_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            source = root / "workspace"
            source.mkdir()
            target = source / "payload.txt"
            concurrent = root / "concurrent.txt"
            concurrent.write_text("concurrent!!!", encoding="utf-8")
            concurrent.chmod(0o600)
            concurrent_stat = concurrent.stat()
            staging_parent = root / "commit-staging"
            staging_parent.mkdir(mode=0o700)
            attacker_script = """\
import os
import sys
import time
from pathlib import Path

staging_parent = Path(sys.argv[1])
concurrent = Path(sys.argv[2])
target = Path(sys.argv[3])
deadline = time.monotonic() + 8
while time.monotonic() < deadline:
    for staging in staging_parent.glob("khaos-changes-*"):
        if (staging / ".race-ready").exists():
            os.replace(concurrent, target)
            (staging / ".race-done").write_text("done", encoding="utf-8")
            print("replaced", flush=True)
            raise SystemExit(0)
    time.sleep(0.005)
raise SystemExit(21)
"""
            attacker = subprocess.Popen(
                (
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    attacker_script,
                    str(staging_parent),
                    str(concurrent),
                    str(target),
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
            )
            original_clone = workspace_changes_module._clone_file_from_descriptor

            def race_after_clone(
                source_fd: int, directory_fd: int, destination_name: str
            ) -> None:
                original_clone(source_fd, directory_fd, destination_name)
                staging = next(staging_parent.glob("khaos-changes-*"))
                (staging / ".race-ready").write_text("ready", encoding="utf-8")
                deadline = time.monotonic() + 5
                while (
                    not (staging / ".race-done").exists()
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.005)
                if not (staging / ".race-done").exists():
                    raise WorkspaceCommitError("post-clone target race timed out")

            try:
                with workspace_snapshot(source) as snapshot:
                    (snapshot.path / target.name).write_text(
                        "Runner output", encoding="utf-8"
                    )
                    with _pipe_pair() as (
                        request_read,
                        request_write,
                        response_read,
                        response_write,
                    ):
                        send_frame(
                            request_write,
                            {
                                "version": PROTOCOL_VERSION,
                                "request_id": "a" * 32,
                                "operation": "workspace.commit",
                                "payload": {},
                            },
                        )
                        with (
                            patch.object(
                                workspace_changes_module,
                                "_clone_file_from_descriptor",
                                race_after_clone,
                            ),
                            patch(
                                "tempfile.gettempdir",
                                return_value=str(staging_parent),
                            ),
                        ):
                            with self.assertRaises(WorkspaceCommitOutcomeUncertain):
                                _serve_fixture_commit(
                                    request_read, response_write, snapshot
                                )
                        response = receive_frame(response_read)
                attacker_output, attacker_error = attacker.communicate(timeout=8)
            finally:
                if attacker.poll() is None:
                    attacker.kill()
                    attacker.communicate()

            self.assertEqual(
                attacker.returncode,
                0,
                attacker_error.decode("utf-8", "replace"),
            )
            self.assertEqual(attacker_output, b"replaced\n")
            self.assertEqual(
                response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "a" * 32,
                    "ok": False,
                    "error": {"code": "commit_outcome_uncertain"},
                },
            )
            target_stat = target.stat()
            self.assertEqual(target.read_text(encoding="utf-8"), "concurrent!!!")
            self.assertEqual(target_stat.st_mode & 0o777, 0o600)
            self.assertEqual(target_stat.st_nlink, 1)
            self.assertEqual(
                (target_stat.st_dev, target_stat.st_ino),
                (concurrent_stat.st_dev, concurrent_stat.st_ino),
            )
            self.assertFalse(concurrent.exists())
            self.assertEqual([path.name for path in source.iterdir()], [target.name])
            self.assertEqual(list(staging_parent.iterdir()), [])

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_commit_child_preserves_new_file_temporary_path_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            source = root / "workspace"
            source.mkdir()
            concurrent = root / "concurrent.txt"
            concurrent.write_text("concurrent", encoding="utf-8")
            concurrent_stat = concurrent.stat()
            staging_parent = root / "commit-staging"
            staging_parent.mkdir(mode=0o700)
            attacker_script = """\
import os
import sys
import time
from pathlib import Path

source = Path(sys.argv[1])
concurrent = Path(sys.argv[2])
staging_parent = Path(sys.argv[3])
deadline = time.monotonic() + 8
while time.monotonic() < deadline:
    for staging in staging_parent.glob("khaos-changes-*"):
        ready = staging / ".temporary-race-ready"
        if ready.exists():
            name = ready.read_text(encoding="utf-8")
            os.replace(concurrent, source / name)
            (staging / ".temporary-race-done").write_text("done", encoding="utf-8")
            print(name, flush=True)
            raise SystemExit(0)
    time.sleep(0.005)
raise SystemExit(21)
"""
            attacker = subprocess.Popen(
                (
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    attacker_script,
                    str(source),
                    str(concurrent),
                    str(staging_parent),
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
            )
            original_clone = workspace_changes_module._clone_file_from_descriptor

            def replace_temp_before_clone(
                source_fd: int,
                directory_fd: int,
                destination_name: str,
            ) -> None:
                temporary_entries = tuple(source.glob(".khaos-*.tmp"))
                if destination_name == "payload.txt":
                    self.assertEqual(len(temporary_entries), 1)
                    staging = next(staging_parent.glob("khaos-changes-*"))
                    (staging / ".temporary-race-ready").write_text(
                        temporary_entries[0].name, encoding="utf-8"
                    )
                    done = staging / ".temporary-race-done"
                    deadline = time.monotonic() + 5
                    while not done.exists() and time.monotonic() < deadline:
                        time.sleep(0.005)
                    if not done.exists():
                        raise WorkspaceCommitError(
                            "new-file temporary replacement race timed out"
                        )
                return original_clone(source_fd, directory_fd, destination_name)

            try:
                with workspace_snapshot(source) as snapshot:
                    (snapshot.path / "payload.txt").write_text(
                        "Runner output", encoding="utf-8"
                    )
                    with _pipe_pair() as (
                        request_read,
                        request_write,
                        response_read,
                        response_write,
                    ):
                        send_frame(
                            request_write,
                            {
                                "version": PROTOCOL_VERSION,
                                "request_id": "b" * 32,
                                "operation": "workspace.commit",
                                "payload": {},
                            },
                        )
                        with (
                            patch.object(
                                workspace_changes_module,
                                "_clone_file_from_descriptor",
                                replace_temp_before_clone,
                            ),
                            patch(
                                "tempfile.gettempdir",
                                return_value=str(staging_parent),
                            ),
                        ):
                            with self.assertRaises(WorkspaceCommitOutcomeUncertain):
                                _serve_fixture_commit(
                                    request_read, response_write, snapshot
                                )
                        response = receive_frame(response_read)
                attacker_output, attacker_error = attacker.communicate(timeout=8)
            finally:
                if attacker.poll() is None:
                    attacker.kill()
                    attacker.communicate()

            self.assertEqual(
                attacker.returncode,
                0,
                attacker_error.decode("utf-8", "replace"),
            )
            self.assertEqual(attacker_output.count(b"\n"), 1)
            temporary_name = attacker_output.decode("utf-8").strip()
            self.assertTrue(
                temporary_name.startswith(".khaos-")
                and temporary_name.endswith(".tmp")
            )
            self.assertEqual(
                response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "b" * 32,
                    "ok": False,
                    "error": {"code": "commit_outcome_uncertain"},
                },
            )
            self.assertEqual(
                (source / "payload.txt").read_text(encoding="utf-8"),
                "Runner output",
            )
            preserved = source / temporary_name
            self.assertEqual(preserved.read_text(encoding="utf-8"), "concurrent")
            preserved_stat = preserved.stat()
            self.assertEqual(
                (preserved_stat.st_dev, preserved_stat.st_ino),
                (concurrent_stat.st_dev, concurrent_stat.st_ino),
            )
            self.assertFalse(concurrent.exists())
            self.assertEqual(
                sorted(path.name for path in source.iterdir()),
                sorted(("payload.txt", preserved.name)),
            )
            self.assertEqual(list(staging_parent.iterdir()), [])

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_commit_child_preserves_prepared_file_replacement_race(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            source = root / "workspace"
            source.mkdir()
            target = source / "payload.txt"
            target.write_text("baseline", encoding="utf-8")
            concurrent = root / "concurrent.txt"
            concurrent.write_text("concurrent", encoding="utf-8")
            concurrent_stat = concurrent.stat()
            staging_parent = root / "commit-staging"
            staging_parent.mkdir(mode=0o700)
            attacker_script = """\
import os
import sys
import time
from pathlib import Path

source = Path(sys.argv[1])
concurrent = Path(sys.argv[2])
staging_parent = Path(sys.argv[3])
deadline = time.monotonic() + 8
while time.monotonic() < deadline:
    for staging in staging_parent.glob("khaos-changes-*"):
        ready = staging / ".race-ready"
        if ready.exists():
            name = ready.read_text(encoding="utf-8")
            os.replace(concurrent, source / name)
            (staging / ".race-done").write_text("done", encoding="utf-8")
            print(name, flush=True)
            raise SystemExit(0)
    time.sleep(0.005)
raise SystemExit(21)
"""
            attacker = subprocess.Popen(
                (
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    attacker_script,
                    str(source),
                    str(concurrent),
                    str(staging_parent),
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
            )
            original_matches = workspace_changes_module._prepared_file_matches
            race_started = False

            def race_before_prepared_file_check(
                replacement, name: str, *, after_swap: bool
            ) -> bool:
                nonlocal race_started
                if not after_swap and not race_started:
                    race_started = True
                    staging = next(staging_parent.glob("khaos-changes-*"))
                    (staging / ".race-ready").write_text(name, encoding="utf-8")
                    deadline = time.monotonic() + 5
                    while (
                        not (staging / ".race-done").exists()
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.005)
                    if not (staging / ".race-done").exists():
                        raise WorkspaceCommitError(
                            "prepared file replacement race timed out"
                        )
                return original_matches(replacement, name, after_swap=after_swap)

            try:
                with workspace_snapshot(source) as snapshot:
                    (snapshot.path / target.name).write_text(
                        "runner output", encoding="utf-8"
                    )
                    with _pipe_pair() as (
                        request_read,
                        request_write,
                        response_read,
                        response_write,
                    ):
                        send_frame(
                            request_write,
                            {
                                "version": PROTOCOL_VERSION,
                                "request_id": "c" * 32,
                                "operation": "workspace.commit",
                                "payload": {},
                            },
                        )
                        with (
                            patch.object(
                                workspace_changes_module,
                                "_prepared_file_matches",
                                race_before_prepared_file_check,
                            ),
                            patch(
                                "tempfile.gettempdir",
                                return_value=str(staging_parent),
                            ),
                        ):
                            with self.assertRaises(WorkspaceCommitOutcomeUncertain):
                                _serve_fixture_commit(
                                    request_read, response_write, snapshot
                                )
                        response = receive_frame(response_read)
                attacker_output, attacker_error = attacker.communicate(timeout=8)
            finally:
                if attacker.poll() is None:
                    attacker.kill()
                    attacker.communicate()

            self.assertEqual(
                attacker.returncode,
                0,
                attacker_error.decode("utf-8", "replace"),
            )
            raced_name = attacker_output.decode("utf-8").strip()
            self.assertTrue(raced_name.startswith(".khaos-"))
            self.assertEqual(
                response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "c" * 32,
                    "ok": False,
                    "error": {"code": "commit_outcome_uncertain"},
                },
            )
            self.assertEqual(target.read_text(encoding="utf-8"), "baseline")
            raced_entry = source / raced_name
            self.assertEqual(raced_entry.read_text(encoding="utf-8"), "concurrent")
            raced_stat = raced_entry.stat()
            self.assertEqual(
                (raced_stat.st_dev, raced_stat.st_ino),
                (concurrent_stat.st_dev, concurrent_stat.st_ino),
            )
            self.assertFalse(concurrent.exists())

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_commit_child_preserves_displaced_backup_replacement_before_unlink(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            source = root / "workspace"
            source.mkdir()
            target = source / "payload.txt"
            target.write_text("baseline", encoding="utf-8")
            concurrent = root / "concurrent.txt"
            concurrent.write_text("concurrent", encoding="utf-8")
            concurrent_stat = concurrent.stat()
            staging_parent = root / "commit-staging"
            staging_parent.mkdir(mode=0o700)
            attacker_script = """\
import os
import sys
import time
from pathlib import Path

source = Path(sys.argv[1])
concurrent = Path(sys.argv[2])
staging_parent = Path(sys.argv[3])
deadline = time.monotonic() + 8
while time.monotonic() < deadline:
    for staging in staging_parent.glob("khaos-changes-*"):
        ready = staging / ".backup-race-ready"
        if ready.exists():
            name = ready.read_text(encoding="utf-8")
            os.replace(concurrent, source / name)
            (staging / ".backup-race-done").write_text("done", encoding="utf-8")
            print(name, flush=True)
            raise SystemExit(0)
    time.sleep(0.005)
raise SystemExit(21)
"""
            attacker = subprocess.Popen(
                (
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    attacker_script,
                    str(source),
                    str(concurrent),
                    str(staging_parent),
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
            )
            original_match = workspace_changes_module._matches_displaced_entry
            race = {"started": False}

            def replace_after_backup_validation(
                directory_fd: int, name: str, expected
            ) -> bool:
                matched = original_match(directory_fd, name, expected)
                if matched and name.startswith(".khaos-") and not race["started"]:
                    race["started"] = True
                    staging = next(staging_parent.glob("khaos-changes-*"))
                    (staging / ".backup-race-ready").write_text(
                        name, encoding="utf-8"
                    )
                    deadline = time.monotonic() + 5
                    done = staging / ".backup-race-done"
                    while not done.exists() and time.monotonic() < deadline:
                        time.sleep(0.005)
                    if not done.exists():
                        raise WorkspaceCommitError(
                            "displaced backup replacement race timed out"
                        )
                return matched

            try:
                with workspace_snapshot(source) as snapshot:
                    (snapshot.path / target.name).write_text(
                        "runner output", encoding="utf-8"
                    )
                    with _pipe_pair() as (
                        request_read,
                        request_write,
                        response_read,
                        response_write,
                    ):
                        send_frame(
                            request_write,
                            {
                                "version": PROTOCOL_VERSION,
                                "request_id": "9" * 32,
                                "operation": "workspace.commit",
                                "payload": {},
                            },
                        )
                        with (
                            patch.object(
                                workspace_changes_module,
                                "_matches_displaced_entry",
                                replace_after_backup_validation,
                            ),
                            patch(
                                "tempfile.gettempdir",
                                return_value=str(staging_parent),
                            ),
                        ):
                            try:
                                _serve_fixture_commit(
                                    request_read, response_write, snapshot
                                )
                                outcome = "applied"
                            except WorkspaceCommitOutcomeUncertain:
                                outcome = "uncertain"
                            except WorkspaceCommitError:
                                outcome = "rejected"
                        response = receive_frame(response_read)
                attacker_output, attacker_error = attacker.communicate(timeout=8)
            finally:
                if attacker.poll() is None:
                    attacker.kill()
                    attacker.communicate()

            self.assertEqual(
                attacker.returncode,
                0,
                attacker_error.decode("utf-8", "replace"),
            )
            raced_name = attacker_output.decode("utf-8").strip()
            self.assertTrue(raced_name.startswith(".khaos-"))
            preserved = source / raced_name
            self.assertTrue(
                preserved.exists(),
                "commit unlinked the competing inode after validating its backup path",
            )
            self.assertEqual(preserved.read_text(encoding="utf-8"), "concurrent")
            preserved_stat = preserved.stat()
            self.assertEqual(
                (preserved_stat.st_dev, preserved_stat.st_ino),
                (concurrent_stat.st_dev, concurrent_stat.st_ino),
            )
            self.assertFalse(concurrent.exists())
            self.assertEqual(outcome, "uncertain")
            self.assertEqual(target.read_text(encoding="utf-8"), "runner output")
            self.assertEqual(
                response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "9" * 32,
                    "ok": False,
                    "error": {"code": "commit_outcome_uncertain"},
                },
            )

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_commit_child_unlink_does_not_follow_raced_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            source = root / "workspace"
            source.mkdir()
            target = source / "payload.txt"
            target.write_text("baseline", encoding="utf-8")
            canary = root / "outside-canary.txt"
            canary.write_text("outside-canary", encoding="utf-8")
            canary_before = canary.read_bytes()
            replacement = root / "raced-symlink"
            replacement.symlink_to(canary)
            staging_parent = root / "commit-staging"
            staging_parent.mkdir(mode=0o700)
            attacker_script = """\
import os
import sys
import time
from pathlib import Path

source = Path(sys.argv[1])
replacement = Path(sys.argv[2])
staging_parent = Path(sys.argv[3])
deadline = time.monotonic() + 8
while time.monotonic() < deadline:
    for staging in staging_parent.glob("khaos-changes-*"):
        ready = staging / ".final-unlink-race-ready"
        if ready.exists():
            name = ready.read_text(encoding="utf-8")
            os.replace(replacement, source / name)
            (staging / ".final-unlink-race-done").write_text("done")
            print(name, flush=True)
            raise SystemExit(0)
    time.sleep(0.005)
raise SystemExit(21)
"""
            attacker = subprocess.Popen(
                (
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    attacker_script,
                    str(source),
                    str(replacement),
                    str(staging_parent),
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
            )
            original_remove = workspace_changes_module._remove_entry_at
            race = {"started": False}

            def replace_with_symlink_before_unlink(
                directory_fd: int, name: str, kind: str
            ) -> None:
                if not race["started"] and kind == "file" and name.startswith(
                    ".khaos-"
                ):
                    race["started"] = True
                    staging = next(staging_parent.glob("khaos-changes-*"))
                    (staging / ".final-unlink-race-ready").write_text(
                        name, encoding="utf-8"
                    )
                    deadline = time.monotonic() + 5
                    done = staging / ".final-unlink-race-done"
                    while not done.exists() and time.monotonic() < deadline:
                        time.sleep(0.005)
                    if not done.exists():
                        raise WorkspaceCommitError(
                            "final unlink symlink race timed out"
                        )
                original_remove(directory_fd, name, kind)

            try:
                with workspace_snapshot(source) as snapshot:
                    (snapshot.path / target.name).write_text(
                        "validated candidate", encoding="utf-8"
                    )
                    with _pipe_pair() as (
                        request_read,
                        request_write,
                        response_read,
                        response_write,
                    ):
                        send_frame(
                            request_write,
                            {
                                "version": PROTOCOL_VERSION,
                                "request_id": "d" * 32,
                                "operation": "workspace.commit",
                                "payload": {},
                            },
                        )
                        with (
                            patch.object(
                                workspace_changes_module,
                                "_remove_entry_at",
                                replace_with_symlink_before_unlink,
                            ),
                            patch(
                                "tempfile.gettempdir",
                                return_value=str(staging_parent),
                            ),
                        ):
                            changes = _serve_fixture_commit(
                                request_read, response_write, snapshot
                            )
                        response = receive_frame(response_read)
                attacker_output, attacker_error = attacker.communicate(timeout=8)
            finally:
                if attacker.poll() is None:
                    attacker.kill()
                    attacker.communicate()

            self.assertEqual(
                attacker.returncode,
                0,
                attacker_error.decode("utf-8", "replace"),
            )
            raced_name = attacker_output.decode("utf-8").strip()
            self.assertTrue(raced_name.startswith(".khaos-"))
            self.assertEqual(changes.modified, 1)
            self.assertEqual(target.read_text(encoding="utf-8"), "validated candidate")
            self.assertEqual(canary.read_bytes(), canary_before)
            self.assertFalse(os.path.lexists(source / raced_name))
            self.assertEqual(
                response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "d" * 32,
                    "ok": True,
                    "result": {"added": 0, "modified": 1, "deleted": 0},
                },
            )

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_commit_child_cannot_unlink_after_parent_detaches(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            source = root / "workspace"
            nested = source / "nested"
            nested.mkdir(parents=True)
            target = nested / "payload.txt"
            target.write_text("baseline", encoding="utf-8")
            detached = root / "detached-parent"
            outside = root / "outside-canary.txt"
            outside.write_text("outside-canary", encoding="utf-8")
            outside_digest = hashlib.sha256(outside.read_bytes()).digest()
            staging_parent = root / "commit-staging"
            staging_parent.mkdir(mode=0o700)
            commit_finished = root / "commit-finished"
            attacker_script = """\
import sys
import time
from pathlib import Path

staging_parent = Path(sys.argv[1])
nested = Path(sys.argv[2])
detached = Path(sys.argv[3])
commit_finished = Path(sys.argv[4])
deadline = time.monotonic() + 8
while time.monotonic() < deadline:
    for staging in staging_parent.glob("khaos-changes-*"):
        ready = staging / ".unlink-after-identity-ready"
        if ready.exists():
            nested.rename(detached)
            (staging / ".unlink-after-parent-moved").write_text("moved")
            result = staging / ".unlink-after-identity-result"
            deadline = time.monotonic() + 5
            while not result.exists() and time.monotonic() < deadline:
                time.sleep(0.005)
            if not result.exists():
                raise SystemExit(22)
            result_value = result.read_text(encoding="utf-8")
            (staging / ".unlink-after-identity-result-read").write_text("read")
            deadline = time.monotonic() + 5
            while not commit_finished.exists() and time.monotonic() < deadline:
                time.sleep(0.005)
            if not commit_finished.exists():
                raise SystemExit(23)
            print(result_value, flush=True)
            raise SystemExit(0)
    time.sleep(0.005)
raise SystemExit(21)
"""
            attacker = subprocess.Popen(
                (
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    attacker_script,
                    str(staging_parent),
                    str(nested),
                    str(detached),
                    str(commit_finished),
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
            )
            original_commit = broker_module.commit_snapshot
            original_remove = workspace_changes_module._remove_entry_at
            staging_location: dict[str, Path] = {}
            race = {"started": False, "reported": False}

            def tracked_commit(
                snapshot, *, workspace_write_scope=None, before_live_mutations
            ):
                def remember_staging(path: Path, file_paths, entry_paths) -> None:
                    staging_location["path"] = path
                    before_live_mutations(path, file_paths, entry_paths)

                return original_commit(
                    snapshot,
                    workspace_write_scope=workspace_write_scope,
                    before_live_mutations=remember_staging,
                )

            def publish_remove_result(value: str) -> None:
                staging = staging_location["path"]
                result = staging / ".unlink-after-identity-result"
                result.write_text(value, encoding="utf-8")
                deadline = time.monotonic() + 5
                acknowledged = staging / ".unlink-after-identity-result-read"
                while not acknowledged.exists() and time.monotonic() < deadline:
                    time.sleep(0.005)
                if not acknowledged.exists():
                    raise WorkspaceCommitError(
                        "parent detach race did not observe the unlink result"
                    )

            def detach_parent_before_remove(
                directory_fd: int, name: str, kind: str
            ) -> None:
                if not race["started"] and kind == "file" and name.startswith(".khaos-"):
                    race["started"] = True
                    staging = staging_location["path"]
                    (staging / ".unlink-after-identity-ready").write_text(
                        "ready", encoding="utf-8"
                    )
                    deadline = time.monotonic() + 5
                    moved = staging / ".unlink-after-parent-moved"
                    while not moved.exists() and time.monotonic() < deadline:
                        time.sleep(0.005)
                    if not moved.exists():
                        raise WorkspaceCommitError(
                            "parent detach race timed out before removal"
                        )

                try:
                    original_remove(directory_fd, name, kind)
                except OSError as exc:
                    if race["started"] and not race["reported"]:
                        publish_remove_result(f"denied:{exc.errno}")
                        race["reported"] = True
                    raise
                else:
                    if race["started"] and not race["reported"]:
                        publish_remove_result("removed")
                        race["reported"] = True

            try:
                with workspace_snapshot(source) as snapshot:
                    (snapshot.path / "nested" / target.name).write_text(
                        "candidate", encoding="utf-8"
                    )
                    with _pipe_pair() as (
                        request_read,
                        request_write,
                        response_read,
                        response_write,
                    ):
                        send_frame(
                            request_write,
                            {
                                "version": PROTOCOL_VERSION,
                                "request_id": "a" * 32,
                                "operation": "workspace.commit",
                                "payload": {},
                            },
                        )
                        with (
                            patch(
                                "khaos.kernel.broker.commit_snapshot",
                                tracked_commit,
                            ),
                            patch.object(
                                workspace_changes_module,
                                "_remove_entry_at",
                                detach_parent_before_remove,
                            ),
                            patch(
                                "tempfile.gettempdir",
                                return_value=str(staging_parent),
                            ),
                        ):
                            with self.assertRaises(WorkspaceCommitOutcomeUncertain):
                                _serve_fixture_commit(
                                    request_read, response_write, snapshot
                                )
                        response = receive_frame(response_read)
                        commit_finished.write_text("finished", encoding="utf-8")
                attacker_output, attacker_error = attacker.communicate(timeout=8)
            finally:
                if attacker.poll() is None:
                    attacker.kill()
                    attacker.communicate()

            self.assertEqual(
                attacker.returncode,
                0,
                attacker_error.decode("utf-8", "replace"),
            )
            self.assertRegex(
                attacker_output.decode("utf-8").strip(), r"^denied:(?:1|13)$"
            )
            self.assertFalse(nested.exists())
            self.assertTrue(detached.is_dir())
            self.assertIn(
                b"baseline",
                [path.read_bytes() for path in detached.iterdir() if path.is_file()],
            )
            self.assertEqual((detached / target.name).read_bytes(), b"candidate")
            self.assertEqual(
                hashlib.sha256(outside.read_bytes()).digest(), outside_digest
            )
            self.assertEqual(
                response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "a" * 32,
                    "ok": False,
                    "error": {"code": "commit_outcome_uncertain"},
                },
            )

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_commit_child_preserves_new_directory_after_parent_failure(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            source = root / "workspace"
            source.mkdir()
            staging_parent = root / "commit-staging"
            staging_parent.mkdir(mode=0o700)
            real_parent_check = workspace_changes_module._parent_binding_is_current
            parent_check_count = 0

            def reject_after_directory_creation(
                root_fd,
                source_root,
                components,
                parent_fd,
                active_directories,
                mount_point,
            ) -> bool:
                nonlocal parent_check_count
                current = real_parent_check(
                    root_fd,
                    source_root,
                    components,
                    parent_fd,
                    active_directories,
                    mount_point,
                )
                if components == ():
                    parent_check_count += 1
                    if parent_check_count == 2:
                        return False
                return current

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "created").mkdir()
                with _pipe_pair() as (
                    request_read,
                    request_write,
                    response_read,
                    response_write,
                ):
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": "d" * 32,
                            "operation": "workspace.commit",
                            "payload": {},
                        },
                    )
                    with (
                        patch.object(
                            workspace_changes_module,
                            "_parent_binding_is_current",
                            reject_after_directory_creation,
                        ),
                        patch(
                            "tempfile.gettempdir",
                            return_value=str(staging_parent),
                        ),
                    ):
                        with self.assertRaisesRegex(
                            WorkspaceCommitOutcomeUncertain,
                            "partially applied",
                        ):
                            _serve_fixture_commit(
                                request_read, response_write, snapshot
                            )
                    response = receive_frame(response_read)

            self.assertTrue((source / "created").is_dir())
            self.assertEqual(list(source.iterdir()), [source / "created"])
            self.assertEqual(
                response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "d" * 32,
                    "ok": False,
                    "error": {"code": "commit_outcome_uncertain"},
                },
            )

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_commit_child_preserves_replacement_after_post_install_failure(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            source = root / "workspace"
            source.mkdir()
            target = source / "payload.txt"
            concurrent = root / "concurrent.txt"
            concurrent.write_text("concurrent", encoding="utf-8")
            concurrent_stat = concurrent.stat()
            staging_parent = root / "commit-staging"
            staging_parent.mkdir(mode=0o700)
            attacker_script = """\
import os
import sys
import time
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
concurrent = Path(sys.argv[3])
staging_parent = Path(sys.argv[4])
deadline = time.monotonic() + 8
while time.monotonic() < deadline:
    for staging in staging_parent.glob("khaos-changes-*"):
        if (staging / ".rollback-race-ready").exists():
            if target.read_text(encoding="utf-8") != "runner output":
                raise SystemExit(22)
            os.replace(concurrent, target)
            (staging / ".rollback-race-done").write_text("done", encoding="utf-8")
            print("replaced", flush=True)
            raise SystemExit(0)
    time.sleep(0.005)
raise SystemExit(21)
"""
            attacker = subprocess.Popen(
                (
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    attacker_script,
                    str(source),
                    str(target),
                    str(concurrent),
                    str(staging_parent),
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
            )
            original_install = workspace_changes_module._install_staged_file

            def fail_after_install(
                destination_name,
                staged_name,
                expected_output,
                parent_binding_check,
                parent_fd,
                staging_fd,
                temporary_name,
                cleanup_temporary_name,
                on_live_mutation,
            ) -> None:
                binding_checks = 0

                def fail_after_clone() -> bool:
                    nonlocal binding_checks
                    binding_checks += 1
                    valid = parent_binding_check()
                    if binding_checks == 2 and valid:
                        staging = next(staging_parent.glob("khaos-changes-*"))
                        (staging / ".rollback-race-ready").write_text(
                            "ready", encoding="utf-8"
                        )
                        deadline = time.monotonic() + 5
                        done = staging / ".rollback-race-done"
                        while not done.exists() and time.monotonic() < deadline:
                            time.sleep(0.005)
                        if not done.exists():
                            raise WorkspaceCommitError(
                                "post-install replacement race timed out"
                            )
                        return False
                    return valid

                return original_install(
                    destination_name,
                    staged_name,
                    expected_output,
                    fail_after_clone,
                    parent_fd,
                    staging_fd,
                    temporary_name,
                    cleanup_temporary_name,
                    on_live_mutation,
                )

            try:
                with workspace_snapshot(source) as snapshot:
                    (snapshot.path / target.name).write_text(
                        "runner output", encoding="utf-8"
                    )
                    with _pipe_pair() as (
                        request_read,
                        request_write,
                        response_read,
                        response_write,
                    ):
                        send_frame(
                            request_write,
                            {
                                "version": PROTOCOL_VERSION,
                                "request_id": "a" * 32,
                                "operation": "workspace.commit",
                                "payload": {},
                            },
                        )
                        with (
                            patch.object(
                                workspace_changes_module,
                                "_install_staged_file",
                                fail_after_install,
                            ),
                            patch(
                                "tempfile.gettempdir",
                                return_value=str(staging_parent),
                            ),
                        ):
                            with self.assertRaises(WorkspaceCommitOutcomeUncertain):
                                _serve_fixture_commit(
                                    request_read, response_write, snapshot
                                )
                        response = receive_frame(response_read)
                attacker_output, attacker_error = attacker.communicate(timeout=8)
            finally:
                if attacker.poll() is None:
                    attacker.kill()
                    attacker.communicate()

            self.assertEqual(
                attacker.returncode,
                0,
                f"{attacker_error.decode('utf-8', 'replace')}; "
                f"target_exists={target.exists()}; "
                f"target_content={target.read_text(encoding='utf-8') if target.exists() else None!r}; "
                f"response={response!r}",
            )
            self.assertEqual(attacker_output, b"replaced\n")
            self.assertTrue(
                target.exists(),
                "failed new-file installation removed a concurrent replacement",
            )
            self.assertEqual(target.read_text(encoding="utf-8"), "concurrent")
            target_stat = target.stat()
            self.assertEqual(
                (target_stat.st_dev, target_stat.st_ino),
                (concurrent_stat.st_dev, concurrent_stat.st_ino),
            )
            self.assertFalse(concurrent.exists())
            self.assertEqual(
                response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "a" * 32,
                    "ok": False,
                    "error": {"code": "commit_outcome_uncertain"},
                },
            )

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_commit_child_preserves_prepared_cleanup_replacement_race(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            source = root / "workspace"
            source.mkdir()
            target = source / "payload.txt"
            target.write_text("baseline", encoding="utf-8")
            concurrent = root / "concurrent.txt"
            concurrent.write_text("concurrent", encoding="utf-8")
            concurrent_stat = concurrent.stat()
            staging_parent = root / "commit-staging"
            staging_parent.mkdir(mode=0o700)
            attacker_script = """\
import os
import sys
import time
from pathlib import Path

source = Path(sys.argv[1])
concurrent = Path(sys.argv[2])
staging_parent = Path(sys.argv[3])
deadline = time.monotonic() + 8
while time.monotonic() < deadline:
    for staging in staging_parent.glob("khaos-changes-*"):
        armed = staging / ".cleanup-armed"
        ready = staging / ".race-ready"
        if armed.exists():
            name = armed.read_text(encoding="utf-8")
            if ready.exists():
                os.replace(concurrent, source / name)
                (staging / ".race-done").write_text("done", encoding="utf-8")
                print(name, flush=True)
                raise SystemExit(0)
            if time.monotonic() + 0.1 >= deadline:
                print(f"cleanup-armed-without-stat-race:{name}", flush=True)
                raise SystemExit(22)
    time.sleep(0.005)
raise SystemExit(21)
"""
            attacker = subprocess.Popen(
                (
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    attacker_script,
                    str(source),
                    str(concurrent),
                    str(staging_parent),
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
            )
            control: dict[str, str | bool] = {}
            original_swap = workspace_changes_module._rename_swap

            def replace_before_cleanup_swap(
                directory_fd: int, source_name: str, destination_name: str
            ) -> None:
                if (
                    destination_name == control.get("name")
                    and control.get("raced") is not True
                ):
                    control["raced"] = True
                    staging = next(staging_parent.glob("khaos-changes-*"))
                    (staging / ".race-ready").write_text(
                        destination_name, encoding="utf-8"
                    )
                    deadline = time.monotonic() + 5
                    while (
                        not (staging / ".race-done").exists()
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.005)
                    if not (staging / ".race-done").exists():
                        raise WorkspaceCommitError(
                            "prepared cleanup race timed out"
                        )
                original_swap(directory_fd, source_name, destination_name)

            def abort_after_preparation(
                _root_fd,
                _source_root,
                _baseline,
                _output,
                _plan,
                _staged_files,
                _staging_fd,
                _active_directories,
                _mount_point,
                prepared,
                _on_live_mutation,
            ) -> None:
                control["name"] = next(iter(prepared.values())).name
                staging = next(staging_parent.glob("khaos-changes-*"))
                (staging / ".cleanup-armed").write_text(
                    str(control["name"]), encoding="utf-8"
                )
                control["armed"] = True
                raise WorkspaceCommitError("injected post-preflight abort")

            try:
                with workspace_snapshot(source) as snapshot:
                    (snapshot.path / target.name).write_text(
                        "runner output", encoding="utf-8"
                    )
                    with _pipe_pair() as (
                        request_read,
                        request_write,
                        response_read,
                        response_write,
                    ):
                        send_frame(
                            request_write,
                            {
                                "version": PROTOCOL_VERSION,
                                "request_id": "e" * 32,
                                "operation": "workspace.commit",
                                "payload": {},
                            },
                        )
                        with (
                            patch.object(
                                workspace_changes_module,
                                "_apply_prepared_changes",
                                abort_after_preparation,
                            ),
                            patch.object(
                                workspace_changes_module,
                                "_rename_swap",
                                replace_before_cleanup_swap,
                            ),
                            patch(
                                "tempfile.gettempdir",
                                return_value=str(staging_parent),
                            ),
                        ):
                            with self.assertRaises(WorkspaceCommitOutcomeUncertain):
                                _serve_fixture_commit(
                                    request_read, response_write, snapshot
                                )
                        response = receive_frame(response_read)
                attacker_output, attacker_error = attacker.communicate(timeout=8)
            finally:
                if attacker.poll() is None:
                    attacker.kill()
                    attacker.communicate()

            self.assertEqual(
                attacker.returncode,
                0,
                attacker_error.decode("utf-8", "replace"),
            )
            raced_name = attacker_output.decode("utf-8").strip()
            self.assertTrue(raced_name.startswith(".khaos-"))
            self.assertEqual(
                response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "e" * 32,
                    "ok": False,
                    "error": {"code": "commit_outcome_uncertain"},
                },
            )
            self.assertEqual(target.read_text(encoding="utf-8"), "baseline")
            raced_entry = source / raced_name
            self.assertEqual(raced_entry.read_text(encoding="utf-8"), "concurrent")
            raced_stat = raced_entry.stat()
            self.assertEqual(
                (raced_stat.st_dev, raced_stat.st_ino),
                (concurrent_stat.st_dev, concurrent_stat.st_ino),
            )
            self.assertFalse(concurrent.exists())

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_commit_child_restores_a_concurrent_target_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            source = root / "workspace"
            source.mkdir()
            target = source / "payload.txt"
            target.write_text("baseline", encoding="utf-8")
            concurrent = root / "concurrent.txt"
            concurrent.write_text("concurrent", encoding="utf-8")
            concurrent_stat = concurrent.stat()
            staging_parent = root / "commit-staging"
            staging_parent.mkdir(mode=0o700)
            attacker_script = """\
import os
import sys
import time
from pathlib import Path

staging_parent = Path(sys.argv[1])
concurrent = Path(sys.argv[2])
target = Path(sys.argv[3])
deadline = time.monotonic() + 8
while time.monotonic() < deadline:
    for staging in staging_parent.glob("khaos-changes-*"):
        if (staging / ".race-ready").exists():
            os.replace(concurrent, target)
            (staging / ".race-done").write_text("done", encoding="utf-8")
            print("replaced", flush=True)
            raise SystemExit(0)
    time.sleep(0.005)
raise SystemExit(21)
"""
            attacker = subprocess.Popen(
                (
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    attacker_script,
                    str(staging_parent),
                    str(concurrent),
                    str(target),
                ),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
            )
            original_commit = broker_module.commit_snapshot
            original_swap = workspace_changes_module._rename_swap
            staging_location: dict[str, Path] = {}
            race_started = False

            def tracked_commit(
                snapshot, *, workspace_write_scope=None, before_live_mutations
            ):
                def remember_staging(path: Path, file_paths, entry_paths) -> None:
                    staging_location["path"] = path
                    before_live_mutations(path, file_paths, entry_paths)

                return original_commit(
                    snapshot,
                    workspace_write_scope=workspace_write_scope,
                    before_live_mutations=remember_staging,
                )

            def replace_target_before_swap(
                directory_fd: int, source_name: str, destination_name: str
            ) -> None:
                nonlocal race_started
                if (
                    destination_name == target.name
                    and source_name.startswith(".khaos-")
                    and not race_started
                ):
                    race_started = True
                    staging = staging_location["path"]
                    (staging / ".race-ready").write_text(
                        "ready", encoding="utf-8"
                    )
                    deadline = time.monotonic() + 5
                    while (
                        not (staging / ".race-done").exists()
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.005)
                    if not (staging / ".race-done").exists():
                        raise WorkspaceCommitError(
                            "target replacement attack timed out"
                        )
                original_swap(directory_fd, source_name, destination_name)

            try:
                with workspace_snapshot(source) as snapshot:
                    (snapshot.path / target.name).write_text(
                        "runner", encoding="utf-8"
                    )
                    with _pipe_pair() as (
                        request_read,
                        request_write,
                        response_read,
                        response_write,
                    ):
                        send_frame(
                            request_write,
                            {
                                "version": PROTOCOL_VERSION,
                                "request_id": "f" * 32,
                                "operation": "workspace.commit",
                                "payload": {},
                            },
                        )
                        with (
                            patch(
                                "khaos.kernel.broker.commit_snapshot",
                                tracked_commit,
                            ),
                            patch(
                                "khaos.kernel.workspace_changes._rename_swap",
                                replace_target_before_swap,
                            ),
                            patch(
                                "tempfile.gettempdir",
                                return_value=str(staging_parent),
                            ),
                        ):
                            with self.assertRaises(WorkspaceCommitOutcomeUncertain):
                                _serve_fixture_commit(
                                    request_read, response_write, snapshot
                                )
                        response = receive_frame(response_read)
                attacker_output, attacker_error = attacker.communicate(timeout=8)
            finally:
                if attacker.poll() is None:
                    attacker.kill()
                    attacker.communicate()

            self.assertEqual(
                attacker.returncode,
                0,
                attacker_error.decode("utf-8", "replace"),
            )
            self.assertEqual(attacker_output, b"replaced\n")
            self.assertEqual(
                response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "f" * 32,
                    "ok": False,
                    "error": {"code": "commit_outcome_uncertain"},
                },
            )
            target_stat = target.stat()
            self.assertEqual(target.read_text(encoding="utf-8"), "concurrent")
            self.assertEqual(
                (target_stat.st_dev, target_stat.st_ino),
                (concurrent_stat.st_dev, concurrent_stat.st_ino),
            )
            self.assertEqual([path.name for path in source.iterdir()], [target.name])
            self.assertEqual(list(staging_parent.iterdir()), [])

    def test_caller_cancel_before_commit_discards_snapshot_changes(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            target = source / "file.txt"
            target.write_text("before", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "file.txt").write_text("runner", encoding="utf-8")
                with _pipe_pair() as (
                    request_read,
                    request_write,
                    _response_read,
                    response_write,
                ):
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": "f" * 32,
                            "operation": "workspace.commit",
                            "payload": {},
                        },
                    )
                    with self.assertRaisesRegex(
                        IPCProtocolError, "cancelled before application"
                    ):
                        _serve_fixture_commit(
                            request_read,
                            response_write,
                            snapshot,
                            cancel_requested=lambda: True,
                        )

            self.assertEqual(target.read_text(encoding="utf-8"), "before")

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_caller_cancel_at_commit_gate_prevents_live_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            source = root / "workspace"
            source.mkdir()
            target = source / "file.txt"
            target.write_text("before", encoding="utf-8")
            staging_parent = root / "commit-staging"
            staging_parent.mkdir(mode=0o700)
            original_sandbox = apply_workspace_commit_sandbox
            cancellation_checks = 0

            def mark_gate_ready(
                snapshot, staging_path: Path, file_paths, entry_paths
            ) -> None:
                original_sandbox(
                    snapshot, staging_path, file_paths, entry_paths
                )
                (staging_path / ".commit-ready").touch()

            def cancel_after_gate_ready() -> bool:
                nonlocal cancellation_checks
                cancellation_checks += 1
                return any(
                    (staging / ".commit-ready").exists()
                    for staging in staging_parent.glob("khaos-changes-*")
                )

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "file.txt").write_text("after", encoding="utf-8")
                with _pipe_pair() as (
                    request_read,
                    request_write,
                    response_read,
                    response_write,
                ):
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": "e" * 32,
                            "operation": "workspace.commit",
                            "payload": {},
                        },
                    )
                    with (
                        patch(
                            "khaos.kernel.macos_seatbelt.apply_workspace_commit_sandbox",
                            mark_gate_ready,
                        ),
                        patch(
                            "tempfile.gettempdir",
                            return_value=str(staging_parent),
                        ),
                    ):
                        with self.assertRaisesRegex(
                            WorkspaceCommitError, "cancelled before mutation"
                        ):
                            _serve_fixture_commit(
                                request_read,
                                response_write,
                                snapshot,
                                cancel_requested=cancel_after_gate_ready,
                            )
                    response = receive_frame(response_read)

            self.assertGreaterEqual(cancellation_checks, 2)
            self.assertEqual(target.read_text(encoding="utf-8"), "before")
            self.assertEqual(
                response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "e" * 32,
                    "ok": False,
                    "error": {"code": "commit_rejected"},
                },
            )

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_commit_child_cannot_read_or_write_outside_the_validated_changeset(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            nested = source / "nested"
            nested.mkdir()
            outside_canary = Path(value) / "outside-secret.txt"
            outside_canary.write_text("outside-secret", encoding="utf-8")
            changed = nested / "changed.txt"
            untouched = nested / "untouched.txt"
            deleted = nested / "deleted.txt"
            deleted_symlink = nested / "link-out"
            empty_directory = nested / "empty-to-delete"
            empty_directory.mkdir()
            deleted_symlink.symlink_to(outside_canary)
            changed.write_text("before", encoding="utf-8")
            untouched.write_text("protected", encoding="utf-8")
            deleted.write_text("remove", encoding="utf-8")
            original_sandbox = apply_workspace_commit_sandbox

            with workspace_snapshot(source) as snapshot:
                snapshot_nested = snapshot.path / "nested"
                (snapshot_nested / "changed.txt").write_text(
                    "after", encoding="utf-8"
                )
                added = snapshot_nested / "new" / "deep" / "added.txt"
                added.parent.mkdir(parents=True)
                added.write_text("added", encoding="utf-8")
                (snapshot_nested / "deleted.txt").unlink()
                (snapshot_nested / "link-out").unlink()
                (snapshot_nested / "empty-to-delete").rmdir()
                with _pipe_pair() as (
                    request_read,
                    request_write,
                    response_read,
                    response_write,
                ):
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": "b" * 32,
                            "operation": "workspace.commit",
                            "payload": {},
                        },
                    )

                    def apply_sandbox_and_probe(
                        snapshot_value, staging_path, file_paths, entry_paths
                    ) -> None:
                        original_sandbox(
                            snapshot_value,
                            staging_path,
                            file_paths,
                            entry_paths,
                        )
                        try:
                            changed.chmod(0o777)
                        except OSError as exc:
                            if exc.errno not in (errno.EPERM, errno.EACCES):
                                raise
                        else:
                            raise AssertionError(
                                "Seatbelt allowed a content-only target chmod"
                            )
                        try:
                            descriptor = os.open(changed, os.O_WRONLY)
                        except OSError as exc:
                            if exc.errno not in (errno.EPERM, errno.EACCES):
                                raise
                        else:
                            os.close(descriptor)
                            raise AssertionError(
                                "Seatbelt allowed direct target file writes"
                            )
                        try:
                            untouched.read_text(encoding="utf-8")
                        except OSError as exc:
                            if exc.errno not in (errno.EPERM, errno.EACCES):
                                raise
                        else:
                            raise AssertionError(
                                "Seatbelt allowed reading an untouched workspace file"
                            )
                        try:
                            untouched.stat()
                        except OSError as exc:
                            if exc.errno not in (errno.EPERM, errno.EACCES):
                                raise
                        else:
                            raise AssertionError(
                                "Seatbelt allowed reading untouched file metadata"
                            )
                        try:
                            deleted_symlink.read_text(encoding="utf-8")
                        except OSError as exc:
                            if exc.errno not in (errno.EPERM, errno.EACCES):
                                raise
                        else:
                            raise AssertionError(
                                "Seatbelt allowed reading through a scoped symlink"
                            )
                        try:
                            untouched.write_text("unauthorized", encoding="utf-8")
                        except OSError as exc:
                            if exc.errno not in (errno.EPERM, errno.EACCES):
                                raise
                        else:
                            raise AssertionError(
                                "Seatbelt allowed a write outside the changeset"
                            )

                    with patch(
                        "khaos.kernel.macos_seatbelt.apply_workspace_commit_sandbox",
                        apply_sandbox_and_probe,
                    ):
                        changes = _serve_fixture_commit(
                            request_read, response_write, snapshot
                        )
                    response = receive_frame(response_read)

            self.assertTrue(response["ok"])
            self.assertEqual((changes.added, changes.modified, changes.deleted), (3, 1, 3))
            self.assertEqual(changed.read_text(encoding="utf-8"), "after")
            self.assertEqual(untouched.read_text(encoding="utf-8"), "protected")
            self.assertFalse(deleted.exists())
            self.assertFalse(empty_directory.exists())
            self.assertFalse(deleted_symlink.exists())
            self.assertEqual(outside_canary.read_text(encoding="utf-8"), "outside-secret")
            self.assertEqual(
                (nested / "new" / "deep" / "added.txt").read_text(
                    encoding="utf-8"
                ),
                "added",
            )

    @unittest.skipUnless(
        sys.platform == "darwin" and SANDBOX_EXECUTABLE.is_file(),
        "requires the real macOS Seatbelt backend",
    )
    def test_commit_child_aborts_if_kernel_dies_before_accept(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve()
            source = root / "workspace"
            source.mkdir()
            target = source / "file.txt"
            target.write_text("before", encoding="utf-8")
            staging_parent = root / "commit-staging"
            staging_parent.mkdir(mode=0o700)
            worker_waiting = root / "worker-waiting"
            worker_error = root / "worker-error"
            committer_pid_file = root / "committer-pid"

            with workspace_snapshot(source) as snapshot, _pipe_pair() as (
                request_read,
                request_write,
                response_read,
                response_write,
            ):
                (snapshot.path / "file.txt").write_text("after", encoding="utf-8")
                send_frame(
                    request_write,
                    {
                        "version": PROTOCOL_VERSION,
                        "request_id": "f" * 32,
                        "operation": "workspace.commit",
                        "payload": {},
                    },
                )
                worker_pid = os.fork()
                if worker_pid == 0:
                    try:
                        os.setsid()
                        from khaos.kernel import macos_seatbelt

                        original_fork = os.fork
                        original_write = broker_module._write_all
                        active_staging: dict[str, Path] = {}

                        def tracked_fork() -> int:
                            child_pid = original_fork()
                            if child_pid > 0:
                                committer_pid_file.write_text(
                                    str(child_pid), encoding="ascii"
                                )
                            return child_pid

                        def apply_sandbox_and_track(
                            snapshot_value,
                            staging_path,
                            file_paths,
                            entry_paths,
                        ):
                            apply_workspace_commit_sandbox(
                                snapshot_value,
                                staging_path,
                                file_paths,
                                entry_paths,
                            )
                            active_staging["path"] = staging_path

                        def write_and_track_ready(descriptor, data):
                            original_write(descriptor, data)
                            if data == broker_module._COMMIT_READY:
                                (active_staging["path"] / ".ready").touch()

                        broker_module.os.fork = tracked_fork
                        broker_module._write_all = write_and_track_ready
                        macos_seatbelt.apply_workspace_commit_sandbox = (
                            apply_sandbox_and_track
                        )
                        cancellation_checks = 0

                        def hold_before_accept() -> bool:
                            nonlocal cancellation_checks
                            cancellation_checks += 1
                            if cancellation_checks == 1:
                                return False
                            worker_waiting.write_text("waiting", encoding="ascii")
                            while True:
                                time.sleep(0.01)

                        with patch(
                            "tempfile.gettempdir",
                            return_value=str(staging_parent),
                        ):
                            _serve_fixture_commit(
                                request_read,
                                response_write,
                                snapshot,
                                cancel_requested=hold_before_accept,
                            )
                    except BaseException as exc:
                        worker_error.write_text(
                            f"{type(exc).__name__}: {exc}", encoding="utf-8"
                        )
                        os._exit(1)
                    os._exit(0)

                try:
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        if worker_error.exists():
                            self.fail(worker_error.read_text(encoding="utf-8"))
                        ready_files = list(
                            staging_parent.glob("khaos-changes-*/.ready")
                        )
                        if (
                            worker_waiting.exists()
                            and committer_pid_file.exists()
                            and ready_files
                        ):
                            break
                        time.sleep(0.02)
                    else:
                        self.fail("commit child did not reach its pre-accept gate")

                    committer_pid = int(
                        committer_pid_file.read_text(encoding="ascii")
                    )
                    os.kill(worker_pid, signal.SIGKILL)
                    waited_pid, status = os.waitpid(worker_pid, 0)
                    self.assertEqual(waited_pid, worker_pid)
                    self.assertTrue(os.WIFSIGNALED(status))

                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        process_state = subprocess.run(
                            ("/bin/ps", "-o", "stat=", "-p", str(committer_pid)),
                            capture_output=True,
                            text=True,
                        ).stdout.strip()
                        if not process_state or process_state.startswith("Z"):
                            break
                        time.sleep(0.02)
                    self.assertTrue(
                        not process_state or process_state.startswith("Z"),
                        "commit child survived Kernel death before authorization",
                    )
                    self.assertEqual(target.read_text(encoding="utf-8"), "before")
                    self.assertEqual(list(staging_parent.iterdir()), [])
                finally:
                    try:
                        os.killpg(worker_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        os.waitpid(worker_pid, os.WNOHANG)
                    except ChildProcessError:
                        pass

    def test_commit_rejects_a_late_cancel_then_commits_validated_output(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            target = source / "file.txt"
            target.write_text("before", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "file.txt").write_text("after", encoding="utf-8")
                with _pipe_pair() as (
                    request_read,
                    request_write,
                    response_read,
                    response_write,
                ):
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": "c" * 32,
                            "operation": "process.cancel",
                            "payload": {"process_request_id": "e" * 32},
                        },
                    )
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": "a" * 32,
                            "operation": "workspace.commit",
                            "payload": {},
                        },
                    )
                    changes = _serve_fixture_commit(
                        request_read, response_write, snapshot
                    )
                    cancel_response = receive_frame(response_read)
                    commit_response = receive_frame(response_read)

            self.assertEqual(
                cancel_response,
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": "c" * 32,
                    "ok": False,
                    "error": {"code": "process_not_active"},
                },
            )
            self.assertTrue(commit_response["ok"])
            self.assertEqual(changes.modified, 1)
            self.assertEqual(target.read_text(encoding="utf-8"), "after")

    def test_unsupported_operation_does_not_mutate_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            target = source / "file.txt"
            target.write_text("before", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "file.txt").write_text("runner", encoding="utf-8")
                with _pipe_pair() as (
                    request_read,
                    request_write,
                    response_read,
                    response_write,
                ):
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": "c" * 32,
                            "operation": "process.exec",
                            "payload": {"argv": ["/bin/bash"]},
                        },
                    )
                    with self.assertRaisesRegex(
                        IPCProtocolError, "operation is not supported"
                    ):
                        _serve_fixture_commit(request_read, response_write, snapshot)
                    response = receive_frame(response_read)

            self.assertEqual(response["error"], {"code": "operation_not_supported"})
            self.assertEqual(target.read_text(encoding="utf-8"), "before")

    def test_rejected_changeset_returns_a_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            outside = Path(value) / "outside.txt"
            outside.write_text("protected", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "escape").symlink_to(outside)
                with _pipe_pair() as (
                    request_read,
                    request_write,
                    response_read,
                    response_write,
                ):
                    send_frame(
                        request_write,
                        {
                            "version": PROTOCOL_VERSION,
                            "request_id": "d" * 32,
                            "operation": "workspace.commit",
                            "payload": {},
                        },
                    )
                    with self.assertRaises(WorkspaceCommitError):
                        _serve_fixture_commit(request_read, response_write, snapshot)
                    response = receive_frame(response_read)

            self.assertEqual(response["error"], {"code": "commit_rejected"})
            self.assertEqual(outside.read_text(encoding="utf-8"), "protected")
            self.assertFalse((source / "escape").exists())


@contextmanager
def _pipe_pair() -> Iterator[tuple[int, int, int, int]]:
    request_read, request_write = os.pipe()
    response_read, response_write = os.pipe()
    try:
        yield request_read, request_write, response_read, response_write
    finally:
        for descriptor in (request_read, request_write, response_read, response_write):
            os.close(descriptor)


@contextmanager
def _deny_khaos_temp_unlink(*, fail_once: bool = False) -> Iterator[None]:
    real_unlink = os.unlink
    failed = False

    def fail_temporary_unlink(path, *args, **kwargs) -> None:
        nonlocal failed
        if (
            isinstance(path, str)
            and path.startswith(".khaos-")
            and path.endswith(".tmp")
            and (not fail_once or not failed)
        ):
            failed = True
            raise OSError(errno.EACCES, "injected temp cleanup failure")
        real_unlink(path, *args, **kwargs)

    supported_functions = os.supports_dir_fd | {fail_temporary_unlink}
    with (
        patch.object(os, "unlink", fail_temporary_unlink),
        patch.object(os, "supports_dir_fd", supported_functions),
    ):
        yield


if __name__ == "__main__":
    unittest.main()
