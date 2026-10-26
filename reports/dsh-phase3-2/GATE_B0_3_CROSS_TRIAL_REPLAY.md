# Gate B.0.3 Cross-Trial Replay

**Automated negative checks: PASS. Signed replay attempts: NOT_RUN.** Trial B did not establish the required cross-workspace refusal. The objective therefore requires stopping subsequent signed experiments; no signed replay, replacement, missing-parent, or wrong-digest attempt was made.

| Case | Automated evidence | Signed result |
|---|---|---|
| Stale Trial/runtime identity | Workspace identity evaluator rejects foreign runtime-trial/session bindings | NOT_RUN |
| Reused Trial A approval digest | Paired-trial evaluator detects approval digest reuse | NOT_RUN |
| Cross-trial result injection, including same content digest | Identity binding rejects foreign-trial delivery; identical content digest alone is accepted when request/trial identities differ | NOT_RUN |
| Workspace identity replacement | Builder/runner tests reject marker replay, workspace substitution, and inode replacement | NOT_RUN |
| Missing parent terminal event | Result-binding evaluator fails when the trusted parent terminal record is absent | NOT_RUN |
| Wrong result text digest | Host/parent/DSH digest mismatch is rejected by automated evaluator tests | NOT_RUN |

## Runtime observations relevant to replay

The two signed workspaces had distinct runtime trial IDs, Launcher task IDs, workspace-session IDs, directory inodes, marker hashes, request IDs, and approval digests. Trial A and Trial B's authorized `fee.py` reads produced the same result-text digest, as expected for identical file contents. The two requests and approvals were different. The pair evaluator separately records `result_content_digest_overlap=true`; it does not treat content-hash equality by itself as replay.

The official pair report remains **FAIL** because Trial B's symlink result did not identify an enforcement refusal. Its cross-trial signed replay field is `NOT_ATTEMPTED_IN_SIGNED_UI`. Automated tests do not substitute for the six signed cases above.

## Focused automated suite

`python3 -m unittest discover -s tests -p 'test_dsh_xpc_acceptance_*.py' -v`: **30 PASS**. The cases include stale approval, foreign runtime identity, reused approval digest, mismatched result digest, absent parent terminal, workspace marker replacement, wrong canary binding, and fail-closed handling of an unclassified `rc=1`.
