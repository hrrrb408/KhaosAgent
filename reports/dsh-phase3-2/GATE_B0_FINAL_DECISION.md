# Gate B.0 Final Decision

**Checkpoint:** 2026-10-25; corrected signed app and canonical suite passed, but signed UI trials and final-head CI are pending.
**Engineering status:** `PARTIAL`; the signed multi-workspace acceptance is blocked at the UI gate.

| Required output | Status at this checkpoint |
|---|---|
| Gate B.0 Engineering | PARTIAL |
| Signing Root Cause | PARTIAL; historical `CSSMERR_TP_NOT_TRUSTED` origin unknown |
| Signing Identity | VALID |
| Small Signed App | PASS at `520d659`; report-only final-head commit requires a fresh exact-source app before trial |
| Actual Experimental Source Changes | YES |
| Runtime Workspace Binding | IMPLEMENTED in experimental Launcher overlay |
| Prebuilt App Reuse | IMPLEMENTED with fail-closed signature and receipt validation |
| Workspace Isolation Unit Tests | PASS |
| Stale Authorization Replay Tests | PASS |
| Workspace Replacement Tests | PASS |
| Cross-Trial Result Isolation | PASS in synthetic evidence-validator tests; signed replay not attempted |
| Experimental Launcher Trusted Delta | DECLARED |
| Signed Multi-Workspace Acceptance | BLOCKED before Trial A; prior Trial A attempt FAILED |
| One App / Two Workspaces | NOT_PROVEN |
| Large GGUF Copies | 0 REQUIRED |
| Real Model Invocations | 0 REQUIRED |
| Historical Files Deleted | 0 |
| Canonical Tests | 463 PASS at `520d659903fce78b489452bb5316f349f163e33f` |
| Security Freeze | Default PASS (0 sensitive changes); exact-base PASS (5 declared sensitive changes) |
| Final-Head GitHub CI | PENDING |
| Independent Security Review | PENDING / NOT_PERFORMED |
| Gate B Real-Model Readiness | BLOCKED pending signed acceptance and independent review |
| Owner Action Required | YES for resolving the separate open Picker and action-time per-operation approvals; no signing repair is needed |
| Updated PR | #48 |

## Decision basis

The implementation and unit-level negative tests are complete, and a valid signing identity is available. Two signed Trial A attempts exposed successive experimental result-schema gaps; both failed closed after one scoped read, with no workspace mutation or model invocation. The corrected trace, Host telemetry, and client telemetry allowlists validate the runtime ID at their respective boundaries. A no-model app at source SHA `520d659` passed deep/strict signature and exact-source prebuilt validation, and the 463-test canonical suite plus both Security Freeze checks pass. A subsequent report-only commit moved `HEAD`, so that app cannot be reused at the final PR head. The actual two-workspace signed trial was not started because a separate Khaos Picker was open and the acceptance procedure forbids concurrent Pickers. A fresh final-head app, UI trials, exact-head CI, and independent security review remain pending. This is not an Engineering PASS and must not be presented as signed multi-workspace acceptance.
