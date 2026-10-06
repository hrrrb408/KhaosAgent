"""Small untrusted Runner entrypoint for the Seed coding operation."""

from __future__ import annotations

import os
import json
import sys
from pathlib import Path

from .ipc import (
    MAX_PLUGIN_INPUT_BYTES,
    MAX_PLUGIN_INPUT_NESTING,
    PROTOCOL_VERSION,
    answer_ping,
    is_valid_token,
    receive_frame,
    validate_runner_source,
    _json_nesting_within_limit,
)
from .runner_sdk import plugin_output
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
        or set(payload) not in ({"source"}, {"source", "input"})
    ):
        return 2

    source = validate_runner_source(payload["source"])
    namespace: dict[str, object] = {"__name__": "__khaos_plugin__"}
    code = compile(source, "<untrusted-plugin>", "exec", dont_inherit=True)
    exec(code, namespace, namespace)
    entrypoint = namespace.get("run")
    if not callable(entrypoint):
        return 2
    if "input" in payload:
        try:
            encoded_input = json.dumps(
                payload["input"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8", errors="strict")
        except (TypeError, ValueError, UnicodeEncodeError):
            return 2
        if (
            len(encoded_input) > MAX_PLUGIN_INPUT_BYTES
            or not _json_nesting_within_limit(
                encoded_input,
                maximum_depth=MAX_PLUGIN_INPUT_NESTING,
            )
        ):
            return 2
        result = entrypoint(payload["input"])
        plugin_output(result)
        return 0
    result = entrypoint()
    if result is None:
        return 0
    return result if type(result) is int and 0 <= result <= 255 else 2

if __name__ == "__main__":
    sys.exit(main())
