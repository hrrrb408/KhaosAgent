# Gate B.0 Final Decision

**Checkpoint:** 2026-10-25; experimental runtime binding and result-correlation implementation are present. The corrected result path has unit evidence but no post-correction signed exercise.

**Engineering status:** `PARTIAL`; signed multi-workspace acceptance remains blocked by failed A/B evidence and the untested post-trial result-correlation correction.

| Required output | Status |
|---|---|
| Gate B.0 Engineering | PARTIAL |
| Signing Root Cause | PARTIAL; historical `CSSMERR_TP_NOT_TRUSTED` source unknown |
| Signing Identity | VALID |
| Small Signed App | PASS at source SHA `a387aeee`; one unchanged no-model app used for both workspace attempts |
| Actual Experimental Source Changes | YES |
| Runtime Workspace Binding | IMPLEMENTED in experimental Launcher overlay |
| Prebuilt App Reuse | IMPLEMENTED with fail-closed signer and receipt validation |
| Workspace Isolation Unit Tests | PASS |
| Stale Authorization Replay Tests | PASS |
| Workspace Replacement Tests | PASS |
| Cross-Trial Result Isolation | PASS in synthetic evidence-validator tests; signed result replay NOT_RUN |
| Experimental Launcher Trusted Delta | DECLARED |
| Signed Multi-Workspace Acceptance | BLOCKED; both signed records have formal FAIL verdicts |
| One App / Two Workspaces | NOT_PROVEN |
| Large GGUF Copies | 0 |
| Real Model Invocations | 0 |
| Historical Files Deleted | 0 |
| Canonical Tests | PASS — 464 tests in 843.146 seconds |
| Security Freeze | Default PASS; exact-base PASS (5 declared sensitive changes) |
| Final-Head GitHub CI | PENDING push and exact-head checks |
| Independent Security Review | PENDING / NOT_PERFORMED |
| Gate B Real-Model Readiness | BLOCKED |
| Owner Action Required | NO signing repair required |
| Updated PR | #48; draft and unmerged |

## Decision basis

The signing identity is usable, and one small signed app was used unchanged with two independently selected workspaces. Trial A completed its five signed operations, passed its two public tests and three hidden checks, and changed only the intended source file. Trial B returned a nonzero Runner result without disclosing the out-of-scope canary or changing its workspace. These observations are retained, but both acceptance records failed result-identity validation; Trial B also ended incomplete, so they do not establish signed multi-workspace acceptance.

The experimental source now binds the exact Launcher result text digest and emits a parent-process terminal record after a Host reply. Focused builder, runner, pinned DSH, and Swift syntax checks pass. This correction was made after the signed attempts and has not been signed-tested. No real model was invoked, no `.gguf` was copied, and the production Kernel/ABI/runtime authority did not change. Independent security review remains required. Do not present Gate B real-model readiness or One App / Two Workspaces as PASS.
