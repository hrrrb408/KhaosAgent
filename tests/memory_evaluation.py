from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from khaos.kernel.plugin_lifecycle import PluginCandidate, replace_plugin_state
from khaos.launcher import run_workspace_command


EVALUATION_FORMAT = "khaos-memory-eval-v1"
EVALUATOR_VERSION = "fixed-memory-replay-v1"


@dataclass(frozen=True)
class SampleResult:
    sample_id: str
    passed: bool
    output: dict[str, Any]


@dataclass(frozen=True)
class CandidateResult:
    candidate_digest: str
    manifest_digest: str
    scope_digest: str
    sample_results: tuple[SampleResult, ...]

    @property
    def passed(self) -> int:
        return sum(result.passed for result in self.sample_results)

    @property
    def failed(self) -> int:
        return len(self.sample_results) - self.passed


@dataclass(frozen=True)
class MemoryEvaluation:
    baseline: CandidateResult
    candidate: CandidateResult
    dataset_digest: str
    sample_count: int
    regressions: tuple[str, ...]
    improvements: tuple[str, ...]

    def review_record(self) -> dict[str, object]:
        return {
            "baseline_digest": self.baseline.candidate_digest,
            "baseline_fail": self.baseline.failed,
            "baseline_pass": self.baseline.passed,
            "candidate_digest": self.candidate.candidate_digest,
            "candidate_fail": self.candidate.failed,
            "candidate_manifest_digest": self.candidate.manifest_digest,
            "candidate_pass": self.candidate.passed,
            "candidate_scope_digest": self.candidate.scope_digest,
            "dataset_digest": self.dataset_digest,
            "evaluator_version": EVALUATOR_VERSION,
            "format": EVALUATION_FORMAT,
            "improvements": list(self.improvements),
            "regressions": list(self.regressions),
            "sample_count": self.sample_count,
        }


def load_dataset(dataset_path: Path) -> tuple[bytes, dict[str, Any]]:
    encoded = dataset_path.read_bytes()
    dataset = json.loads(encoded.decode("utf-8", errors="strict"))
    if (
        type(dataset) is not dict
        or set(dataset) != {"format", "samples"}
        or dataset["format"] != EVALUATION_FORMAT
        or type(dataset["samples"]) is not list
        or not dataset["samples"]
        or len(dataset["samples"]) > 128
        or _canonical(dataset) != encoded
    ):
        raise ValueError("Memory evaluation dataset is not canonical")
    sample_ids: set[str] = set()
    for sample in dataset["samples"]:
        if (
            type(sample) is not dict
            or set(sample) != {"expected", "id", "initial_items", "request"}
            or type(sample["id"]) is not str
            or not sample["id"]
            or sample["id"] in sample_ids
            or type(sample["initial_items"]) is not dict
            or any(
                type(key) is not str or type(value) is not str
                for key, value in sample["initial_items"].items()
            )
            or type(sample["request"]) is not dict
            or sample["request"].get("operation") != "recall"
            or type(sample["expected"]) is not dict
            or set(sample["expected"]) != {"found", "value"}
            or type(sample["expected"]["found"]) is not bool
            or (
                sample["expected"]["value"] is not None
                and type(sample["expected"]["value"]) is not str
            )
        ):
            raise ValueError("Memory evaluation sample is invalid")
        sample_ids.add(sample["id"])
    return encoded, dataset


