# M8.5.2 — Adversarial and Failure-Path Test Report

Status: **focused headless cases pass; full Gate A matrix NOT_PROVEN**
Evidence refreshed: 2026-10-18

## Passed focused coverage

- Real macOS Seatbelt and Kernel headless staged-replacement success: exactly one scoped file modified; mode `0640` preserved; no temp entry; canary unchanged; unscoped canary read denied; focused retest passed.
- Deterministic injected temp creation, write, `fsync`, and pre-replace failures: target unchanged and no committed changes.
- Injected cleanup failure: temp remains only in the private snapshot; Kernel rejects the complete changeset before live mutation.
- Injected post-replace exception: command returns nonzero, but the complete target replacement is committed; only the target appears in the changeset and no temp remains.
- Existing exact-scope/link/canary, unreadable-baseline move, alias metadata, snapshot/path, and cross-process changeset race regressions listed in `RUNNER_FEASIBILITY.md` pass.
- Signed v8 positive path: the exact proposal was reviewed and approved once; the signed Runner returned code 0 and the parent acceptance verified `added=0/modified=1/deleted=0`, exact final bytes and mode, no temp residue, unchanged canary, only `tags.py` changed, successful focused test, complete Task Record, and deep strict code signature. The fixture was removed at teardown. Evidence: `gate-a-signed-runner-v8.json`.
- Signed refusal v2: the exact `tags.py` proposal was displayed and denied once; the Task Record reports zero Runner executions and `task_cancelled`, while source bytes, mode, canary, git status, and temp paths remain unchanged. The enclosing signed XPC request-attack test also passed. Evidence: `gate-a-signed-refusal-v2.json`.

## Limits and missing cases

The injected I/O errors are deterministic test hooks, not OS-originated failures. Signed v8 proves the successful exact-file path, and refusal v2 proves denial without Runner execution. Target-specific cancellation/process termination and the required signed traversal, alias, out-of-scope, rename/TOCTOU, unreadable-baseline, and changeset-rejection outcomes remain NOT_PROVEN. Existing generic cancellation and race tests are supporting regression evidence, not proof of every edit-specific state.

The canonical suite passed on the latest test harness with 381 tests in 708.963 seconds. The signed v8 positive and signed refusal v2 paths also passed. These results do not close the remaining Gate A matrix.
