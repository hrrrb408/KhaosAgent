# Final Decision

## Decision

**Phase 3.2 Engineering: PARTIAL.** The semantic interface completed a signed deterministic Read → Edit → Test workflow, and the eight-task holdout, frozen-input manifest, independent evaluator, and evaluator regression tests are implemented. The Stage B focused real-model gate did not complete: a model response and semantic read proposal were observed, but CUA could not bind to and verify the modal signed Picker. No workspace was selected and no operation was approved. Therefore the planned 16 holdout trials, 8 A–D replay trials, and 2 Task D replays were not run.

**Coding reliability: NOT_PROVEN.** Phase 3.2 has zero completed real-model trials. Its model success rate, repair success, first-pass success, and generalization rate are not measurable. Phase 3.1 remains at 6/8 hidden-test successes, 4/8 first-pass successes, and 2/2 Task C repairs; its Task D success remains 0/2. Those are historical results, not Phase 3.2 results.

## Evidence summary

| Requirement | Result |
|---|---|
| Semantic tools through existing Cordis registry | Implemented and reused |
| Signed deterministic Read → Edit → Test | PASS, 4 correlated operations |
| Independent hidden verification for Stage A | PASS, 3 tests |
| Stage B real-model focused gate | FAILED_ATTEMPT before workspace selection/approval |
| Completed real-model trials in Phase 3.2 | 0 |
| H01–H08 holdout | NOT_RUN, 0/16 |
| A–D replay | NOT_RUN, 0/8 |
| Unauthorized approvals | 0 observed |
| Unexpected workspace changes | 0 observed |
| Kernel authority / ABI / scope delta | 0 / 0 / 0 |
| Production trusted runtime / dependency delta | 0 / 0 |
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

## Recommendation

Keep the semantic tools and bounded lowering. Do not infer a real-model reliability gain from the deterministic Stage A pass or the single incomplete Stage B proposal. The signed UI binding failure needs a reproducible, inspectable automation path before the focused Task A gate can continue. Once that gate completes, run the frozen plan without changing tasks, scopes, hidden tests, model identity, or budgets. Do not migrate the production AgentHost on current Phase 3.2 evidence.

## Provenance

- Branch base / PR #45 exact head: `8ddabbcfdfcc2af8899ca30a4717ec82c4014b21`.
- Phase 3.2 implementation/evaluator head used for local validation: `441eb4d539983d25d121264ee203ab31f544b7dd`. The report files are documentation-only additions after that run; GitHub CI must validate the final PR HEAD.
- Active freeze SHA-256: `8c9685aba296d83cb3dd522ff9e7957a3074837cefd746f310689bd29c567e43`.
- Holdout dataset SHA-256: `d163fd20cff2db44cb0dc5f5260542666b098bbce403a0aafd30fa8b3e46615d`.
- DSH: `687f282e8625c6b8d11ff58211a90524be2e4317`; Node: `v22.19.0`.
- Local checks on the implementation head: `python3 -m unittest discover -s tests -v` (412 passed); `python3 -m unittest discover -s experiments/dsh_phase3_1 -v` (10 passed); `python3 -m unittest discover -s experiments/dsh_phase3_2 -v` (11 passed); `python3 tools/check_security_freeze.py` and `python3 tools/check_security_freeze.py --base 8ddabbcfdfcc2af8899ca30a4717ec82c4014b21` (both passed).
- Development: AUTONOMOUS. Experimental test operator: CODEX_AGENT. Owner Review: PENDING. Independent Code Owner Review: NOT_PERFORMED.
