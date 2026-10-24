# Coding Reliability Comparison

## Aggregate comparison

| Measure | Phase 3 baseline | Phase 3.1 semantic tools | Phase 3.2 generalization |
|---|---:|---:|---:|
| Completed real-model AgentLoop trials | 8 | 8 | 0 (one timed-out attempt reached independent verification) |
| Local model calls / responses | NOT_REPORTED | NOT_REPORTED | 8 / 8 across two Stage B attempts (1 + 7) |
| Hidden-test success | 0/8 | 6/8 | 0/1 independently evaluated attempts; hidden suite FAIL |
| First-pass hidden-test success | 0/8 | 4/8 | 0; no edit was proposed |
| Repair success | 0/2 | 2/2 (Task C) | 0/0; no repair was proposed |
| Approved Runner operations in real-model attempts | 1 | 30 | 6 |
| Tool-format / out-of-policy failures | 8 | 0 | 0 observed in 8 semantic proposals |
| Semantic tool parsing/lowering | Not applicable | 32/32, 32/32 | 8/8 proposals across 2 Task A attempts |
| In-policy proposals approved and executed | Not applicable | 30 approved operations | 6/7 in Attempt 2; one pending at timeout |
| Tool result delivery / Session continuity | Not measured | 32/32 / 32/32 | 6/6 completed operations in Attempt 2 |
| Signed test-result false-success status | Not measured | No discrepancy reported | UNRESOLVED: signed 0 vs independent 1 on both suites |
| Unauthorized approvals | 0 | 0 | 0 observed |
| Unexpected workspace changes | 0 | 0 | 0 observed |
| Observed Kernel authority violations | 0 | 0 | 0 |

Phase 3.2 Stage B now has two Task A attempts. Attempt 1 produced one valid semantic `read_file` proposal but stopped at the workspace Picker. Attempt 2 used the same frozen task and local model, produced seven semantic proposals (four reads and three public-test runs), and completed six approved Kernel/Runner operations. It timed out before AgentLoop termination and proposed no edit. Independent evaluation of its unchanged workspace failed both the public and hidden tests.

There is an unresolved result conflict in Attempt 2: both signed `run_tests` operations delivered `returncode=0` and DSH status `ok`, while independent public and hidden verification returned 1. The preserved raw evidence contains hashes and structured metadata but not the command's complete output, so the conflict cannot be attributed to a specific layer yet. It must not be counted as a false-success claim by the model or as a proven Kernel defect. It prevents treating test-result handling as validated.

## Failure attribution and conclusion

Phase 3 exposed that free-form low-level command and scope construction was unreliable: eight out-of-policy proposals and one actual Runner operation across eight trials. Phase 3.1's semantic interface removed those formatting failures in its measured runs: 32/32 semantic calls parsed and lowered, 30 operations were approved and executed, and six tasks passed independent hidden tests. The two Task D edits were denied because they were semantically incomplete; neither denial expanded authority or changed the workspace.

Phase 3.2 confirms that the observed model outputs fit and lower through the semantic interface, but it does not establish a coding-reliability improvement. Session telemetry correlates all six completed operation results with the following model turns. The independent task result is a failure, and the signed test return code disagrees with independent verification. The Stage A deterministic pass verifies a successful signed tool path, not error-result handling or model reasoning. Generalization beyond A–D remains untested; H01–H08 did not run.

Failure attribution for the latest attempt is therefore split by layer: semantic formatting and lowering succeeded for all 8 observed proposals; 6 requests reached and completed the Kernel/Runner path; 6 results reached DSH Session and the next model turn; no edit or repair proposal followed; independent verification failed; the two signed test statuses conflict with the independent results; and the AgentLoop timed out while a seventh request awaited an unexpected Picker. The test-result conflict is an integration/evidence blocker, not evidence that the model succeeded.

Recommendation remains limited to experimental use. Keep the semantic schema stable while investigating the exact signed `run_tests` result discrepancy. Do not claim a Phase 3.2 reliability improvement, and do not migrate the production AgentHost based on this evidence.
