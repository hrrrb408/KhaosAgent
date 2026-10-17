# M8.2.1 Completion Audit

## Required closure values

```text
Engineering Closure: CONDITIONAL
Terminal Capture Reliability: PASS
M8.2 Historical Final Host Outcome: RECOVERED
Action Contract Root Cause: PARTIALLY_PROVEN
Coding Reliability Closure: NOT_PROVEN
```

The historical M8.2 final task outcome is recovered from the Attempt 02 Launcher Task Record: the task failed with `invalid_model_output_shape` after seven successful tool operations. Adjacent sanitized Host events report an initial shape failure and a failed correction with a missing known `text` field. The raw rejected model response is unavailable, and those Host events do not include an explicit attempt ID; the field-level attribution therefore remains partial.

Attempt 01's post-cancellation Host result remains `NOT_PROVEN`. The original one-off M8.2 driver source is unavailable, so the exact historical capture code defect remains `NOT_PROVEN`; the committed evidence aggregation omitted raw terminal evidence that still existed locally.

The historical capture gap is now explained at the evidence-aggregation level: the Task Record and Host diagnostic file remained in the raw Attempt 02 directory but were omitted from the committed M8.2 summaries. The one-off historical driver source is absent, so the exact faulty code path is not proven. The current observer's deterministic signed-product and offline tests demonstrate that status/record outcomes are saved per attempt, while process exit and text markers alone remain insufficient.

## Conditions before engineering closure

Engineering closure remains `CONDITIONAL` because PR #30 is intentionally left as an open Draft and independent Code Owner approval remains `NOT PROVEN` in single-maintainer mode. Its implementation SHA `3b651d2f6c6b69a4162a8b9ef8ec77a6bbef92a2` has passing `security-tests` and `security-freeze` checks. The report-only follow-up SHA must also pass both checks before this audit is final.

For final closure, verify:

1. PR #30 remains stacked on exact PR #29 HEAD `3cdf26e1933dbcf9896dcd83a0cb6e05eadff92b`, without auto-merge;
2. the final report-only head passes the required remote checks.

Terminal Capture Reliability is `PASS` based on 27 focused observer tests, the full 368-test macOS suite, and the signed-product deterministic acceptance. Evidence covers completion, failure, cancellation, budget exhaustion, observed Host termination, missing records, process-only exit, attempt separation, and bounded redaction. This does not establish Coding Reliability.

## Required change accounting

```text
Production code delta: 0 product runtime files; external capture/recheck and test code changed
Trusted code delta: 0 runtime TCB files/lines
New architecture concepts: 0
New trusted processes: 0
New IPC operations: 0
New persistent state: 0 production state; per-attempt sanitized evidence JSON/JSONL only
New dependencies: 0
Removed duplication / abstractions: shared live/snapshot summary implementation; no framework added
```

Do not change `Coding Reliability Closure: NOT_PROVEN` based on deterministic probe results. Do not rewrite the historical M8.2 report or claim the recovered error is a successful model completion. Attempt 01's post-cancellation Host response remains `NOT_PROVEN`; future use of the observer does not retroactively resolve it.
