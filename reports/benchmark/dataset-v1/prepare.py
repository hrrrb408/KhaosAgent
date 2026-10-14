#!/usr/bin/env python3
"""Freeze a small, reproducible Khaos coding-task set from merged fixes."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
FREEZE_DATE = "2026-10-14T00:00:00+08:00"
REPOSITORY = "https://github.com/hrrrb408/KhaosAgent"

TASKS = [
    {
        "id": "ipc-json-depth-bounds",
        "source_commit": "3c112b5f8ccb2a630fcfdc2d997e37cc4492cf3f",
        "category": ["single-file bug", "protocol boundary", "test diagnosis"],
        "title": "Bound IPC JSON nesting consistently",
        "prompt": (
            "The IPC JSON decoder behaves differently for deeply nested input on "
            "supported Python versions. Make over-depth frames fail consistently "
            "through the existing bounded protocol error path, preserve normal "
            "frames and the error envelope, and add focused regression coverage. "
            "Do not widen protocol limits."
        ),
        "tests": [["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_ipc.py", "-v"]],
    },
    {
        "id": "plugin-package-grant",
        "source_commit": "4d9a805a238404cd6e4e621c30bd9aa9deeba1d5",
        "category": ["boundary bug", "single production module", "signed-product test"],
        "title": "Honor the selected Plugin package grant",
        "prompt": (
            "The signed Launcher selects a Plugin package through the system "
            "Picker, but package reads must remain within the exact security-scoped "
            "grant returned by that choice. Fix the handoff so the selected package "
            "can be read and the grant is released on every exit path; do not broaden "
            "package access."
        ),
        "tests": [["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_macos_xpc_sandbox.py", "-k", "test_seed_app_builds_and_authenticates_its_kernel_service", "-v"]],
    },
    {
        "id": "macos26-agent-generation-api",
        "source_commit": "9aaaaeb5ffd1313e07604a3732a337b403796387",
        "category": ["single-file compatibility bug", "runtime integration"],
        "title": "Restore local generation on macOS 26",
        "prompt": (
            "The AgentHost no longer compiles against the macOS 26 FoundationModels "
            "GenerationOptions API. Restore the local generation path while keeping "
            "greedy sampling and the existing response-token limits for both Agent "
            "actions and Candidate output. Do not add a provider fallback or change "
            "the sandbox."
        ),
        "tests": [["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_macos_xpc_sandbox.py", "-k", "test_seed_app_builds_and_authenticates_its_kernel_service", "-v"]],
    },
    {
        "id": "trusted-kernel-apfs-trim",
        "source_commit": "39cb0f21e1ffd7fc6f49d0e7bf6d599b6615c184",
        "category": ["behavior-preserving refactor", "TCB reduction"],
        "title": "Remove the duplicate direct APFS backend",
        "prompt": (
            "The signed Kernel Python bundle still contains a direct APFS image "
            "backend even though image ownership is enforced through the authenticated "
            "Broker lease. Remove that duplicate backend while preserving the Broker "
            "checks and fail-closed behavior. Keep the change focused and update the "
            "relevant contract and build checks."
        ),
        "tests": [["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_broker.py", "-v"]],
    },
    {
        "id": "runner-failure-diagnostics",
        "source_commit": "1157e60d3f92c515ef5f4790abcf06c7540756b6",
        "category": ["multi-file failure handling", "bounded diagnostics", "composite"],
        "title": "Add bounded Runner failure diagnostics",
        "prompt": (
            "A Worker-launched Runner can fail before its startup handshake, but the "
            "failure stage is currently lost. Add a bounded internal diagnostic with "
            "a closed stage/category, child exit status, and elapsed time. At most "
            "4 KiB of pre-Plugin stderr may be read and it must be reduced to a closed "
            "category and discarded; keep the public error generic and preserve the "
            "standalone Runner behavior. Update tests and ABI documentation."
        ),
        "tests": [
            ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_ipc.py", "-v"],
            ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_launcher.py", "-v"],
            ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_workspace_xpc_bridge.py", "-v"],
        ],
    },
    {
        "id": "runner-startup-classification",
        "source_commit": "8a23c293a280bd3973fd0cf04bc11b86e0f5ea79",
        "category": ["multi-file exception handling", "failure diagnosis"],
        "title": "Classify bounded Runner startup failures",
        "prompt": (
            "Runner startup can fail during the sandbox probe, process spawn, peer "
            "identity check, or pipe handshake. Preserve the generic public failure "
            "while recording only a bounded, closed internal stage/category and child "
            "status. Keep timeouts, peer checks, scope, and fail-closed behavior intact; "
            "add focused tests."
        ),
        "tests": [
            ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_worker.py", "-v"],
            ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_broker.py", "-v"],
        ],
    },
    {
        "id": "runner-exception-classification",
        "source_commit": "5ac2e5f9a6b7cdaddb37ea18c28192b7b2e49a99",
        "category": ["single-module bug", "exception classification", "secret-safe diagnostics"],
        "title": "Distinguish OS and Python startup exceptions",
        "prompt": (
            "The bounded Runner startup classifier sometimes labels Python exceptions "
            "as operating-system failures. Classify only known OS exception classes as "
            "runner_os_error; RuntimeError, TypeError, and ValueError must remain "
            "runner_startup_exception. Keep raw stderr private and discarded, and add "
            "focused regression tests."
        ),
        "tests": [["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_worker.py", "-v"]],
    },
    {
        "id": "runner-peer-socket-race",
        "source_commit": "89895bac619d6f9549dd035a883de2f3842d5d2d",
        "category": ["multi-file race", "process identity boundary", "adversarial test"],
        "title": "Keep the peer socket through both PID checks",
        "prompt": (
            "The Runner startup parent closes its AF_UNIX connection after checking "
            "the child PID. If the child is scheduled later, its LOCAL_PEERPID query "
            "can fail with ENOTCONN before the first ping. Keep the connection alive "
            "until the child validates the parent PID and acknowledges completion under "
            "the existing deadline. Preserve PID/nonce checks, sandbox policy, and "
            "fail-closed behavior."
        ),
        "tests": [
            ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_peer_identity.py", "-v"],
            ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_worker.py", "-v"],
        ],
    },
    {
        "id": "nested-image-cleanup-reconciliation",
        "source_commit": "abc854bdb7081945661a25842e5dcd5f13de23f6",
        "category": ["edge-case cleanup", "test failure diagnosis", "real-OS test"],
        "title": "Reconcile nested image cleanup in the mount probe",
        "prompt": (
            "The mount attack fixture can see an empty device inventory briefly while "
            "its inner image still owns the outer work volume. It then raises and masks "
            "the primary fixture failure during outer cleanup. Make the fixture recover "
            "using the existing bounded identity checks, preserve the primary exception, "
            "and retain fail-closed cleanup behavior."
        ),
        "tests": [["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_macos_seatbelt.py", "-v"]],
    },
    {
        "id": "pipe-handshake-diagnostic-test",
        "source_commit": "25510f66a554029786747bf963dd86d62c896e6b",
        "category": ["test failure diagnosis", "real-OS regression coverage"],
        "title": "Test real Runner pipe-handshake diagnostics",
        "prompt": (
            "Add a real macOS Seatbelt regression test for a malformed Runner ping "
            "before Plugin source delivery. The test should verify the closed "
            "pipe-handshake diagnostic, child exit status, bounded elapsed time, no raw "
            "stderr field, and an unchanged workspace. Keep it skipped when the real "
            "macOS Runner is unavailable."
        ),
        "tests": [["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_worker.py", "-v"]],
        "grading_note": "Test-only task; also review that the new test fails under a deliberately wrong diagnostic category.",
    },
    {
        "id": "bounded-lifecycle-acceptance-wait",
        "source_commit": "59ef76f5fb64c8219b023dd5dbcb7a41f37d37f9",
        "category": ["test harness repair", "bounded wait", "failure diagnostics"],
        "title": "Bound the interactive lifecycle test wait",
        "prompt": (
            "The signed-product Plugin lifecycle test can wait indefinitely when its "
            "expected UI marker never arrives. Make the wait bounded, report the missing "
            "marker and captured diagnostics, and clean up the launched process on timeout."
        ),
        "tests": [["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_macos_xpc_sandbox.py", "-k", "test_seed_app_builds_and_authenticates_its_kernel_service", "-v"]],
        "grading_note": "Test-only task; score via bounded-timeout behavior and process cleanup under a missing-marker fault injection.",
    },
    {
        "id": "replacement-racer-termination-wait",
        "source_commit": "98f8a72966aa2f74643431b6c9ca2f6d0e095511",
        "category": ["test harness repair", "process race", "cleanup"],
        "title": "Wait for the replacement racer to exit",
        "prompt": (
            "A workspace race test can observe its readiness marker before the replacement "
            "racer has terminated. Make the test wait for the child to exit before checking "
            "final workspace state, while retaining bounded cleanup if the process stalls."
        ),
        "tests": [["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_workspace_changes.py", "-v"]],
        "grading_note": "Test-only task; score via a delayed child-exit fault injection and bounded process cleanup.",
    },
]


def git(*args: str, env: dict[str, str] | None = None, cwd: Path = ROOT) -> bytes:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    ).stdout


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def make_snapshot(task: dict[str, object], baseline: str) -> str:
    task_id = str(task["id"])
    bundle_path = OUT / "frozen" / f"{task_id}.bundle"
    with tempfile.TemporaryDirectory(prefix=f"khaos-{task_id}-") as temporary:
        workspace = Path(temporary) / task_id
        workspace.mkdir()
        archive = git("archive", "--format=tar", baseline)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
            bundle.extractall(workspace, filter="data")
        subprocess.run(["git", "-C", str(workspace), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(workspace), "branch", "-M", "main"], check=True)
        subprocess.run(["git", "-C", str(workspace), "config", "user.name", "Khaos Reliability Benchmark"], check=True)
        subprocess.run(["git", "-C", str(workspace), "config", "user.email", "benchmark@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(workspace), "add", "--all"], check=True)
        fixed_env = os.environ.copy()
        fixed_env["GIT_AUTHOR_DATE"] = FREEZE_DATE
        fixed_env["GIT_COMMITTER_DATE"] = FREEZE_DATE
        subprocess.run(
            ["git", "-C", str(workspace), "commit", "-q", "-m", f"frozen benchmark baseline: {task_id}"],
            check=True,
            env=fixed_env,
        )
        baseline_commit = git("rev-parse", "HEAD", cwd=workspace).decode().strip()
        subprocess.run(
            ["git", "-C", str(workspace), "bundle", "create", str(bundle_path), "--all"],
            check=True,
        )
    return baseline_commit


def main() -> None:
    if len(TASKS) < 10 or len(TASKS) > 15:
        raise SystemExit("dataset must contain 10-15 tasks")
    if (OUT / "frozen").exists() or (OUT / "private").exists() or (OUT / "manifest.json").exists():
        raise SystemExit("dataset outputs already exist; refusing to replace them")
    (OUT / "frozen").mkdir(parents=True)

    manifest: dict[str, object] = {
        "format": "khaos-coding-reliability-dataset-v1",
        "frozen_at": FREEZE_DATE,
        "source_repository": REPOSITORY,
        "selection": "12 recent Khaos maintenance and test-reliability fixes/features from the public repository history, stratified across protocol, scope, compatibility, refactor, Runner, race, cleanup, and test-harness work; selection is fixed before model runs.",
        "scope_limitations": [
            "This is a Khaos-specific sample, not a representative cross-project SWE-bench score.",
            "The historical source commits and task text are public; model pretraining contamination cannot be ruled out.",
            "Model task workspaces contain one frozen root commit only; no future commit objects or hidden grading patches are copied into them.",
            "Tasks 10-12 measure test and harness repair, and task 9 targets a test fixture; these results are reported separately from production-code fix rate.",
        ],
        "tasks": [],
    }

    for task in TASKS:
        source = str(task["source_commit"])
        baseline = git("rev-parse", f"{source}^").decode().strip()
        gold_patch = git("diff", "--binary", baseline, source)
        source_patch = git("diff", "--binary", baseline, source, "--", "khaos", "tools")
        test_patch = git("diff", "--binary", baseline, source, "--", "tests")
        changed_paths = git("diff", "--name-only", baseline, source).decode().splitlines()
        public_tests = git("ls-tree", "-r", "--name-only", baseline, "--", "tests").decode().splitlines()
        baseline_tree = git("rev-parse", f"{baseline}^{{tree}}").decode().strip()
        baseline_commit = make_snapshot(task, baseline)

        private_dir = OUT / "private" / str(task["id"])
        write_file(private_dir / "gold.patch", gold_patch)
        write_file(private_dir / "source.patch", source_patch)
        write_file(private_dir / "hidden-tests.patch", test_patch)
        entry = {
            **task,
            "repository": REPOSITORY,
            "source_commit": source,
            "source_commit_url": f"{REPOSITORY}/commit/{source}",
            "base_commit": baseline,
            "base_tree_sha": baseline_tree,
            "frozen_baseline_commit": baseline_commit,
            "workspace": f"frozen/{task['id']}.bundle",
            "changed_paths": changed_paths,
            "public_test_files": public_tests,
            "gold_patch_sha256": sha256(gold_patch),
            "source_patch_sha256": sha256(source_patch),
            "hidden_tests_patch_sha256": sha256(test_patch),
            "hidden_test_patch_present": bool(test_patch),
        }
        manifest["tasks"].append(entry)

    manifest_path = OUT / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"froze {len(TASKS)} task baselines: {manifest_path}")


if __name__ == "__main__":
    main()
