# Signed product acceptance plan and status

## Current status

No A4 interactive signed acceptance ran. The separately authorized one-time deterministic short `tags.py` replay is already recorded as `A2-REPLAY-01` in `reports/m8-secure-edit-final-gate/SIGNED_TEST_REPORT.md`; its immutable evidence is `reports/m8-secure-edit-final-gate/SIGNED_TEST_REPORT-A2-REPLAY-01.json`. It completed successfully, but covers only that short operation and does not establish A4 preview/cancellation or B38. The replay authorization is spent, and the ordinary positive edit is not repeated. The canonical suite's existing disposable Runner tests and signed product-bundle authentication/invalid-request test are not A4 signed acceptance and do not establish the new UI or cancel flow.

Trusted implementation is blocked until an independent security review approves the exact protected code diff. Any later Run once action must be separately approved by the user through the Launcher. Do not automate approval or cancellation clicks.

## B38 — complex preview review

After review and implementation, use the existing disposable test fixture with no real user files. Confirm the actual signed Launcher shows a preview derived from the request it will submit, the same request digest, exact read/write scopes, and complete expanded argv/script/decoded values. Cover multiline, Unicode, JSON escapes, CRLF/LF, quotes/backslashes, control/bidi/zero-width characters, near-limit input, empty `newText`, oversized input and parser mismatch. For every incomplete recognized request, confirm Run once is disabled and no Runner starts. Denial must leave the fixture unchanged. The parent test must compare the accepted request digest and final fixture hash; it must not repeat the ordinary positive `tags.py` operation.

## B32 — approval then cancel before Runner

Reach the post-approval/pre-Runner synchronization point in a disposable fixture. User cancels the active task. Verify the exact task/request invalidation, Runner execution count zero, no late approval restart, unchanged fixture hashes, and truthful Launcher/Host terminal result. Historical approval denial is not a substitute.

## B34 — commit cutoff and late cancellation

Use the existing deterministic Kernel synchronization at READY/ACCEPT, bound to the actual signed Launcher cancellation action and request ID. Exercise cancellation before the commit cutoff and a cancellation observed after an already completed commit. Record the exact cancel request/ack, final Kernel reply, added/modified/deleted counts, parent-process final hashes, Launcher Task Record and Agent Host result. Cancellation acknowledgement alone is not evidence of final state.

## Uncertain outcome and stale task

In an isolated reviewed fixture, force the existing `commit_outcome_uncertain` path. Verify the signed UI and Task Record say `Workspace Outcome: Uncertain`; do not assert rollback. Also test lost reply, `process_not_active`, stale task/request/connection cancellation, old Host reply after task replacement, and two task identities to prove isolation. A canceled task must never trigger an automatic retry.

All acceptance hooks and any fixture changes require normal Security Freeze review. Signed results must state exact SHA, request IDs, process/Runner observation, Kernel result, parent-side fixture hashes and Task Record. Interactive steps remain user actions.
