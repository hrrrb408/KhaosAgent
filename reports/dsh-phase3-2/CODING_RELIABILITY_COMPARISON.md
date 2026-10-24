# Coding Reliability Comparison

## Aggregate comparison

| Measure | Phase 3 baseline | Phase 3.1 semantic tools | Phase 3.2 generalization |
|---|---:|---:|---:|
| Completed real-model trials | 8 | 8 | 0 |
| Hidden-test success | 0/8 | 6/8 | NOT_MEASURED |
| First-pass hidden-test success | 0/8 | 4/8 | NOT_MEASURED |
| Repair success | 0/2 | 2/2 (Task C) | NOT_MEASURED |
| Approved Runner operations in real-model trials | 1 | 30 | 0 |
| Tool-format / out-of-policy failures | 8 | 0 | NOT_MEASURED |
| Semantic tool parsing/lowering | Not applicable | 32/32, 32/32 | One Stage B proposal observed, not a completed trial |
| Tool result delivery / Session continuity | Not measured | 32/32 / 32/32 | NOT_MEASURED |
| Unauthorized approvals | 0 | 0 | 0 observed |
| Unexpected workspace changes | 0 | 0 | 0 observed |
| Observed Kernel authority violations | 0 | 0 | 0 |

Phase 3.2's Stage B trace contains one local-provider model response and one `read_file` call that passed DSH parsing, argument validation, deterministic lowering, and proposal submission telemetry. The CUA client failed to bind to the modal signed workspace Picker. Since no workspace selection, approval, Kernel result, or Runner operation followed, these events are not a benchmark trial and are not included in the aggregate rates above.

## Failure attribution and conclusion

Phase 3 exposed that free-form low-level command and scope construction was unreliable: eight out-of-policy proposals and one actual Runner operation across eight trials. Phase 3.1's semantic interface removed those formatting failures in its measured runs: 32/32 semantic calls parsed and lowered, 30 operations were approved and executed, and six tasks passed independent hidden tests. The two Task D edits were denied because they were semantically incomplete; neither denial expanded authority or changed the workspace.

Phase 3.2 adds generalization coverage and hardens frozen evaluation, but it adds no valid real-model coding outcome. The Stage A deterministic pass verifies the signed tool path, not reasoning. The Phase 3.1 improvement remains the best real-model evidence; generalization beyond A–D is unproven until the frozen H01–H08 trials run.

Recommendation remains limited to experimental use. Keep the semantic tool schema stable. Do not claim a Phase 3.2 reliability improvement, and do not migrate the production AgentHost based on the current Phase 3.2 trial count.
