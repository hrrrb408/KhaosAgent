# Khaos × DSH Phase 2: Decision

Date: 2026-10-20

## Decision

`CONDITIONAL GO` for continued isolated experimentation only. This does not
authorize replacing the production AgentHost or starting a production
migration.

The latest real signed AgentHost XPC hostile-plugin attack passed at source
SHA `6962a07338da4c5ce1ddc5fa5eb3c68a62aab826`; its evidence is
`signed-xpc-attack-6962a07.json`. It verified direct and child-process
workspace denials, credential denial, localhost and external network denial,
Kernel write denial, oversized-scope rejection, unchanged canaries and Kernel
hash, deep signature validity, and Node process-group cleanup. The bounded DSH
adapter and Cordis lifecycle suite passed 9/9 on pinned DSH SHA
`687f282e8625c6b8d11ff58211a90524be2e4317`.

The signed Cordis lifecycle acceptance passed at source SHA
`81923b77e0c632291cdc317e396a62edca75fba1`; its evidence is
`cordis-plugin-lifecycle-81923b7.json`. The signed app and all three XPC
components reported the same Team ID. It required no Picker or Runner approval
and does not prove workspace-operation or XPC crash/recovery behavior.

The canonical Khaos suite passed at source SHA `6962a073`: 404 tests in
844.086 seconds. Both `python3 tools/check_security_freeze.py` and the check
against exact PR #41 base `b08ab11e01663d2b26304cb541efb5361dea0417` passed with
zero sensitive changes. These local results are SHA-bound. Before this
report-only revision, PR #43 head `56744ef9bcd5385df37a96c2b158de819765bdf4`
passed exact-head GitHub Seed CI
([run 39394236276](https://github.com/hrrrb408/KhaosAgent/actions/runs/39394236276),
16m57s) and Security Freeze
([run 39394236305](https://github.com/hrrrb408/KhaosAgent/actions/runs/39394236305)).
The earlier checks on `8d920ca7971826072df3fd077e7ca8640e39a4b9` are
historical. This report-only commit also requires exact-head checks; PR #43's
description records the current head and its check runs after they complete.

The signed Read → Edit → Test acceptance app built at `a276538` but waited at
the workspace Picker because the owner was unavailable to perform the required
UI action. It timed out after 600 seconds with no workspace selected and no
Runner request. The record is
`failed_attempts/coding-read-edit-test-a276538.failed.json`; this is a failed
attempt, not a pass, approval denial, or cancellation.

## Evidence still required

- Signed B32, pre-commit, and post-commit cancellation with owner UI actions.
- Signed Node child-crash/recovery and AgentHost XPC crash/recovery, each with
  the later independently approved task.
- Signed deterministic Read → Edit → Test completion and fake-result
  acceptance.
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
