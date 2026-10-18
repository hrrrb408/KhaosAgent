# M8.5.2 — Security Invariants and Delta

Status: **runtime delta 0; Gate A remains NOT_PROVEN**
Baseline: PR #33 head `1d1457f43f788d30f6fa4f48890b900ef9406c07`

## Preserved boundaries

| Invariant | Evidence in this branch | Limit |
|---|---|---|
| AgentHost/model do not write the live workspace directly | The test proposal goes through existing Launcher → Kernel → Runner APIs | No production Edit Action was integrated |
| User approval remains independent per operation | v8 displayed the complete fixed request and recorded one Run once decision; refusal v2 recorded one denial and zero executions | Broad reviewability near size and Unicode limits remains NOT_PROVEN |
| Workspace scopes remain exact | v8 signed request and headless tests use only `tags.py` read/write scope | Broader target-specific adversarial paths remain NOT_PROVEN |
| Complete changeset is checked before live writeback | Cleanup-failure test leaves the temp in the private snapshot and observes whole-changeset rejection | This is deterministic fault injection, not an OS-originated cleanup error |
| Model text is data, not executable source | Probe JSON-encodes `oldText` and `newText` as separate argv arguments | Production translation does not yet exist |
| Nonzero command status is not treated as rollback | Tests inspect actual final target/changeset after post-replace exception | This does not establish general transactionality |

## TCB and architecture accounting

```text
Production code delta: 0 lines
Trusted code delta: 0 lines / 0 files
New architecture concepts: 0
New trusted processes: 0
New IPC operations: 0
New persistent state: 0
New dependencies: 0
New permissions: 0
New tool/context/timeout budget: 0
```

Only test probe code, tests, Freeze governance inputs, and reports changed. Independent Code Owner approval remains NOT_PROVEN. The current-tree and exact-base Security Freeze checks pass.

## Residual security evidence

Gate A's positive signed edit path passed in v8 with parent-side final-state inspection, and signed refusal passed in v2. The remaining target-specific scope, alias, rename/TOCTOU, unreadable-baseline, cancellation/termination, and changeset-rejection outcomes remain unproven. No security claim should exceed the enumerated evidence.
