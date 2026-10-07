from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from khaos.kernel.plugin_lifecycle import (
    PluginCandidate,
    read_plugin_state,
    replace_plugin_state,
)
from khaos.launcher import run_workspace_command


EVALUATION_FORMAT = "khaos-memory-eval-v1"
EVALUATOR_VERSION = "fixed-memory-replay-v2"


@dataclass(frozen=True)
class SampleResult:
    sample_id: str
    passed: bool
    output: dict[str, Any]
    state_sha256: str | None


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
        request = sample.get("request") if type(sample) is dict else None
        expected = sample.get("expected") if type(sample) is dict else None
        valid_recall = (
            type(request) is dict
            and request.get("operation") == "recall"
            and set(request) == {"key", "operation"}
            and type(request.get("key")) is str
            and type(expected) is dict
            and set(expected) == {"found", "value"}
            and type(expected["found"]) is bool
            and (
                expected["value"] is None
                or type(expected["value"]) is str
            )
        )
        valid_remember = (
            type(request) is dict
            and request.get("operation") == "remember"
            and set(request) == {"key", "operation", "value"}
            and type(request.get("key")) is str
            and type(request.get("value")) is str
            and type(expected) is dict
            and expected == {"remembered": True}
        )
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
            or not (valid_recall or valid_remember)
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
    samples_by_id = {sample["id"]: sample for sample in dataset["samples"]}
    candidate_result = CandidateResult(
        candidate_digest=candidate_result.candidate_digest,
        manifest_digest=candidate_result.manifest_digest,
        scope_digest=candidate_result.scope_digest,
        sample_results=tuple(
            SampleResult(
                result.sample_id,
                result.passed and _state_compatible(
                    samples_by_id[result.sample_id],
                    baseline_by_id[result.sample_id],
                    result,
                ),
                result.output,
                result.state_sha256,
            )
            for result in candidate_result.sample_results
        ),
    )
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
        state_after = read_plugin_state(state_root, "memory")
        if sample["request"]["operation"] == "recall" and state_after != initial_state:
            raise AssertionError("Memory recall changed isolated state")
        output = json.loads(result.stdout)
        if type(output) is not dict:
            raise AssertionError("Memory evaluation output must be an object")
        expected = sample["expected"]
        request = sample["request"]
        if request["operation"] == "recall":
            passed = (
                output.get("operation") == "recall"
                and output.get("key") == request["key"]
                and type(output.get("found")) is bool
                and output.get("found") is expected["found"]
                and output.get("value") == expected["value"]
            )
        else:
            passed = (
                output.get("operation") == "remember"
                and output.get("key") == request["key"]
                and output.get("remembered") is expected["remembered"]
            )
        state_digest = (
            hashlib.sha256(state_after).hexdigest()
            if state_after is not None
            else None
        )
        sample_results.append(
            SampleResult(sample["id"], passed, output, state_digest)
        )
    return CandidateResult(
        candidate_digest=candidate.candidate_digest,
        manifest_digest=candidate.manifest_digest,
        scope_digest=candidate.scope_digest,
        sample_results=tuple(sample_results),
    )


def _state_compatible(
    sample: dict[str, Any],
    baseline: SampleResult,
    candidate: SampleResult,
) -> bool:
    request = sample["request"]
    if request["operation"] == "remember":
        return (
            baseline.state_sha256 is not None
            and baseline.state_sha256 != _initial_state_digest(sample)
            and candidate.state_sha256 == baseline.state_sha256
        )
    return candidate.state_sha256 == _initial_state_digest(sample)


def _initial_state_digest(sample: dict[str, Any]) -> str:
    return hashlib.sha256(
        _canonical({"format": "khaos-memory-v1", "items": sample["initial_items"]})
    ).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8", errors="strict")
