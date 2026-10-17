# M8.2 Historical Evidence Recovery

## Sources and integrity

The source files below remain in the local, untracked experiment run directory. Their contents are not copied into this report or staged. Hashes were recomputed from the retained files during this audit.

Source directory: `reports/benchmark/dataset-v1/runs/api/runner-exception-classification/`

| Attempt | File | Bytes | SHA-256 |
|---|---|---:|---|
| 01 | `m8-2-glm53-01/launcher.stdout` | 106 | `e48da922067801db2bff9d37166ebc9739c6f51b9307b65c2a576fc3ca7dc14c` |
| 01 | `m8-2-glm53-01/launcher.stderr` | 300 | `49ad6110a886c2f3d7676c948a76e87d933ac32cc681ca7865ca4ea89777efa4` |
| 01 | `m8-2-glm53-01/agenthost-action-diagnostics.log` | 108 | `78ba5e9b92206635b01dd3d0ca0b3e7bd3028e9974f0414d3c7d762630c0c023` |
| 01 | `m8-2-glm53-01/run.json` | 4,346 | `9101305604f521bc6473c9d9624fa08015046d71927a625d42786c7467d33fdf` |
| 02 | `m8-2-glm53-02/launcher.stdout` | 487 | `d5cb20cd4cedf7f5e9f1628e4ab902bed7c29adc5ba8a4e15f5976b16de6629c` |
| 02 | `m8-2-glm53-02/launcher.stderr` | 2,299 | `9500ecfd9b3269407836d1ea64940b3fdc308b4e3bb3d1266d34ed10433db6cc` |
| 02 | `m8-2-glm53-02/agenthost-action-diagnostics.log` | 990 | `b8dcd8c93fd98f96c18646129705494278fddd72c261864c3acb25bf83ecec30` |
| 02 | `m8-2-glm53-02/run.json` | 2,542 | `cde2b0695c8634156d9b559f2d1789eef74b7d7b3632204eb1c27e5bd83f4f28` |

The Attempt 02 raw Launcher and Host capture files have matching filesystem modification times around 2026-10-17 23:38:45 Asia/Shanghai. The Host records themselves carry 2026-10-17 23:38:36 local timestamps and process label `KhaosAgentHost[8713]`. Attempt 02's `run.json` names the attempt but remains `prepared`, has no start time or Launcher exit code, and must not be treated as its completion record. The direct Launcher stdout Task Record is the completion evidence.

## Attempt 01

The retained Launcher sequence and the committed attempt report establish that remote task-data approval was followed by an accepted initial list proposal, a workspace Picker request, and user cancellation before Runner execution. The raw output has no `Launcher task status` or `Launcher task record`. Its Host diagnostic file contains only the filter header and no matching event. No Runner operation or changed path is recorded.

**Recovery result:** workspace cancellation before Runner execution is supported; the post-cancellation Host response and final task terminal are `NOT_PROVEN`. The zero waiter code, if any, is not a substitute for a task record.

## Attempt 02

The raw `launcher.stdout` has a Launcher Task Record with seven proposals, seven executed command return codes all zero, cumulative Runner time 38.799 seconds, 7,109 bounded result bytes, and stop reason `Agent Host or model failed: invalid_model_output_shape`. It has no final `Khaos:` response marker and no separate `Launcher task status` line. The record therefore establishes a failed task, not a successful completion.

The raw `agenthost-action-diagnostics.log` contains three sanitized records associated with the same local run directory and time window:

1. `initial_response_failed`, attempt `initial`, stage `action_shape`, error `invalid_model_output_shape`, expected keys 10, actual keys 9, missing known key `text`, unexpected key count 0.
2. `correction_requested`.
3. `correction_response_failed`, attempt `correction`, stage `action_shape`, same error and key counts, missing known key `text`, unexpected key count 0.

No model response text, prompt, workspace file content, or API key is reproduced here. The raw diagnostic file has no explicit M8.2 attempt identifier; its association with Attempt 02 is based on its location in that attempt's run directory and the matching process/time window. The Launcher Task Record independently ties the final error code to Attempt 02.

The earlier committed `attempt-02-summary.json`, `attempt-02-host-diagnostics.json`, and M8.2 `REPORT.md` state that the Host terminal/diagnostic event was not captured. A later `log show` query for the stated subsystem/category returned only its header. The newly recovered local `agenthost-action-diagnostics.log` conflicts with the old diagnostic summary; the old historical files are intentionally unchanged.

**Recovery result:** final Host/task outcome `RECOVERED` as a failure with `invalid_model_output_shape`. The field-level shape failure is supported by the adjacent sanitized Host records; because those records lack a run ID, the field-level causal attribution is `PARTIALLY_PROVEN`. The exact rejected model JSON remains unavailable.

## Other findings and limits

- Attempt 02 followed seven successful tool results with a Host/model shape failure and failed correction; it did not reach a final text response.
- The raw Task Record resolves the old `ATTEMPT_02_FINAL_HOST_OUTCOME_NOT_CAPTURED` gap. It does not make the task a coding-quality attempt: no candidate edits or model-proposed tests occurred, and the hidden grader tested an unchanged baseline copy.
- The original one-off replay driver source was not present in the repository or preserved raw run directory. The evidence proves that local raw terminal records existed but were omitted from committed summaries; the exact historical code defect is `NOT_PROVEN`.
- Raw run files remain untracked and unstaged because they include sensitive experiment output and grading material. This report contains only bounded, sanitized facts and source hashes.
