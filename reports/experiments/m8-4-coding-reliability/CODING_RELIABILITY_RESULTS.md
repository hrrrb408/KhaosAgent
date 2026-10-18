# M8.4 coding reliability results

**Four formal attempts completed; four NO_CANDIDATE. Coding PASS: A 0/2, C 0/2. General Coding Reliability Closure: NOT_PROVEN.** All original independent graders completed in isolated clones with the original hidden patch applied, no candidate paths copied, hidden-test command return code 1 and no timeout. Grader invocation itself completed successfully. No hidden result or gold patch was returned to a model.

| Attempt | Read proposals / approvals / executions | Return-zero / nonzero | Actual Task Record | Runner seconds / result bytes | Candidate / hidden result |
| --- | --- | --- | --- | --- | --- |
| a-01 | 7/7/7 | 7/0 | task_failed, invalid_model_output_shape | 62.530 / 5134 | NO_CANDIDATE / test exit 1 |
| c-01 | 8/8/8 | 7/1 | budget_exhausted | 55.023 / 7506 | NO_CANDIDATE / test exit 1 |
| c-02 | 7/7/7 | 6/1 | task_failed, invalid_model_output_shape | 55.923 / 5946 | NO_CANDIDATE / test exit 1 |
| a-02 | 7/7/7 | 7/0 | task_completed, final response | 40.034 / 4159 | NO_CANDIDATE / test exit 1 |

All write scopes were empty. Parent inspection after each product exit confirmed baseline HEAD 7b6af61b3925b28ef105ea521c49424344de04c5, clean Git status and zero-byte candidate diff. Across 29 executions: 27 returned zero and two nonzero. Source files changed=0, accepted/executable write proposals=0, model test operations=0, failure-driven source repair attempts=0. Rejected raw actions were not retained; no claim about unobservable edit intent is made.

Code reading occurred. Read sequences alone do not prove correct bug localization. Code editing, model testing, test-failure analysis, code repair and successful independent candidate verification were not reached. c-02 revised a failed read script and then returned zero; this is read-command correction, not source repair. c-01's src listing failed and parent inspection found no src directory; the exact bounded error payload is not retained. The precise underlying c-02 read exception is also unknown.

A/a-02 is a useful limit on attribution: all eight initial responses passed strict validation and its final response completed, but it still produced no code. Launcher task_completed describes the bounded Agent task terminal, not the independent benchmark outcome. Likewise tool return zero and waiter exit zero are not coding success. A/a-01 and c-02 stopped on rejected output/correction, while c-01 exhausted the unchanged eight-tool budget reading. These paths identify where progress stopped without proving planning, context, localization, selection, truncation, sandbox or provider behavior as the sole cause.

Task terminal evidence is complete for 4/4. Whole-attempt Host diagnostic evidence is complete for 3/4; c-02 retains INCOMPLETE_HOST_DIAGNOSTIC_GAP and unknown original waiter exit. The same original product continued after interruption; no attempt or operation was replayed. Coding outcomes and grading are known independently of missing Host event totals.

The bounded protocol fix recovered eight eligible responses, but no real coding candidate was produced. Future investigation should separately measure code selection/editing, context use and test feedback with preregistered evidence. This result neither proves general inability nor licenses extra attempts, budget expansion, prompt changes or manual candidate repair.
