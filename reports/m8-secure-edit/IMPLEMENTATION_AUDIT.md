# M8.5.2 — Implementation and TCB Audit

Status: **no production implementation started**
Baseline: PR #33 head `1d1457f43f788d30f6fa4f48890b900ef9406c07`

## Changed files

- `tests/macos_xpc_probe/AgentHostSandboxModelProbe.swift`: deterministic test-only proposal/result behavior for staged-edit feasibility; now validates that the Runner's bounded stdout contains `EDIT_APPLIED` before echoing it.
- `tests/test_macos_xpc_sandbox.py`: real macOS Seatbelt/Kernel headless success and injected-failure cases, plus signed staged-edit acceptance assertions.
- `security/security-change.json`, `security/tcb-manifest.json`, and `security/freeze-baseline.json`: exact-base test-governance declaration and hashes.
- `reports/m8-secure-edit/`: evidence and audit documents.

No `khaos/` production file changed. The v8 signed Runner executed one explicitly authorized replacement in a disposable workspace. Parent acceptance verified the final bytes and mode, exact one-file changeset, no temp residue, canary preservation, focused test, Task Record, and deep strict signature. Refusal v2 passed with zero Runner executions and no workspace change. The current diff adds no runtime capability and changes no trusted enforcement behavior. The remaining Gate A attack matrix is still open, so Phase 2 remains stopped.

## Required accounting

```text
Production code delta: 0
Trusted code delta: 0 files / 0 lines
New architecture concepts: 0
New trusted processes: 0
New IPC operations: 0
New persistent state: 0
New dependencies: 0
Removed duplication / abstractions: 0
```

The test probe duplicates a bounded fixed command fixture rather than adding a production abstraction. No production Edit Action should be added until Gate A is complete. If implementation later proceeds, it must remain in the untrusted Host and lower to the existing `AgentShellProposal`; trusted changes are outside scope.

## Governance

Current-tree and exact-base Security Freeze checks pass. The declaration is a review aid, not independent approval. Independent Code Owner approval remains NOT_PROVEN.
