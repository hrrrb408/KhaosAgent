# Final Decision

## Phase 3.2.1 integrity-closure addendum

**Phase 3.2.1 Engineering: PARTIAL.** The signed test-result blocker is closed for the controlled result matrix: the real failure, real pass, zero-test, fake-success, and unknown/import-error cases all produced the expected bounded DSH result and matched their signed Kernel/Launcher records. The fresh focused Task A signed public result also matched the independent public and hidden evaluators. The historical conflict is proven to be a workspace/snapshot identity mismatch before Runner execution, but its exact historical Picker path or snapshot-mapping subcomponent was not retained. The focused local-model run produced correct code, then repeated the same `read_file` request and timed out; it is not a completed AgentLoop trial.

**Coding reliability: NOT_PROVEN.** This phase did not run the Holdout or A–D replay. The one focused Task A output passed public and hidden verification, but the AgentLoop timed out at 600 seconds after reaching its 8-operation limit. Seven of eight tool results reached DSH Session and were observed by the next turn; the eighth was Kernel-completed but not observed before timeout.

| Phase 3.2.1 requirement | Result |
|---|---|
| Root cause | PROVEN as workspace/snapshot identity mismatch before Runner; exact historical UI-versus-Launcher point UNKNOWN |
| Original Task A public test | FAIL, 2 tests / 1 failure / rc 1 on the preserved original source |
| Signed failure / success / zero-test / fake-success / unknown | PASS, one signed Launcher → Kernel → Runner operation each; DSH result correlated |
| Kernel → Launcher result consistency | PASS for the new signed fixture matrix and focused public `run_tests` result |
| Launcher → DSH Session consistency | PASS for each completed operation; focused run 7/8 delivered before timeout |
| Focused real-model trials | 1 attempted; 0 completed AgentLoop trials |
| Task A coding result | Expected edit; signed public 2/2 and independent hidden 3/3 passed; AgentLoop timed out |
| Unauthorized approvals / unexpected workspace changes | 0 / 0 |
| Kernel authority / ABI / workspace scope delta | 0 / 0 / 0 |
| Production trusted runtime / dependencies | 0 / 0 |
| Separate signed test-process cancellation | NOT_RUN; unknown-result case signed, cancellation/late-result tests remain in existing deterministic/XPC suites |
| Canonical suite | PASS, 415 tests in 869.279 seconds |
| Phase 3.1 / Phase 3.2 evaluator suites | PASS, 10 / 11 tests |
| DSH XPC acceptance builder / runner tests | PASS, 11 tests |
| Security Freeze default inventory | PASS; all manifest file digests match |
| Security Freeze PR #46 target base | PASS, base `8ddabbcfdfcc2af8899ca30a4717ec82c4014b21`, 5 declared sensitive governance paths |
| Security Freeze Phase 3.2.1 start base | PASS with a temporary exact-base declaration; the committed declaration remains bound to the PR target because the checker accepts one base per declaration |
| Final-head GitHub CI | External evidence; use the check attached to the exact current PR #46 head. Checks on earlier SHAs do not carry forward |
| Owner Review / Independent Code Owner Review | PENDING / NOT_PERFORMED |

The integrity gate is closed for the exercised fail/pass/zero-test/fake-success/unknown cases. The overall phase remains PARTIAL because the exact old Picker/snapshot identity was not retained and the focused AgentLoop did not terminate. No full Holdout or A–D replay was started.

## Decision

**Phase 3.2 Engineering: PARTIAL (historical status).** The semantic interface completed a signed deterministic Read → Edit → Test workflow. Two Stage B Task A attempts ran: one stopped before workspace selection; the second completed six approved operations, timed out, and showed a signed/independent result conflict. Phase 3.2.1 later reconciled that conflict as a workspace/snapshot identity mismatch and added signed result-integrity evidence. This historical status is retained; see the addendum above for the current result.

**Coding reliability: NOT_PROVEN.** Phase 3.2 remains at zero completed AgentLoop trials. Phase 3.2.1 added one focused Task A attempt with the correct edit and passing independent public/hidden tests, but the AgentLoop repeated reads and timed out. Phase 3.1 remains at 6/8 hidden-test successes, 4/8 first-pass successes, and 2/2 Task C repairs; its Task D success remains 0/2. Those are historical results and are not updated by the Phase 3.2.1 focused attempt.

## Historical Phase 3.2 evidence snapshot

The table below records the Phase 3.2 assessment before this integrity-closure addendum. Its unresolved-result entries are superseded by the evidence above; the original records remain unchanged.

