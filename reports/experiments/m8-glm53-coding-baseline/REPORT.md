# Khaos M8.0 — GLM-5.3 Coding Baseline Experiment

Experiment date: 2026-10-17. Branch: `experiment/m8-glm53-coding-baseline`.

**Experiment Closure: COMPLETE for the authorized one-attempt experiment; engineering validation passed as recorded below. Coding Reliability Closure: NOT_PROVEN. Coding Outcome: FAILED.** GLM-5.3 was genuinely called through the Coding Plan endpoint and the unchanged signed product. It produced six independently approved, successfully executed operations before terminating with `invalid_model_output_shape`. It generated no edit and ran no test. The original independent hidden-test grader failed. No second formal attempt, Flash rerun, prompt tuning, or Harness repair was performed.

## Baseline and minimal change

Remote `main` was fetched and verified as the requested M7 integration commit `27ef0b4787f807fc76ffd7ba9cdb467ffc9a2f27`; there was no baseline drift. The experiment source/build commit is `61abe742fbfbabf48cb096031d72eac0d04c3a80`. Main was not reset, overwritten or modified. Existing untracked artifacts and historical failures were preserved.

The complete production diff is one model string in untrusted `khaos/macos/AgentHost.swift`: `glm-5.3-flash` → `glm-5.3`. Prompt, Agent Action parser/schema, history management, correction behavior, Launcher, Kernel, Runner, builder, admission and tests are unchanged. No runtime TCB file changed.

Required project documents were read before editing; their hashes are in [experiment-config.json](experiment-config.json). Original task preparation, capture and grading tools were inspected and reused without modification. This is a model experiment, with no new subsystem or dependency.

| Frozen condition | Value |
| --- | --- |
| Task ID | `runner-exception-classification` |
| Original task prompt SHA-256 | `7a86c99de62538d4c514cb0f5fa1dd31d747701be60f03c12d4a2420736810a2` |
| Workspace baseline commit | `7b6af61b3925b28ef105ea521c49424344de04c5` |
| Hidden-test patch SHA-256 | `185ea8ada844d790c0d716b2d7d921c8c4e739b238baa5d1b7b325e6fc446e16` |
| Provider / model | `bigmodel-coding-plan` / `glm-5.3` |
| Endpoint | `https://open.bigmodel.cn/api/coding/paas/v4/chat/completions` |
| App build record SHA-256 | `b387fc6d9980787a2812b92006cda6ae95a5b3d771b477971b64d112371fef2b` |
| Signed Agent Host executable SHA-256 | `17434468d50426b36983b9fe91446d7ead0b5892ccabf05aef3a2fa7f4019c49` |
| Temperature / top-p | `1` / `0.95` |
| Reasoning / thinking | `max`; `enabled`, `clear_thinking=false` |
| Response protocol | Non-streaming `json_object`, existing exact Agent Action keys/types |
| Output / correction tokens | `32768` / `1024`, correction effort `low` |
| Correction / request timeout | Existing at-most-once correction per turn; existing deadline; 600 seconds |
| Context / tool limit | 8192 history bytes / 8 tool calls |
| Runner total / operation budget | 180 seconds / 30 seconds |
| Result / aggregate limit | 4096 bytes / 32768 bytes |

The full source map, selected executable hashes, signing identity and toolchain are retained in [build.json](build.json). The separately built app is `/Users/huangruibang/Applications/Khaos M8.0 GLM-5.3 Baseline-2026-10-17.app`; no installed app was overwritten. “App Build SHA” here identifies the signed embedded build record and individual executables; no single directory/archive hash is claimed.

## Interface and signed-product checks

