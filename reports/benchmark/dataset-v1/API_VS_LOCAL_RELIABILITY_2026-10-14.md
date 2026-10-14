# Khaos Coding Agent Reliability Baseline

- **Updated:** 2026-10-15 (formal model runs were completed on 2026-10-14)
- **Repository baseline:** `95cad40cdf2540ffa409a5ec276d53720d6f9ce8`
- **Dataset:** v1, 12 frozen tasks, manifest SHA-256 `ffa69ed0e27e50f94d48feae9cc56828b87838020d1f3871a7664be2b547d491`

## Executive result

The CPU-only Qwen3.8-27B feasibility gate passed. The signed-product AgentHost also completed one bounded read/edit/verify smoke in 27m24s. These results establish that this setup can run the model and complete a small coding task, but they do not establish benchmark reliability.

Both formal 12-task runs completed through the real signed product and its existing AgentHost → Trusted Launcher → Kernel → Seatbelt Runner path. GLM-5.3-Flash Coding Plan received the product's separate data-send approval for all 12 formal tasks. The remote client ran in the untrusted AgentHost with no local fallback; the Kernel remained outside that remote data flow. Neither model produced a candidate change in any task: **Qwen completed 0/12 and GLM completed 0/12**. All 24 formal workspaces are clean, and the hidden grader copied zero candidate paths for each run.

The same focused test commands were run against both models' unchanged workspaces. Eight task suites pass on the untouched baseline and on the gold change; four Runner repair suites fail on the untouched baseline. These are baseline checks, not model scores. For the four discriminating tasks, neither model supplied a candidate to grade. The three test-only tasks require the fault-injection checks specified in the manifest; those checks were not run, so their regular test-command passes do not score task completion.

**Recommendation:** keep Qwen3.8-27B out of the default coding-model slot for now. It runs CPU-only with stable 8K/16K settings and passed one real product smoke, but it completed none of the frozen tasks and incurs long waits. GLM did not outperform it on task completion in this run. Since neither completed a task, these results do not support a model-quality ranking.

## Phase gates

| Phase | Result | Evidence |
|---|---|---|
| Phase 0: CPU-only Qwen feasibility | PASS | 8K and 16K runs stable; 5.87 generation tok/s and 16.44 prompt tok/s average; no swap increase attributable to the runs. [Phase 0 report](../../qwen38-phase0-2026-10-14.md) |
| Phase 1: AgentHost compatibility | PASS, one smoke | Signed product completed one four-operation read/edit/verify task; parent retest returned 0 in 27m24s. This is a narrow smoke, not a reliability result. [Phase 1 report](../../qwen38-agenthost-compatibility-2026-10-14.md) |
| Phase 2: frozen dataset | PASS | 12 task prompts, disposable baselines, test commands, and grading patches frozen before model runs. [Dataset notes](DATASET.md) |
| Phase 3: GLM-5.3-Flash Coding Plan | ATTEMPTED; 0/12 completed | All 12 formal task data prompts were approved in the signed product. No candidate file changed. |
| Phase 4: Qwen3.8-27B | ATTEMPTED; 0/12 completed | 12 formal task attempts; no candidate file changed. Earlier five IPC attempts were preflight/timeout attempts; formal IPC attempt is `attempt-06`. |
| Phase 5: grading and analysis | COMPLETE WITH LIMITATIONS | The same grading commands ran for 12 API and 12 local attempts. Four suites distinguish baseline from gold. The three test-only tasks still need their manifest-specified fault injections for a task-level score. |

## Reliability comparison

| Measure | GLM-5.3-Flash Coding Plan | Qwen3.8-27B CPU-only |
|---|---:|---:|
| Formal tasks attempted | 12 | 12 |
| Tasks with a model-produced candidate | 0 | 0 |
| Candidate paths copied into grader | 0 | 0 |
| Task completion | 0/12 | 0/12 |
| Focused grader command groups passing on unchanged workspace | 8/12 | 8/12 |
| Focused grader command groups failing on unchanged workspace | 4/12 | 4/12 |
| Model tokens / API cost | Not exposed by Agent protocol | Not applicable |

The 8 passing suites are not eight model successes: the baseline already passes them. The 4 failing suites correspond to the Runner diagnostics/startup/exception/peer-socket tasks, where the required changes are absent. For task-only regression-test work, the ordinary suite can pass without proving that the added test catches its intended fault; those tests remain unscored here because the mutation/fault-injection checks were not run.

