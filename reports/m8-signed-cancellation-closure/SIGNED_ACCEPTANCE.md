# Signed acceptance

B32, B34 pre-commit, B34 post-commit, and B39 terminal consistency across those
cancellation cases are **PASS_L4**. Approval refusal is not post-approval
cancellation. No test code simulates approval or cancellation; the real signed
App received owner-authorized native UI actions. B34 actions were operated by
the agent at the owner's explicit direction and are labeled that way throughout.

The production app is separately built from unmodified inputs; each acceptance
app uses test-only overlays. Each attempt retains its build record,
source/binary hashes, signature verification, workspace, Kernel events,
Launcher logs and JSON result. Failed attempts are never overwritten.

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
build receipts record production-hook isolation PASS. The original pre-commit
attempt1 and post-commit attempt1 apps were not launched.

### B34 pre-commit attempt 2: cancel acknowledged, evidence assertion incomplete

- The owner approved Candidate B and clicked Cancel at `KERNEL_READY_PRE_ACCEPT`.
  The signed app acknowledged `cancel_accepted`; the original Kernel reply was
  `process_cancelled`; the Launcher Task Record says `not_committed`; the Host
  received the same terminal result; and workspace hashes matched before, at
  the barrier, and after cancellation.
- This attempt is **NOT_PROVEN** because its acceptance instrumentation did not
  capture the Runner `process.exec` request or staged private changeset, and its
  runner also incorrectly expected `commit_rejected` instead of the observed
  `process_cancelled`. The original evidence is retained at
  `/Users/huangruibang/Applications/khaos-m8-a7-pre-commit-attempt2/`.
- Its signed source commit was `c5edbeffa75512ba4b8fca8b83d20069312464da`;
  build receipt SHA-256 `971808ce8e99b171f006a7d3b5b06666f3af21e658f4f85e355053bea01d3c32`;
  production test-hook isolation was **PASS**. Signed identity
  `Apple Development: 8613929930739 (8X4352T2RG)`, Team ID `UBAP6LN5AM`,
  CDHash `6182f17a7a8d334c764364a8a470f87dd3695481`. Launcher SHA-256
  `7cb1bd34da7f38751fcbcb6f9251cd09aae485f8cb24c745564d010a780c935d`, Kernel
  `2ef2f078e74b923c3cc69ed8fd2dca2581c9ab911e80feee77196c8fea2cf449`, Agent
  Host `5a32d96b16d6a4dbc4b8f77dd2fa1d8ecd9c746b92cbc795f7bbe81149273dc4`.
- Task ID `7ab54829-86ce-43b5-b24b-4a01790b8b3c`; Request ID
  `bd80973139bb4a49bffd5e72ebc51f02`; Workspace Session ID
  `43741c46-10b4-4090-873d-795d6d89e53e`; XPC Connection ID
  `88693d75-215f-402e-98e5-0da945d7bb39`; invocation SHA-256
  `29e5ed74d9bc9f56ec57b0208becb439d86e7ae0fd0fe87d6c56965d5aa3b721`.
  The owner action is not repeated evidence for a later corrected signed build.

The earlier B34 attempt 2 remains **NOT_PROVEN** because it did not bind the
Runner request and private staged change. B34 attempt 6 exposed a release-order
race in the test controller; attempt 7 below is the corrected signed run.

### B34 pre-commit attempt 6: cancellation acknowledgment released too early

- The real signed app reached the correct `KERNEL_READY_PRE_ACCEPT` barrier after
  one Runner request had changed the private snapshot. A maintainer-authorized
  agent UI action clicked Cancel on the original Task Progress window. The app
  returned `cancel_accepted`, but the controller released the barrier before
  the Python Launcher forwarded the matching `workspace.cancel` frame to its
  Kernel worker. The Kernel then accepted and committed the staged changeset.
- This is **FAILED_ATTEMPT**, not a pre-commit cancellation pass. Original Kernel
  response was successful `output`; the workspace changed from `476ac287…` to
  `8db3b1d5…`; and the Task Record and Host receipt truthfully said committed,
  Runner return code 0. The harness failed because it expected an error response.
  All artifacts are preserved at
  `/Users/huangruibang/Applications/khaos-m8-a7-pre-commit-attempt6/`.