def evaluate_memory_candidates(
    baseline: PluginCandidate,
    candidate: PluginCandidate,
    dataset_path: Path,
    *,
    scratch: Path,
) -> MemoryEvaluation:
    dataset_bytes, dataset = load_dataset(dataset_path)
    scratch.mkdir(parents=True, exist_ok=False)
    baseline_result = _evaluate_candidate(
        baseline, dataset["samples"], scratch / "baseline"
    )
    candidate_result = _evaluate_candidate(
        candidate, dataset["samples"], scratch / "candidate"
    )
    baseline_by_id = {item.sample_id: item for item in baseline_result.sample_results}
    candidate_by_id = {item.sample_id: item for item in candidate_result.sample_results}
    regressions = tuple(
        sample_id
        for sample_id, result in baseline_by_id.items()
        if result.passed and not candidate_by_id[sample_id].passed
    )
    improvements = tuple(
        sample_id
        for sample_id, result in baseline_by_id.items()
        if not result.passed and candidate_by_id[sample_id].passed
    )
    return MemoryEvaluation(
        baseline=baseline_result,
        candidate=candidate_result,
        dataset_digest=hashlib.sha256(dataset_bytes).hexdigest(),
        sample_count=len(dataset["samples"]),
        regressions=regressions,
        improvements=improvements,
    )


def verify_evaluation_binding(
    record: dict[str, object],
    *,
    candidate_digest: str,
    manifest_digest: str,
    scope_digest: str,
    baseline_digest: str,
    dataset_bytes: bytes,
) -> None:
    expected = {
        "candidate_digest": candidate_digest,
        "candidate_manifest_digest": manifest_digest,
        "candidate_scope_digest": scope_digest,
        "baseline_digest": baseline_digest,
        "dataset_digest": hashlib.sha256(dataset_bytes).hexdigest(),
    }
    if any(record.get(key) != value for key, value in expected.items()):
        raise ValueError("Memory evaluation binding is stale")


def _evaluate_candidate(
    candidate: PluginCandidate,
    samples: list[dict[str, Any]],
    state_parent: Path,
) -> CandidateResult:
    if candidate.manifest.plugin_id != "memory":
        raise ValueError("evaluation candidate must keep the memory Plugin ID")
    if (
        candidate.manifest.process_exec
        or candidate.manifest.read_scope
        or candidate.manifest.write_scope
    ):
        raise ValueError("Memory evaluation candidates must remain state-only")
    state_parent.mkdir(parents=True, exist_ok=False)
    sample_results: list[SampleResult] = []
    for index, sample in enumerate(samples):
        state_root = state_parent / str(index)
        workspace = state_parent / f"workspace-{index}"
        workspace.mkdir()
        initial_state = _canonical(
            {"format": "khaos-memory-v1", "items": sample["initial_items"]}
        )
        replace_plugin_state(state_root, "memory", initial_state)
        result = run_workspace_command(
            workspace,
            runner_source=candidate.source.decode("utf-8", errors="strict"),
            process_exec_allowed=False,
            plugin_id="memory",
            plugin_state_root=state_root,
            plugin_input=sample["request"],
            timeout_seconds=10,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"Memory evaluation Runner failed for {sample['id']}: {result.stderr}"
            )
        if (result.added, result.modified, result.deleted) != (0, 0, 0):
            raise AssertionError("Memory evaluation changed its workspace")
        if any(workspace.iterdir()):
            raise AssertionError("Memory evaluation left a workspace entry")
        if _read_state(state_root) != initial_state:
            raise AssertionError("read-only Memory evaluation changed isolated state")
        output = json.loads(result.stdout)
        if type(output) is not dict:
            raise AssertionError("Memory evaluation output must be an object")
        expected = sample["expected"]
        # Only the public recall result is scored. Extra Candidate fields such
        # as a self-reported score do not affect evaluation.
        passed = (
            output.get("operation") == "recall"
            and output.get("key") == sample["request"]["key"]
            and type(output.get("found")) is bool
            and output.get("found") is expected["found"]
            and output.get("value") == expected["value"]
        )
        sample_results.append(SampleResult(sample["id"], passed, output))
    return CandidateResult(
        candidate_digest=candidate.candidate_digest,
        manifest_digest=candidate.manifest_digest,
        scope_digest=candidate.scope_digest,
        sample_results=tuple(sample_results),
    )


def _read_state(state_root: Path) -> bytes | None:
    path = state_root / "memory" / "state.json"
    return path.read_bytes() if path.exists() else None


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8", errors="strict")
