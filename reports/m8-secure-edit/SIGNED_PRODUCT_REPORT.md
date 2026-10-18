# M8.5.2A — Signed Product Report

Status: **partial signed evidence; Gate A remains NOT_PROVEN**
Evidence refreshed: 2026-10-18
Model mode: deterministic Model Probe; `provider=null`; no remote model call
Baseline: PR #33 head `1d1457f43f788d30f6fa4f48890b900ef9406c07`

## Product and trust path

The positive and refusal runs used the repository's signed macOS Seed product test, Launch Services, the signed Launcher, the real Kernel XPC service, the existing Seatbelt Runner, a disposable workspace snapshot, and the normal changeset validation path. The test's parent process verified deep strict code-signature validity. The XPC product's source-digest and request-attack regression checks ran in the same outer acceptance test and passed.

The transient `.app` bundle was removed during test teardown. The retained v8 evidence records `codesign_deep_strict_verified=true`, but does not retain the signing identifier, Team ID, designated requirement, or bundle path. Those identity details are therefore **NOT_RECORDED** here; the evidence supports deep strict verification at acceptance time, not a current signature inspection of a retained bundle.

## Positive staged replacement — v8

Evidence: [`gate-a-signed-runner-v8.json`](gate-a-signed-runner-v8.json)

- Run: 2026-10-18 11:33:33–11:34:52 UTC.
- Model mode: deterministic signed-runner probe; no provider or network model.
- Approval: one complete request was shown and approved once. Request digest: `ac7c277dc46bc43aef330f48e8fe569612779c2ff78ad129022820189a0d1ce1`.
- Operation: fixed Python script via `python3 -I -B -c`; the edit strings were JSON arguments, not source interpolation. `readScope=["tags.py"]`, `writeScope=["tags.py"]`.
- Runner: exactly one execution, return code 0, bounded result 139 bytes, terminal `task_completed`.
- Changeset: `added=0`, `modified=1`, `deleted=0`; only `tags.py` changed. Final SHA-256: `8db3b1d5a79058bc0db32f9904c38162c6384ff813d41ab45b9db2348a264a63`.
- Final state: mode `0640` preserved, no temporary entry remained, canary unchanged, and the parent focused test returned 0. The complete Task Record was present.
- Fixture: disposable workspace removed at teardown.

This proves one exact-file positive staged replacement through the signed product path. It does not prove the required path/alias/race attack matrix, broad approval reviewability, or the full Agent read → failing test → edit → retest loop.

## User refusal — v2

Evidence: [`gate-a-signed-refusal-v2.json`](gate-a-signed-refusal-v2.json)

- Run: 2026-10-18 11:44:28–11:44:56 UTC.
- The Launcher displayed one proposal with the same exact `tags.py` scope. The user selected Cancel.
- Task Record: one approval presentation, one denial, zero Runner executions, zero command return codes, terminal `task_cancelled`.
- Parent checks: source and canary unchanged, zero workspace changes, no temporary entry, complete terminal evidence.
- The enclosing signed product/XPC request-attack test also passed.

Refusal v1 first exposed a missing test-harness cleanup branch for the exact empty PluginStore scaffold created by the service. That scaffold cleanup was narrowed to the exact empty test artifact, and v2 passed the complete outer test. No product runtime file was changed.

## Earlier attempts and corrected harness issues

The signed v4 request expired without approval. The v6 UI attempt selected a no-argument Launcher instance and recorded zero Agent Runner calls. In v7, the Runner executed once, but the parent assertion searched the Agent final response for a marker that existed in Runner stdout; the harness failed before final-state assertions. The probe was corrected to assert the bounded Runner stdout marker. The corrected v8 positive acceptance and v2 refusal acceptance pass.

## Acceptance boundary

| Claim | Result |
|---|---|
| Signed positive single-file staged replacement | PASS for the exact v8 fixture and scope |
| Signed refusal produces no Runner execution or workspace mutation | PASS in v2 |
| Signed approval content and execution scopes match for the tested request | PASS for the exact short request |
| Broad path traversal, symlink/hardlink, alias, race, unreadable-baseline, cancellation, termination, nonzero-exit and changeset-rejection matrix | NOT_PROVEN |
| Full deterministic coding loop with an initial failing test and a post-edit Runner retest | NOT_RUN as a complete signed Agent loop |
| Production structured `edit` Action | NOT_STARTED |

The exact positive and refusal records are bounded acceptance summaries. They do not contain workspace file contents or API credentials. The canonical test suite and Freeze results are recorded in `REGRESSION_REPORT.md` and `RUNNER_FEASIBILITY.md`.