The [official GLM-5.3 model guide](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3) identifies `glm-5.3`, Coding Plan availability and thinking/reasoning support. The [Chat Completion API](https://docs.bigmodel.cn/api-reference/模型-api/对话补全) and [structured-output guide](https://docs.bigmodel.cn/cn/guide/capabilities/struct-output) describe the existing request/JSON mechanisms. No interface incompatibility requiring a code change was established. The unchanged `clear_thinking=false` field was accepted; its server-side semantics were not independently proven.

1. A synthetic request containing no project data returned HTTP 200, reported model `glm-5.3`, finish reason `stop`, and valid `{"ok":true}` JSON: 2.018 seconds, 35 prompt tokens, 43 completion tokens (36 reasoning), 78 total. [API evidence](api-preflight.json). No automatic retry or fallback.
2. Existing builder completed the independent signed app; `--verify-app` passed, including a repeat after the experiment. Its `--bootstrap-check` verified Kernel and snapshot-broker XPC peer authentication.
3. The signed product received a synthetic-only prompt, proposed `list` with read scope `fixture`, received separate approval, executed with return code 0, received its 197-byte bounded result, and produced a legal final summary. The synthetic workspace remained byte-for-byte unchanged. [Product evidence](smoke-product.json), [events](smoke-agent-events.jsonl).
4. A separate no-key refusal check selected `Do not send`. Existing diagnostics recorded denial before a Host turn, workspace Picker or tool proposal; the disposable workspace was unchanged. Its raw process status `terminated_without_task_record` is expected refusal evidence, not a coding success. [Refusal evidence](refusal-product.json).

The unchanged Launcher labels the service “GLM-5.3-Flash Coding Plan.” This stale display text is a real limitation and was not silently rewritten in the trusted UI. The endpoint/data categories matched the explicit human authorization; actual model selection is established by signed Host source and the synthetic API response. Two old remote opt-in test evidence labels also hardcode Flash; those paths were not used to label this experiment.

## Authorized frozen attempt

The human explicitly authorized the synthetic compatibility check and one original frozen attempt, naming the exact endpoint and data categories. [authorization.json](authorization.json) records the scope. Each actual operation was independently reviewed in the signed Launcher; all were confined to the original disposable workspace. The frozen workspace contains public tests but not the separately applied hidden grading patch or reference answers. The key was supplied only as authentication through the existing environment/Host flow and was not put in prompts, argv, reports or model input.

Preparation used the existing `prepare_run.py` with `--model api --task-id runner-exception-classification --attempt m8-glm53-01`. The raw run retains the original task source commit (`5ac2e5f9a6b7cdaddb37ea18c28192b7b2e49a99`); `product_source_commit` separately identifies the signed Harness build. The original prompt bytes were hashed and passed unchanged to the signed `--agent` mode. The archived [product driver](product-driver.py.txt) and [synthetic API driver](api-preflight-driver.py.txt) preserve orchestration provenance and are not instructions to repeat the authorized calls. A thin external launch/capture driver only supplied stdin, isolated logs and the existing key, launched through Launch Services, and watched existing diagnostics; it did not generate actions, alter prompts/results, call tools for the model, inject approvals, or grade answers. Native dialogs were operated through CUA after review. [Tool-review records and raw run](evidence/run.json), [Launcher output](evidence/launcher.stdout), [diagnostics](evidence/launcher.stderr), [events](evidence/agent-events.jsonl).

| Operation | Independently approved read scope | Actual return code | Bounded result bytes |
| --- | --- | --- | --- |
| 1. Kernel directory listing | `tests` | 0 | 1541 |
| 2. Python read/search for exception/import clues | `tests/test_runner_sdk.py` | 0 | 381 |
| 3. Python search for exception labels | `tests` | 0 | 127 |
| 4. Python search for startup references | `tests` | 0 | 972 |
| 5. Python inspect public test prefix | `tests/test_worker.py` | 0 | 1064 |
| 6. Python inspect startup classifier source | `khaos` | 0 | 1051 |

All six approvals had an empty write scope. There were six proposals, six approvals and six executions: one list and five read-only Python commands. Cumulative Runner time was 19.385 seconds and aggregate result bytes 5136, within the original budgets. The model read relevant code. There was no source edit, test execution or failure-driven code repair by the model; [candidate.diff](evidence/candidate.diff) is empty. A zero Launcher process exit means the CLI shut down normally, and does not mean the coding task succeeded.

After operation 6, the product stopped with the exact category `invalid_model_output_shape`. The existing decoder assigns this category when a parsed JSON object's key set does not match the exact expected set. The correction path and bounds were preserved. The retained Launcher evidence does not expose the original rejected response, particular missing/extra keys, initial rejection category, per-turn correction diagnostics or number of provider requests; none is reconstructed from the final error alone. Host/Launcher/Kernel validation was not bypassed.

The unchanged independent `grade_attempt.py` cloned the frozen baseline, found no candidate paths, applied the original hash-verified hidden patch, and executed the recorded test command. It completed without timeout: return code 1, 18 tests, three failing subtests for RuntimeError, TypeError and ValueError. This is the original task defect, with no grading environment exception. [Grade](evidence/grade.json), [grader stderr](evidence/grader-test-01.stderr). Hidden tests were applied only after the model process had exited and were never returned to it.

## Historical comparison

| Metric | GLM-5.3-Flash historical M7 run | GLM-5.3 actual M8 run |
| --- | --- | --- |
| Action Contract | FAILED: wire contract after correction | FAILED: output shape after six valid proposals |
| Legal Tool Calls | 1 | 6 |
| Actual Tool Executions | 1 | 6 |
| Code modifications | 0 | 0 |
| Tests executed by model | 0 | 0 |
| Hidden Test | FAILED | FAILED |
| Coding Outcome | FAILED | FAILED |
| Observed Launcher wait intervals | 23.423 s, 24.660 s | 7.745–70.838 s; seven intervals below |
| Pure model response latency | Unavailable | NOT_PROVEN |
| Token usage | Unavailable | NOT_PROVEN; ordinary Host drops usage |
| Runner time | 3.196 s | 19.385 s |

Historical Flash observed waits were 23.423 and 24.660 seconds ([original event copy](evidence/historical-flash-agent-events.jsonl)). Observed M8 Launcher wait intervals were 7.745, 8.349, 5.500, 5.097, 5.919, 38.707 and 70.838 seconds. They include IPC, watcher polling and potentially the existing correction; they are not pure provider inference latency. Synthetic direct API timing/tokens above are separate and must not substitute for formal task telemetry. Full comparison and timing records: [comparison.json](comparison.json), [benchmark-result.json](benchmark-result.json).

The historical Flash app came from `0a2a37aa07475eb2c307f7e5cab13ca071ef2b4b`; the new build came from `61abe742fbfbabf48cb096031d72eac0d04c3a80`. Inspection found no changes to the relevant Harness/Launcher/Action parser/Protocol between that old source and M7 final main. The actual recorded build source maps differ only in AgentHost.swift; reversing the one model string produces the exact historical Host hash. Frozen task, baseline, hidden patch, prompts, request parameters and budgets match. This strengthens comparability, but it remains a historical comparison: commits/build times differ, sampling is stochastic and hosted weights/provider state are not pinned. There was no separately authorized paired Flash rerun. The observed improvement is continued legal interaction; it did not establish successful coding or a causal/general reliability improvement.

## Safety and engineering acceptance

The complete canonical suite passed **341 tests in 663.882 seconds** (return code 0), including real cancellation, sandbox and XPC attacks. Default, exact-base and base-commit Security Freeze checks passed. [validation.json](validation.json), [security-audit.json](security-audit.json) and [canonical-run.json](canonical-run.json) contain the terminal engineering results; [canonical.log](canonical.log) preserves the complete suite output. No deterministic result is counted as real-model coding evidence. The additional signed per-tool cancellation scenario was NOT_RUN to avoid adding model attempts; refusal was exercised above, and existing canonical cancellation/timeout/security regressions are reported separately.

The exact-base and default Security Freeze checks passed with zero sensitive changes. All 34 runtime TCB files were compared with M7 baseline. No sensitive path changed, so the existing Freeze rules do not require a new sensitive-code declaration or reviewed manifest update; no inherited declaration was fabricated or repinned. Independent Code Owner approval remains NOT_PROVEN in the inherited single-maintainer configuration. GitHub required CI and protection are checked for the delivered PR; main will not be merged by this experiment.

```text
Production code delta: +1/-1, untrusted model string only
Trusted code delta: 0 (34 runtime TCB files unchanged)
New architecture concepts: 0
New trusted processes: 0
New IPC operations: 0
New runtime persistent state: 0 (only external experiment evidence)
New dependencies: 0
Removed duplication / abstractions: 0
```

No authority, Kernel IPC, sandbox/XPC/signature boundary, admission, approval, Workspace scope or budget was expanded. Benchmark tasks, hidden tests, grader and historical failure evidence were not changed. The evidence inventory records their verification hashes. No test was deleted, skipped or weakened to produce success.

## Conclusions and follow-up

GLM-5.3 is callable and can produce valid actions with tool-result feedback in this Harness. It progressed beyond Flash's first-list failure, but still failed before any edit or test, and did not pass the original hidden tests. Therefore upgrading the model did not resolve this coding failure in the authorized attempt.

A structured-output/exact-action-shape failure is established; the precise raw-output cause and necessity of a particular Harness modification are NOT_PROVEN. Context eviction, planning or provider behavior must not be declared causal without new evidence. A separate authorized Coding Reliability investigation should first make bounded rejection/usage telemetry inspectable and diagnose schema adherence; any Harness or prompt changes and further calls belong in a separate experiment with their own safety review. No such changes were made here.

**Experiment Closure: COMPLETE.** The authorized attempt, independent grading, local engineering checks and evidence are complete; the delivery PR records its exact-head remote checks. **Coding Reliability Closure: NOT_PROVEN**; the observed Coding Outcome is **FAILED**. A single future pass would also be insufficient to establish broad reliability.