The comparison is tied to this Khaos-specific sample. It is not a general software-engineering benchmark score, and public source history means pretraining contamination cannot be ruled out.

## Per-task outcomes

| Task | Qwen3.8-27B observation | GLM-5.3-Flash observation | Baseline grading interpretation |
|---|---|---|---|
| `ipc-json-depth-bounds` | Guessed a nonexistent root path; read returned 1; no patch. | Guessed nonexistent `ipc_.py` / `test_ipc_.py`; read returned 1, then asked for exact paths. | Test passes on baseline and gold; non-discriminating. |
| `plugin-package-grant` | Guessed a root path; first read returned 1; second wrong-path proposal was cancelled. | Asked for exact source paths before proposing a tool. | Test passes on baseline and gold; non-discriminating. |
| `macos26-agent-generation-api` | Root read and directory listing without read scope returned 1. | Kernel rejected one proposal as invalid argv or workspace scope before Runner execution. | Test passes on baseline and gold; non-discriminating. The scope denial is fail-closed behavior, not evidence of a Kernel defect. |
| `trusted-kernel-apfs-trim` | Asked for repository paths; no proposal. | Asked for exact paths; no proposal. | Test passes on baseline and gold; non-discriminating. |
| `runner-failure-diagnostics` | No proposal; response said repository context was missing. | Approved read of `README.md` and `AGENTS.md` stopped with `runner_failed`; no result returned. | Discriminating suite fails without the requested diagnostics implementation. |
| `runner-startup-classification` | Asked for exact Runner paths; no proposal. | Guessed `runner.py` / `test_runner.py` (return 1), then an approved read stopped with `runner_failed`. | Worker suite fails because the required classifier is absent; broker suite passes. |
| `runner-exception-classification` | Guessed a wrong root path (return 1), then asked for exact paths. | Guessed `runner.py` / `test_runner.py` (return 1), then asked for exact paths. | Discriminating worker suite fails without the exception-classification change. |
| `runner-peer-socket-race` | Asked for parent/child socket source paths; no proposal. | Guessed `runner.py` / `test_runner.py`; read returned 1, then asked for exact paths. | Discriminating peer and worker suites fail without the race fix. |
| `nested-image-cleanup-reconciliation` | Two wrong-path reads returned 1; no patch. | Guessed nonexistent fixture paths in two approved reads; both returned 1. | Test passes on baseline and gold; non-discriminating. |
| `pipe-handshake-diagnostic-test` | Wrong-path read failed, then a later Runner request failed. | Approved read of `README.md` and `AGENTS.md` stopped with `runner_failed`. | Regular worker suite passes on the grader copy. Manifest fault-sensitivity check was not run; no model test change was produced. |
| `bounded-lifecycle-acceptance-wait` | Asked for the signed-product lifecycle test path; no proposal. | Approved read of the lifecycle test stopped with `commit_rejected`; no accepted command result was returned. | Focused signed-product test passes on the grader copy. Missing-marker fault injection was not run; no model test change was produced. |
| `replacement-racer-termination-wait` | Asked for the workspace-race test path; no proposal. | Two wrong-path reads returned 1; no patch. | Workspace-changes suite passes on the grader copy. Delayed-child fault injection was not run; no model test change was produced. |

Sanitized `run.json` and `grade.json` records for the 24 formal attempts are committed under [`published-runs`](published-runs/README.md). They retain the per-attempt results while redacting local paths and raw log locations. Full workspaces, grader copies, preflight attempts, and raw stdout/stderr remain in the local evidence archive and are not part of this public commit. API task 1's formal attempt is `attempt-04`; its earlier Launch Services preflight attempts remain local. Local task 1's formal attempt is `attempt-06`; earlier preflight/timeout attempts remain local.

## Agent behavior, execution, and attribution limits

The formal GLM runs recorded 13 tool proposals: 12 received a user tool approval and one invalid-scope proposal was rejected before approval. Eight command return codes reached the Agent record, all 1. Three more approved requests stopped with `runner_failed`; one approved request returned `commit_rejected` with no accepted command return code. Attempt records sum to 38.989 seconds of Runner time, including requests that later failed; the invalid-scope proposal was rejected before Runner execution. No task exhausted the 8-call or 180-second cumulative Runner budget.

