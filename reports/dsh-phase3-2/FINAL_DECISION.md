# Final Decision

## Decision

**Phase 3.2 Engineering: PARTIAL.** The semantic interface completed a signed deterministic Read → Edit → Test workflow, and the eight-task holdout, frozen-input manifest, independent evaluator, and evaluator regression tests are implemented. Two Stage B Task A attempts ran. The first stopped before workspace selection. The second completed six approved signed Kernel/Runner operations and delivered each result through DSH Session, but timed out before AgentLoop termination. Independent public and hidden checks both failed on the unchanged workspace. Two signed `run_tests` results reported exit code 0, which conflicts with those independent failures. This discrepancy remains unresolved, so the test-result path is not considered validated. The 16 holdout trials, remaining A–D trials, and 2 Task D replays were not run.

**Coding reliability: NOT_PROVEN.** Phase 3.2 has zero completed AgentLoop trials and one Task A attempt with independent verification, which failed. The second attempt produced 7/7 parsed/lowered semantic proposals, 6 approved operations, 6/6 Session result deliveries and continuity checks, and no edit proposal. The independent failure and the conflicting signed test return codes prevent attributing the outcome solely to model reasoning or claiming that `run_tests` reliably reports failures. Phase 3.1 remains at 6/8 hidden-test successes, 4/8 first-pass successes, and 2/2 Task C repairs; its Task D success remains 0/2. Those are historical results, not Phase 3.2 results.

## Evidence summary

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

## Recommendation

Keep the semantic tools and bounded lowering for experimental use. First reproduce and resolve the signed `run_tests` return-code conflict in the existing trusted execution path, then rerun the focused Task A gate from a clean frozen workspace. Do not continue to the larger holdout until signed failure results agree with independent verification. Preserve the frozen tasks, scopes, hidden tests, model identity, and budgets. Do not migrate the production AgentHost on current Phase 3.2 evidence.

## Provenance

- Branch base / PR #45 exact head: `8ddabbcfdfcc2af8899ca30a4717ec82c4014b21`.
- Phase 3.2 implementation/evaluator head used for local validation: `441eb4d539983d25d121264ee203ab31f544b7dd`. The report files are documentation-only additions after that run; GitHub CI must validate the final PR HEAD.
- Active freeze SHA-256: `8c9685aba296d83cb3dd522ff9e7957a3074837cefd746f310689bd29c567e43`.
- Holdout dataset SHA-256: `d163fd20cff2db44cb0dc5f5260542666b098bbce403a0aafd30fa8b3e46615d`.
- DSH: `687f282e8625c6b8d11ff58211a90524be2e4317`; Node: `v22.19.0`.
- Local checks on the implementation head: `python3 -m unittest discover -s tests -v` (412 passed); `python3 -m unittest discover -s experiments/dsh_phase3_1 -v` (10 passed); `python3 -m unittest discover -s experiments/dsh_phase3_2 -v` (11 passed); `python3 tools/check_security_freeze.py` and `python3 tools/check_security_freeze.py --base 8ddabbcfdfcc2af8899ca30a4717ec82c4014b21` (both passed).
- Development: AUTONOMOUS. Experimental test operator: CODEX_AGENT. Owner Review: PENDING. Independent Code Owner Review: NOT_PERFORMED.
