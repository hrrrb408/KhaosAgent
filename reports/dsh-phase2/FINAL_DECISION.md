# Khaos × DSH Phase 2: Decision

Date: 2026-10-20

## Decision

`CONDITIONAL GO` for continued isolated experimentation only. This does not
authorize replacing the production AgentHost or starting a production
migration.

The real signed AgentHost XPC hostile-plugin attack passed at exact source SHA
`a2765389989d7c4290eb754b459f2a516990d155`; its evidence is
`signed-xpc-attack-a276538.json`. It verified workspace and Kernel access
denials, credential and network denial, scope rejection, deep signature
validity, unchanged canaries, and Node process-group cleanup. The bounded DSH
adapter regression suite passed 8/8 after the result-message callback fix.
The current-head and PR #41 base Security Freeze checks passed with zero
sensitive changes at `a276538`. The canonical suite passed at that source SHA:
404 tests in 807.939 seconds. Final PR #43 CI and Security Freeze checks after
the report commit remain pending.

The signed Read → Edit → Test acceptance app built at `a276538` but waited at
the workspace Picker because the owner was unavailable to perform the required
UI action. It timed out after 600 seconds with no workspace selected and no
Runner request. The record is
`failed_attempts/coding-read-edit-test-a276538.failed.json`; this is a failed
attempt, not a pass, approval denial, or cancellation.

## Evidence still required

- Signed B32, pre-commit, and post-commit cancellation with owner UI actions.
- Signed Node crash/recovery acceptance with a later independently approved
  task.
- Signed deterministic Read → Edit → Test completion and fake-result
  acceptance.
- PR #43 Seed CI and Security Freeze checks after the final report commit.
- Independent Code Owner review; `NOT_PROVEN` in single-maintainer mode.

Until those checks are complete, Phase 2 is not a GO for formal Harness
Migration. No claim is made that DSH is safe as a production AgentHost.

## Authority, architecture, and TCB deltas

```text
Production code delta: 0
Trusted code delta: 0
Kernel Authority Delta: 0
Kernel ABI Delta: 0
Workspace Scope Authority Delta: 0
Trusted Runtime Delta: 0
New architecture concepts: 0
New trusted processes: 0
New IPC operations: 0
New persistent state: 0
Production dependencies: 0
Experimental dependencies: pinned DSH + Node.js v22.19.0, test build only
Removed duplication / abstractions: 0
```

The DSH runtime and test Host override are untrusted/test-only. Trusted
Candidate approval, Kernel execution, and commit validation remain unchanged.
