# Root Cause and Fix

## Root cause

**Proven cause class:** the historical signed attempt and the independent evaluator did not use the same Task A source/workspace snapshot. The historical Runner output and `read_file(fee.py)` result hashes reproduce from the corrected rounded source, although the preserved original workspace still contained `return amount * rate` and no edit proposal occurred. The original source fails the public tests under both available Python interpreters. The first divergence is before Kernel execution, at workspace/snapshot identity selection or mapping.

**Exact historical subcomponent: unknown.** The old Picker-selected absolute path and snapshot identity were not recorded. The retained evidence cannot distinguish a wrong workspace being selected in the UI from a later Launcher bookmark/snapshot mapping issue. No evidence supports blaming test-summary parsing, Kernel result serialization, or DSH Session result delivery for that historical mismatch.

During the fresh signed Task A run, the Picker initially retained a different `coding-workspace` path from a previous scratch directory. Codex did not select it. The Picker was navigated to the Runner-printed absolute path; the path was re-opened and checked, and the fixture file hashes matched before selection. This is direct evidence that a stale Picker location can create the observed input mismatch, but it does not prove that the exact old run used that same stale path.

## Minimum repair

1. The experimental `run_tests` adapter now verifies test-result semantics instead of equating `ok=true` or exit code 0 with a test pass. It requires a positive test count and a consistent structured summary; it reports `passed`, `failed`, `invalid`, `unverified`, or `mismatch` distinctly.
2. The real-runner `TEST_SCRIPT` emits bounded test counts and treats zero executed tests as an invalid result. Fake success text cannot override the unittest result.
3. `PUBLIC_TEST_RESULT_VERIFIED` telemetry is allowlisted at both experimental boundaries and records only bounded status/count fields. The event is correlated to the model/tool call, Launcher Task/Request, invocation digest, Kernel result digest, DSH Session delivery, and next-turn continuity.
4. Signed UI operators verify the absolute disposable workspace path and initial fixture hashes before choosing the Picker result. For every request they review the exact task, path, command, scopes, digest, and approval state.

No production Kernel, Kernel ABI, workspace authority, sandbox, or network permission was changed. The correction is in the experimental semantic result path and acceptance procedure; no Kernel fix was justified by the evidence.

## Verification

- Signed failure, pass, zero-test, fake-success, and import-error fixtures all passed their independent expectation checks. Their immutable result JSON and raw-log hashes are listed in `SIGNED_FAILURE_ACCEPTANCE.md`.
- The focused real-model `run_tests` result had return code 0 and a verified summary of 2 tests, 0 failures, 0 errors. The same workspace passed the read-only public evaluator (2 tests) and hidden evaluator (3 tests).
- The focused task changed only `fee.py`; the unscoped Canary hash was unchanged. Unauthorized proposals/approvals: 0.
- Session telemetry sequence was valid through 94 events. Seven tool results were delivered to the DSH Session and observed by the next model turn. The eighth operation was approved and Kernel-completed but did not reach a DSH result-delivery event before timeout.
- The real model did not terminate the AgentLoop within 600 seconds and repeated the same `read_file(fee.py)` invocation. This is a remaining Agent policy/loop-completion issue, not a test-result conflict.

## Remaining evidence gap

The historical Picker path/snapshot ID is unavailable. The current code does not retroactively fill that gap. The fresh run proves the path-checked procedure and result consistency, but the exact old UI-versus-bookmark subcomponent remains `UNKNOWN`. A separate signed test-process cancellation was also not run; cancellation/late-result behavior remains supported by the existing deterministic semantic-tool and signed XPC cancellation tests.
