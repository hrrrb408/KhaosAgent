# M8.5.2A.7 implementation audit

Base: PR #40 `707395146bbaf6be9ac6f58ae1f538e443b064a8`, stacked on open Draft
#39 `dee62b20dc1acbd64b009d47c29dc3f42ba9fdde`. Remote main at inspection:
`27ef0b4787f807fc76ffd7ba9cdb467ffc9a2f27`. No existing PR is merged or changed.
M8.7 conclusions are in [its audit](../m8-architecture-consolidation/COMPLETION_AUDIT.md).

## Minimal synchronization

`tests/signed_cancellation_fixture.py` edits only the builder's private snapshot.
The production builder and production Kernel/client/Runner source have no hook,
environment switch, new compile flag, new operation, or test-file import.
Every anchor must occur exactly once, repeated overlays fail, all overlaid bytes
are hashed before ordinary compilation and signing. The harness records its own
and the deterministic model probe's digests in the signed build record.

- B32: a DispatchSemaphore blocks the existing serial client's beginSubmission,
  after actual approval. Only the real cancellation method signals it. The normal
  cancellation flag and existing completion path then prevent submission.
- B34 pre: after the committer reports READY, pause before the existing cancel
  recheck and ACCEPT. The external controller releases only after receiving the
  original connection's cancellation acknowledgment. Existing logic sends ABORT.
- B34 post: pause after the real commit child is reaped, status/version validated,
  and APPLIED counts known. Cancellation cannot replace the existing summary.
- Test observers record workspace.run ingress, an authenticated Runner
  `process.exec` request, the staged private write path and digest immediately
  before commit authorization, the original serialized Kernel response, and
  exact terminal text received by Host. Observers neither write response bytes
  nor select outcomes.

All barriers expire after 55 seconds (below the existing execution deadlines).
Timeout is failed acceptance; pre-ACCEPT timeout aborts, post-commit timeout keeps
the known committed result. There is no automatic retry; each manual attempt is
preserved in a separate directory. The control path is baked into the signed
fixture, outside workspace/Host/Runner scopes. The barrier
controls timing only; separate test-only observers record bounded stage and
digest metadata. The owner must click Run Once and Cancel; no program
synthesizes actions.

Existing READY/ACCEPT, command handle, Task Record, launch/sign/hash helpers and
fixed Candidate B model probe are reused. Legacy managed-process lifecycle tests
were checked for process ownership lessons; no legacy Host backend is reused.
The timing primitive is Apple's existing
[DispatchSemaphore](https://developer.apple.com/documentation/dispatch/dispatchsemaphore).
No new framework/dependency/process/RPC or durable product state is introduced.

## Necessary production change

Audit found active cancellation invalidated Host without delivering the operation
result. Launcher now uses the existing bounded terminal tool_result channel with
can_continue=false, ignores **every** returned action, records delivery separately,
and ends the session. Kernel result/commit mapping is unchanged. This belongs in
Launcher because only it knows the approved request and authoritative observed
Kernel outcome; Host cannot certify its own terminal result. Reusing the existing
send/wait path is smaller than an acknowledgment protocol or new IPC operation.
Missing delivery remains unconfirmed. Kernel authority, ABI, write/read scope,
Seatbelt, snapshot and approval binding delta: **0**. A text Host response confirms
transport processing, not model honesty; signed fixture additionally echoes the
exact received terminal bytes for comparison.

## Evidence boundaries

Preparation attempts 1 and 2 were compile/isolation checks during development;
neither was launched for manual acceptance. Preserve them under
`~/Applications/khaos-m8-a7-b32-attempt{1,2}`. Only subsequent exact-source receipts
can establish final signed acceptance. Current statuses and evidence are recorded
in the other three reports; no L4 claim is inherited from these preparation builds.

Attempt 6 exposed a test-only receipt assertion defect: the deterministic Host
probe's encoded response contains the exact terminal result followed by fixed
probe instructions. The previous whole-payload equality check rejected this
valid receipt. `host_receipt_contains_terminal` now verifies the exact terminal
bytes as a prefix, with a focused regression test that rejects a mismatched
prefix. This correction changes no signed product input, production behavior,
authorization rule or TCB boundary. Attempt 6's original runner failure remains
preserved; its separate `reconciliation.json` records the corrected checks over
the exact signed-run artifacts.

B34 pre-commit attempt 2 exposed two test-evidence defects: Runner execution
was instrumented before its authenticated IPC request, and the expected Kernel
code was `commit_rejected` even though the actual cancellation result is
`process_cancelled`. The corrected private overlay records the Runner's
`process.exec` request and staged `tags.py` digest before the existing commit
gate, and expects `process_cancelled`. The signed attempt remains
`NOT_PROVEN`; a fresh owner-operated run is required to exercise the corrected
observer.
