# M8.2.1 Terminal Path Audit

## Result

The task path already emits a bounded Launcher task record. M8.2 Attempt 02's raw run directory contains that record and identifies a failed task with `invalid_model_output_shape`; the earlier committed summary did not include this local raw capture. The final task outcome is therefore recovered, although the exact one-off replay driver's aggregation behavior is not recoverable from source.

## End-to-end path

```text
BigModel response
  → untrusted Agent Host decode and exact Action validation
  → AgentHostReply over the existing Host/Launcher channel
  → Launcher validates the reply and presents the existing approval UI
  → existing Kernel workspace operation
  → bounded Tool Result returned to the Host with canContinue
  → next Host response, or a task stop/final response
  → Launcher task status and task record on stdout
  → attempt-scoped evidence snapshot
```

The model response and Action validation remain untrusted Agent Host behavior. The Kernel permission and workspace boundary are not changed by this work.

## Observable stages and meaning

| Stage | Existing observation | What it proves |
|---|---|---|
| Proposal | `tool-proposal kind=list|shell` | A valid proposal reached the Launcher path. It does not prove approval. |
| Approval | `tool=approval-presented`, `tool=approved`, or `tool=approval-denied` | The corresponding UI decision was observed. |
| Execution | `tool=executed returncode=N` and the task record's return-code array | The Launcher received a bounded Kernel result. Return code zero is not task success. |
| Result returned | `tool-result ... can_continue=...` | The bounded result was sent to the Host. |
| Host reply after result | `tool-response ... status=accepted|rejected` | The Launcher observed an allowed or disallowed Host reply. It does not prove task completion. |
| Model/Action diagnosis | Fixed-format Host diagnostic event | The named decode/validation/correction stage and allowlisted metadata were observed. No raw response is retained. |
| Final response | `Khaos: ...` marker | A final text action was emitted. Without a task status/record, it is not promoted to task completion. |
| Task terminal | `Launcher task status` and/or `Launcher task record` | The Launcher recorded a completed, failed, stopped, or budget-exhausted task outcome. Conflicting markers fail closed. |
| Process exit | Waiter PID no longer exists or the test waiter returned | Process lifecycle only. Exit code zero is not task completion. |

The trusted Launcher writes the task record at its normal task loop boundary. For a returned final response it reports `finished`; for failure, user cancellation, budget exhaustion, Host/IPC failure, or rejected operation it records a stop/failure reason. The current record includes proposal count, executed command return codes, cumulative Runner time, bounded result bytes, and a bounded stop reason. The report intentionally does not treat that record as evidence that broader tests passed.

## Capture gap found

The previous `capture_agent_events.py` observer emitted generic `task_record` events and did not create an attempt-scoped normalized terminal summary. The old frozen recheck driver also stopped with an error when no task record appeared, rather than recording an explicit unknown result. This left a gap in downstream evidence handling: available raw outcomes were not normalized and retained consistently with the attempt.

The new observer keeps process exit separate from task outcome. It snapshots after the waiter exits, records a sanitized terminal summary, and emits `terminal_outcome_not_captured` when no task status/record or observed process termination establishes an outcome. A final text marker alone remains a response observation, not a task terminal. When Task Status/Record gives `final_response`, the summary records that business response even if the product stdout has no `Khaos:` text marker. Multiple or conflicting status/record markers also fail closed.

## Historical conclusion

Attempt 02 did not complete successfully: its retained Launcher task record says `Agent Host or model failed: invalid_model_output_shape`. The adjacent raw Host diagnostic capture records an initial Action shape rejection, a correction request, and a second Action shape rejection. Attempt 01 has no retained terminal task record; its post-cancellation Host result remains `NOT_PROVEN`.

The exact one-off replay driver source was not recovered. The evidence proves an aggregation/reporting omission; it does not prove which line in that absent driver caused the omission. See [HISTORICAL_EVIDENCE_RECOVERY.md](HISTORICAL_EVIDENCE_RECOVERY.md).

## Evidence boundaries

- Static code describes possible paths; it is not evidence that a particular historical attempt took one.
- The M8.2 Task Record and raw diagnostics are preserved locally under the untracked attempt directory and identified by SHA-256 in the recovery report.
- The earlier committed M8.2 summary remains unchanged and continues to state that no final marker was captured; the new report explains the newly recovered raw evidence.
- No synthetic result is attributed to a real model attempt.

## M8.2.1 answer

The final M8.2 Attempt 02 state was not captured in the committed summary because the retained raw Task Record and Host diagnostic capture were omitted during evidence aggregation. The original one-off driver is unavailable, so the exact code defect remains `NOT_PROVEN`. Attempt 02's final task failure itself is recovered directly from the raw Launcher Task Record. The current evidence path is verifiably improved by the 26 observer tests, the full 367-test suite, and deterministic signed-product acceptance. Future coding runs can retain task terminal outcomes with attempt-scoped sanitized summaries; this is execution-observation evidence, not coding-quality evidence. Attempt 01's post-cancel Host response remains `NOT_PROVEN`.
