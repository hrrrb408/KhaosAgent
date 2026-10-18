# Signed Product Acceptance Plan

## Completed signed cases

| Case | Fixture and request | Approval / expected execution | Status |
|---|---|---|---|
| Positive staged replacement | Disposable `tags.py`; fixed deterministic shell proposal; `readScope=["tags.py"]`, `writeScope=["tags.py"]`; one modified path expected. | One explicit Run once decision; one Runner execution; inspect final bytes, mode, canary, temp, Task Record and signature. | Historical v8 PASS and separately authorized replay PASS. Both records retained. |
| User refusal | Same narrow fixture/proposal and exact scopes. | User denies; zero Runner executions; inspect unchanged workspace and terminal state. | Historical v2 PASS. Not repeated. |

## Remaining L4 scenarios

These scenarios are not authorized by the one-use positive replay approval. Each new Launcher operation requires its own review and decision. No UI automation may click Run once or Cancel for the user.

| Scenario | Exact fixture shape | Expected result | Status |
|---|---|---|---|
| Approved request cancelled before Runner start | Disposable workspace; one bounded, non-mutating shell proposal; empty scopes; capture the approval/Task Record transition. | Approval may be recorded, but Runner count 0 and workspace unchanged. | BLOCKED_PENDING_APPROVAL |
| Cancel after source read, before replacement | Disposable `tags.py`; fixed Staged Replacement; exact tags.py scopes; deterministic read marker. | `process_cancelled`; live target/canaries unchanged; no temp. | L3 PASS; signed L4 BLOCKED_PENDING_APPROVAL |
| Cancel after private replacement, before commit | Same exact tags.py fixture; deterministic post-`os.replace` marker. | Capture actual commit result; do not infer rollback from terminal label. | L3 PASS at pre-commit point; signed L4 BLOCKED_PENDING_APPROVAL |
| Cancel at or after commit cutoff | Same fixture with a deterministic Kernel commit boundary. | Record whether commit completed and inspect final bytes; no rollback claim after the boundary. | NOT_RUN; BLOCKED_PENDING_APPROVAL |
| Runner terminated before replacement | Same exact scopes; hold Runner after source read and terminate only the identified Runner. | Kernel terminal result plus child/Runner PID exit and unchanged live workspace. | L3 PASS; signed L4 BLOCKED_PENDING_APPROVAL |
| Runner terminated after replacement | Same exact scopes; hold Runner after private `os.replace` and terminate only the identified Runner. | Capture commit outcome independently from Runner exit and inspect final workspace. | L3 PASS; signed L4 BLOCKED_PENDING_APPROVAL |
| Long/multiline approval review | Separate bounded proposals for newline, Unicode, quotes, backslashes and near-limit payloads, with exact displayed argv/scope/digest comparison. | User can inspect the complete request; displayed and executed values match; over-limit values fail closed. | NOT_RUN; BLOCKED_PENDING_APPROVAL |

No authorization is inferred from the signed v8/v2 records, the M8.4 remote-model approval, or the replay approval used in this branch.
