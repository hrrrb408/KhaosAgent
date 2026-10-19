"""Opt-in manual signed acceptance. Never simulates approval or cancellation.

Run --prepare first, then --run after inspecting the build record and isolation
receipt. Artifacts are retained on success and failure; use a new directory for
any new attempt. The ordinary production builder is unmodified.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import build_macos_seed as builder
from signed_cancellation_fixture import CASES, MARKER, host_receipt_contains_terminal, overlay
from test_macos_xpc_sandbox import MacOSXPCSandboxTests


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def binaries(app: Path) -> dict[str, Path]:
    return {
        "launcher": app / "Contents/MacOS/KhaosSeed",
        "kernel": app / "Contents/XPCServices/KernelProduction.xpc/Contents/MacOS/KernelProduction",
        "agent_host": app / "Contents/XPCServices/KhaosAgentHost.xpc/Contents/MacOS/KhaosAgentHost",
    }


def prepare(root: Path, case: str, signer: str) -> None:
    root.mkdir(parents=True, exist_ok=False)
    (root / "kernel-events.jsonl").touch(mode=0o600)
    harness = MacOSXPCSandboxTests()
    probe = harness._compile_agent_host_model_probe(root)
    model = root / "model.gguf"
    model.write_text("deterministic fixture; no real model\n")
    license = root / "model-license.txt"
    license.write_text("Khaos test fixture\n")
    arguments = dict(signing_identity=signer, python_executable=Path(sys.executable).resolve(),
                     llama_cli=probe, model_file=model, model_license=license)
    production = root / "Production.app"
    builder.build_app(production, **arguments)
    original_snapshot = builder._snapshot_sources
    overlay_hashes = {}

    def acceptance_snapshot(destination, expected_inputs):
        hashes = original_snapshot(destination, expected_inputs)
        overlay_hashes.update(overlay(destination, root, case))
        hashes.update(overlay_hashes)
        for path in (Path(__file__), Path(__file__).with_name("signed_cancellation_fixture.py"),
                     ROOT / "tests/macos_xpc_probe/AgentHostSandboxModelProbe.swift"):
            hashes[str(path.relative_to(ROOT))] = sha(path)
        return hashes

    acceptance = root / "Acceptance.app"
    with patch.object(builder, "_snapshot_sources", acceptance_snapshot):
        builder.build_app(acceptance, **arguments)
    for app in (production, acceptance):
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    production_record = json.loads((production / "Contents/Resources/build-inputs.json").read_text())
    acceptance_record = json.loads((acceptance / "Contents/Resources/build-inputs.json").read_text())
    for relative in overlay_hashes:
        assert production_record["source_sha256"][relative] == sha(ROOT / relative)
        assert acceptance_record["source_sha256"][relative] == overlay_hashes[relative]
    for path in binaries(production).values():
        assert MARKER.encode() not in path.read_bytes()
        assert b"POST_APPROVAL_PRE_SUBMIT" not in path.read_bytes()
        assert b"acceptance-barrier=" not in path.read_bytes()
    python_root = production / "Contents/XPCServices/KernelProduction.xpc/Contents/Resources"
    for path in python_root.rglob("*.py"):
        assert MARKER.encode() not in path.read_bytes()
    assert b"WORKSPACE_RUN_SUBMISSION" in binaries(acceptance)["kernel"].read_bytes()
    if case == "b32":
        assert b"acceptance-barrier=" in binaries(acceptance)["launcher"].read_bytes()
    save(root / "build.json", {
        "case": case, "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_diff_sha256": hashlib.sha256(subprocess.check_output(["git", "diff", "HEAD"], cwd=ROOT)).hexdigest(),
        "production_test_hook_isolation": "PASS", "acceptance_overlay_sha256": overlay_hashes,
        "fixture_sha256": sha(Path(__file__).with_name("signed_cancellation_fixture.py")),
        "harness_sha256": sha(Path(__file__)),
        "production_binary_sha256": {name: sha(path) for name, path in binaries(production).items()},
        "acceptance_binary_sha256": {name: sha(path) for name, path in binaries(acceptance).items()},
        "production_build_record": production_record, "acceptance_build_record": acceptance_record,
    })
    print(f"PREPARED {root}; inspect build.json before --run", flush=True)


def run(root: Path) -> None:
    receipt = json.loads((root / "build.json").read_text())
    case = receipt["case"]
    app = root / "Acceptance.app"
    for name, path in binaries(app).items():
        assert sha(path) == receipt["acceptance_binary_sha256"][name]
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    evidence_path = root / "acceptance.json"
    if evidence_path.exists():
        raise ValueError("refusing to overwrite an attempt")
    workspace = root / "workspace"
    workspace.mkdir()
    (workspace / "tags.py").write_text('def parse_tags(value):\n    return value.split(",")\n')
    (workspace / "unscoped-canary.txt").write_text("synthetic unscoped canary\n")
    before = {p.name: sha(p) for p in workspace.iterdir()}
    prompt = root / "prompt.txt"
    prompt.write_text("KHAOS_STAGED_EDIT_FEASIBILITY_PROBE KHAOS_SIGNED_CANCELLATION_RECEIPT Apply the one fixed staged replacement to tags.py.\n")
    out, err = root / "launcher.stdout", root / "launcher.stderr"
    out.touch()
    err.touch()
    result = {"status": "RUNNING", "case": case, "build_receipt_sha256": sha(root / "build.json"),
              "workspace_before": before, "owner_review": "PENDING"}
    save(evidence_path, result)
    process = subprocess.Popen(["/usr/bin/open", "-n", "-W", "-a", str(app), "--stdin", str(prompt),
                                "--stdout", str(out), "--stderr", str(err), "--args", "--agent"])
    stage = "POST_APPROVAL_PRE_SUBMIT" if case == "b32" else (
        "KERNEL_READY_PRE_ACCEPT" if case == "pre-commit" else "KERNEL_POST_COMMIT_PRE_REPLY")
    print(f"USER ACTION REQUIRED\nTest: {case}\nCurrent Stage: workspace Picker / Candidate B preview\n"
          f"Requested User Action: select {workspace}; review tags.py scopes and click Run Once.\n"
          "Expected Observable Result: original Task Progress pauses at the named acceptance barrier.\n", flush=True)
    barrier_seen = False
    cancel_seen = False
    deadline = time.monotonic() + 600
    try:
        while time.monotonic() < deadline:
            stderr = err.read_text(errors="replace")
            events = [json.loads(line) for line in (root / "kernel-events.jsonl").read_text().splitlines()]
            reached = (f"acceptance-barrier={stage}" in stderr if case == "b32"
                       else any(e["stage"] == stage for e in events))
            if reached and not barrier_seen:
                barrier_seen = True
                result["workspace_at_barrier"] = {p.name: sha(p) for p in workspace.iterdir()}
                result["barrier"] = stage
                save(evidence_path, result)
                print(f"USER ACTION REQUIRED\nTest: {case}\nCurrent Stage: {stage}\n"
                      "Requested User Action: click Cancel task in the original signed Task Progress window now (within 55 seconds).\n"
                      "Expected Observable Result: cancellation uses the original Task/XPC connection; "
                      + ("committed tags.py remains committed." if case == "post-commit" else "live workspace stays unchanged.")
                      + "\n", flush=True)
            if "acceptance-cancellation-ack=" in stderr and not cancel_seen:
                cancel_seen = True
                # Ack follows the Kernel's signal write. This only releases the
                # test pause; it cannot choose the result or grant authority.
                (root / "release").touch(mode=0o600, exist_ok=False)
            if process.poll() is not None:
                break
            time.sleep(0.05)
        assert process.poll() == 0, f"signed app did not finish: {process.poll()}"
        assert barrier_seen and cancel_seen, "missing stage or actual cancellation acknowledgment"
        stderr = err.read_text()
        assert "TIMEOUT" not in stderr
        events = [json.loads(line) for line in (root / "kernel-events.jsonl").read_text().splitlines()]
        assert not any(e["stage"] == "barrier_timeout" for e in events)
        records = [json.loads(line.partition("Launcher task record: ")[2]) for line in out.read_text().splitlines()
                   if line.startswith("Launcher task record: ")]
        assert len(records) == 1, records
        record = records[0]
        assert record["cancellation_requested"] is True
        assert record["terminal_result_delivery"] == "delivered"
        sent = next(line.partition("acceptance-terminal-sent=")[2] for line in stderr.splitlines()
                    if "acceptance-terminal-sent=" in line)
        received = next(line.partition("CANCELLATION_RECEIPT_BASE64=")[2] for line in stderr.splitlines()
                        if "acceptance-host-receipt=CANCELLATION_RECEIPT_BASE64=" in line)
        assert host_receipt_contains_terminal(sent, received), "Host did not receive the exact terminal data"
        result["host_terminal_receipt_base64"] = received
        requests = record["workspace_requests"]
        assert len(requests) == 1
        request = requests[0]
        assert request["approval"] == "approved_candidate_b_preview"
        assert request["cancellation_requested"] is True
        submissions = [e for e in events if e["stage"] == "WORKSPACE_RUN_SUBMISSION"]
        runners = [e for e in events if e["stage"] == "RUNNER_EXECUTION"]
        private_changes = [e for e in events if e["stage"] == "PRIVATE_CHANGESET_READY"]
        replies = [json.loads(base64.b64decode(e["response_base64"])) for e in events if e["stage"] == "ORIGINAL_KERNEL_REPLY"]
        after = {p.name: sha(p) for p in workspace.iterdir()}
        assert after["unscoped-canary.txt"] == before["unscoped-canary.txt"]
        assert set(after) == set(before), "unexpected temporary entries"
        if case == "b32":
            assert not submissions and not runners and not replies
            assert request["kernel_result"].startswith("not_submitted:")
            assert request["commit_outcome"] == "not_committed" and after == before
        else:
            assert len(submissions) == len(runners) == len(replies) == 1
            assert submissions[0]["request_id"] == request["request_id"] == replies[0]["request_id"]
            assert runners[0]["workspace_request_id"] == request["request_id"]
            assert len(private_changes) == 1, private_changes
            change = private_changes[0]
            assert change["staged_write_paths"] == ["tags.py"], change
            expected_tags = (
                'def parse_tags(value):\n'
                '    return [part.strip() for part in value.split(",") if part.strip()]\n'
            ).encode()
            assert change["staged_file_sha256"]["tags.py"] == hashlib.sha256(expected_tags).hexdigest()
            if case == "pre-commit":
                assert replies[0]["error"]["code"] == "process_cancelled", replies
                assert request["kernel_result"] == "error:process_cancelled"
                assert request["commit_outcome"] == "not_committed" and after == before
            else:
                assert replies[0]["ok"] is True
                assert request["kernel_result"] == "output"
                assert request["commit_outcome"] == "committed"
                assert after["tags.py"] != before["tags.py"]
                assert after == result["workspace_at_barrier"]
        result.update(status="PASS_SIGNED_KERNEL_WORKSPACE_LAUNCHER", task_record=record,
                      kernel_events=events, original_kernel_replies=replies,
                      private_changes=private_changes,
                      kernel_submission_count=len(submissions), runner_execution_count=len(runners),
                      workspace_after=after, host_terminal_delivery="PASS_EXACT_DATA_RECEIPT",
                      stdout_sha256=sha(out), stderr_sha256=sha(err))
    except BaseException as error:
        result.update(status="FAILED_ATTEMPT", error=str(error), workspace_after={p.name: sha(p) for p in workspace.iterdir()})
        raise
    finally:
        save(evidence_path, result)
        if process.poll() is None:
            MacOSXPCSandboxTests._terminate_product_executable(binaries(app)["launcher"])
            process.wait(timeout=10)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--case", choices=sorted(CASES))
    parser.add_argument("--signing-identity")
    args = parser.parse_args()
    directory = args.directory.expanduser().absolute()
    if args.prepare:
        if not args.case or not args.signing_identity:
            parser.error("--prepare requires --case and --signing-identity")
        prepare(directory, args.case, args.signing_identity)
    else:
        run(directory)
