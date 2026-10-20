# Khaos × DSH Phase 2: Decision

Date: 2026-10-20

## Decision

`CONDITIONAL GO` for continued isolated experimentation only. This is not
approval to replace the production AgentHost or to begin a production migration.

The pinned DSH adapter has a bounded proposal/result path through the existing
Launcher interface, and its eight deterministic adapter tests pass. The
signed runtime bundle compiles with dependencies bundled. The signed
standalone Node/DSH packaging smoke passed at 111,028,546 app bytes and
55,590,912 Node RSS bytes, with matching Team IDs and the expected sandbox
entitlements. The real signed AgentHost XPC hostile-plugin attack also passed
at source SHA `efadf67a35bb70e0441f737af457a619e7c8aae3`; its external evidence
record is `/tmp/khaos-dsh-phase2/signed-xpc-attack-efadf67.json`. That attack
has not yet been rerun at the coding acceptance source SHA `ddf41da`. The
signed coding app built successfully at `ddf41da`, but its UI acceptance
timed out at the Picker before a workspace selection reached the app; no
Runner operation was submitted. The canonical Khaos suite passed 404 tests
at `ddf41da` and both local Security Freeze checks passed. PR #43
`security-tests` and `security-freeze` checks passed at `ddf41da`; after the
evidence-report commit `15ac0e4`, the Freeze check passed and `security-tests`
was still pending at the latest poll.

## Evidence still required

- Signed B32, pre-commit, and post-commit cancellation with owner UI actions.
- Signed Node crash/recovery acceptance with a later independently approved
  task.
- Signed deterministic Read → Edit → Test completion and fake-result
  acceptance.
- A signed XPC hostile-plugin attack on the current integration source head.
- Final Seed CI and Security Freeze checks after the final evidence/document
  commit.
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
