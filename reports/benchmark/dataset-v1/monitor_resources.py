#!/usr/bin/env python3
"""Sample signed Khaos local-run process RSS/CPU and system swap."""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--app-marker", required=True)
    parser.add_argument("--interval-seconds", type=float, default=5)
    parser.add_argument("--stop-after-exit-seconds", type=float, default=15)
    args = parser.parse_args()
    output = args.output.expanduser().absolute()
    if output.exists():
        parser.error(f"refusing to overwrite resource samples: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    seen = False
    exited_at: float | None = None
    swap_pattern = re.compile(r"used =\s*([0-9.]+)M")

    with output.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["sample_utc", "process_role", "pid", "cpu_percent", "rss_kib", "elapsed", "swap_used_mib"]
        )
        while True:
            listing = subprocess.run(
                ["ps", "-axo", "pid=,ppid=,pcpu=,rss=,etime=,command="],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            rows: list[tuple[int, str, str, str, str, str]] = []
            for line in listing.splitlines():
                fields = line.strip().split(maxsplit=5)
                if len(fields) != 6:
                    continue
                pid, _ppid, cpu, rss, elapsed, command = fields
                # The signed app path contains spaces; test the command prefix
                # instead of splitting it into whitespace-delimited tokens.
                if int(pid) == os.getpid() or not command.startswith(args.app_marker):
                    continue
                if "/KhaosLlama/llama-cli " in command:
                    role = "llama-cli"
                elif "/KhaosAgentHost.xpc/Contents/MacOS/KhaosAgentHost" in command:
                    role = "agenthost"
                elif "/KernelProduction.xpc/Contents/MacOS/KernelProduction" in command:
                    role = "kernel-xpc"
                elif "/KernelSnapshotBroker.xpc/Contents/MacOS/KernelSnapshotBroker" in command:
                    role = "snapshot-broker"
                elif "/Contents/MacOS/KhaosSeed" in command:
                    role = "launcher"
                elif "workspace_xpc_bridge" in command:
                    role = "kernel-bridge"
                elif "khaos.kernel.worker" in command:
                    role = "kernel-worker"
                else:
                    role = "other-product-process"
                rows.append((int(pid), role, cpu, rss, elapsed, command))

            swap_result = subprocess.run(
                ["sysctl", "vm.swapusage"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            match = swap_pattern.search(swap_result)
            swap_used = match.group(1) if match else ""
            now = datetime.now(timezone.utc).isoformat()
            for pid, role, cpu, rss, elapsed, _command in rows:
                writer.writerow([now, role, pid, cpu, rss, elapsed, swap_used])
            if rows:
                stream.flush()
                seen = True
                exited_at = None
            elif seen:
                exited_at = exited_at or time.monotonic()
                if time.monotonic() - exited_at >= args.stop_after_exit_seconds:
                    break
            time.sleep(args.interval_seconds)


if __name__ == "__main__":
    main()
