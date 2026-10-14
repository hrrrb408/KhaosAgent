#!/usr/bin/env python3
"""Timestamp bounded Launcher/Agent diagnostic markers without copying task text."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdout", required=True, type=Path)
    parser.add_argument("--stderr", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--poll-seconds", type=float, default=0.2)
    args = parser.parse_args()
    output = args.output.expanduser().absolute()
    if output.exists():
        parser.error(f"refusing to overwrite event record: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    offsets = {args.stdout: 0, args.stderr: 0}
    pending = {args.stdout: b"", args.stderr: b""}
    task_record_seen = False
    with output.open("x", encoding="utf-8") as stream:
        while True:
            for path in (args.stderr, args.stdout):
                if not path.exists():
                    continue
                with path.open("rb") as source:
                    source.seek(offsets[path])
                    chunk = source.read()
                    offsets[path] = source.tell()
                combined = pending[path] + chunk
                complete = combined.splitlines(keepends=True)
                if complete and not complete[-1].endswith((b"\n", b"\r")):
                    pending[path] = complete.pop()
                else:
                    pending[path] = b""
                for raw_line in complete:
                        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                        if line.startswith("agent-session="):
                            event = line.removeprefix("agent-session=")
                        elif line.startswith("Launcher task status:"):
                            event = "task_status"
                        elif line.startswith("Launcher task record:"):
                            event = "task_record"
                            task_record_seen = True
                        else:
                            continue
                        stream.write(
                            json.dumps(
                                {
                                    "observed_at_utc": datetime.now(timezone.utc).isoformat(),
                                    "event": event,
                                },
                                sort_keys=True,
                            )
                            + "\n"
                        )
                        stream.flush()
            if task_record_seen:
                break
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
