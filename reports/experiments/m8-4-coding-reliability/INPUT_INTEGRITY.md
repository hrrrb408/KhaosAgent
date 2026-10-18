# M8.4 input integrity

PASS. Prompt, baseline bundle HEAD and hidden patch match the objective. The manifest, preparer, grader, gold patch, hidden patch and baseline bundle are byte-identical to PR #31 head. Full SHA-256 values are in experiment-config.json. Four independent clean baseline clones are prepared. No hidden tests or reference patch are in model workspaces. Both input copies and the clean workspace baseline were checked before each completed session.

Both the repository inputs and the actual private copied dataset are rehashed before each launch and before independent grading. The workspace HEAD must still equal the frozen baseline at launch. Candidate snapshots include tracked and untracked Git changes without modifying the index or following symlink targets. Original grader path validation and test-edit exclusion remain unchanged. A grader invocation failure preserves the already-saved terminal/diagnostics and a private-output hash summary marked GRADER_ERROR / NOT_CAPTURED.

Final parent audit confirms all four formal workspaces remain at the exact clean baseline with empty candidate diffs. The 24 required per-attempt JSON artifacts and 29 unique approved request/review hashes pass artifact-audit-final.json. The frozen protocol SHA-256 remains fc4518e1e978cf4e747befcf727c7c5e03bac58cfc89d5bda42cd8c0f77ea9af.
