# Signed acceptance

B32 is **PASS_L4** from the owner-operated signed acceptance in attempt 6 and
its preserved-artifact reconciliation. B34 pre-commit, B34 post-commit and the
complete B39 matrix remain **NOT_PROVEN**. Approval refusal is not post-approval
cancellation. No user action is simulated.

The implementation commit is `c7c1354ce67a60721c28328d675bec32404d79dd`.
Attempts 3 and 4 were built from `64fa81387811ff9c5904cd22e3547de112be3a51`;
the commits after `c7c1354` changed only reports. The production app is
separately built from unmodified inputs; each acceptance app uses test-only
overlays. Each attempt retains its build record, source/binary hashes,
signature verification, workspace, Kernel events, Launcher logs and JSON
result. Failed attempts are never overwritten.

## Development preparation history

- `~/Applications/khaos-m8-a7-b32-attempt1`: compiled production + initial overlay;
  no manual run, no L4 claim. Predates terminal-delivery change.
- `~/Applications/khaos-m8-a7-b32-attempt2`: compiled during terminal-receipt
  development; no manual run, no L4 claim. Superseded fixture, preserved.
- `~/Applications/khaos-m8-a7-b32-attempt3`: signed run timed out before workspace
  selection; detail below.

The harness records source commit, dirty-diff digest, signed certificate, binary
hashes, Request/Task/workspace-session/XPC IDs, frozen invocation digest, approval,
barrier, exact workspace hashes, Kernel ingress and Runner counts, original
serialized response, Task Record, and exact terminal-data receipt from the
sandboxed Host's deterministic model probe. This is protocol acceptance, not
real-model coding-quality evidence.

## B32 attempt 3: no UI selection observed

- Outcome: `FAILED_ATTEMPT_PRE_APPROVAL_UI`; this is not a cancellation failure
  and is not B32 evidence.
- Signed app source commit: `c7c1354ce67a60721c28328d675bec32404d79dd`.
- The harness opened the system workspace Picker, but the owner did not select
  the disposable workspace before the 600-second outer deadline. Therefore
  Candidate preview, approval, POST_APPROVAL_PRE_SUBMIT barrier, Cancel, and
  workspace.run were never reached. No Task Record was produced.
- Workspace before and after hashes matched: `tags.py`
  `476ac287f5ed529f016a1ba705a336abb57f38156da8a097a2a0ddbed2e5f164`;
  `unscoped-canary.txt`
  `b8245a42e2c8d3a781e1235308f65911a61b1462df2bc56e47ab2eae7e45c9de`.
- Build and attempt artifacts are retained in
  `/Users/huangruibang/Applications/khaos-m8-a7-b32-attempt3/`.
  No acceptance claim or approval was inferred.
- The subsequent signed run is retained in
  `/Users/huangruibang/Applications/khaos-m8-a7-b32-attempt4/`; its result is
  documented below.

## B32 attempt 4: signed Picker timed out before approval

- Result: `FAILED_ATTEMPT_PRE_APPROVAL_UI`; B32 remains **NOT_PROVEN**. The
  signed app opened the real macOS workspace Picker. The owner did not select
  the disposable workspace within 600 seconds, so Candidate preview, Run Once,
  POST_APPROVAL_PRE_SUBMIT, Cancel, and `workspace.run` were never reached.
- Build receipt SHA-256:
  `69a9735809a3707b803856181580e8ac72760344a26e267f5a59bed2fc86b14f`.
  Receipt source commit: `64fa81387811ff9c5904cd22e3547de112be3a51`.
- Signed app: `org.khaos.Seed`; Apple Development identity
  `8613929930739 (8X4352T2RG)`; Team ID `UBAP6LN5AM`; CDHash
  `57cd15c2bd044cccfb881a05fcb763c6c3340138`.
- Acceptance Launcher SHA-256:
  `5df42fd5347d04d278c675650e58e0e410aaffff1df3b98838cc56984eafde2d`.
  Kernel: `2517eadb10df5457385467791267b2a5d780d9a85e1a433c9da48830331dc497`.
  Agent Host: `6a1928a2320268a44818f37f6ed00c06b6231232e51f8b09414b08b28bfab0c9`.
- Test-hook isolation: **PASS**. Production Launcher/Kernel/Agent Host hashes
  are recorded in `build.json`; barrier markers are absent from the production
  binaries and embedded Python sources.
- Request/Task IDs, workspace session, frozen invocation digest, approval
  decision, and cancellation stage are not present in the captured artifacts.
  No Kernel submission, Runner execution, original Kernel result, or Launcher
  Task Record was observed. `kernel-events.jsonl` is empty.
- Workspace before/after SHA-256 is identical:
  `tags.py` `476ac287f5ed529f016a1ba705a336abb57f38156da8a097a2a0ddbed2e5f164`;
  `unscoped-canary.txt`
  `b8245a42e2c8d3a781e1235308f65911a61b1462df2bc56e47ab2eae7e45c9de`.
