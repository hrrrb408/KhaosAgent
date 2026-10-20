# Khaos × DSH Phase 2: Decision

Date: 2026-10-20

## Decision

`CONDITIONAL GO` for continued isolated experimentation only. This is not
approval to replace the production AgentHost or to begin a production migration.

The pinned DSH adapter has a bounded proposal/result path through the existing
Launcher interface, and its seven deterministic adapter tests pass. The
signed runtime bundle compiles with dependencies bundled. The signed
standalone Node/DSH packaging smoke passed at 111,028,546 app bytes and
55,590,912 Node RSS bytes, with matching Team IDs and the expected sandbox
entitlements. The real signed AgentHost XPC hostile-plugin attack also passed
at source SHA `3d144da2e182ed8e0303965d92b177cd2e3eccd5`; its external evidence
record is `/tmp/khaos-dsh-phase2/signed-xpc-attack-3d144da.json`. These checks
do not prove the signed lifecycle acceptance or coding UI workflow.

## Evidence still required

- Signed B32, pre-commit, and post-commit cancellation with owner UI actions.
- Signed Node crash/recovery acceptance with a later independently approved
  task.
- Signed deterministic Read → Edit → Test and fake-result acceptance.
- Successful Seed CI for the exact Draft PR head.
- Independent Code Owner review; `NOT_PROVEN` in single-maintainer mode.

Until those checks are complete, Phase 2 is not a GO for formal Harness
Migration. No claim is made that DSH is safe as a production AgentHost.

## Authority and architecture deltas

```text
Kernel Authority Delta: 0
Kernel ABI Delta: 0
Workspace Scope Authority Delta: 0
Trusted Runtime Delta: 0
Production Dependency Delta: 0
Experimental Dependency Delta: pinned DSH + Node.js v22.19.0, test build only
New trusted processes: 0
New IPC operations: 0
New persistent state: 0
New architecture concepts: 0
```

The DSH runtime and test Host override are untrusted/test-only. Trusted
Candidate approval, Kernel execution, and commit validation remain unchanged.
