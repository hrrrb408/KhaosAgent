#!/usr/bin/env python3
"""Run signed fake-result trials with narrowly injected retention failures."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import experimental_artifact_retention as retention  # noqa: E402
from tools import run_dsh_xpc_attack_acceptance as acceptance  # noqa: E402

CASES = ("archive-failure", "identity-substitution", "active-reference", "unknown-reference")
AUTHORIZATION = "Owner-delegated disposable experiment for M-Disk.1.2/1.3"
UI_SCOPE = (
    "One synthetic fake-result test command in the invocation-owned disposable workspace; "
    "review the displayed task, digest, executable, exact scopes, and expected exit status 1. "
    "No historical Scratch or model access."
)


def write_private(path: Path, payload: object) -> None:
    encoded = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def process_records(report: dict[str, object]) -> list[dict[str, object]]:
    signed = report.get("signed_ui_evidence")
    if not isinstance(signed, dict):
        return []
    output: list[dict[str, object]] = []
    for task in signed.get("launcher_task_records", []):
        if not isinstance(task, dict):
            continue
        requests = task.get("workspace_requests", [])
        output.append({
            "task_id": task.get("task_id"),
            "stop_reason": task.get("stop_reason"),
            "executed_command_return_codes": task.get("executed_command_return_codes"),
            "requests": [
                {
                    "request_id": request.get("request_id"),
                    "invocation_sha256": request.get("invocation_sha256"),
                    "kernel_result": request.get("kernel_result"),
                    "runner_return_code": request.get("runner_return_code"),
                    "commit_outcome": request.get("commit_outcome"),
                    "read_scope": request.get("read_scope"),
                    "write_scope": request.get("write_scope"),
                }
                for request in requests if isinstance(request, dict)
            ],
        })
    return output


def app_identity(scratch: Path) -> dict[str, object]:
    app = scratch / "Khaos DSH XPC Acceptance.app"
    record_path = app / "Contents/Resources/build-inputs.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    verified = subprocess.run(
        ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
        check=False,
        capture_output=True,
        text=True,
    )
    details = subprocess.run(
        ["/usr/bin/codesign", "-dv", "--verbose=4", str(app)],
        check=False,
        capture_output=True,
        text=True,
    )
    combined = details.stdout + details.stderr
    fields = {}
    for line in combined.splitlines():
        for name in ("Identifier", "TeamIdentifier"):
            prefix = f"{name}="
            if line.startswith(prefix):
                fields[name.lower()] = line[len(prefix):]
    return {
        "bundle": str(app),
        "build_record_sha256": file_sha256(record_path),
        "source_sha": record.get("khaos_source_sha"),
        "dsh_sha": record.get("dsh_sha"),
        "node_version": record.get("node_version"),
        "signing_certificate_sha1": record.get("signing_certificate_sha1", record.get("certificate_sha1")),
        **fields,
        "deep_signature_verified": verified.returncode == 0,
        "signature_verification_returncode": verified.returncode,
    }


def clean_owned_scratch(scratch: Path, device: int, inode: int, fingerprint: str) -> tuple[bool, str]:
    return retention.cleanup_invocation_scratch(
        scratch,
        device,
        inode,
        expected_tree_fingerprint=fingerprint,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES, required=True)
    parser.add_argument("--dsh-source", type=Path, required=True)
    parser.add_argument("--node-archive", type=Path, required=True)
    parser.add_argument("--signing-identity", required=True)
    parser.add_argument("--evidence-path", type=Path, required=True)
    args = parser.parse_args()
    evidence_path = args.evidence_path.expanduser().absolute()
    retention.require_private_directory(evidence_path.parent.resolve(strict=True))
    if evidence_path.exists():
        parser.error("evidence path already exists")

    state: dict[str, object] = {"case": args.case}
    original_tempdir = tempfile.TemporaryDirectory

    def capture_tempdir(*values, **options):
        temporary = original_tempdir(*values, **options)
        state["temporary"] = temporary
        state["scratch"] = Path(temporary.name).resolve(strict=True)
        return temporary

    patches = [patch.object(acceptance.tempfile, "TemporaryDirectory", side_effect=capture_tempdir)]
    original_capture = acceptance.capture_failure_bundle
    original_cleanup = acceptance.cleanup_invocation_scratch

    if args.case == "archive-failure":
        def fail_after_signed_run(_path: Path) -> dict[str, object]:
            state["signed_runner_completed"] = True
            raise RuntimeError("injected post-run evidence archive failure")

        def incomplete_archive(_scratch: Path, destination: Path, **_options) -> dict[str, object]:
            destination.mkdir(mode=0o700)
            partial = destination / "incomplete.synthetic"
            descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
            state["archive_fault"] = "controlled partial archive write"
            return {
                "status": "INCOMPLETE",
                "directory": str(destination),
                "missing_required_files": ["injected_archive_write_interruption"],
                "source_tree_fingerprint_sha256": None,
                "source_tree_stable_during_capture": False,
            }

        patches.extend([
            patch.object(acceptance, "inventory_path", side_effect=fail_after_signed_run),
            patch.object(acceptance, "capture_failure_bundle", side_effect=incomplete_archive),
        ])
    elif args.case == "identity-substitution":
        def substitute_then_check(scratch: Path, device: int, inode: int, **options):
            parked = scratch.with_name(scratch.name + ".identity-test-parked")
            original = retention.inventory_path(scratch)
            if parked.exists():
                raise RuntimeError("identity test quarantine name already exists")
            os.rename(scratch, parked)
            scratch.mkdir(mode=0o700)
            marker = scratch / "replacement-marker.txt"
            marker.write_text("replacement remains unchanged\n", encoding="utf-8")
            state.update({
                "parked_original": parked,
                "original_inventory": original,
                "replacement_identity": (scratch.stat().st_dev, scratch.stat().st_ino),
            })
            result = original_cleanup(scratch, device, inode, **options)
            state["cleanup_result"] = result
            return result

        patches.append(patch.object(acceptance, "cleanup_invocation_scratch", side_effect=substitute_then_check))
    elif args.case == "active-reference":
        def active_reference(scratch: Path, device: int, inode: int, **options):
            target = scratch / "agent-task.txt"
            program = "import sys; f=open(sys.argv[1], 'rb'); print('READY', flush=True); sys.stdin.readline(); f.close()"
            child = subprocess.Popen(
                [sys.executable, "-c", program, str(target)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            state["reference_process_pid"] = child.pid
            try:
                selector = selectors.DefaultSelector()
                selector.register(child.stdout, selectors.EVENT_READ)
                if not selector.select(timeout=10) or child.stdout.readline().strip() != "READY":
                    raise RuntimeError("synthetic reference process did not become ready")
                observed, pids = retention.lsof_references(scratch)
                state["lsof_state"] = observed
                state["lsof_pids"] = pids
                if observed != "REFERENCED":
                    result = (False, "active_process_not_observed_by_lsof")
                else:
                    result = original_cleanup(
                        scratch,
                        device,
                        inode,
                        **options,
                        reference_check=lambda _path: (observed, pids),
                    )
                state["cleanup_result"] = result
                return result
            finally:
                if child.stdin is not None:
                    child.stdin.write("release\n")
                    child.stdin.flush()
                    child.stdin.close()
                child.wait(timeout=10)
                state["reference_process_exit"] = child.returncode

        patches.append(patch.object(acceptance, "cleanup_invocation_scratch", side_effect=active_reference))
    else:
        def unknown_reference(scratch: Path, device: int, inode: int, **options):
            result = original_cleanup(
                scratch,
                device,
                inode,
                **options,
                reference_check=lambda _path: ("UNKNOWN", []),
            )
            state["cleanup_result"] = result
            state["lsof_state"] = "CONTROLLED_UNKNOWN_INJECTION"
            return result

        patches.append(patch.object(acceptance, "cleanup_invocation_scratch", side_effect=unknown_reference))

    command = [
        "run_dsh_xpc_attack_acceptance.py",
        "--dsh-source", str(args.dsh_source.resolve(strict=True)),
        "--node-archive", str(args.node_archive.resolve(strict=True)),
        "--signing-identity", args.signing_identity,
        "--mode", "fake-result",
        "--operator", "codex_agent",
        "--operator-authorization", AUTHORIZATION,
        "--authorized-ui-scope", UI_SCOPE,
        "--evidence-path", str(evidence_path),
        "--timeout-seconds", "600",
    ]
    previous_argv = sys.argv
    run_error: BaseException | None = None
    try:
        with patch.object(sys, "argv", command):
            with ExitStack() as stack:
                for item in patches:
                    stack.enter_context(item)
                try:
                    exit_code = acceptance.main()
                except BaseException as error:
                    run_error = error
                    exit_code = 1
    finally:
        sys.argv = previous_argv

    scratch = state.get("scratch")
    if not isinstance(scratch, Path):
        raise RuntimeError("acceptance runner did not create an invocation scratch")
    runner_evidence = evidence_path.with_name(
        f"{evidence_path.stem}.failed.json" if args.case == "archive-failure" else evidence_path.name
    )
    report = json.loads(runner_evidence.read_text(encoding="utf-8"))
    retention_path = evidence_path.with_name(
        f"{evidence_path.stem}.failed-retention.json" if args.case == "archive-failure"
        else f"{evidence_path.stem}.retention.json"
    )
    retention_report = json.loads(retention_path.read_text(encoding="utf-8"))

    if args.case == "archive-failure":
        if not state.get("signed_runner_completed") or report.get("result") != "FAILED_ATTEMPT":
            raise RuntimeError("archive failure did not follow the signed Runner result")
        if retention_report.get("status") != "RETAINED_EVIDENCE_IDENTITY_OR_PROCESS_UNRESOLVED":
            raise RuntimeError("incomplete archive did not fail closed")
    elif exit_code != 0:
        raise RuntimeError(f"signed acceptance runner returned {exit_code}")

    app_path = scratch / "Khaos DSH XPC Acceptance.app"
    parked = state.get("parked_original")
    if isinstance(parked, Path):
        app_path = parked / app_path.name
    app_record = app_identity(scratch if app_path.parent == scratch else app_path.parent)
    task_records = process_records(report)
    artifact = report.get("artifact_retention", {})
    scratch_record = artifact.get("scratch_artifact", {}) if isinstance(artifact, dict) else {}
    observed_fingerprint = (
        scratch_record.get("tree_fingerprint_sha256")
        or retention_report.get("scratch_tree_fingerprint_sha256")
    )
    post_cleanup: list[dict[str, object]] = []

    if args.case == "identity-substitution":
        replacement_identity = state.get("replacement_identity")
        if not isinstance(replacement_identity, tuple) or not scratch.joinpath("replacement-marker.txt").is_file():
            raise RuntimeError("replacement fixture did not remain at the original invocation path")
        replacement_inventory = retention.inventory_path(scratch)
        cleaned, reason = clean_owned_scratch(
            scratch,
            int(replacement_inventory["device"]),
            int(replacement_inventory["inode"]),
            str(replacement_inventory["tree_fingerprint_sha256"]),
        )
        post_cleanup.append({"fixture": "replacement", "cleaned": cleaned, "reason": reason})
        if cleaned:
            parked = state["parked_original"]
            os.rename(parked, scratch)
            original = state["original_inventory"]
            cleaned, reason = clean_owned_scratch(
                scratch,
                int(original["device"]),
                int(original["inode"]),
                str(original["tree_fingerprint_sha256"]),
            )
            post_cleanup.append({"fixture": "parked_original", "cleaned": cleaned, "reason": reason})
    elif scratch.exists() and isinstance(scratch_record, dict) and observed_fingerprint:
        cleaned, reason = clean_owned_scratch(
            scratch,
            int(scratch_record["expected_device"]),
            int(scratch_record["expected_inode"]),
            str(observed_fingerprint),
        )
        post_cleanup.append({"fixture": "invocation_scratch", "cleaned": cleaned, "reason": reason})

    summary = {
        "schema": 1,
        "case": args.case,
        "operator": "codex_agent",
        "owner_personally_clicked": False,
        "authorization": AUTHORIZATION,
        "ui_scope": UI_SCOPE,
        "runner_result": report.get("result"),
        "runner_evidence_sha256": file_sha256(runner_evidence),
        "retention_record_sha256": file_sha256(retention_path),
        "signed_app": app_record,
        "source_sha": report.get("source_sha", app_record.get("source_sha")),
        "launcher_tasks": task_records,
        "evidence_result": (
            report.get("artifact_retention", {}).get("evidence_bundle")
            if isinstance(report.get("artifact_retention"), dict) else None
        ),
        "cleanup_status": retention_report.get("status"),
        "cleanup_reason": retention_report.get("reason"),
        "scratch_before_post_test_cleanup": {
            "device": scratch_record.get("observed_device", scratch_record.get("expected_device")),
            "inode": scratch_record.get("observed_inode", scratch_record.get("expected_inode")),
            "tree_fingerprint_sha256": observed_fingerprint,
        },
        "active_process_check": {
            "state": state.get("lsof_state", "CLEAR_BY_SIGNED_RUNNER_CHECK"),
            "pids": state.get("lsof_pids", []),
            "synthetic_process_exit": state.get("reference_process_exit"),
            "forced_termination": False,
        },
        "substitution_preserved": (
            state.get("cleanup_result", [None, None])[1] == "scratch_identity_changed"
            if args.case == "identity-substitution" else None
        ),
        "post_test_fixture_cleanup": post_cleanup,
        "driver_exception": f"{type(run_error).__name__}: {run_error}" if run_error else None,
        "historical_paths_accessed": False,
        "historical_mutations": 0,
        "model_or_GGUF_bundled": False,
    }
    summary_path = evidence_path.with_name(f"{evidence_path.stem}.retention-case.json")
    write_private(summary_path, summary)
    print(f"retention_case_evidence={summary_path}")
    print(f"retention_case_sha256={file_sha256(summary_path)}")
    return 0 if exit_code == 0 or args.case == "archive-failure" else exit_code


if __name__ == "__main__":
    raise SystemExit(main())