- Source commit `5251cfa38cdfd84cd428f65b7589a35bb508992e`; build receipt
  SHA-256 `e99fffc46bfc9dc9b092dd42195c5c68b7fd273648b53db1471e53c7a77f6441`;
  production-hook isolation **PASS**. Signed identity `Apple Development:
  8613929930739 (8X4352T2RG)`, Team `UBAP6LN5AM`, Bundle ID `org.khaos.Seed`,
  CDHash `acf91fc08f797dde0686c119350b67f019fec656`. Launcher SHA-256
  `0e6a5b1295c9dcbc0e30b40eee6a407a73763ddd094550ec49a94ea080182981`, Kernel
  `5159eba9a3b4dda9b4d66acf971daa51d56690469870608522fea115e241a725`, Agent
  Host `75e54d9e8a093254942d81870e090bb9a7c5130f4f035c949581bd33aff2a4bd`.
- Task ID `66aaa170-3346-4bb1-b9fb-f927202e0497`; Request ID
  `c2eba1b830ad42bcb4e79da862e844da`; Workspace Session ID
  `18fa99ce-3043-4817-a5a6-ee464a97bf4a`; XPC Connection ID
  `afedd009-0947-4db1-845b-8a14c452f294`; invocation SHA-256
  `c36bd0f3de49730428af21b4d3d4ea01a4b172771831ef9ebf85551c08632553`.

### B34 pre-commit attempt 7: synchronized cancellation forwarded to Kernel

- The corrected signed build is from exact source commit
  `184c2c609d7123a692c8e8778b617cc1dfba07e6`; source-diff SHA-256 is the empty
  tree `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`;
  build receipt SHA-256 `df7414b4fb2e2ee526b0afe8edd3a46b5f63f6f5261f2200a40aaef9f0d50e97`.
  Production-hook isolation **PASS**. Signed identity `Apple Development:
  8613929930739 (8X4352T2RG)`, Team `UBAP6LN5AM`, Bundle ID `org.khaos.Seed`,
  CDHash `de6bda27f1b70f0072813f38481666b61b3d01a3`. Acceptance Launcher SHA-256
  `22804f90525a34f813acd7730b794acb8a6feb2830c62a431a6248552c3f1e8a`, Kernel
  `1276cf25e2e52ae046a14778cffb0aa3ced51f408b4c7fe79a5a3569923943be`, Agent
  Host `0a76f99bec6074df0d26f9eaf2a29b4722d030397ed8b38214e6c24cd3bbfe37`.
- A maintainer-authorized agent UI operation selected the disposable workspace,
  reviewed the actual Candidate B replacement and exact `tags.py` read/write
  scopes, clicked Run Once, then clicked Cancel at `KERNEL_READY_PRE_ACCEPT`.
  The Kernel barrier stayed closed until a test-only
  `WORKSPACE_CANCEL_FORWARDED` event linked the XPC request to the same internal
  workspace request; only then was the barrier released.
- Task ID `4baf75f1-e2ac-4f91-955b-d98681e8224a`; Request ID
  `ac8383a0793a4c25bf484688b3d3517d`; internal workspace request ID
  `c4cbd5b7191428cad0c07c02bfce3901`; Runner request ID
  `9193b6f629b4b30e515471351b934f08`; Workspace Session ID
  `74542503-9f03-4595-823d-013ededec374`; XPC Connection ID
  `2513b969-9725-4352-b066-ccb21a9719be`; invocation SHA-256
  `6d1152b673d3f3dd9ca3307479e3925b7a35a152df3b5d59bae1d97cc45eba56`.
- Approval was `approved_candidate_b_preview`. Kernel submission count **1**;
  authenticated Runner request count **1**. Private snapshot changed only
  `tags.py`, from baseline SHA-256
  `476ac287f5ed529f016a1ba705a336abb57f38156da8a097a2a0ddbed2e5f164` to
  candidate SHA-256
  `8db3b1d5a79058bc0db32f9904c38162c6384ff813d41ab45b9db2348a264a63`.
  Original Kernel terminal result was `process_cancelled`; Task Record says
  `commit_outcome=not_committed`, `kernel_result=error:process_cancelled`, and
  `terminal_result_delivery=delivered`. Its `runner_execution=unknown` and null
  return code are retained as recorded; the authenticated Runner request and
  private staged write are separately observed. Workspace hashes before, at the
  barrier, and after match (`tags.py` baseline above;
  `unscoped-canary.txt` SHA-256
  `b8245a42e2c8d3a781e1235308f65911a61b1462df2bc56e47ab2eae7e45c9de`). The
  Host receipt contains the exact Launcher terminal bytes. This satisfies
  **B34 pre-commit PASS_L4** and proves this B34 subcase of terminal consistency.
  Full attempt artifacts remain at
  `/Users/huangruibang/Applications/khaos-m8-a7-pre-commit-attempt7/`.

