#!/usr/bin/env python3
"""Check whether each frozen task's tests reject the untouched baseline."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DATASET = Path(__file__).resolve().parents[1]


def run(command: list[str], *, cwd: Path | None = None, timeout: int = 1200) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def clone(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = run(["git", "clone", "--no-hardlinks", "--no-local", str(source), str(destination)])
    if result.returncode:
        raise RuntimeError(result.stderr or f"git clone failed: {source}")
    result = run(["git", "remote", "remove", "origin"], cwd=destination)
    if result.returncode:
        raise RuntimeError(result.stderr or f"could not remove origin: {destination}")


def apply_if_missing(repo: Path, patch: Path) -> str:
    if not patch.exists() or patch.stat().st_size == 0:
        return "empty"
    reverse = run(["git", "apply", "--reverse", "--check", str(patch)], cwd=repo)
    if reverse.returncode == 0:
        return "already_in_gold_patch"
    check = run(["git", "apply", "--check", str(patch)], cwd=repo)
    if check.returncode:
        raise RuntimeError(f"patch does not apply to {repo}: {check.stderr}")
    applied = run(["git", "apply", str(patch)], cwd=repo)
    if applied.returncode:
        raise RuntimeError(f"could not apply {patch}: {applied.stderr}")
    return "applied"


def safe_test_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("KHAOS_RUN_PRODUCT_")
        and not key.startswith("KHAOS_BIGMODEL_")
        and key not in {"KHAOS_REAL_MODEL_APP", "KHAOS_BIGMODEL_API_KEY"}
    }


def grade_variant(
    repo: Path,
    commands: list[list[str]],
    log_dir: Path,
    timeout: int,
) -> tuple[list[dict[str, Any]], bool]:
    log_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for index, command in enumerate(commands, start=1):
        started = datetime.now(timezone.utc)
        t0 = time.monotonic()
        try:
            result = subprocess.run(
                command,
                cwd=repo,
                env=safe_test_environment(),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return_code: int | None = result.returncode
            stdout, stderr = result.stdout, result.stderr
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            return_code = None
            stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            timed_out = True
        stdout_path = log_dir / f"test-{index:02d}.stdout"
        stderr_path = log_dir / f"test-{index:02d}.stderr"
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        results.append(
            {
                "argv": command,
                "started_at_utc": started.isoformat(),
                "elapsed_seconds": round(time.monotonic() - t0, 3),
                "return_code": return_code,
                "timed_out": timed_out,
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
            }
        )
    passed = bool(results) and all(item["return_code"] == 0 and not item["timed_out"] for item in results)
    return results, passed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--output", type=Path, default=DATASET / "validation" / "baseline-discrimination.json")
    args = parser.parse_args()
    output = args.output.expanduser().absolute()
    if output.exists():
        parser.error(f"refusing to overwrite audit report: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
    report: dict[str, Any] = {
        "format": "khaos-benchmark-baseline-discrimination-v1",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_manifest_sha256": __import__("hashlib").sha256((DATASET / "manifest.json").read_bytes()).hexdigest(),
        "timeout_seconds_per_test": args.timeout_seconds,
        "tasks": [],
    }
    with tempfile.TemporaryDirectory(prefix="khaos-dataset-audit-") as temp_root:
        temp = Path(temp_root)
        for task in manifest["tasks"]:
            task_id = task["id"]
            source = DATASET / task["workspace"]
            hidden = DATASET / "private" / task_id / "hidden-tests.patch"
            gold = DATASET / "private" / task_id / "gold.patch"
            task_result: dict[str, Any] = {"task_id": task_id}
            task_temp = temp / task_id
            base_repo = task_temp / "baseline"
            gold_repo = task_temp / "gold"
            try:
                clone(source, base_repo)
                task_result["baseline_patch_state"] = apply_if_missing(base_repo, hidden)
                base_tests, base_passed = grade_variant(
                    base_repo,
                    task["tests"],
                    output.parent / "discrimination-logs" / task_id / "baseline",
                    args.timeout_seconds,
                )
                clone(source, gold_repo)
                gold_result = run(["git", "apply", "--check", str(gold)], cwd=gold_repo)
                if gold_result.returncode:
                    raise RuntimeError(f"gold patch does not apply: {gold_result.stderr}")
                applied_gold = run(["git", "apply", str(gold)], cwd=gold_repo)
                if applied_gold.returncode:
                    raise RuntimeError(f"could not apply gold patch: {applied_gold.stderr}")
                task_result["gold_hidden_patch_state"] = apply_if_missing(gold_repo, hidden)
                gold_tests, gold_passed = grade_variant(
                    gold_repo,
                    task["tests"],
                    output.parent / "discrimination-logs" / task_id / "gold",
                    args.timeout_seconds,
                )
                task_result.update(
                    {
                        "baseline_all_tests_passed": base_passed,
                        "baseline_tests": base_tests,
                        "gold_all_tests_passed": gold_passed,
                        "gold_tests": gold_tests,
                        "discriminates_untouched_baseline": gold_passed and not base_passed,
                        "assessment": (
                            "scorable_by_tests"
                            if gold_passed and not base_passed
                            else "tests_pass_baseline_and_gold"
                            if gold_passed and base_passed
                            else "gold_patch_or_test_command_failed"
                        ),
                    }
                )
            except Exception as exc:
                task_result["audit_error"] = f"{type(exc).__name__}: {exc}"
                task_result["discriminates_untouched_baseline"] = False
            report["tasks"].append(task_result)
            print(json.dumps({"task_id": task_id, "assessment": task_result.get("assessment", task_result.get("audit_error"))}), flush=True)

    report["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["discriminating_task_count"] = sum(bool(item.get("discriminates_untouched_baseline")) for item in report["tasks"])
    report["task_count"] = len(report["tasks"])
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output), "discriminating_task_count": report["discriminating_task_count"], "task_count": report["task_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
