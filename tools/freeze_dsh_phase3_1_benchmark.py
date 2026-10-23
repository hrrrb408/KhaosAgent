#!/usr/bin/env python3
"""Freeze Phase 3.1 coding and runtime inputs before signed model trials."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.dsh_phase3 import benchmark


PR44_HEAD = "391848b02a2ec4d095cef7f71f2e55947ec24b24"
PHASE3_DATASET_SHA256 = "033f5d9c776f025e21642911b6d13e2afcc32b876a39fab377ae0a6279dc5091"
SOURCE_INPUTS = (
    "experiments/dsh_phase3/benchmark.py",
    "experiments/dsh_phase3/test_benchmark.py",
    "experiments/dsh-feasibility/DSHAgentHostAcceptance.swift",
    "experiments/dsh-feasibility/dsh-agent-telemetry.ts",
    "experiments/dsh-feasibility/dsh-agenthost-runtime.ts",
    "experiments/dsh-feasibility/khaos-capability-adapter.ts",
    "experiments/dsh-feasibility/khaos-local-model.ts",
    "experiments/dsh-feasibility/khaos-model-bridge.ts",
    "experiments/dsh-feasibility/khaos-model-bridge.test.ts",
    "experiments/dsh-feasibility/khaos-semantic-tools.ts",
    "experiments/dsh-feasibility/khaos-semantic-tools.spec.ts",
    "experiments/dsh_phase3_1/test_signed_trial_evaluator.py",
    "tools/build_dsh_xpc_acceptance_app.py",
    "tools/run_dsh_xpc_attack_acceptance.py",
    "tools/run_dsh_feasibility_probe.py",
    "tools/run_dsh_model_bridge_tests.py",
    "tools/run_dsh_signed_runtime_probe.py",
    "tools/freeze_dsh_phase3_1_benchmark.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def command(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


def machine_facts() -> dict[str, str]:
    facts = {
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "python": sys.version.split()[0],
    }
    if platform.system() == "Darwin":
        facts["macos_version"] = platform.mac_ver()[0]
        try:
            facts["cpu"] = command("/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string")
            facts["memory_bytes"] = command("/usr/sbin/sysctl", "-n", "hw.memsize")
        except (OSError, subprocess.CalledProcessError):
            facts["hardware_details"] = "NOT_MEASURED"
    return facts


def task_records() -> dict[str, object]:
    result: dict[str, object] = {}
    for task_id, task in sorted(benchmark.TASKS.items()):
        result[task_id] = {
            "title": task.title,
            "original_prompt_sha256": digest_text(task.prompt),
            "public_fixture_sha256": {
                name: digest_text(contents) for name, contents in sorted(task.public_files.items())
            },
            "hidden_test_sha256": digest_text(task.hidden_test),
            "read_scope": list(task.read_scope),
            "write_scope": list(task.write_scope),
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-file", type=Path, required=True)
    parser.add_argument("--node-executable", type=Path, required=True)
    parser.add_argument("--node-archive", type=Path, required=True)
    parser.add_argument("--dsh-source", type=Path, required=True)
    parser.add_argument("--signed-app", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    model_file = args.model_file.expanduser().resolve(strict=True)
    node_executable = args.node_executable.expanduser().resolve(strict=True)
    node_archive = args.node_archive.expanduser().resolve(strict=True)
    dsh_source = args.dsh_source.expanduser().resolve(strict=True)
    signed_app = args.signed_app.expanduser().resolve(strict=True)
    output_path = args.output.expanduser().absolute()
    if output_path.exists():
        parser.error("--output must be new; frozen evidence is immutable")
    if benchmark.dataset_digest() != PHASE3_DATASET_SHA256:
        parser.error("Phase 3 benchmark task dataset differs from its frozen historical digest")

    source_sha = command("git", "rev-parse", "HEAD", cwd=ROOT)
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", PR44_HEAD, "HEAD"],
        cwd=ROOT,
        check=False,
    )
    if ancestry.returncode != 0:
        parser.error("Khaos source does not descend from the exact PR #44 HEAD")
    dsh_sha = command("git", "rev-parse", "HEAD", cwd=dsh_source)
    if dsh_sha != "687f282e8625c6b8d11ff58211a90524be2e4317":
        parser.error("DSH checkout does not match the pinned Phase 3 revision")
    if command("git", "status", "--porcelain", cwd=dsh_source):
        parser.error("DSH checkout must be clean before the benchmark is frozen")
    build_record_path = signed_app / "Contents/Resources/build-inputs.json"
    if not build_record_path.is_file():
        parser.error("signed app does not contain build-inputs.json")
    build_record = json.loads(build_record_path.read_text(encoding="utf-8"))
    if build_record.get("khaos_source_sha") != source_sha:
        parser.error("signed app source SHA differs from the current Khaos HEAD")
    if build_record.get("dsh_sha") != dsh_sha:
        parser.error("signed app DSH SHA differs from the pinned DSH checkout")
    if build_record.get("semantic_tools") is not True:
        parser.error("signed app was not built with the semantic-tool Candidate B script")
    inputs = {name: sha256(ROOT / name) for name in SOURCE_INPUTS}
    model_sha = sha256(model_file)
    build_model_sha = build_record.get("dsh_local_model", {}).get("sha256") \
        if isinstance(build_record.get("dsh_local_model"), dict) else None
    if build_model_sha is None and isinstance(build_record.get("dsh_local_model"), dict):
        build_model_sha = build_record["dsh_local_model"].get("model_sha256")
    if build_model_sha != model_sha:
        parser.error("signed app local model hash differs from the selected benchmark model")
    node_version = command(str(node_executable), "--version")
    if node_version != "v22.19.0":
        parser.error("Node executable does not match the frozen DSH Node version")

    record = {
        "schema": "khaos-dsh-phase3-1-benchmark-freeze-v1",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "historical_parent": {
            "phase3_pr44_head": PR44_HEAD,
            "phase3_dataset_sha256": PHASE3_DATASET_SHA256,
            "phase3_hidden_test_success": "0/8",
            "phase3_first_pass_success": "0/8",
            "phase3_repair_success": "0/2",
            "phase3_provenance_limit": "original oracle source hashes were incomplete; see reports/dsh-phase3/benchmark-freeze-audit.json",
            "phase3_raw_evidence_unchanged": True,
        },
        "experiment": {
            "khaos_source_sha": source_sha,
            "phase3_1_base_sha": PR44_HEAD,
            "dsh_sha": dsh_sha,
            "node_version": node_version,
            "node_executable_sha256": sha256(node_executable),
            "node_archive_sha256": sha256(node_archive),
            "model": {
                "file_name": model_file.name,
                "sha256": model_sha,
                "size_bytes": model_file.stat().st_size,
                "upstream_identity": "UNKNOWN; Phase 3 evidence did not record it",
                "quantization": "NOT_MEASURED",
                "provider": "local CPU-only llama.cpp",
            },
            "signed_app_build_inputs_sha256": sha256(build_record_path),
            "signed_app_build_source_sha256": build_record.get("source_sha256", {}),
            "signed_app_test_only_source_sha256": build_record.get("test_only_sources_sha256", {}),
            "signing_certificate_sha1": build_record.get("certificate_sha1"),
            "llama_runtime": build_record.get("dsh_local_model"),
            "signed_app_bundle_sha256": sha256(
                signed_app / "Contents/XPCServices/KhaosAgentHost.xpc/Contents/MacOS/KhaosAgentHost"
            ),
            "source_inputs_sha256": inputs,
            "machine": machine_facts(),
        },
        "benchmark": {
            "dataset_sha256": benchmark.dataset_digest(),
            "original_prompts_preserved": True,
            "tasks": task_records(),
            "limits": {
                "max_tool_operations_per_task": 8,
                "max_write_operations_per_task": 3,
                "max_repair_attempts_per_task": 3,
                "max_wall_time_seconds_per_task": 600,
            },
            "hidden_tests_outside_model_workspace": True,
            "independent_verification": "experiments/dsh_phase3/benchmark.py:verify_hidden",
        },
        "model_input_contract": {
            "user_prompt": "exact original Task.prompt from benchmark.py",
            "semantic_system_instructions": "source-hash-bound in dsh-agenthost-runtime.ts",
            "tool_schemas_and_lowering": "source-hash-bound in khaos-semantic-tools.ts",
            "workspace_data_remote_transfer": "none; local model only",
            "model_output_is_untrusted": True,
        },
        "operator_policy": {
            "operator": "codex_agent",
            "authorization": "Owner-delegated disposable experiment",
            "owner_personally_clicked": False,
            "production_approval": False,
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.chmod(output_path, 0o600)
    print(f"freeze_sha256={sha256(output_path)}")
    print(f"manifest={output_path}")
    print(f"khaos_source_sha={source_sha}")
    print(f"dsh_sha={dsh_sha}")
    print(f"model_sha256={model_sha}")
    print(f"node_sha256={sha256(node_executable)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
