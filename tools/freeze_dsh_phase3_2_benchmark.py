#!/usr/bin/env python3
"""Freeze Phase 3.2 task, runtime, and harness inputs before model evaluation."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

from dsh_phase3 import benchmark as phase3_benchmark  # noqa: E402
from dsh_phase3_2 import benchmark as phase32_benchmark  # noqa: E402

PHASE31_FREEZE_SHA256 = "ff0075a1f44b21be91e685c153a6fb22bb4f02301a62496e930bbc81de35f65d"
PHASE31_DATASET_SHA256 = "033f5d9c776f025e21642911b6d13e2afcc32b876a39fab377ae0a6279dc5091"
PHASE31_MODEL_SHA256 = "fadc3e5f8d42bf7e894a785b05082e47daee4df26680389817e2093056f088ad"
PHASE31_NODE_ARCHIVE_SHA256 = "1c3a9e78da501bbc1f0c99fbbb69bb7c722bc7a9bf30128b21ea502f3905892a"
BASE_SHA = "8ddabbcfdfcc2af8899ca30a4717ec82c4014b21"
DSH_SHA = "687f282e8625c6b8d11ff58211a90524be2e4317"

SOURCE_FILES = (
    "experiments/dsh-feasibility/DSHAgentHostAcceptance.swift",
    "experiments/dsh-feasibility/DSHModelBridgeProtocol.swift",
    "experiments/dsh-feasibility/DSHModelBridgeService.swift",
    "experiments/dsh-feasibility/DSHModelBridgePeerProbe.swift",
    "experiments/dsh-feasibility/dsh-agent-telemetry.ts",
    "experiments/dsh-feasibility/dsh-agenthost-runtime.ts",
    "experiments/dsh-feasibility/khaos-model-bridge.ts",
    "experiments/dsh-feasibility/dsh-tool-result.ts",
    "experiments/dsh-feasibility/khaos-local-model.ts",
    "experiments/dsh-feasibility/khaos-semantic-tools.ts",
    "experiments/dsh-feasibility/khaos-semantic-tools.spec.ts",
    "experiments/dsh-feasibility/dsh-semantic-fixture.ts",
    "experiments/dsh-feasibility/dsh-capability-lifecycle-probe.ts",
    "experiments/dsh-feasibility/khaos-capability-adapter.ts",
    "experiments/dsh-feasibility/malicious-cordis-plugin.ts",
    "experiments/dsh-feasibility/khaos-model-bridge.test.ts",
    "experiments/dsh_phase3/benchmark.py",
    "experiments/dsh_phase3/test_acceptance_policy.py",
    "experiments/dsh_phase3/test_benchmark.py",
    "experiments/dsh_phase3/plugin_evolution/tag-plugin.ts",
    "experiments/dsh_phase3/plugin_evolution/baseline.ts",
    "experiments/dsh_phase3/plugin_evolution/candidate_v1.ts",
    "experiments/dsh_phase3/plugin_evolution/malicious_candidate.ts",
    "experiments/dsh_phase3/plugin_evolution/runner.ts",
    "experiments/dsh_phase3_2/benchmark.py",
    "experiments/dsh_phase3_2/test_benchmark.py",
    "experiments/dsh_phase3_2/evaluate_trials.py",
    "experiments/dsh_phase3_2/test_evaluate_trials.py",
    "experiments/dsh_phase3_2/sandboxed_eval.py",
    "tools/build_dsh_xpc_acceptance_app.py",
    "tools/run_dsh_xpc_attack_acceptance.py",
    "tools/run_dsh_signed_runtime_probe.py",
    "tools/run_dsh_feasibility_probe.py",
    "tools/run_dsh_model_bridge_tests.py",
    "tools/run_dsh_plugin_evaluation.py",
    "tools/freeze_dsh_phase3_2_benchmark.py",
    "tests/signed_cancellation_fixture.py",
    "tests/macos_xpc_probe/TrustedEditApprovalProbe.swift",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def task_records() -> dict[str, object]:
    return {
        task_id: phase32_benchmark.task_record(task)
        | {
            "max_tool_operations": phase32_benchmark.MAX_TOOL_OPERATIONS,
            "max_write_operations": phase32_benchmark.MAX_WRITE_OPERATIONS,
            "max_repair_attempts": phase32_benchmark.MAX_REPAIR_ATTEMPTS,
            "max_wall_time_seconds": phase32_benchmark.MAX_WALL_TIME_SECONDS,
        }
        for task_id, task in sorted(phase32_benchmark.TASKS.items())
    }


def build_manifest(
    *, dsh_source: Path, node_archive: Path, node_binary: Path, model_file: Path,
    model_runtime: Path, model_license: Path, frozen_at_utc: str,
    implementation_commit_sha: str | None = None,
) -> dict[str, object]:
    phase31_path = ROOT / "reports/dsh-phase3-1/benchmark-freeze.json"
    phase31_sha = sha256(phase31_path)
    if phase31_sha != PHASE31_FREEZE_SHA256:
        raise RuntimeError(f"Phase 3.1 freeze changed: {phase31_sha}")
    phase31 = json.loads(phase31_path.read_text(encoding="utf-8"))
    if phase31.get("benchmark", {}).get("dataset_sha256") != PHASE31_DATASET_SHA256:
        raise RuntimeError("Phase 3.1 dataset digest does not match its historical report")
    if sha256(model_file) != PHASE31_MODEL_SHA256:
        raise RuntimeError("the local model differs from the Phase 3.1 frozen model")
    if sha256(node_archive) != PHASE31_NODE_ARCHIVE_SHA256:
        raise RuntimeError("the Node archive differs from the Phase 3.1 frozen runtime")
    if git(dsh_source, "rev-parse", "HEAD") != DSH_SHA:
        raise RuntimeError("DSH source is not at the frozen upstream revision")
    if git(dsh_source, "status", "--porcelain"):
        raise RuntimeError("DSH source tree has uncommitted changes")
    node_version = subprocess.run(
        [str(node_binary), "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if node_version != "v22.19.0":
        raise RuntimeError(f"Node version differs from Phase 3.1: {node_version}")

    return {
        "schema": "khaos-dsh-phase3-2-benchmark-freeze-v1",
        "frozen_at_utc": frozen_at_utc,
        "experiment": {
            "phase": "3.2",
            "branch_base_sha": BASE_SHA,
            "required_head_sha": BASE_SHA,
            "implementation_commit_sha": implementation_commit_sha or git(ROOT, "rev-parse", "HEAD"),
            "phase31_freeze_sha256": phase31_sha,
            "phase31_dataset_sha256": PHASE31_DATASET_SHA256,
            "phase31_results_preserved": {
                "trials": 8,
                "hidden_test_success": "6/8",
                "first_pass_success": "4/8",
                "task_c_repair_success": "2/2",
                "task_d_success": "0/2",
            },
            "phase3_original_result_preserved": {
                "hidden_test_success": "0/8",
                "first_pass_success": "0/8",
            },
        },
        "runtime": {
            "dsh_sha": git(dsh_source, "rev-parse", "HEAD"),
            "dsh_expected_sha": DSH_SHA,
            "node_version": node_version,
            "node_archive_sha256": sha256(node_archive),
            "node_binary_sha256": sha256(node_binary),
            "model_upstream_identity": "UNKNOWN; Phase 3.1 did not record a verified upstream model name",
            "model_file_sha256": sha256(model_file),
            "model_runtime_sha256": sha256(model_runtime),
            "model_license_sha256": sha256(model_license),
            "model_quantization": "NOT_MEASURED",
            "provider": "local_cpu_llama_cpp",
            "remote_data_transfer": False,
        },
        "datasets": {
            "phase31_replay": {
                "task_ids": list(phase3_benchmark.TASKS),
                "dataset_sha256": phase3_benchmark.dataset_digest(),
                "task_prompts_preserved": True,
                "task_fixtures_and_hidden_tests_bound_by": "reports/dsh-phase3-1/benchmark-freeze.json",
                "max_tool_operations": 8,
                "max_write_operations": 3,
                "max_repair_attempts": 3,
                "max_wall_time_seconds": 600,
            },
            "phase32_holdout": {
                "task_ids": list(sorted(phase32_benchmark.TASKS)),
                "task_count": len(phase32_benchmark.TASKS),
                "dataset_sha256": phase32_benchmark.dataset_digest(),
                "task_records": task_records(),
                "max_tool_operations": phase32_benchmark.MAX_TOOL_OPERATIONS,
                "max_write_operations": phase32_benchmark.MAX_WRITE_OPERATIONS,
                "max_repair_attempts": phase32_benchmark.MAX_REPAIR_ATTEMPTS,
                "max_wall_time_seconds": phase32_benchmark.MAX_WALL_TIME_SECONDS,
            },
        },
        "trial_plan": {
            "phase32_stage_b_task_a_trials": 2,
            "phase31_task_d_replays": 2,
            "phase32_holdout_trials": 16,
            "phase31_a_to_d_comparison_trials": 8,
            "minimum_total_trials": 24,
            "planned_total_trials_including_focused_and_d_replays": 28,
            "trial_ids_per_task": ["1", "2"],
            "operator": "codex_agent",
            "authorization": "Owner-delegated disposable experiment",
            "owner_personally_clicked": False,
        },
        "source_sha256": {name: sha256(ROOT / name) for name in SOURCE_FILES},
        "dataset_sha256": phase32_benchmark.dataset_digest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsh-source", type=Path, required=True)
    parser.add_argument("--node-archive", type=Path, required=True)
    parser.add_argument("--node-binary", type=Path, required=True)
    parser.add_argument("--model-file", type=Path, required=True)
    parser.add_argument("--model-runtime", type=Path, required=True)
    parser.add_argument("--model-license", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports/dsh-phase3-2/benchmark-freeze.json",
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = args.output.expanduser().absolute()
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if args.check:
        if not output.is_file():
            parser.error("freeze manifest does not exist")
        recorded = json.loads(output.read_text(encoding="utf-8"))
        current = build_manifest(
            dsh_source=args.dsh_source.expanduser().resolve(strict=True),
            node_archive=args.node_archive.expanduser().resolve(strict=True),
            node_binary=args.node_binary.expanduser().resolve(strict=True),
            model_file=args.model_file.expanduser().resolve(strict=True),
            model_runtime=args.model_runtime.expanduser().resolve(strict=True),
            model_license=args.model_license.expanduser().resolve(strict=True),
            frozen_at_utc=recorded.get("frozen_at_utc", now),
            implementation_commit_sha=recorded.get("experiment", {}).get("implementation_commit_sha"),
        )
        if recorded != current:
            raise SystemExit("FAIL: frozen benchmark inputs or source hashes changed")
        print(f"PASS: frozen dataset_sha256={current['dataset_sha256']}")
        print(f"manifest_sha256={sha256(output)}")
        return 0

    if output.exists():
        parser.error("freeze output already exists; it is immutable")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(
        dsh_source=args.dsh_source.expanduser().resolve(strict=True),
        node_archive=args.node_archive.expanduser().resolve(strict=True),
        node_binary=args.node_binary.expanduser().resolve(strict=True),
        model_file=args.model_file.expanduser().resolve(strict=True),
        model_runtime=args.model_runtime.expanduser().resolve(strict=True),
        model_license=args.model_license.expanduser().resolve(strict=True),
        frozen_at_utc=now,
    )
    output.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: frozen dataset_sha256={manifest['dataset_sha256']}")
    print(f"manifest_sha256={sha256(output)}")
    print(f"output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
