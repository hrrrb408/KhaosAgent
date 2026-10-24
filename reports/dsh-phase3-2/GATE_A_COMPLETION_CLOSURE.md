# Phase 3.2.2 Gate A Completion Closure

## Scope and decision

The deterministic signed Gate A is closed for the three required lifecycle cases: a complete repair workflow, repeated-read no-progress termination, and tool-budget exhaustion. Each ran in a fresh disposable workspace through the experimental signed app, Trusted Launcher, Security Kernel, and Runner. No real model was configured or invoked. The hidden verifier ran only after the repair workflow completed; it was not run for intentionally incomplete terminal cases.

This is deterministic integration evidence, not real-model coding reliability evidence. The prior Phase 3.2.1 real-model timeout remains in the historical record and is not replaced by these results.

## Signed runs

All three runs used source SHA `782097413789e3dc5d9e795cf9bbb799879ae303`, DSH SHA `687f282e8625c6b8d11ff58211a90524be2e4317`, Node `v22.19.0`, and the locally signed arm64 experimental app (199,220,599 bytes for the latter two runs; the repair app was 199,220,598 bytes). Deep signature verification passed. The app had no model configured and no network entitlement. Operator was `codex_agent`, authorization was `Owner-delegated disposable experiment`, and `Owner Personally Clicked` was `NO` for every run.

| Trial | Signed outcome | Kernel/Runner operations | Agent terminal | Independent hidden verification | Evidence |
|---|---|---:|---|---|---|
| `stage-a-5-repair` | PASS | 4: public tests fail (rc 1), read, one fixed Candidate B edit to `fee.py`, public tests pass (rc 0) | completed; 4 tool results; no unresolved result | PASS, 3/3 | JSON SHA-256 `f4ea2c8dcf30343acfd3f45798aa7c2738de17aa5623feffbbcb25545e5219e4`; `/Users/huangruibang/.codex/evidence/khaos-dsh-phase3-2/gate-a-stage-a-5-repair.json` |
| `stage-a-20-repeated-read` | PASS for expected fail-closed behavior | 2 signed reads; the repeated third proposal was stopped locally and did not become a Launcher request | incomplete `no_progress_limit`; one termination event; unresolved result false | NOT_RUN because the agent correctly terminated incomplete | JSON SHA-256 `ef691e95e54a3b3446053a3984b47a6827a274db30a26e2c4f0db516699117ff`; `/Users/huangruibang/.codex/evidence/khaos-dsh-phase3-2/gate-a-stage-a-20-repeated-read.json` |
| `stage-a-21-budget-exhaustion` | PASS for expected fail-closed behavior | 1 signed read; no further Launcher request | incomplete `tool_budget_exhausted`; one termination event; unresolved result false | NOT_RUN because the agent correctly terminated incomplete | JSON SHA-256 `98a53365cf3ca5c4a4e97f142909ca8c095c43298ffcafe45507318de88ea880`; `/Users/huangruibang/.codex/evidence/khaos-dsh-phase3-2/gate-a-stage-a-21-budget-exhaustion.json` |

For every executed operation, the recorded correlation checks passed: Launcher request identity and Kernel result matched; the result reached DSH Session before the next turn; event order and request scope/return code were valid. Workspace identity bindings passed for all 4, 2, and 1 requests respectively. The binding uses the disposable workspace path hash, device/inode, identity marker and fixture manifest, plus Launcher Task ID, Request ID, approval digest, and workspace session ID. Each run had a distinct task and workspace identity. In the repeated-read case, only the first two requests were submitted. The final workspace hashes show no changes in either incomplete case; in the repair case, only `fee.py` changed and the canary and test fixture remained byte-identical.

The acceptance JSON reports the internal Kernel `snapshot_identity` field as `NOT_AVAILABLE`. These results therefore prove the selected disposable-workspace identity binding and request/session continuity captured by the acceptance overlay; they do not claim an independently exported Kernel snapshot ID.

Across these trials: 3 signed deterministic runs, 7 actual Runner operations, 0 model calls, 0 unauthorized approvals, 0 out-of-scope proposals, 0 unexpected workspace mutations, and 0 observed Kernel authority violations. UI-inclusive durations were 71.9916s, 42.4927s, and 26.4605s. These durations include operator UI time and are not model latency measurements.

Raw launcher logs are retained as gzip files alongside the owner-only evidence JSON. Their compressed and decompressed SHA-256 values are recorded inside each JSON file. The evidence files explicitly record that API keys were redacted before writing. The historical `stage-a-2-repair` failure JSON remains unchanged (SHA-256 `21ee73683c6415379485663c7b713125c8c4ddf94b7d9378f64b13e514438b3c`).

## Evaluator defect and correction

The earlier `stage-a-2-repair` signed execution completed the real sequence and produced the expected nested test result (`failed`, return code 1), but its evidence evaluator interpreted a normally completed semantic `run_tests` tool envelope as a tool error. That caused a false acceptance-level `FAIL`; it did not indicate a Launcher, Kernel, or Runner failure. The original result and raw logs are preserved without rewriting.

The evaluator now separates tool-call delivery from test outcome. It requires a successful semantic tool envelope with the matching Tool Call ID, then compares the correlated `PUBLIC_TEST_RESULT_VERIFIED` event against the actual Runner return code (rc 0 = passed, rc 1 = failed). Non-test operations cannot carry a public-test event. A regression test covers a delivered `run_tests` result whose public tests genuinely fail. The repaired signed `stage-a-5-repair` run confirms the initial failing result was delivered and observed before DSH proposed its repair.

Relevant implementation: `tools/run_dsh_xpc_attack_acceptance.py` and `tests/test_dsh_xpc_acceptance_runner.py`. The fix changes acceptance evidence classification only; it does not alter production execution or authority.

## Exact validation and limits

- `tests/test_dsh_xpc_acceptance_runner.py`: 10 passed.
- `tests/test_dsh_xpc_acceptance_builder.py`: 6 passed.
- Security Freeze default inventory: PASS, zero undeclared sensitive changes.
- Security Freeze against PR #46 base `8ddabbcfdfcc2af8899ca30a4717ec82c4014b21`: PASS, 5 declared test/governance paths.
- Kernel authority delta: 0.
- Kernel ABI delta: 0.
- Workspace scope authority delta: 0.
- Production trusted runtime delta: 0.
- Production dependency delta: 0.
- Real-model evaluation and holdout: NOT_RUN in this Gate A closure.
- Owner Review: PENDING. Independent Code Owner Review: NOT_PERFORMED.

Canonical full-suite and final-head CI status are recorded in `FINAL_DECISION.md` only after those checks run against the final report commit.
