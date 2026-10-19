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

Attempt 7 packaged `Production.app` and `Acceptance.app` from the same clean
source commit `184c2c609d7123a692c8e8778b617cc1dfba07e6`. The production build
record says `production_test_hook_isolation=PASS`; the builder asserted that
the marker, barrier label and acceptance event strings are absent from all
production executables and bundled Python sources. Production binary SHA-256:
Launcher `eed6fe31929d69dc2d640a347883a2777f3f0054e6d86100f33b90a733c3a581`,
Kernel `b933a530cb86b17c4a33b6bc01799bb813c0e419c48c96c81b34ce70f2b64522`,
Agent Host `dcb651244186850a7dec94cb8557e19f71bc5d9cf480c80e6d3a6c274b77754d`.
The signed acceptance build embeds the test-only overlay and has Launcher
`22804f90525a34f813acd7730b794acb8a6feb2830c62a431a6248552c3f1e8a`, Kernel
`1276cf25e2e52ae046a14778cffb0aa3ced51f408b4c7fe79a5a3569923943be`, Agent
Host `0a76f99bec6074df0d26f9eaf2a29b4722d030397ed8b38214e6c24cd3bbfe37`.
The separate signed post-commit build at `ef0d2081c7504a335b070e367d9ecb9b97e3f10a`
also records production-hook isolation PASS.

- B32: a DispatchSemaphore blocks the existing serial client's beginSubmission,
  after actual approval. Only the real cancellation method signals it. The normal
  cancellation flag and existing completion path then prevent submission.
- B34 pre: after the committer reports READY, pause before the existing cancel
  recheck and ACCEPT. The controller releases only after the test observer sees
  the matching `workspace.cancel` frame written to the original Kernel worker,
  correlated through the XPC-to-worker request bridge. `cancel_accepted` alone
  does not release the barrier. Existing Kernel logic then sends ABORT.
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
fixture, outside workspace/Host/Runner scopes. The barrier controls timing only;
separate test-only observers record bounded stage and digest metadata. The owner
explicitly authorized agent-operated UI acceptance for this run. The signed App
received native Run Once and Cancel UI actions; no test code simulated or
prefilled either decision. Reports distinguish these maintainer-authorized
agent operations from owner-personal clicks.

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
gate, and expects `process_cancelled`.

B34 pre-commit attempt 6 then showed that the test controller released the
barrier on `cancel_accepted`, before the XPC-to-Python Launcher poll forwarded
the matching cancellation frame. The real Kernel committed successfully and
the Launcher/Host accurately reported that outcome. The fixture now emits
`WORKSPACE_CANCEL_FORWARDED` only after `send_frame` writes the original
`workspace.cancel` message, checks both bridged request IDs, and only then
releases the pre-commit barrier. Attempt 7 exercised this corrected sequence in
the signed app: one authenticated Runner request and private staged edit were
observed, the Kernel returned `process_cancelled`, live workspace hashes stayed
unchanged, and the Task Record and exact Host receipt said `not_committed`.
This correction is confined to the acceptance build overlay and harness.

The signed post-commit attempt 2 reached `KERNEL_POST_COMMIT_PRE_REPLY` only
after `COMMIT_APPLIED` and a verified live `tags.py` replacement. A
maintainer-authorized agent UI cancellation occurred at that barrier. The same
XPC-to-worker request bridge recorded the forwarded cancellation, while the
original Kernel response, Task Record and Host receipt all retained the
successful committed result and Runner return code 0. The live file and canary
hashes matched that outcome. B34 pre-commit, B34 post-commit and B39 terminal
consistency for these cancellation cases are now `PASS_L4`; this does not close
the separate B11/B33/B35/B36 Gate A evidence gaps or Owner Review.
