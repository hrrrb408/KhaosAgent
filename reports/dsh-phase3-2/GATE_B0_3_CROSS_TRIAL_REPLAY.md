# Gate B.0.3 Cross-Trial Replay

**Automated negative checks: PASS. Signed replay attempts: NOT_RUN.**

| Case | Automated result | Signed result |
|---|---|---|
| Stale Trial/runtime identity | Foreign runtime trial is rejected by the workspace identity evaluator | NOT_RUN |
| Reused old approval digest | Paired-trial evaluator rejects approval digest reuse | NOT_RUN |
| Old result injected into another trial with matching content digest | Rejected because the foreign runtime identity does not match | NOT_RUN |
| Workspace marker or directory identity replacement | Existing builder/runner tests reject marker replay and inode replacement | NOT_RUN |
| Missing parent terminal event | Evaluator rejects the request/result binding | NOT_RUN |
| Wrong result text digest | Evaluator rejects parent/Host/DSH digest mismatch | NOT_RUN |

Result-text digests may repeat when two authorized reads return identical content. Digest equality alone is not replay evidence; the trial, request, approval, workspace session, parent terminal, and DSH delivery bindings must all match. The pair report now records whether content digests overlap while separately requiring distinct request IDs and approval digests.

These are deterministic unit/evaluator checks. No signed Trial A/B session existed in this run, so none of the six negative cases received signed UI coverage.
