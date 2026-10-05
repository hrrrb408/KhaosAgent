from __future__ import annotations

import base64
import errno
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from khaos.ipc import (
    PROTOCOL_VERSION,
    is_valid_token,
    ping_peer,
    receive_frame,
    send_frame,
    validate_runner_source,
)
from khaos.kernel.peer_identity import accept_local_peer_pid, local_peer_pid_listener


def _plugin_source() -> str:
    snapshot_path = os.environ["KHAOS_PROBE_SNAPSHOT_PATH"]
    sibling_path = os.environ["KHAOS_PROBE_SIBLING_PATH"]
    outside_path = os.environ["KHAOS_PROBE_OUTSIDE_PATH"]
    network_port = int(os.environ["KHAOS_PROBE_NETWORK_PORT"])
    return validate_runner_source(
        f"""\
import errno
import socket
import sys
from pathlib import Path
from khaos.ipc import IPCProtocolError
from khaos.runner_sdk import fs_read

snapshot = {snapshot_path!r}
sibling = {sibling_path!r}
outside = {outside_path!r}
network_port = {network_port}

def must_be_denied(action, label):
    try:
        action()
    except OSError as error:
        if error.errno not in (errno.EPERM, errno.EACCES):
            raise
        print(f"{{label}}=denied", file=sys.stderr)
        return
    raise SystemExit(f"{{label}}=allowed")

def run():
    must_be_denied(lambda: Path(snapshot).read_text(), "plugin-snapshot-read")
    must_be_denied(lambda: Path(sibling).read_text(), "plugin-sibling-read")
    must_be_denied(lambda: Path(outside).read_text(), "plugin-outside-read")
    must_be_denied(
        lambda: Path(snapshot).with_name("plugin-write.txt").write_text("blocked"),
        "plugin-snapshot-write",
    )
    must_be_denied(
        lambda: Path(outside + ".plugin-write").write_text("blocked"),
        "plugin-outside-write",
    )
    try:
        socket.create_connection(("127.0.0.1", network_port), timeout=1)
    except OSError as error:
        if error.errno not in (errno.EPERM, errno.EACCES):
            raise
        print("plugin-network=denied", file=sys.stderr)
    else:
        raise SystemExit("plugin-network=allowed")

    data = fs_read("workspace-note.txt")
    if data != b"broker-mediated":
        raise SystemExit("plugin-fs-read=invalid")
    print("plugin-fs-read=broker-mediated", file=sys.stderr)
    try:
        fs_read("../outside-secret.txt")
    except IPCProtocolError:
        print("plugin-fs-escape=denied", file=sys.stderr)
    else:
        raise SystemExit("plugin-fs-escape=allowed")
    return 0
"""
    )


def _send_filesystem_reply(process: subprocess.Popen[bytes], request: dict) -> None:
    if process.stdin is None or set(request) != {
        "version",
        "request_id",
        "operation",
        "payload",
    }:
        raise RuntimeError("Runner filesystem request envelope is invalid")
    request_id = request.get("request_id")
    payload = request.get("payload")
    if (
        type(request.get("version")) is not int
        or request["version"] != PROTOCOL_VERSION
        or not is_valid_token(request_id)
        or request.get("operation") != "fs.read"
        or type(payload) is not dict
        or set(payload) != {"path"}
        or type(payload.get("path")) is not str
    ):
        raise RuntimeError("Runner filesystem request schema is invalid")

    if payload["path"] == "workspace-note.txt":
        response = {
            "version": PROTOCOL_VERSION,
            "request_id": request_id,
            "ok": True,
            "result": {"data_base64": base64.b64encode(b"broker-mediated").decode()},
        }
    else:
        response = {
            "version": PROTOCOL_VERSION,
            "request_id": request_id,
            "ok": False,
            "error": {"code": "path_not_readable"},
        }
    send_frame(process.stdin.fileno(), response, timeout_seconds=3)


def main() -> int:
    package_root = Path(__file__).resolve().parent
    bootstrap = (
        "import sys\n"
        f"sys.path.insert(0, {str(package_root)!r})\n"
        "from khaos.runner import main\n"
        "raise SystemExit(main())\n"
    )
    runner_environment = {
        "PATH": "/usr/bin:/bin",
        "PYTHONHOME": os.environ["PYTHONHOME"],
        "PYTHONDONTWRITEBYTECODE": "1",
        "TMPDIR": os.environ["TMPDIR"],
    }
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix="k-", dir=runner_environment["TMPDIR"]) as scratch:
            with local_peer_pid_listener(Path(scratch)) as (listener, socket_path):
                process = subprocess.Popen(
                    (
                        sys.executable,
                        "-I",
                        "-S",
                        "-c",
                        bootstrap,
                        str(socket_path),
                    ),
                    cwd="/",
                    env=runner_environment,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    close_fds=True,
                    start_new_session=True,
                )
                accept_local_peer_pid(listener, process.pid)
            if process.stdin is None or process.stdout is None:
                raise RuntimeError("Runner IPC pipes are unavailable")
            ping_peer(process.stdout.fileno(), process.stdin.fileno(), timeout_seconds=3)
            send_frame(
                process.stdin.fileno(),
                {
                    "version": PROTOCOL_VERSION,
                    "request_id": os.urandom(16).hex(),
                    "operation": "plugin.start",
                    "payload": {"source": _plugin_source()},
                },
                timeout_seconds=3,
            )
            for _ in range(2):
                _send_filesystem_reply(
                    process, receive_frame(process.stdout.fileno(), timeout_seconds=5)
                )
            process.stdin.close()
            process.wait(timeout=5)
            stdout = process.stdout.read()
            stderr = process.stderr.read() if process.stderr is not None else b""
            if process.returncode != 0 or stdout:
                raise RuntimeError(
                    f"Runner exit={process.returncode}; stdout={stdout!r}; "
                    f"stderr={stderr.decode(errors='replace')}"
                )
            print("khaos-runner-exit=0")
            sys.stdout.write(stderr.decode("utf-8", errors="strict"))
            return 0
    finally:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
