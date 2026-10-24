# Signed Test Result Integrity Audit

## Finding

The original Phase 3.2 disagreement is **proven to be an input/workspace identity mismatch before Runner execution**, not a test-result normalization error in the Kernel. The historical record does not retain the Picker-selected path or snapshot identity, so the exact subcomponent that selected or mapped the wrong workspace remains unknown. The old results must not be described as runs against the preserved original fixture.

The new signed regression matrix agrees with the independent evaluator for failing, passing, zero-test, fake-success, and import-error inputs. A fresh focused Task A run also produced a signed `run_tests` pass that matched the independent public and hidden evaluators. That real-model AgentLoop did not terminate: it spent the remaining operation budget repeating `read_file` and timed out. This is a separate loop-completion failure; it does not reverse the test-result evidence.

## Historical conflict reconstruction

Phase 3.2 Stage B attempt 2 reported two signed `run_tests` calls with return code 0 while the preserved, unmodified Task A workspace failed both public and hidden evaluation. Its `fee.py` and `test_public.py` hashes were respectively `f9d50dd40515ba0c09b5520a596820120b3cad4a114946cda1b91b15807059bd` and `870c0ab16d7f10fdf01569b0487a488a66efb74b061f83504e183588da50fd4d`.

The historical Runner output is reproducible from the *rounded* `fee.py` source, not the preserved original source: the old `run_tests` result digests (`launcher_result_sha256=bcf499…`, DSH result `9804e8…`, 410 bytes) and the `read_file` digest for `fee.py` (`launcher_result_sha256=82945c…`, DSH result `da0d3…`, 201 bytes) match the corrected source. Re-running the fixed test script against the original workspace with `/usr/bin/python3` 3.9.6 and Homebrew Python 3.13.4 returns 1, with two tests and one failure. The first observable divergence is therefore the workspace/snapshot input before the Kernel executed the command.

The old attempt did not retain the Picker path or snapshot ID. We cannot distinguish a wrong Picker selection from a later Launcher workspace/bookmark mapping error. We found a live stale-Picker condition during the new run: its initial Go To path pointed at a different disposable directory (`…bn09_1k9/coding-workspace`) than the current Runner-printed directory (`…omcze7ba/coding-workspace`). The stale path was not selected; the Picker was navigated to the exact printed path, then its files and initial hashes were checked before opening it. This demonstrates the failure mode, but does not retroactively identify the exact historical selection.

## Result semantics and fix

The experimental semantic adapter now treats the process result, test summary, and test verdict as distinct values. A public-test pass requires a non-empty test count, a valid structured summary, zero failures and errors, and a consistent process return code. Zero tests are `invalid`; missing or malformed summaries are `unverified`; contradictions are `mismatch`. None may be surfaced as a test pass. Bounded `PUBLIC_TEST_RESULT_VERIFIED` telemetry records only status and test counts, not prompts, file contents, or test output.

The signed test-result fixtures exercise that rule through the real Launcher → Kernel → Runner path. For the focused model run, the operator also verified the Picker's absolute path and the initial public-file hashes before selecting the workspace. No production Kernel, ABI, scope, or network change was made.

## New focused signed run

| Field | Evidence |
|---|---|
| Trial / Task | `phase321-focused-task-a-01` / `A` |
| Source / DSH / Node | `2a73f48d9291a11cbac3612410cbeb9e651cf540` / `687f282e8625c6b8d11ff58211a90524be2e4317` / `v22.19.0` |
| Local model | `bundled-cpu`; SHA-256 `fadc3e5f8d42bf7e894a785b05082e47daee4df26680389817e2093056f088ad`; 18,556,689,568 bytes |
| Signed app | 18,766,087,429 bytes; deep/strict signature valid; `org.khaos.Seed`; Team ID `UBAP6LN5AM` |
| Task / Session | `28322cef-9251-4229-8a6f-544421e22e72` / `khaos-phase31-0a215af2-74f4-4121-a916-0de10a32d940` |
| Public test request | Request ID `11da042c79d04e85bd9db990f7ab49c9`; request digest `c2ff3374e81b7a93f55ea7fdcfb2d4566a4fb68f3a47537ae7014c399956f785`; invocation digest `03fe7f35ff86ee14b5656b4c73f7292ad101fe32326a2f6e874b6e5e333ab424` |
| Signed result | Kernel/Runner return code `0`; result SHA-256 `f9ecbf8bc5b643f10094c443ca90b42ac093cd9aabcaf7d44c663d96ed043782`; `PUBLIC_TEST_RESULT_VERIFIED`: 2 run, 0 failures, 0 errors, 0 skipped |
| Session evidence | `TOOL_RESULT_DELIVERED` matched the Launcher result hash; continuity and next-turn observation were `true` |
| Independent verification | Public `2/2 PASS`; hidden `3/3 PASS`; read-only, network-denied evaluator |
| Workspace delta | Only `fee.py`; no unexpected changes; Canary unchanged; no symlinks |
| AgentLoop outcome | Timeout at the 600-second task limit; 8 model calls/proposals; 7 complete Session result chains; operation 8 was submitted and Kernel-completed, but its result was not observed in DSH Session before timeout; no `AGENT_TERMINATED` event |

The focused run is **not** counted as a completed AgentLoop trial or a benchmark trial success. It does prove that the correct signed public-test result and the independent hidden-test verdict agree for the changed fixture. The model emitted five additional identical `read_file(fee.py)` proposals after its initial read; all requests used the same invocation digest and remained within the 8-operation budget. The final pending result was read-only.

## Boundaries

- Phase 3.2 `0/8`, Phase 3.1 `6/8`, and the two historical Phase 3.2 Task A attempts remain unchanged.
- Integrity Freeze V4 remains unchanged: SHA-256 `d801025b3378d1e30a86095ad6eebf7fee7d09eadcd50b27fab350a32397f7a3`.
- Raw UI/Runner evidence remains in owner-only `/private/tmp/khaos-dsh-phase3-2-1-evidence/`; it is not copied into Git. The failure-attempt JSON for the focused run has SHA-256 `12c6e2fbc7827425ed94395384eb7f462b924da5038d056a8aa90746dacf7e04`; the preserved signed stderr has SHA-256 `a0572c862f411e61e649b34fd0ed246d4a316c8193a85bcae5512e2c5048d2df`.
- Operator: `codex_agent`. Authorization: `Owner-delegated disposable experiment`. Owner personally clicked: `NO`. Unauthorized approvals: 0.
