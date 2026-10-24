# Phase 3.2 Benchmark Provenance

## Active immutable freeze

The active manifest is `benchmark-freeze-v4.json`. It was frozen at `2026-10-24T01:27:11Z`, before Phase 3.2 model evaluation, from implementation commit `49511756dab3447a17c460f28381bae7de9d044d` and exact branch base `8ddabbcfdfcc2af8899ca30a4717ec82c4014b21` (PR #45 head).

- Freeze SHA-256: `8c9685aba296d83cb3dd522ff9e7957a3074837cefd746f310689bd29c567e43`.
- H01–H08 dataset SHA-256: `d163fd20cff2db44cb0dc5f5260542666b098bbce403a0aafd30fa8b3e46615d`.
- Phase 3.1 replay dataset SHA-256: `033f5d9c776f025e21642911b6d13e2afcc32b876a39fab377ae0a6279dc5091`.
- Freeze source hashes: the manifest binds benchmark/evaluator sources, hidden oracles, fixtures, signed build inputs, pinned DSH/Node, and model inputs.
- Verification: `tools/freeze_dsh_phase3_2_benchmark.py --check` passed against the frozen inputs; the independent evaluator's source-hash check also passed.

Freeze versions v1–v3 remain in the repository as historical records. V4 became active after the evaluator was corrected to retain incomplete request correlation as unknown rather than indexing a missing Launcher request. No benchmark task, prompt, hidden oracle, scope, or Phase 3 result was changed by that correction. Phase 3's original `0/8` and Phase 3.1's `6/8` hidden-test result remain separately bound by the manifest and their original reports.

## Fixed datasets and limits

The holdout contains eight different synthetic coding tasks: H01 whitespace-normalized labels, H02 tiered shipping, H03 half-open time-window overlap, H04 bounded retry parsing, H05 zero-denominator repair, H06 page clamping, H07 multi-step event log, and H08 multi-step seat ledger. Each task has its own public fixture, hidden oracle outside the model workspace, unscoped canary, explicit read/write allowlists, and task-specific prompt hashes.

The holdout budget is 12 tool operations, 3 writes, 3 repair attempts, and 600 seconds per trial. Phase 3.1 A–D replay retains its original prompts, fixtures, hidden tests, and scopes, with limits of 8 operations, 3 writes, 3 repairs, and 600 seconds. Hidden tests are run only by the independent verifier on a disposable copy.

The frozen plan calls for 16 H01–H08 trials, 8 A–D comparison trials, 2 focused Task A trials before the full holdout, and 2 Task D replays: 28 planned trials, with at least 24 overall. Two focused Task A attempts were made. Attempt 1 stopped at the workspace Picker before an operation. Attempt 2 completed six approved Kernel/Runner operations, then timed out before AgentLoop termination. Independent public and hidden tests failed on its unchanged workspace, while the two signed `run_tests` operations reported return code 0. This unresolved evidence conflict means Stage B did not pass; the holdout and remaining replay trials were not started.

The Phase 3.2 report records both attempts without changing the v4 freeze or the prior Phase 3/3.1 results. Attempt 2 is an independently evaluated failed timeout, not a completed AgentLoop trial. Its model produced 7 semantic proposals and all 7 passed DSH parsing and lowering; 6 approved results were observed in the correlated DSH Session. No edit proposal or unauthorized approval occurred.

| Holdout task | Result |
|---|---|
| H01 | NOT_RUN — Stage B gate incomplete |
| H02 | NOT_RUN — Stage B gate incomplete |
| H03 | NOT_RUN — Stage B gate incomplete |
| H04 | NOT_RUN — Stage B gate incomplete |
| H05 | NOT_RUN — Stage B gate incomplete |
| H06 | NOT_RUN — Stage B gate incomplete |
| H07 | NOT_RUN — Stage B gate incomplete |
| H08 | NOT_RUN — Stage B gate incomplete |

The Phase 3.1 A–D replay and Task D replay were also NOT_RUN. Their baseline results remain in the original Phase 3.1 report.

## Model and runtime identity

- Provider: local CPU llama.cpp; remote data transfer: false.
- Model SHA-256: `fadc3e5f8d42bf7e894a785b05082e47daee4df26680389817e2093056f088ad`.
- Verified upstream model name: `UNKNOWN` (not recorded in Phase 3.1); quantization: `NOT_MEASURED`.
- llama.cpp runtime SHA-256: `134c1054f24057b12eeada8974e5e20815bba07a89ba2e79a3376c233a8b2fdd`.
- DSH: `687f282e8625c6b8d11ff58211a90524be2e4317`.
- Node: `v22.19.0`, binary SHA-256 `0d005c18e095027ca8f9fe1cc1126f767ee4ad7b004f4d6fb781ec4228a7c5d1`.

No model name or quantization has been inferred from a filename. The original Phase 3 and Phase 3.1 results were not overwritten.
