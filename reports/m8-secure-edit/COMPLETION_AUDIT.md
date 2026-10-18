# M8.5.2 — Completion Audit

Status: **CONDITIONAL / INCOMPLETE — positive signed path passed; Gate A matrix not proven**
Evidence refreshed: 2026-10-18
Baseline: PR #33 head `1d1457f43f788d30f6fa4f48890b900ef9406c07`

## Repository and stacked-PR audit

At the latest read-only GitHub check, `origin/main` is `27ef0b4787f807fc76ffd7ba9cdb467ffc9a2f27`; PR #33 is open and its head matches the M8.5.2 base. PRs #27–#33 are all open with clean merge state and successful `security-freeze` and `security-tests` checks. The dependency chain is #27 on `main`, #28 on `main`, #29 on #28, #30 on #29, #31 on #30, #32 on #31, and #33 on #32. No PR was modified or merged by this work.

## Required terminal status

```text
Engineering Closure: CONDITIONAL
Signed Runner Feasibility: PASS for the exact one-file staged replacement; broader Gate A NOT_PROVEN
Structured Edit Implementation: NOT_STARTED
Edit Security Invariants: PARTIAL (signed success and refusal paths plus headless failure and scope evidence)
Approval Reviewability: PARTIAL (v8 exact request was displayed and approved; v2 refusal recorded; broad input-length cases remain untested)
Deterministic Staged-Edit Product Flow: PASS (v8; one approved replacement and parent retest)
Full Deterministic Coding Loop: NOT_RUN (production Edit Action is not integrated)
Runtime TCB Delta: 0
Real-Model Edit Reliability: NOT_PROVEN
Coding Reliability Closure: NOT_PROVEN
```

## Evidence supporting this status

The real macOS headless Seatbelt/Kernel path passed the deterministic staged replacement and injected failure-state checks. Signed v8 then passed the exact one-file replacement through the signed product, Launcher approval, XPC Kernel, Runner, changeset validation, and parent-side retest. Signed refusal v2 passed without invoking Runner. The canonical suite passed on the final test harness with 381 tests, exit code 0, and 708.963 seconds process duration. The default signed product/XPC identity smoke test and both current-tree/exact-base Freeze checks passed after the final security metadata update.

The signed v4 request expired without a decision. The v6 UI attempt selected the wrong no-argument Launcher instance and recorded zero Agent Runner calls. In v7, the exact `tags.py` request ran once but the parent assertion looked for the Runner stdout marker in the Agent final response, so final-state assertions did not run. The probe was corrected to validate and return the marker from actual Runner stdout. In v8, the user authorized one additional local deterministic replay, and the signed Launcher displayed request digest `ac7c277dc46bc43aef330f48e8fe569612779c2ff78ad129022820189a0d1ce1`, the complete fixed argv, and exact `readScope=["tags.py"]` / `writeScope=["tags.py"]`. One Run once decision produced one Runner execution with exit code 0, a 139-byte bounded result, and `added=0/modified=1/deleted=0`. Parent assertions verified final source SHA-256 `8db3b1d5a79058bc0db32f9904c38162c6384ff813d41ab45b9db2348a264a63`, preserved mode, no temporary entry, unchanged canary, exact changed path, successful focused test, complete Task Record, and deep strict code signature. The Agent task ended `task_completed`; teardown removed the disposable fixture. Signed refusal v2 displayed the same bounded proposal and recorded one denial, zero Runner calls, unchanged source/canary/workspace, no temp entry, and `task_cancelled`; the enclosing signed XPC request-attack checks passed. Refusal v1 recorded the denial but its wrapper hit a missing cleanup branch for an exact empty PluginStore scaffold. The cleanup branch is fixed, and refusal v2 passed the complete signed test.

No production Edit Action was implemented because Gate A requires complete evidence before Phase 2.

## Remaining completion conditions

1. Complete the target-specific traversal, absolute/empty path, symlink leaf/ancestor, hardlink, Unicode/case alias, rename race, TOCTOU, out-of-scope sibling, hidden-canary, and unreadable-baseline cases required by the objective. The signed refusal scenario now passes.
2. Keep Phase 2 stopped until all Gate A criteria are supported by executable evidence. The production four-field Action remains unimplemented.
3. Run final Freeze checks on the final tree, preserve independent Code Owner status as NOT_PROVEN unless supplied, and submit a Draft PR without merging if the remaining evidence is delivered as a research/blocker change.

This report is an interim accurate closure record, not a claim that the requested structured edit tool is complete.
