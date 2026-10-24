# Signed Test Result Acceptance

All cases below used the exact experimental source SHA `2a73f48d9291a11cbac3612410cbeb9e651cf540`, a deep/strictly verified signed app, the disposable fixture workspace, one approved fixed `run_tests` request, the exact declared file scopes, and an independent event/result evaluator. Each case ran through Launcher → Kernel → Runner. No case wrote a workspace file; each Canary was unchanged and each result was observed by the DSH Session's next turn.

| Case | Signed fixture result | Runner RC / tests | Task ID / Request ID | Evidence JSON SHA-256 |
|---|---|---:|---|---|
| A — original Task A fails | `failed`; 1 failure; DSH observed the failure | `1` / 2 | `c243ddb8-1fe0-444e-93e2-0d61416b8e78` / `6980abcf5d3449d1a367b09e20bbe9d2` | `d09179ea93976fea66586c63e73f1afa72929863bf7bc234c91ad7ab47c74589` |
| B — corrected public fixture | `passed`; no failures/errors; DSH observed success | `0` / 2 | `4f1aa6c1-7708-49da-9aa4-32a7cedc06b5` / `64cd88ed2fcb4b8ebac7791fa03a86b2` | `60b15d6945115dd3e343ed1a82ed31a1aec0ba1058086f799d4bded5fd6b4bc5` |
| C — zero discovered tests | `invalid`, `zero_tests_executed`, `can_continue=false`; no pass reported | `2` / 0 | `7d44d8c4-a5d6-4a7b-b9eb-79564eb91115` / `f35131a94bc341f1b5f4366ff59740b7` | `12713fb2785d587b335ceb24aaac87952de2a4f344b5521b3e53a655c278a253` |
| D — fake “OK” text before a real assertion failure | `failed`; actual unittest failure overrode printed success text | `1` / 1 | `1705c290-193a-41b5-95dc-d2e29d95f749` / `227dc606366a4091b6d76f823f953973` | `8b3c3dce8e4575a28e78fdd0712d600e3bfde5edd6fb703b571a37fd45e2c8fa` |
| E — syntax/import error | `unverified`, `test_summary_missing`; no pass reported | `1` / no valid summary | `d82c992d-355c-4a25-8550-05ffdb2aa1ec` / `3fabff7a09124ea0bc956e0f57dc45e8` | `d51b10dc9b4cd8a86b5855a1982bb079f6cac395ecca0bcbd14effdb768dde9c` |
| F — unknown result | The signed import-error path is the unknown-result case: DSH receives `unverified`; no automatic pass or retry | `1` / no valid summary | Same signed E case; no second Runner submission | Same signed E evidence |

For every row, `kernel_result=output`, the recorded Runner return code matched the Launcher request, the bounded test-status event matched the DSH tool result, and Session continuity/next-turn observation passed. The test-status summaries contained only counts and status. The full synthetic outputs and their digests are retained in owner-only local evidence folders referenced by each JSON record.

Case F validates an unknown result, as allowed by the acceptance definition. Cancellation and late-result semantics are covered by the existing DSH semantic-tool cancellation/late-result tests and the repository's real XPC cancellation tests; a separate signed **test-process cancellation** was not run in this closure. This distinction is retained rather than claiming a signed cancellation case that was not exercised.

## Focused real-model result

The separate local-model Task A trial was not part of the five deterministic result fixtures. It generated the correct one-file edit, and the signed public runner plus independent public/hidden evaluators all passed. The AgentLoop then repeated the same read request until the 8-operation limit and timed out; therefore this is evidence of correct result semantics and code output, not a completed AgentLoop trial.

## Operator and build record

- Operator: `codex_agent`; authorization: `Owner-delegated disposable experiment`; `Owner Personally Clicked: NO`.
- Signing identity SHA-1: `81E5B3D53290732C30A9D823874EBAB6E947AB55`; Team ID `UBAP6LN5AM`; app identifier `org.khaos.Seed`.
- DSH: `687f282e8625c6b8d11ff58211a90524be2e4317`; Node: `v22.19.0`.
- Local model SHA-256: `fadc3e5f8d42bf7e894a785b05082e47daee4df26680389817e2093056f088ad`; runtime was CPU-only and offline.
- Integrity Freeze V4 SHA-256: `d801025b3378d1e30a86095ad6eebf7fee7d09eadcd50b27fab350a32397f7a3`.
- Kernel authority/ABI/scope changes: none in this Phase 3.2.1 diff.