- Preserved artifacts:
  `/Users/huangruibang/Applications/khaos-m8-a7-b32-attempt4/`. Its
  `acceptance.json` says `FAILED_ATTEMPT` with `signed app did not finish: None`;
  this report classifies the actual stage as pre-approval Picker timeout. It is
  not a cancellation failure and supplies no L4 pass evidence.

## B32 attempt 5: cancellation action not received before barrier timeout

- Outcome: `FAILED_ATTEMPT`; no L4 evidence. The owner selected the disposable
  workspace and approved Run Once, but no cancellation acknowledgment arrived
  before the 55-second barrier expired. The Launcher record says
  `cancellation_requested=false`; the request ended as
  `not_submitted:kernel_request_timeout`. Kernel submission and Runner counts
  were zero, and workspace hashes remained unchanged. This is an incomplete
  manual action, not a cancellation failure.
- Artifacts are retained in
  `/Users/huangruibang/Applications/khaos-m8-a7-b32-attempt5/`.

## B32 attempt 6: owner cancellation after approval, before submission

- Result: **PASS_L4** after reconciling the saved signed-run artifacts with the
  corrected receipt assertion. The original run script exited at a false
  whole-response equality assertion: the deterministic Host probe returns the
  exact terminal bytes followed by fixed probe instructions. The corrected
  check verifies those exact bytes as the Host receipt prefix. Its focused
  regression test passes. The original failed `acceptance.json` is preserved;
  the separate `reconciliation.json` records every replayed assertion and
  input-artifact hash. No UI was replayed during reconciliation.
- Signed app: `org.khaos.Seed`; Apple Development identity
  `8613929930739 (8X4352T2RG)`; Team ID `UBAP6LN5AM`; CDHash
  `29161729c37aa1eae35adb55d77e1fe7fcf69551`; deep signature verification
  **PASS**. Source commit: `f6f8b67164eb690cd4d62dc6736025bf3dbd764d`;
  source diff SHA-256 is the empty-diff digest.
- Build receipt SHA-256:
  `a76d5c5213f9d4d6263818bd88105c2a107b99897628daee0b90ee4be80b2005`.
  Production test-hook isolation: **PASS**. Acceptance Launcher SHA-256
  `ac5ae51e54c8ad807375bcdcbe79a215fb35bbc44405791240563ce1c6f1ebda`;
  Kernel `af8acd009de7b868f0f5518f0a62a15d8657b06d765edcbdb69a93241b7bd574`;
  Agent Host `82d3aaf5de82b0f41f60d816cad7e2c16afc0fd9eb265e0fa1fb159ab8ec5f1f`.
- The owner approved Candidate B, then clicked Cancel while the original task
  showed the authenticated-connection progress message and the test barrier was
  `POST_APPROVAL_PRE_SUBMIT`. Task ID `3c0848a2-9986-4c2f-9797-662a84597305`;
  Request ID `551281db419241bab1e3cd06fd065a1d`; Workspace Session ID
  `ba23c463-917d-46c1-aa51-4dda82f4292e`; XPC Connection ID
  `b922d9d7-8ea2-4bf9-833d-d586a4d3378b`; frozen invocation SHA-256
  `220f63aaf41b5400ef4d905cf6067a3d237a86ced29cfa866ee94d05be905807`.
- Approval: `approved_candidate_b_preview`. Cancellation acknowledgment:
  `not_sent_before_submission`. Kernel submission count **0**; Runner execution
  count **0**. Original terminal result:
  `not_submitted:cancelled_before_runner_submission`. The Launcher Task Record
  has `cancellation_requested=true`, `commit_outcome=not_committed`,
  `runner_execution=not_started`, and `terminal_result_delivery=delivered`.
- Workspace before, at the barrier, and after match exactly:
  `tags.py` `476ac287f5ed529f016a1ba705a336abb57f38156da8a097a2a0ddbed2e5f164`;
  `unscoped-canary.txt`
  `b8245a42e2c8d3a781e1235308f65911a61b1462df2bc56e47ab2eae7e45c9de`.
  `kernel-events.jsonl` is empty. The Host receipt decodes to the exact
  143-byte Launcher terminal result followed by the fixed bounded probe text.
- All attempt files, including the initial runner failure, are retained in
  `/Users/huangruibang/Applications/khaos-m8-a7-b32-attempt6/`.

## B34 build preparation and current outcomes

Signed pre-commit and post-commit acceptance apps are prepared at
`/Users/huangruibang/Applications/khaos-m8-a7-pre-commit-attempt1/` and
`/Users/huangruibang/Applications/khaos-m8-a7-post-commit-attempt1/`. Their
build receipts record production-hook isolation PASS. Neither app was launched
for manual acceptance. B34 pre-commit cancellation, B34 post-commit cancellation
and B39 terminal consistency remain **NOT_PROVEN**.
