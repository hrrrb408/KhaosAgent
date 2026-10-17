# Minimal Terminal Capture Design

## Scope

The change is limited to the external experiment observer, frozen-recheck driver, and test-only signed-product evidence assertions. It does not modify AgentHost runtime code, the trusted Launcher, the Kernel, the Action schema, the prompt, approval flow, scope enforcement, budgets, or Kernel IPC.

## Evidence inputs

The observer reuses existing Launcher stdout/stderr markers and the existing bounded Host action-diagnostic format. It supports:

- live capture while the Launcher waiter is running;
- a one-shot snapshot after the caller has waited for the product process;
- a stable, validated attempt ID;
- a separately recorded waiter PID/exit observation;
- full-file SHA-256 digests for inputs up to 16 MiB, with only a bounded 256 KiB tail parsed;
- an explicit truncation flag that makes the evidence summary incomplete.

The frozen recheck start mode passes the attempt ID and `open -W` PID to the observer. Finish takes a new snapshot after the waiter is expected to exit. If no Task Status or Task Record exists, it saves `terminal_outcome_not_captured` and skips grading rather than failing without a record or inferring success from the waiter.

The deterministic signed-product acceptance takes a separate summary for each test task. It asserts the expected task class for normal completion, an invalid local-model response, user denial, Picker cancellation, budget exhaustion, and observed Host termination. The local-model guard reports `local_model_invalid_output` before a Launcher Task Record exists, so the observer correctly leaves the task outcome unknown. Offline synthetic Task Records and bounded Host events separately cover JSON-stage and repeated Action-shape failures. A synthetic seven-command task verifies that seven separately approved successful calls can be followed by a final response and a completed Task Record.

## Sanitization and bounds

- Only fixed Launcher event strings and allowlisted `list`/`shell` kinds are retained. Unknown `agent-session` text is dropped.
- Return codes, byte counts, and proposal counts are range checked. The existing task record limits are enforced (at most 8 proposals/return codes, 180 Runner seconds, and 32 KiB bounded result bytes).
- Host diagnostics are accepted only for the fixed event, attempt, stage, error-code, and known Action-field allowlists. Each source line must be at most 512 UTF-8 bytes; at most 27 diagnostic events enter one summary.
- Input parsing is bounded to the final 256 KiB of each source file. Full-file SHA-256 is computed incrementally only when an input is at most 16 MiB; larger or changing inputs are marked truncated and are not fully hashed. Truncation makes the summary incomplete.
- Live capture emits at most 128 incremental events plus one terminal summary. It runs for at most 3,600 seconds with a poll interval capped at 10 seconds.
- Summary output contains no model response, prompt, Workspace text, Tool Result text, raw stderr, or credential. Source logs are represented by SHA-256 and truncation metadata only.
- Attempt IDs are 1–64 safe identifier characters. Output files are created exclusively and are never overwritten.

## Classification rules

1. One unambiguous Launcher Task Status or Task Record is the primary task outcome. When its reason code is `final_response`, `agent_final_response_observed` is true even if stdout has no `Khaos:` text marker.
2. Conflicting or repeated terminal records produce `terminal_outcome_not_captured`.
3. The count of `Khaos:` text markers is reported separately as `event_counts.agent_final_response_marker`. A text marker without a Launcher task status/record sets `agent_final_response_observed` but leaves the task outcome unknown.
4. A waiter exit, including exit code zero, is recorded separately and never establishes task success.
5. A process termination may be classified as `agent_host_terminated` or `launcher_terminated` only when the test/driver separately observed that process termination.
6. Missing task terminal evidence, stopped capture, or truncated input is explicitly marked as unknown/incomplete.
7. `tool_result` and Host response acceptance are separate events; a successful command is not a task completion.

## Attempt association and retention

New summaries carry the attempt ID and hashes of their input files. The signed-product test uses one unique label and output file per task. Historical Host diagnostics lack an embedded attempt ID, so the report states the run-directory/time-window association and its limitation. No new task ID is added to Trusted IPC.

Summaries are ordinary test/experiment artifacts under the attempt directory. There is no production database, service, telemetry upload, or new persistent product state. macOS unified-log retention remains controlled by the OS; the M8.2.1 report does not rely on a historical `log show` query that returned no event rows.

## Reuse and TCB accounting

The implementation parses existing Launcher task status/record and bounded diagnostics; it adds no new product authority or trusted code. `_capture_summary` is shared by live and snapshot modes so both use the same sanitizer and classification rules.

```text
Production product code delta: 0
Trusted code delta: 0 runtime TCB files/lines
New architecture concepts: 0
New trusted processes: 0
New IPC operations: 0
New production persistent state: 0
New dependencies: 0
```

The test-only `.terminal.jsonl` and external experiment `terminal-outcome.jsonl` are evidence artifacts, not runtime state.
