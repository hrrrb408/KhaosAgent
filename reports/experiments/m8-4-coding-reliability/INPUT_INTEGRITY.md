# M8.4 input integrity

PASS. Prompt, baseline bundle HEAD and hidden patch match the objective. The manifest, preparer, grader, gold patch, hidden patch and baseline bundle are byte-identical to PR #31 head. Full SHA-256 values are in experiment-config.json. Four independent clean baseline clones are prepared. No hidden tests or reference patch are in model workspaces. No remote call has started.

Both the repository inputs and the actual private copied dataset are rehashed before each launch and before independent grading. The workspace HEAD must still equal the frozen baseline at launch. Candidate snapshots include tracked and untracked Git changes without modifying the index or following symlink targets. Original grader path validation and test-edit exclusion remain unchanged. A grader invocation failure preserves the already-saved terminal/diagnostics and a private-output hash summary marked GRADER_ERROR / NOT_CAPTURED.
