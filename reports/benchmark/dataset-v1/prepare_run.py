#!/usr/bin/env python3
"""Create a clean, isolated model attempt from the frozen dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


DATASET = Path(__file__).resolve().parent


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, choices=("local", "api"))
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--attempt", default="attempt-01")
    parser.add_argument("--workspace-root", type=Path)
    args = parser.parse_args()

    manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
    tasks = {task["id"]: task for task in manifest["tasks"]}
    if args.task_id not in tasks:
        parser.error(f"unknown task id: {args.task_id}")
    task = tasks[args.task_id]
    run_dir = DATASET / "runs" / args.model / args.task_id / args.attempt
    if run_dir.exists():
        parser.error(f"refusing to overwrite existing attempt: {run_dir}")
    run_dir.mkdir(parents=True)

    workspace = (
        args.workspace_root.expanduser().absolute() / args.model / args.task_id / args.attempt / "workspace"
        if args.workspace_root is not None
        else run_dir / "workspace"
    )
    workspace.parent.mkdir(parents=True, exist_ok=True)
    frozen = DATASET / task["workspace"]
    subprocess.run(
        ["git", "clone", "--no-hardlinks", "--no-local", str(frozen), str(workspace)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(workspace), "remote", "remove", "origin"],
        check=True,
        capture_output=True,
        text=True,
    )
    baseline = git("-C", str(workspace), "rev-parse", "HEAD")
    if baseline != task["frozen_baseline_commit"]:
        shutil.rmtree(run_dir)
        raise SystemExit(
            f"frozen baseline mismatch: expected {task['frozen_baseline_commit']}, got {baseline}"
        )
    if git("-C", str(workspace), "status", "--porcelain"):
        shutil.rmtree(run_dir)
        raise SystemExit("fresh model workspace is not clean")

    prompt = task["prompt"]
    prompt_path = run_dir / "task-prompt.txt"
    prompt_path.write_text(prompt + "\n", encoding="utf-8")
    (run_dir / "launcher.stdout").touch()
    (run_dir / "launcher.stderr").touch()
    run = {
        "format": "khaos-coding-reliability-attempt-v1",
        "status": "prepared",
        "model": args.model,
        "task_id": args.task_id,
        "attempt": args.attempt,
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": task["source_commit"],
        "source_commit_url": task["source_commit_url"],
        "frozen_baseline_commit": baseline,
        "prompt_sha256": hashlib.sha256(prompt_path.read_bytes()).hexdigest(),
        "workspace": str(workspace),
        "workspace_clean_at_start": True,
        "tools_per_task_limit": 8,
        "runner_cumulative_seconds_limit": 180,
        "runner_single_call_seconds_limit": 30,
        "single_result_bytes_limit": 4096,
        "cumulative_result_bytes_limit": 32768,
        "approval_policy": "review each displayed argv and exact scope; approve only task-confined operations",
        "public_test_commands": task["tests"],
        "grading_note": task.get("grading_note"),
        "started_at_utc": None,
        "completed_at_utc": None,
        "launcher_exit_code": None,
        "parent_test_results": [],
        "hidden_test_results": [],
        "notes": [],
    }
    (run_dir / "run.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"run_dir": str(run_dir), "workspace": str(workspace), "prompt": str(prompt_path), "baseline": baseline}, ensure_ascii=False))


if __name__ == "__main__":
    main()
