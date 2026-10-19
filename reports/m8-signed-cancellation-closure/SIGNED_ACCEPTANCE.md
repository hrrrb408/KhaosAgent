# Signed acceptance

B32, B34 pre-commit, B34 post-commit and B39 are **NOT_PROVEN** until the owner
operates the exact signed acceptance apps and the harness assertions complete.
Approval refusal is not post-approval cancellation. No user action is simulated.

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

## B34 build preparation and current outcomes

Signed pre-commit and post-commit acceptance apps are prepared at
`/Users/huangruibang/Applications/khaos-m8-a7-pre-commit-attempt1/` and
`/Users/huangruibang/Applications/khaos-m8-a7-post-commit-attempt1/`. Their
build receipts record production-hook isolation PASS. Neither app was launched
for manual acceptance. B34 pre-commit cancellation, B34 post-commit cancellation
and B39 terminal consistency remain **NOT_PROVEN**.