The event logs record 12 separate remote-data approvals and 12 tool-approval dialogs. Their presentation-to-decision intervals sum to about 132 seconds for the data gates and 185 seconds for tool approvals. These are logged UI intervals, not model latency or pure user-think time. Task process intervals include model calls, approvals, and product lifecycle, and some task intervals overlap, so they are not summed or treated as model-response time.

Qwen's earlier reliability run sampled 4,709 seconds of `llama-cli` process lifetime across 11 telemetry-complete attempts. This includes model process startup/loading and multiple turns; it is not pure decode time. The IPC task lacks a usable process series. Sampled model RSS was 32.76–33.87 GiB. System-wide swap samples were about 2.39–2.41 GiB with no per-process attribution or reliable per-task delta. See the [Phase 0 report](../../qwen38-phase0-2026-10-14.md) and [Phase 1 report](../../qwen38-agenthost-compatibility-2026-10-14.md) for their separate measurements.

The Agent protocol does not expose reliable per-turn inference time, token counts, or API cost for these coding attempts. Raw first-output Action JSON and correction counts were not retained consistently, so Action JSON validity and false-success claim rates are unknown. No budget exhaustion was observed. The reports do not infer missing values as zero.

`runner_failed` and `commit_rejected` are the bounded errors surfaced to the Agent. The stored task record does not expose a lower-level cause for these requests. They are recorded as unresolved Runner/Kernel execution failures; this benchmark does not establish a product defect or its root cause. The invalid-scope request is separately classified as a correct security denial.

## Three main bottlenecks

1. **Workspace path discovery and scoped tool planning.** Both models asked for exact paths, guessed nonexistent root-level files, or submitted a scope that the Kernel rejected. This is the most consistent observed blocker across the two models. It does not prove that the ABI lacks discovery; it shows that these runs did not successfully discover the relevant source paths.
2. **Opaque fail-closed execution errors.** GLM's approved read requests in three tasks stopped at `runner_failed`, and another stopped at `commit_rejected`. The available evidence does not isolate the cause. These failures blocked the task and need targeted reproduction before any code-level diagnosis.
3. **High local-model wait cost.** Qwen ran at 5.87 generation tok/s on average in Phase 0, and its one successful coding smoke took 27m24s end-to-end. Its formal attempts accumulated 4,709 seconds of sampled model-process time and still produced no candidates.

## Answers and next investment

1. **Is Qwen3.8-27B suitable for the current M4 Pro 48GB Khaos?** It is compatible and can complete a bounded coding smoke, but it is not recommended as the default coding model yet: the formal completion rate was 0/12 and decision latency is high.
2. **Does CPU-only inference support multi-step coding?** It supports at least one real four-operation read/edit/verify task. It did not support reliable completion across the 12-task set in practical time. Do not enable Metal in this phase.
3. **How did API and local reliability differ?** Both completed 0/12 with no candidate edits. Their focused baseline/grader results were identical (8 passing, 4 failing). There is no evidence to rank their coding quality. GLM attempts additionally surfaced Runner/Kernel errors on approved requests; exact root cause is unknown.
4. **What is the largest current capability bottleneck?** Repository path discovery and scoped tool planning, shared by both runs, followed by generic Runner/Kernel failures on some approved operations.
5. **What should be improved next?** Run one controlled, approval-gated repository-discovery experiment through the existing read/list path. Limit it to the selected task root and verify an out-of-scope canary remains unreadable; then rerun one discriminating task. If the existing ABI cannot support that safely, document the evidence before proposing any interface change. Do not expand Kernel authority.

## Security and architecture delta

- Production code delta: 0.
- Trusted code delta: 0.
- New architecture concepts, trusted processes, Kernel IPC operations, persistent product state, and runtime dependencies: 0.
- Candidate workspace edits: 0 for both models; all 24 formal workspaces are clean.
- No Metal/GPU inference, authority expansion, or approval bypass occurred.
- Evaluation reports, grader copies, and logs are artifacts only.
- Removed duplication / abstractions: 0.

Machine-readable per-task rollup: [reliability-rollup.json](reliability-rollup.json). Dataset definition and limitations: [DATASET.md](DATASET.md).
