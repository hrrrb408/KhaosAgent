# Signed acceptance

B32, B34 pre-commit, B34 post-commit and B39 are **NOT_PROVEN** until the owner
operates the exact signed acceptance apps and the harness assertions complete.
Approval refusal is not post-approval cancellation. No user action is simulated.

Code baseline prepared for current acceptance: `c7c1354` (full SHA is in each
build receipt). The production app is separately built from unmodified inputs;
the acceptance app uses the listed test-only overlays. Each new attempt retains
its own build record, source/binary hashes, signature verification, workspace,
Kernel events, Launcher logs and JSON result. Raw artifact paths and outcomes
will be appended here after execution. Failed attempts are never overwritten.

## Development preparation history

- `~/Applications/khaos-m8-a7-b32-attempt1`: compiled production + initial overlay;
  no manual run, no L4 claim. Predates terminal-delivery change.
- `~/Applications/khaos-m8-a7-b32-attempt2`: compiled during terminal-receipt
  development; no manual run, no L4 claim. Superseded fixture, preserved.
- `~/Applications/khaos-m8-a7-b32-attempt3`: final-source preparation in progress.

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
- A new current-source B32 build is being prepared at
  `/Users/huangruibang/Applications/khaos-m8-a7-b32-attempt4/`; no UI run has
  started for that build.
