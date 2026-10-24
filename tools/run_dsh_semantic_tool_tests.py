#!/usr/bin/env python3
"""Run Khaos semantic-tool specs against the exact pinned DSH test harness."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from run_dsh_signed_runtime_probe import PINNED_DSH_SHA, PINNED_NODE_VERSION, output  # noqa: E402


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: run_dsh_semantic_tool_tests.py DSH_SOURCE NODE", file=sys.stderr)
        return 2
    dsh_source = Path(sys.argv[1]).resolve(strict=True)
    node = Path(sys.argv[2]).resolve(strict=True)
    if output(["git", "rev-parse", "HEAD"], cwd=dsh_source) != PINNED_DSH_SHA:
        print(f"DSH must be pinned at {PINNED_DSH_SHA}", file=sys.stderr)
        return 2
    if output([str(node), "--version"]) != PINNED_NODE_VERSION:
        print(f"Node must be {PINNED_NODE_VERSION}", file=sys.stderr)
        return 2
    if not (dsh_source / "node_modules/.bin/vitest").is_file():
        print("install the pinned DSH workspace dependencies first", file=sys.stderr)
        return 2

    source = ROOT / "experiments/dsh-feasibility"
    upstream_mock = dsh_source / "packages/core/agent-loop/tests/mock-adapter.ts"
    if not upstream_mock.is_file():
        print("pinned DSH MockAdapter source is unavailable", file=sys.stderr)
        return 2
    tests_root = dsh_source / "packages/core/agent-loop/tests"
    staging = Path(tempfile.mkdtemp(prefix="khaos-phase32-semantic-", dir=tests_root))
    try:
        for name in (
            "dsh-agent-telemetry.ts",
            "dsh-tool-result.ts",
            "dsh-semantic-fixture.ts",
            "khaos-local-model.ts",
            "khaos-model-bridge.ts",
            "khaos-capability-adapter.ts",
            "khaos-semantic-tools.ts",
            "khaos-semantic-tools.spec.ts",
        ):
            shutil.copy2(source / name, staging / name)
        spec = staging / "khaos-semantic-tools.spec.ts"
        result = subprocess.run(
            [
                str(dsh_source / "node_modules/.bin/vitest"),
                "run",
                "--reporter=verbose",
                str(spec),
            ],
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
