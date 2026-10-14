#!/usr/bin/env python3
"""Grade a completed model attempt in a clean copy with hidden tests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


DATASET = Path(__file__).resolve().parent


def git(*args: str, cwd: Path | None = None, timeout: int = 60) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    ).stdout


def checked_repo_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in (".", "..") for part in path.parts):
        raise ValueError(f"unsafe candidate path: {value!r}")
    if path.parts[0] == ".git":
        raise ValueError("model attempt must not change grader Git metadata")
    return path


def copy_regular_file(source_root: Path, destination_root: Path, relative: PurePosixPath) -> None:
    source = source_root.joinpath(*relative.parts)
    destination = destination_root.joinpath(*relative.parts)
    current = source_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"refusing to grade a symlinked candidate path: {relative}")
    if not source.exists():
        if destination.is_symlink():
            raise ValueError(f"refusing to remove a symlinked grader path: {relative}")
        if destination.exists():
            destination.unlink()
        return
    if not source.is_file():
        raise ValueError(f"candidate path is not a regular file: {relative}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    current = destination_root
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"grader path traverses a symlink: {relative}")
    shutil.copy2(source, destination)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, choices=("local", "api"))
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--attempt", default="attempt-01")
    parser.add_argument("--test-timeout-seconds", type=int, default=1200)
    args = parser.parse_args()

    manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
    tasks = {task["id"]: task for task in manifest["tasks"]}
    if args.task_id not in tasks:
        parser.error(f"unknown task id: {args.task_id}")
    task = tasks[args.task_id]
    run_dir = DATASET / "runs" / args.model / args.task_id / args.attempt
    run_path = run_dir / "run.json"
    if not run_path.is_file():
        parser.error(f"attempt record is missing: {run_path}")
    run = json.loads(run_path.read_text(encoding="utf-8"))
    if run.get("status") == "running":
        parser.error("refusing to grade an unfinished Agent attempt")
    if run.get("hidden_test_results"):
        parser.error("refusing to overwrite existing grading results")
    workspace = Path(run["workspace"]).expanduser().absolute()
    if not workspace.is_dir():
        parser.error(f"model workspace is missing: {workspace}")

    grader = run_dir / "grader-copy"
    if grader.exists():
        parser.error(f"refusing to overwrite grader copy: {grader}")
    frozen = DATASET / task["workspace"]
    subprocess.run(
        ["git", "clone", "--no-hardlinks", "--no-local", str(frozen), str(grader)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(grader), "remote", "remove", "origin"],
        check=True,
        capture_output=True,
        text=True,
    )
    baseline = git("-C", str(grader), "rev-parse", "HEAD").strip()
    if baseline != task["frozen_baseline_commit"]:
        raise SystemExit("grader baseline does not match the frozen task")

    changed = {
        item
        for item in git("-C", str(workspace), "diff", "HEAD", "--name-only", "-z").split("\0")
        if item
    }
    untracked = {
        item
        for item in git(
            "-C", str(workspace), "ls-files", "--others", "--exclude-standard", "-z"
        ).split("\0")
        if item
    }
    candidate_paths = sorted(changed | untracked)
    copied_paths: list[str] = []
    excluded_test_paths: list[str] = []
    for value in candidate_paths:
        relative = checked_repo_path(value)
        if relative.parts[0] == "tests":
            excluded_test_paths.append(value)
            continue
        copy_regular_file(workspace, grader, relative)
        copied_paths.append(value)

    hidden_patch = DATASET / "private" / args.task_id / "hidden-tests.patch"
    hidden_patch_digest = hashlib.sha256(hidden_patch.read_bytes()).hexdigest()
    expected_digest = task.get("hidden_tests_patch_sha256")
    if expected_digest and hidden_patch_digest != expected_digest:
        raise SystemExit("hidden test patch hash does not match the frozen manifest")
    hidden_patch_applied = hidden_patch.stat().st_size > 0
    if hidden_patch_applied:
        subprocess.run(
            ["git", "-C", str(grader), "apply", str(hidden_patch)],
            check=True,
            capture_output=True,
            text=True,
        )

    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("KHAOS_RUN_PRODUCT_")
        and not key.startswith("KHAOS_BIGMODEL_")
        and key != "KHAOS_REAL_MODEL_APP"
    }
    tests: list[dict[str, object]] = []
    for index, command in enumerate(task["tests"], start=1):
        started = datetime.now(timezone.utc)
        try:
            result = subprocess.run(
                command,
                cwd=grader,
                env=environment,
                capture_output=True,
                text=True,
                timeout=args.test_timeout_seconds,
            )
            returncode: int | None = result.returncode
            stdout, stderr = result.stdout, result.stderr
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            returncode = None
            stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            timed_out = True
        (run_dir / f"grader-test-{index:02d}.stdout").write_text(stdout, encoding="utf-8")
        (run_dir / f"grader-test-{index:02d}.stderr").write_text(stderr, encoding="utf-8")
        tests.append(
            {
                "argv": command,
                "started_at_utc": started.isoformat(),
                "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                "return_code": returncode,
                "timed_out": timed_out,
                "stdout_path": str(run_dir / f"grader-test-{index:02d}.stdout"),
                "stderr_path": str(run_dir / f"grader-test-{index:02d}.stderr"),
            }
        )

    grade = {
        "format": "khaos-coding-reliability-grade-v1",
        "graded_at_utc": datetime.now(timezone.utc).isoformat(),
        "task_id": args.task_id,
        "attempt": args.attempt,
        "frozen_baseline_commit": baseline,
        "candidate_paths_copied": copied_paths,
        "candidate_test_edits_excluded": excluded_test_paths,
        "hidden_test_patch_sha256": hidden_patch_digest,
        "hidden_test_patch_applied": hidden_patch_applied,
        "tests": tests,
        "all_test_commands_passed": bool(tests) and all(
            result["return_code"] == 0 and not result["timed_out"] for result in tests
        ),
        "grading_note": task.get("grading_note"),
        "test_timeout_seconds": args.test_timeout_seconds,
    }
    grade_path = run_dir / "grade.json"
    grade_path.write_text(json.dumps(grade, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    run["hidden_test_results"] = tests
    run["grade_path"] = str(grade_path)
    run["grade_all_test_commands_passed"] = grade["all_test_commands_passed"]
    run["candidate_paths_copied_to_grader"] = copied_paths
    run["candidate_test_edits_excluded_from_grader"] = excluded_test_paths
    run["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    run_path.write_text(json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"grade_path": str(grade_path), "all_test_commands_passed": grade["all_test_commands_passed"], "tests": tests}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
