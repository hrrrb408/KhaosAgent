"""Run one explicitly authorized M8.4 slot; never approve UI or retry an attempt."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

from experiment_support import ROOT, TASK, PROMPT_SHA256, WORKSPACE_BASE, sha256, verify_inputs

REPORTS = Path(__file__).resolve().parent
ORDER = ["a-01", "c-01", "c-02", "a-02"]
ENDPOINT = "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def load(path: Path):
    return json.loads(path.read_text())


def candidate_snapshot(workspace: Path) -> tuple[bytes, list[str]]:
    """Include untracked files without changing the index or following symlinks."""
    git = ["git", "-C", str(workspace)]
    options = ["--no-ext-diff", "--no-textconv", "--binary"]
    diff = subprocess.check_output(git + ["diff", *options, "HEAD"])
    tracked = subprocess.check_output(git + ["diff", "--name-only", "-z", "HEAD"])
    untracked = subprocess.check_output(git + ["ls-files", "--others", "--exclude-standard", "-z"])
    paths = sorted(set(p.decode() for p in (tracked + untracked).split(b"\0") if p))
    for path in (p.decode() for p in untracked.split(b"\0") if p):
        result = subprocess.run(git + ["diff", "--no-index", *options, "--", "/dev/null", path],
                                capture_output=True)
        if result.returncode not in (0, 1):
            raise RuntimeError("candidate snapshot failed")
        diff += result.stdout
    return diff, paths


def independent_grade(dataset: Path, run_dir: Path, attempt_id: str) -> dict:
    """Keep grader output private and preserve an explicit error summary."""
    result = subprocess.run([
        sys.executable, str(dataset / "grade_attempt.py"), "--model", "api",
        "--task-id", TASK, "--attempt", attempt_id,
    ], capture_output=True)
    (run_dir / "grader.stdout").write_bytes(result.stdout)
    (run_dir / "grader.stderr").write_bytes(result.stderr)
    summary = {"attempt_id": attempt_id, "grader_exit_code": result.returncode,
               "grader_stdout_sha256": sha256(result.stdout),
               "grader_stderr_sha256": sha256(result.stderr), "raw_test_output_committed": False}
    try:
        if result.returncode != 0:
            raise ValueError("grader invocation failed")
        grade = load(run_dir / "grade.json")
        summary.update(grade_status="COMPLETED", baseline=grade["frozen_baseline_commit"],
            hidden_patch_sha256=grade["hidden_test_patch_sha256"],
            hidden_patch_applied=grade["hidden_test_patch_applied"],
            return_codes=[t["return_code"] for t in grade["tests"]],
            timed_out=[t["timed_out"] for t in grade["tests"]],
            all_test_commands_passed=grade["all_test_commands_passed"],
            graded_candidate_paths=grade["candidate_paths_copied"],
            excluded_test_edits=grade["candidate_test_edits_excluded"],
            raw_grade_sha256=sha256((run_dir / "grade.json").read_bytes()))
    except (OSError, ValueError, KeyError, TypeError):
        summary.update(grade_status="GRADER_ERROR", all_test_commands_passed="NOT_CAPTURED",
                       graded_candidate_paths="NOT_CAPTURED", excluded_test_edits="NOT_CAPTURED")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("attempt", choices=ORDER)
    parser.add_argument("--local-state", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    state = load(args.local_state)
    attempt = state["attempts"][args.attempt]
    run_dir = Path(attempt["run_dir"])
    public = REPORTS / "attempts" / args.attempt
    group = attempt["group"]
    if load(REPORTS / "validation.json")["preflight"] != "PASS":
        raise SystemExit("preflight has not passed")
    config = load(REPORTS / "experiment-config.json")
    if config["protocol_sha256"] != sha256((REPORTS / "EXPERIMENT_PROTOCOL.md").read_bytes()):
        raise SystemExit("preregistered protocol changed")
    for previous in ORDER[:ORDER.index(args.attempt)]:
        if not (Path(state["attempts"][previous]["run_dir"]) / "m84-finished.json").is_file():
            raise SystemExit("fixed experiment order requires the previous slot to finish")
    authorization = load(run_dir / "m84-authorization.json")
    if not (
        authorization.get("authorized") is True
        and authorization.get("attempt_id") == attempt["run_id"]
        and authorization.get("group") == group
        and authorization.get("model") == "glm-5.3"
        and authorization.get("provider") == "bigmodel-coding-plan"
        and authorization.get("endpoint") == ENDPOINT
    ):
        raise SystemExit("fresh explicit authorization does not match this slot")
    if not state.get("hermes_credential_present") or not state.get("hermes_endpoint_matches"):
        raise SystemExit("the existing Hermes credential/endpoint precheck is not satisfied")
    base_lines = [line.split("=", 1)[1] for line in (Path.home() / ".hermes/.env").read_text().splitlines()
                  if line.startswith("GLM_BASE_URL=")]
    base_values = [shlex.split(line) for line in base_lines]
    if len(base_values) != 1 or len(base_values[0]) != 1 or base_values[0][0].rstrip("/") not in {
        ENDPOINT, ENDPOINT.removesuffix("/chat/completions")
    }:
        raise SystemExit("Hermes endpoint metadata no longer matches the approved recipient")
    verify_inputs()
    dataset = Path(state["dataset"])
    verify_inputs(dataset)
    workspace = Path(attempt["workspace"])
    if subprocess.check_output(["git", "-C", str(workspace), "rev-parse", "HEAD"], text=True).strip() != WORKSPACE_BASE:
        raise SystemExit("attempt workspace baseline changed")
    if subprocess.check_output(["git", "-C", str(workspace), "status", "--porcelain"]):
        raise SystemExit("attempt workspace is not clean")
    if sha256((run_dir / "task-prompt.txt").read_bytes()) != PROMPT_SHA256:
        raise SystemExit("attempt prompt changed")
    app = Path(state["app_" + group])
    build = load(REPORTS / "build-integrity.json")[group]
    binaries = {
        "launcher": "Contents/MacOS/KhaosSeed",
        "kernel": "Contents/XPCServices/KernelProduction.xpc/Contents/MacOS/KernelProduction",
        "snapshot_broker": "Contents/XPCServices/KernelSnapshotBroker.xpc/Contents/MacOS/KernelSnapshotBroker",
        "agent_host": "Contents/XPCServices/KhaosAgentHost.xpc/Contents/MacOS/KhaosAgentHost",
    }
    for name, relative in binaries.items():
        if sha256((app / relative).read_bytes()) != build["executables"][name]["signed_sha256"]:
            raise SystemExit(f"signed executable changed: {name}")
    if load(app / "Contents/Resources/build-inputs.json")["source_sha256"] != load(
        REPORTS / f"build-sources-{group.lower()}.json"
    ):
        raise SystemExit("packaged source map changed")
    for process_name in ("KhaosSeed", "KhaosAgentHost"):
        if subprocess.run(["pgrep", "-x", process_name], capture_output=True).returncode == 0:
            raise SystemExit("another Khaos product process is live; inspect it before starting")
    # An exclusive marker consumes this slot even if launch/capture later fails.
    with (run_dir / "m84-started.json").open("x") as stream:
        json.dump({"attempt_id": attempt["run_id"], "group": group,
                   "started_utc": datetime.now(timezone.utc).isoformat()}, stream)
    logs = run_dir / "product-logs"
    logs.mkdir()
    (logs / "stdin").write_bytes((run_dir / "task-prompt.txt").read_bytes())
    for name in ("stdout", "stderr"):
        (logs / name).touch()
    log_path = logs / "host-diagnostics.log"
    spec = importlib.util.spec_from_file_location("m84_existing_launcher", ROOT / "reports/tool-planning/run_experiment.py")
    assert spec and spec.loader
    existing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(existing)
    with log_path.open("x") as log:
        capture = subprocess.Popen([
            "/usr/bin/log", "stream", "--style", "compact", "--color", "none", "--level", "info",
            "--predicate", 'subsystem == "org.khaos.Seed.AgentHost" AND category == "action-diagnostics" AND process == "KhaosAgentHost"',
        ], stdout=log, stderr=subprocess.STDOUT)
        try:
            time.sleep(.3)
            process = existing.launch_product(app, logs)
            run = load(run_dir / "run.json")
            run.update(status="running", started_at_utc=datetime.now(timezone.utc).isoformat(),
                       open_pid=process.pid, diagnostic_pid=capture.pid, group=group,
                       product_source_commit=state["source_" + group])
            save(run_dir / "run.json", run)
            print(json.dumps({"attempt": attempt["run_id"], "group": group,
                              "workspace": str(workspace), "waiter_pid": process.pid}), flush=True)
            returncode = process.wait()
            time.sleep(.5)
        finally:
            capture.terminate()
            capture.wait(timeout=5)
    terminal_path = run_dir / "m84-terminal.json"
    subprocess.run([
        sys.executable, str(ROOT / "reports/benchmark/dataset-v1/capture_agent_events.py"),
        "--snapshot", "--attempt-id", attempt["run_id"],
        "--stdout", str(logs / "stdout"), "--stderr", str(logs / "stderr"),
        "--agenthost-diagnostics", str(log_path), "--waiter-exit-code", str(returncode),
        "--output", str(terminal_path),
    ], check=True, capture_output=True)
    terminal = load(terminal_path)
    host_pids = sorted(set(re.findall(r"KhaosAgentHost\[(\d+):", log_path.read_text())))
    terminal["captured_host_pids"] = host_pids
    terminal["attempt_association_complete"] = len(host_pids) == 1
    run = load(run_dir / "run.json")
    run.update(status="completed" if terminal["evidence_complete"] else "terminal_outcome_incomplete",
               launcher_exit_code=returncode, completed_at_utc=datetime.now(timezone.utc).isoformat())
    save(run_dir / "run.json", run)
    save(public / "terminal-outcome.json", terminal)
    save(public / "action-diagnostics.json", {
        "attempt_id": attempt["run_id"], "events": terminal["host_diagnostic_events"],
        "counts": terminal["event_counts"], "host_pids": host_pids,
        "capture_complete": terminal["diagnostic_capture_complete"] and len(host_pids) == 1,
        "raw_log_sha256": sha256(log_path.read_bytes()),
    })
    diff, candidate_paths = candidate_snapshot(workspace)
    (run_dir / "candidate.patch").write_bytes(diff)
    verify_inputs(dataset)
    grade = independent_grade(dataset, run_dir, attempt["run_id"])
    save(public / "candidate-metadata.json", {
        "attempt_id": attempt["run_id"], "candidate_present": bool(candidate_paths),
        "changed_paths": candidate_paths, "excluded_test_edits": grade["excluded_test_edits"],
        "graded_candidate_paths": grade["graded_candidate_paths"],
        "diff_sha256": sha256(diff), "diff_bytes": len(diff), "raw_diff_committed": False,
    })
    save(public / "grade.json", grade)
    save(public / "tool-summary.json", {
        "attempt_id": attempt["run_id"], "launcher_counts": terminal["event_counts"],
        "return_codes": terminal["executed_command_return_codes"],
        "operation_classifications": "NOT_CAPTURED; attach reviewed per-operation records before analysis",
    })
    public_config = load(public / "attempt-config.json")
    public_config.update(status="EXECUTED_REQUIRES_ANALYSIS", source_commit=state["source_" + group],
                         formal_attempt_started="agent-session=remote-data=approved" in (logs / "stderr").read_text(),
                         remote_completion_requests="NOT_CAPTURED",
                         authorization_sha256=sha256((run_dir / "m84-authorization.json").read_bytes()))
    save(public / "attempt-config.json", public_config)
    save(run_dir / "m84-finished.json", {"terminal_class": terminal["terminal_class"],
        "candidate_present": bool(candidate_paths), "grade_passed": grade["all_test_commands_passed"]})
    print(json.dumps(load(run_dir / "m84-finished.json")), flush=True)


if __name__ == "__main__":
    main()
