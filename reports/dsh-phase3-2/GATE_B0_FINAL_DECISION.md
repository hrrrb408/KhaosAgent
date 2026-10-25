# Gate B.0 Final Decision

**Checkpoint:** 2026-10-25; another corrected signed build and final CI are pending.
**Engineering status:** `PARTIAL` until the corrected signed acceptance and final-head checks complete.

| Required output | Status at this checkpoint |
|---|---|
| Gate B.0 Engineering | PARTIAL |
| Signing Root Cause | PARTIAL; historical `CSSMERR_TP_NOT_TRUSTED` origin unknown |
| Signing Identity | VALID |
| Small Signed App | NOT_RUN for corrected source; pre-correction no-model app passed deep/strict verification |
| Actual Experimental Source Changes | YES |
| Runtime Workspace Binding | IMPLEMENTED in experimental Launcher overlay |
| Prebuilt App Reuse | IMPLEMENTED with fail-closed signature and receipt validation |
| Workspace Isolation Unit Tests | PASS |
| Stale Authorization Replay Tests | PASS |
| Workspace Replacement Tests | PASS |
| Cross-Trial Result Isolation | PASS in synthetic evidence-validator tests; signed replay not attempted |
| Experimental Launcher Trusted Delta | DECLARED |
| Signed Multi-Workspace Acceptance | NOT_RUN for corrected source; prior Trial A attempt FAILED |
| One App / Two Workspaces | NOT_PROVEN |
| Large GGUF Copies | 0 REQUIRED |
| Real Model Invocations | 0 REQUIRED |
| Historical Files Deleted | 0 |
| Canonical Tests | 462 PASS before the latest correction; final run pending |
| Security Freeze | Prior checks passed before the latest correction; final reruns pending |
| Final-Head GitHub CI | PENDING |
| Independent Security Review | PENDING / NOT_PERFORMED |
| Gate B Real-Model Readiness | BLOCKED pending signed acceptance and independent review |
| Owner Action Required | NO for signing; owner UI selections/approvals are required for the signed trials |
| Updated PR | #48 |

## Decision basis

The implementation and unit-level negative tests are complete, and a valid signing identity is available. Two signed Trial A attempts exposed successive experimental result-schema gaps: the tool-result decoder first omitted `runtime_trial_id`; after that fix, the Host and Launcher-client telemetry filters omitted it on the DSH terminal-result event. Both failed closed after one scoped read, with no workspace mutation or model invocation. The trace, Host telemetry, and client telemetry allowlists now validate the runtime ID at their respective boundaries. The fresh signed build, two independent signed trials, final canonical suite, final Security Freeze checks, exact-head CI, and independent security review remain outstanding. This is not an Engineering PASS and must not be presented as signed multi-workspace acceptance.
