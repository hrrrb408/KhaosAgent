#!/usr/bin/env python3
"""Run the Khaos adapter against a pinned, isolated DeepSeek Harness checkout."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile


PINNED_DSH_SHA = "687f282e8625c6b8d11ff58211a90524be2e4317"
PINNED_PNPM = "11.28.5"


def checked_output(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.stdout.strip()


def sandbox_literal(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "\\\\").replace('"', '\\"')
    return f'(subpath "{value}")'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsh-source", type=Path, required=True, help="clean DSH checkout at the pinned SHA")
    parser.add_argument("--pnpm", default="pnpm", help="pnpm 11.28.5 executable")
    args = parser.parse_args()

    if platform.system() != "Darwin":
        parser.error("this feasibility probe requires macOS sandbox-exec")

    source = args.dsh_source.resolve(strict=True)
    if not (source / "package.json").is_file() or not (source / "node_modules").is_dir():
        parser.error("DSH_SOURCE must contain the installed pinned DSH checkout")
    try:
        source.relative_to(Path("/Users"))
    except ValueError:
        pass
    else:
        parser.error("for the test sandbox, clone DSH outside /Users (for example under /tmp)")
    head = checked_output(["git", "rev-parse", "HEAD"], cwd=source)
    if head != PINNED_DSH_SHA:
        parser.error(f"DSH checkout SHA mismatch: expected {PINNED_DSH_SHA}, got {head}")
    status = checked_output(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=source)
    if status:
        parser.error("DSH checkout must be clean before the temporary Khaos probe is staged")

    pnpm = shutil.which(args.pnpm)
    if pnpm is None:
        parser.error(f"pnpm executable not found: {args.pnpm}")
    pnpm_version = checked_output([pnpm, "--version"], cwd=source)
    if pnpm_version != PINNED_PNPM:
        parser.error(f"pnpm version mismatch: expected {PINNED_PNPM}, got {pnpm_version}")

    node = shutil.which("node")
    if node is None:
        parser.error("Node.js is not available on PATH")
    node_version = checked_output([node, "--version"], cwd=source)
    version_parts = tuple(int(part) for part in node_version.lstrip("v").split(".")[:2])
    if not ((version_parts[0] == 22 and version_parts[1] >= 19) or version_parts[0] >= 24):
        parser.error(f"DSH requires Node.js 22.19 or newer; found {node_version}")

    tests = source / "packages/core/agent-loop/tests"
    temp_tests = Path(tempfile.mkdtemp(prefix="khaos-feasibility-", dir=tests))
    temp_root = Path(tempfile.mkdtemp(prefix=".khaos-feasibility-runtime-", dir=source))
    profile_descriptor, profile_name = tempfile.mkstemp(prefix=".khaos-feasibility-", suffix=".sb", dir=source)
    os.close(profile_descriptor)
    sandbox_profile = Path(profile_name)
    try:
        repository_root = Path(__file__).resolve().parents[1]
        probe = repository_root / "experiments/dsh-feasibility"
        shutil.copy2(probe / "khaos-capability-adapter.ts", temp_tests / "khaos-capability-adapter.ts")
        shutil.copy2(probe / "dsh-probe.spec.ts", temp_tests / "dsh-probe.spec.ts")

        # The probe executes untrusted upstream JavaScript. Keep its filesystem
        # writes inside the disposable DSH checkout, deny user files and TCP,
        # and retain only local Unix sockets needed by the test runner.
        sandbox_profile.write_text(
            "\n".join(
                [
                    "(version 1)",
                    "(allow default)",
                    '(deny file-read* (subpath "/Users"))',
                    f"(allow file-read* {sandbox_literal(source)})",
                    "(deny file-write*",
                    "  (require-all",
                    f"    (require-not {sandbox_literal(source)})",
                    '    (require-not (literal "/dev/null"))))',
                    "(deny network* (require-not (local unix-socket)))",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        temp_env = {
            "PATH": os.pathsep.join(
                [
                    str(Path(pnpm).parent),
                    str(Path(node).parent),
                    str(source / "node_modules/.bin"),
                    "/usr/bin",
                    "/bin",
                    "/usr/sbin",
                    "/sbin",
                ]
            ),
            "HOME": str(temp_root),
            "TMPDIR": str(temp_root),
            "XDG_CACHE_HOME": str(temp_root / "cache"),
            "NODE_COMPILE_CACHE": str(temp_root / "node-compile-cache"),
            "npm_config_cache": str(temp_root / "npm-cache"),
            "npm_config_userconfig": "/dev/null",
            "npm_config_globalconfig": "/dev/null",
        }
        (temp_root / "cache").mkdir(exist_ok=True)
        command = [
            "/usr/bin/sandbox-exec",
            "-f",
            str(sandbox_profile),
            pnpm,
            "exec",
            "vitest",
            "run",
            "--reporter=dot",
            str((temp_tests / "dsh-probe.spec.ts").relative_to(source)),
        ]
        print(f"DSH_SHA={head}")
        print(f"Node.js={node_version}")
        print(f"pnpm={pnpm_version}")
        print("Test sandbox: no /Users reads, no external network, writes confined to DSH checkout")
        print("Command: pnpm exec vitest run --reporter=dot <temporary Khaos probe>")
        result = subprocess.run(command, cwd=source, env=temp_env, text=True)
        return result.returncode
    finally:
        shutil.rmtree(temp_tests, ignore_errors=True)
        shutil.rmtree(temp_root, ignore_errors=True)
        sandbox_profile.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
