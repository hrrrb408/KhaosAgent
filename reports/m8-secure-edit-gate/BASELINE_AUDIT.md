# Baseline and Evidence Audit

## Scope

This audit is based on the live GitHub state checked on 2026-10-18. PR #34 is OPEN and Draft, with head `6724d5ac5e52e1c157f3701f30009ed81b55fb90`. Its base is PR #33's head `1d1457f43f788d30f6fa4f48890b900ef9406c07`. This branch is stacked on PR #34's exact head. PRs #27–#34 remain open; none was modified or merged by this task.

The target is only the fixed Candidate B Staged Replacement used by the test-only Shell proposal. Production Structured Edit remains NOT_STARTED. No original benchmark or private/hidden test data was read or changed.

## Existing signed evidence retained

| Evidence | Digest | Result |
|---|---|---|
| `reports/m8-secure-edit/gate-a-signed-runner-v8.json` | `9a14057dcef79ad7ca3285768a84fe4ae1607ca8f3723dbc845f89086df8b7bb` | One signed approval and Runner call; exact `tags.py` scopes; one modified path; final source SHA-256 `8db3b1d5a79058bc0db32f9904c38162c6384ff813d41ab45b9db2348a264a63`; temp absent, mode preserved, canary unchanged, parent focused test passed, Task Record complete. |
| `reports/m8-secure-edit/gate-a-signed-refusal-v2.json` | `f07a2dd6ac77f0df9dacb74fb3498b3311ada0bf60bd5b04b066cddac8a8d1fd` | One proposal presented and denied; zero Runner calls; source, canary and workspace unchanged; terminal `task_cancelled`; capture complete. |

Both artifacts are unchanged. The historical refusal artifact's evidence label is corrected in `EVIDENCE_CORRECTIONS.md`; it is not rewritten.

## Prior headless evidence

PR #34 already carried a fixed-probe positive test and deterministic failure cases. This branch adds Candidate B-specific L3 cases rather than treating generic Kernel tests as substitutes. The final focused group passed 15 tests in 135.338 seconds; the canonical suite passed 394 tests in 804.143 seconds. See `REGRESSION_REPORT.md`.

The audit found a typo in the inherited temp-write failure injection: its embedded script used `ndef`, which caused a syntax error before the intended write hook. The original assertions established unchanged state after a nonzero result but did not prove that the write hook ran. The typo is fixed; the corrected test requires the `INJECTED_TEMP_WRITE_FAILURE` marker and now exercises the intended failure. See `EVIDENCE_CORRECTIONS.md`.

## Boundaries

- The one additional signed positive replay was independently authorized and used once. It is recorded in `gate-a-signed-runner-replay.json`.
- No new refusal, cancellation, termination, long-payload or other signed Runner operation was run.
- Historical L4 evidence is narrow and does not prove the full Gate A matrix.
- `task_completed` records a terminal task state; it does not verify coding quality or a hidden-test objective.