B34 pre-commit is **PASS_L4**. The CUA actions above are recorded as
maintainer-authorized agent operations, not as owner-personal clicks.

### B34 post-commit attempt 2: late cancellation preserves the commit

- Source commit `ef0d2081c7504a335b070e367d9ecb9b97e3f10a`; source-diff SHA-256
  is the empty tree `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`;
  build receipt SHA-256 `8f53d338a8b688d00b53c42e277baf74665ee3d1e25d471420e4d0e5c67fa103`.
  Production-hook isolation **PASS**. Signed identity `Apple Development:
  8613929930739 (8X4352T2RG)`, Team `UBAP6LN5AM`, Bundle ID `org.khaos.Seed`,
  CDHash `9bb06dfa2676c0eafe5e3961cbcfb570b2ef4d89`. Acceptance Launcher SHA-256
  `9de520240e65fe534953e31095c8231c5534b39ade398bdaa411102c62da2d33`, Kernel
  `b14d1807a2192a299274c763b3e26bd879f78aa70be669b9c99c71ac811a66a4`, Agent
  Host `19138b655ea9c466dc0fa3ca6c1e288b182cf919dd9103cba99da3200448f5ec`.
- A maintainer-authorized agent UI operation selected the disposable workspace,
  reviewed Candidate B and exact `tags.py` read/write scopes, clicked Run Once,
  then clicked Cancel at `KERNEL_POST_COMMIT_PRE_REPLY`, after the real Kernel
  emitted `COMMIT_APPLIED`. The cancellation frame was observed with the same
  XPC request and bridged internal workspace request before the test barrier
  released.
- Task ID `607c85a1-18f3-43c5-9168-c475375aae2b`; Request ID
  `1fb056ce6da74ccc825b59b1aa16d278`; internal workspace request ID
  `82a5cc348f28e9f7b71c41f14fde3ade`; Runner request ID
  `d8f0aedb53b3d0dc3124a80f7a9fd620`; Workspace Session ID
  `16671fc9-0751-4050-af9a-67d7242d8bdf`; XPC Connection ID
  `54383353-e191-45ea-b840-012d7c3ed615`; invocation SHA-256
  `a9bd3875450a981d8eec258f1c00076e59958ed1e167034247cfc065febf3f52`.
- Approval was `approved_candidate_b_preview`; cancellation result was
  `cancel_accepted`. Kernel submission count **1**, authenticated Runner request
  count **1**, and commit event reports `added=0, modified=1, deleted=0`.
  Original Kernel terminal result was successful `output` with Runner return
  code **0**. The Task Record says `cancellation_requested=true`,
  `commit_outcome=committed`, `kernel_result=output`,
  `runner_execution=completed`, `runner_return_code=0`, and terminal delivery
  `delivered`. Host received the same terminal bytes followed by its bounded
  probe response. Workspace `tags.py` changed from baseline SHA-256
  `476ac287f5ed529f016a1ba705a336abb57f38156da8a097a2a0ddbed2e5f164` to
  committed SHA-256
  `8db3b1d5a79058bc0db32f9904c38162c6384ff813d41ab45b9db2348a264a63`; the
  canary stayed `b8245a42e2c8d3a781e1235308f65911a61b1462df2bc56e47ab2eae7e45c9de`.
  This is **B34 post-commit PASS_L4**. The original committed result remained
  authoritative despite the later cancellation acknowledgment. Artifacts are
  retained at `/Users/huangruibang/Applications/khaos-m8-a7-post-commit-attempt2/`.

B34 pre-commit: **PASS_L4**. B34 post-commit: **PASS_L4**. B39 terminal
consistency across B32, B34 pre-commit and B34 post-commit: **PASS_L4**. Agent UI
actions were explicitly authorized by the project owner and are reported as
agent-operated UI actions, not owner-personal clicks.
