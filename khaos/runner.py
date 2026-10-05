"""Small untrusted Runner entrypoint for the Seed coding operation."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .ipc import (
    PROTOCOL_VERSION,
    answer_ping,
    is_valid_token,
    receive_frame,
    validate_runner_source,
)
from .kernel.peer_identity import verify_local_parent_pid


_START_FIELDS = {"version", "request_id", "operation", "payload"}


def main() -> int:
    """Run one untrusted plugin entrypoint inside the isolated Runner."""
    if len(sys.argv) != 2:
        return 2
    verify_local_parent_pid(Path(sys.argv[1]), os.getppid())
    answer_ping()
    request = receive_frame(0, timeout_seconds=5)
    request_id = request.get("request_id")
    payload = request.get("payload")
    if (
        set(request) != _START_FIELDS
        or type(request.get("version")) is not int
        or request["version"] != PROTOCOL_VERSION
        or not is_valid_token(request_id)
        or request.get("operation") != "plugin.start"
        or type(payload) is not dict
        or set(payload) != {"source"}
    ):
        return 2

    source = validate_runner_source(payload["source"])
    namespace: dict[str, object] = {"__name__": "__khaos_plugin__"}
    code = compile(source, "<untrusted-plugin>", "exec", dont_inherit=True)
    exec(code, namespace, namespace)
    entrypoint = namespace.get("run")
    if not callable(entrypoint):
        return 2
    result = entrypoint()
    if result is None:
        return 0
    return result if type(result) is int and 0 <= result <= 255 else 2

if __name__ == "__main__":
    sys.exit(main())