| Requirement | Result |
|---|---|
| Semantic tools through existing Cordis registry | Implemented and reused |
| Signed deterministic Read → Edit → Test | PASS, 4 correlated operations |
| Independent hidden verification for Stage A | PASS, 3 tests |
| Stage B real-model focused gate | FAILED_ATTEMPT: 2 attempts; 1 stopped before selection, 1 timed out after 6 operations and failed independent verification |
| Completed real-model AgentLoop trials in Phase 3.2 | 0 |
| Stage B local model calls / responses | 8 / 8 across two attempts |
| Independently evaluated Task A attempts | 0/1 passed; public and hidden checks failed |
| Semantic tool proposals parsed/lowered | 8/8 across both attempts |
| Session result delivery / continuity | 6/6 for Attempt 2's completed operations |
| Signed `run_tests` result consistency | UNRESOLVED: two signed return codes were 0; independent public/hidden results were 1 |
| H01–H08 holdout | NOT_RUN, 0/16 |
| A–D replay | NOT_COMPLETED, Task A attempted twice; remaining runs NOT_RUN |
| Unauthorized approvals | 0 observed |
| Unexpected workspace changes | 0 observed |
| Kernel authority / ABI / scope delta | 0 / 0 / 0 |
| Production trusted runtime / dependency delta | 0 / 0 |
| Attempt 2 model latency | 40,252 ms mean across 7 calls |
| Model-call errors | 0 observed; all 8 calls returned |
| Node/model RSS, token usage, and cost | NOT_MEASURED |
| Deterministic Stage A wall time | 121.2202 s including UI; not a model benchmark |
| Canonical tests | PASS, 412 tests in 871.484 seconds |
| Phase 3.1 evaluator regression tests | PASS, 10 tests |
| Phase 3.2 benchmark/evaluator tests | PASS, 11 tests |
| Security Freeze | PASS, exact base `8ddabbcfdfcc2af8899ca30a4717ec82c4014b21` |
| Exact-head GitHub CI / Draft PR | See current checks on the Draft PR; only the check run bound to the final exact SHA applies |
| Owner Review | PENDING |
| Independent Code Owner Review | NOT_PERFORMED |
| Technical Gate A | UNCHANGED |
| Production Harness migration | NOT_AUTHORIZED |

## Current recommendation

Keep the semantic tools and bounded lowering for experimental use. The signed result-integrity blocker is closed for the exercised fail/pass/zero-test/fake-success/unknown matrix, and the focused Task A's signed result agrees with independent public and hidden verification. The AgentLoop still failed to terminate after repeating reads; coding reliability is not proven. Do not continue to the larger holdout until that loop-completion issue is addressed in a separate bounded experiment. Do not migrate the production AgentHost.

## Provenance

- Branch base / PR #45 exact head: `8ddabbcfdfcc2af8899ca30a4717ec82c4014b21`.
- Phase 3.2.1 start SHA: `d2fe95d8ef6792e9c8e297def9bf18f87914624d`; implementation/evidence SHA: `2a73f48d9291a11cbac3612410cbeb9e651cf540`. The integrity-freeze records are additive V1–V4; active V4 remains unchanged.
- Phase 3.2 implementation/evaluator head used for local validation: `441eb4d539983d25d121264ee203ab31f544b7dd`. The report files are documentation-only additions after that run; GitHub CI must validate the final PR HEAD.
- Active freeze SHA-256: `8c9685aba296d83cb3dd522ff9e7957a3074837cefd746f310689bd29c567e43`.
- Holdout dataset SHA-256: `d163fd20cff2db44cb0dc5f5260542666b098bbce403a0aafd30fa8b3e46615d`.
- DSH: `687f282e8625c6b8d11ff58211a90524be2e4317`; Node: `v22.19.0`.
- Phase 3.2.1 local checks on code SHA `2a73f48d9291a11cbac3612410cbeb9e651cf540`: canonical suite (415 passed in 869.279 seconds); Phase 3.1 evaluator suite (10 passed); Phase 3.2 evaluator suite (11 passed); DSH XPC acceptance builder/runner suites (11 passed). Security Freeze default inventory and PR target base `8ddabbcfdfcc2af8899ca30a4717ec82c4014b21` passed. The additional `--base d2fe95d8ef6792e9c8e297def9bf18f87914624d` check passed with a temporary matching declaration; the committed declaration targets the PR base required by CI.
- The fresh signed binary is bound to implementation SHA `2a73f48d9291a11cbac3612410cbeb9e651cf540`; documentation and freeze-digest bookkeeping added afterward do not alter the signed runtime inputs. GitHub CI is external status bound to the exact PR head, so the current check attached to PR #46 is authoritative; this report does not copy a check result across commits.
- Development: AUTONOMOUS. Experimental test operator: CODEX_AGENT. Owner Review: PENDING. Independent Code Owner Review: NOT_PERFORMED.
