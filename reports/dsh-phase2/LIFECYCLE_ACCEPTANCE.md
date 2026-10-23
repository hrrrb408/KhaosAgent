# DSH Phase 2: Lifecycle Acceptance

Date: 2026-10-23

Every interactive result below is bound to Khaos source SHA
5abf5d34426304b77a0773c1b30eb8814f5aa44c and DSH SHA
687f282e8625c6b8d11ff58211a90524be2e4317. The actual UI operator was
codex_agent under the explicit user authorization recorded in each evidence
JSON and in [signed-ui-operator-decisions-5abf5d3.json](signed-ui-operator-decisions-5abf5d3.json).
No result attributes an action to the project owner.

## Signed cancellation cases

All three cases used the existing trusted Candidate B preview parser and fixed
edit script against tags.py, with exact read/write scope tags.py. The operator
reviewed and approved the displayed preview, then selected Cancel task at the
named barrier.

- B32 passed: cancellation occurred before workspace.run submission. The
  Runner did not start, no commit occurred, and the terminal result was
  delivered. Evidence: [cancellation-b32-5abf5d3.json](cancellation-b32-5abf5d3.json).
- Pre-commit passed: cancellation was forwarded on the original XPC request
  while the Kernel was held at KERNEL_READY_PRE_ACCEPT. The Kernel returned
  process_cancelled, the commit did not occur, private changes were discarded,
  and the original terminal result was delivered. Evidence:
  [cancellation-pre-commit-5abf5d3.json](cancellation-pre-commit-5abf5d3.json).
- Post-commit passed: the edit had committed before cancellation reached the
  KERNEL_POST_COMMIT_PRE_REPLY barrier. The Kernel returned its original
  successful result with Runner return code 0; the committed edit remained in
  the workspace and the Launcher delivered that result. Evidence:
  [cancellation-post-commit-5abf5d3.json](cancellation-post-commit-5abf5d3.json).

Each case retained one task and one request identity, one Candidate B preview
approval, unchanged sibling canary, and its expected commit outcome. AbortSignal
remains cancellation intent from the untrusted adapter; the original Kernel
result controls the terminal outcome.

## Node child crash and recovery

The first independently approved request read only fixture.txt. The injected
Node crash ended that DSH task with dsh_runtime_failed; its completed Kernel
result remains in the Launcher record. A separate task then independently
read fixture.txt successfully. The two tasks and requests have unique IDs,
there was no automatic retry, the sibling canary was unchanged, and the
process scan found no Node process after XPC teardown. This demonstrates a
later task after a Node child failure; it does not claim that the AgentHost XPC
was replaced. Evidence:
[node-crash-recovery-5abf5d3.json](node-crash-recovery-5abf5d3.json).

## AgentHost XPC crash and recovery

The first task's scoped tags.py edit committed before the injected AgentHost
XPC failed while receiving the tool result. The Launcher retained the
committed Kernel result and recorded one transport failure. A separate task
then connected to a fresh AgentHost XPC and read the committed file. Task and
request IDs were unique, the canary was unchanged, and no Node process
survived XPC teardown. Evidence:
[xpc-crash-recovery-5abf5d3.json](xpc-crash-recovery-5abf5d3.json).

## Cordis lifecycle

The signed plugin-lifecycle probe passed duplicate-registration rejection,
single registration, unload removal, late-result rejection, post-unload call
rejection, and terminal-task call rejection. It used the pinned Cordis
ToolRuntime inside the signed test AgentHost XPC. It requested no workspace
Picker or Runner approval. Evidence:
[cordis-plugin-lifecycle-5abf5d3.json](cordis-plugin-lifecycle-5abf5d3.json).

## Operator evidence boundary

The user explicitly delegated these disposable-fixture UI actions to Codex.
The operator was codex_agent, not project_owner. For each signed operation the
approval, request ID, digest, argv, and scope are retained in the companion
operator record. The signed app's workspace-selection flow also performed its
standard Kernel writeback smoke check in the disposable folder; that file is
separate from DSH proposals and is outside the DSH reads. It is disclosed in
the companion record and was not counted as a DSH Runner approval.

The recorded Node crash and XPC crash scenarios exercise these specific
injected failure points. They do not prove every possible IPC race, arbitrary
process termination timing, or same-UID host failure.
