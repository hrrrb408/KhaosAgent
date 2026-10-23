#!/usr/bin/env python3
"""Run the experimental DSH adapter tests with the pinned DSH checkout and Node runtime."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from run_dsh_signed_runtime_probe import PINNED_DSH_SHA, PINNED_NODE_VERSION, output  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsh-source", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    args = parser.parse_args()
    dsh_source = args.dsh_source.resolve(strict=True)
    node = args.node.resolve(strict=True)
    if output(["git", "rev-parse", "HEAD"], cwd=dsh_source) != PINNED_DSH_SHA:
        parser.error(f"DSH must be pinned at {PINNED_DSH_SHA}")
    if output([str(node), "--version"]) != PINNED_NODE_VERSION:
        parser.error(f"Node must be {PINNED_NODE_VERSION}")
    if not (dsh_source / "node_modules/tsx/package.json").is_file():
        parser.error("run pnpm install --frozen-lockfile in the pinned DSH checkout first")

    source = ROOT / "experiments/dsh-feasibility"
    staging_root = dsh_source / ".tmp"
    staging_root.mkdir(exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="khaos-phase3-llm-tests-", dir=staging_root))
    try:
        shutil.copy2(source / "khaos-model-bridge.ts", staging / "khaos-model-bridge.ts")
        shutil.copy2(source / "khaos-local-model.ts", staging / "khaos-local-model.ts")
        shutil.copy2(source / "dsh-agent-telemetry.ts", staging / "dsh-agent-telemetry.ts")
        shutil.copy2(source / "khaos-model-bridge.test.ts", staging / "khaos-model-bridge.test.ts")
        result = subprocess.run(
            [str(node), "--import", "tsx", "--test", str(staging / "khaos-model-bridge.test.ts")],
            cwd=dsh_source,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        print(result.stdout, end="")
        return result.returncode
    finally:
        shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
