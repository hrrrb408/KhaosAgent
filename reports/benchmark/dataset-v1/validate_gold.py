#!/usr/bin/env python3
"""Check that each frozen task's historical fix satisfies its recorded tests."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path


OUT = Path(__file__).resolve().parent
RESULTS = OUT / "validation"
MANIFEST = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    if RESULTS.exists():
        raise SystemExit(f"refusing to overwrite existing validation evidence: {RESULTS}")
    RESULTS.mkdir(parents=True)
    started_at_utc = dt.datetime.now(dt.timezone.utc).isoformat()
    records = []
    all_passed = True
    clean_env = os.environ.copy()
    clean_env.pop("KHAOS_BIGMODEL_API_KEY", None)
    clean_env.pop("KHAOS_RUN_PRODUCT_BIGMODEL_MEMORY_EVOLUTION_UI", None)
    clean_env.pop("KHAOS_RUN_PRODUCT_BIGMODEL_CODING_LOOP_UI", None)
    clean_env.pop("KHAOS_RUN_PRODUCT_BIGMODEL_DATA_DENIAL_UI", None)

    for task in MANIFEST["tasks"]:
        task_id = task["id"]
        workspace = RESULTS / "workspaces" / task_id
        workspace.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(OUT / task["workspace"]), str(workspace)],
            check=True,
        )
        gold_patch = OUT / "private" / task_id / "gold.patch"
        if gold_patch.stat().st_size:
            subprocess.run(
                ["git", "-C", str(workspace), "apply", str(gold_patch)],
                check=True,
            )

        command_records = []
        for index, command in enumerate(task["tests"], start=1):
            started = time.monotonic()
            try:
                result = subprocess.run(
                    command,
                    cwd=workspace,
                    env=clean_env,
                    capture_output=True,
                    timeout=1200,
                )
                return_code = result.returncode
                stdout = result.stdout
                stderr = result.stderr
                error = None
            except subprocess.TimeoutExpired as timeout_error:
                return_code = None
                stdout = timeout_error.stdout or b""
                stderr = timeout_error.stderr or b""
                error = "timeout after 1200 seconds"
            elapsed = round(time.monotonic() - started, 3)
            log_dir = RESULTS / "logs" / task_id
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / f"test-{index}.stdout").write_bytes(stdout)
            (log_dir / f"test-{index}.stderr").write_bytes(stderr)
            command_records.append(
                {
                    "argv": command,
                    "return_code": return_code,
                    "elapsed_seconds": elapsed,
                    "stdout_sha256": digest(stdout),
                    "stderr_sha256": digest(stderr),
                    "stdout_bytes": len(stdout),
                    "stderr_bytes": len(stderr),
                    "error": error,
                }
            )
            passed = return_code == 0
            print(f"{task_id} test {index}/{len(task['tests'])}: {'PASS' if passed else 'FAIL'} ({elapsed:.1f}s)", flush=True)
            all_passed = all_passed and passed

        records.append(
            {
                "task_id": task_id,
                "gold_patch_sha256": task["gold_patch_sha256"],
                "commands": command_records,
                "status": "passed" if all(item["return_code"] == 0 for item in command_records) else "failed",
                "grader_workspace_commit": subprocess.check_output(
                    ["git", "-C", str(workspace), "rev-parse", "HEAD"], text=True
                ).strip(),
                "working_tree_changed": bool(
                    subprocess.check_output(
                        ["git", "-C", str(workspace), "status", "--porcelain"], text=True
                    )
                ),
            }
        )

    result_document = {
        "format": "khaos-coding-reliability-gold-validation-v1",
        "started_at_utc": started_at_utc,
        "finished_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "passed" if all_passed else "failed",
        "tasks": records,
    }
    (RESULTS / "results.json").write_text(
        json.dumps(result_document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"gold validation {result_document['status']}: {RESULTS / 'results.json'}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
