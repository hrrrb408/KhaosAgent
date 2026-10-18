"""Frozen M8.4 inputs and the sole A/C source difference; no model calls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "reports/benchmark/dataset-v1"
BASE = "f5631de1b5ebb056af28bbd145757b6f76053154"
TASK = "runner-exception-classification"
PROMPT_SHA256 = "7a86c99de62538d4c514cb0f5fa1dd31d747701be60f03c12d4a2420736810a2"
WORKSPACE_BASE = "7b6af61b3925b28ef105ea521c49424344de04c5"
HIDDEN_SHA256 = "185ea8ada844d790c0d716b2d7d921c8c4e739b238baa5d1b7b325e6fc446e16"
FROZEN_SHA256 = {
    "manifest.json": "ffa69ed0e27e50f94d48feae9cc56828b87838020d1f3871a7664be2b547d491",
    "grade_attempt.py": "561a6c72dc88fbbb0c747201d99fd249d91a89f176a45c906d0c8116ed7c4c88",
    "prepare_run.py": "219796f25fe87042126b0a4d9fd325bcc25ee93b36baffa3509eb2cc9acbd900",
    f"frozen/{TASK}.bundle": "0b2f23199529a610b6bac146700774ab09b3e6b20e550a08cf889eb039e30f5a",
    f"private/{TASK}/hidden-tests.patch": HIDDEN_SHA256,
    f"private/{TASK}/gold.patch": "be1c5e1b443ec7f265be089ba99b9002014c343b426faefc5c990a06331ca660",
}
NORMALIZATION = '''        // Only list/shell ignore text; scopes and every other field stay explicit.
        if expected == Set(actionOutputKeys),
           actual == expected.subtracting(["text"]),
           let type = object["type"] as? String,
           (type == "list" || type == "shell") {
            var normalized = object
            normalized["text"] = ""
            return (normalized, true)
        }
'''


def strict_source(source: str) -> str:
    if source.count(NORMALIZATION) != 1:
        raise ValueError("Candidate C source does not match the reviewed normalization block")
    return source.replace(NORMALIZATION, "", 1)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_inputs() -> dict[str, object]:
    task = next(t for t in json.loads((DATASET / "manifest.json").read_text())["tasks"] if t["id"] == TASK)
    prompt_hash = sha256((task["prompt"] + "\n").encode())
    hidden_hash = sha256((DATASET / "private" / TASK / "hidden-tests.patch").read_bytes())
    heads = subprocess.check_output(["git", "bundle", "list-heads", str(DATASET / task["workspace"])], text=True)
    if prompt_hash != PROMPT_SHA256 or hidden_hash != HIDDEN_SHA256:
        raise ValueError("frozen prompt or hidden-test hash mismatch; do not run")
    if task["frozen_baseline_commit"] != WORKSPACE_BASE or any(
        line.split()[0] != WORKSPACE_BASE for line in heads.splitlines()
    ):
        raise ValueError("frozen workspace baseline mismatch; do not run")
    hashes = {}
    for relative, expected in FROZEN_SHA256.items():
        path = DATASET / relative
        data = path.read_bytes()
        if sha256(data) != expected:
            raise ValueError(f"benchmark input changed: {relative}")
        hashes[relative] = sha256(data)
    return {"status": "PASS", "task": TASK, "prompt_sha256": prompt_hash,
            "workspace_baseline": WORKSPACE_BASE, "hidden_patch_sha256": hidden_hash,
            "frozen_files_sha256": hashes, "public_test_commands": task["tests"]}


if __name__ == "__main__":
    print(json.dumps(verify_inputs(), indent=2, sort_keys=True))
