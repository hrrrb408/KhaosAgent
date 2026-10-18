# B34 — Commit Cutoff Cancellation

## Trusted boundary reviewed

The Worker obtains a private Snapshot, runs the isolated Runner, validates the complete changeset against the retained write scope, and asks the broker to authorize live mutation. The broker's commit child validates output and installs the live-path Seatbelt profile before sending READY. The parent checks cancellation before READY and again after READY, immediately before sending ACCEPT. An abort before ACCEPT produces no live mutation. After ACCEPT, the commit child may mutate live files; the caller cannot assume rollback. If a failure occurs after a live mutation begins, workspace_changes.py raises WorkspaceCommitOutcomeUncertain. The broker also rejects a delayed process.cancel as process_not_active once process execution has ended.

## Deterministic evidence

| Case | Test evidence | Observed result |
|---|---|---|
| A — cancellation before commit | test_staged_edit_cancellation_after_source_read_before_replace_discards_snapshot and test_staged_edit_cancellation_after_private_replace_discards_snapshot | Both returned process_cancelled before commit. Live tags.py and canary remained unchanged; no temporary entry remained. |
| B — commit cutoff | test_caller_cancel_at_commit_gate_prevents_live_mutation | The real macOS broker test synchronized on READY, delivered cancellation before ACCEPT, received commit_rejected, and left the live target unchanged. test_caller_cancel_before_commit_discards_snapshot_changes also passed. |
| C — signal after live commit | test_staged_edit_late_cancel_reports_the_already_committed_result | The test callback observed the live target only after it contained the replacement. The L3 call returned WorkspaceCommandResult with return code 0 and changeset 0 added / 1 modified / 0 deleted. Final tags.py SHA-256 was 8db3b1d5a79058bc0db32f9904c38162c6384ff813d41ab45b9db2348a264a63; canary SHA-256 remained 0b6ba3c1ade1071adfd0088da2fd0fb0ab3bb522405ddb593d70c192d04836cd; no temp remained. |

The post-commit test demonstrates the observed late cancellation callback and the actual completed L3 result. It is not a signed XPC task-cancel test and does not claim that a post-commit cancellation can reverse a mutation. No Task Record with an accepted cancellation racing this cutoff was captured.

The existing broker test test_commit_child_death_after_a_live_swap_reports_uncertain confirms the distinct uncertain-result path after live mutation begins. Existing partial-write and cleanup tests also assert the structured uncertainty result. These tests establish that the implementation does not infer rollback from a failed commit child; they do not replace the B34 signed Task Record requirement.

## Required statuses

- Pre-Commit Cancellation: PASS (L3)
- Commit-Cutoff Cancellation: PASS (L3; cancellation is synchronized before ACCEPT)
- Post-Commit Cancellation: PASS (L3 result remains success after the test observes the late signal)
- Final Workspace Outcome: VERIFIED for the exercised L3 cases
- Terminal Outcome Consistency: NOT_PROVEN at the signed Task Record level. The L3 API result and live file state agree, but no signed XPC cancellation Task Record was captured.

The deterministic test facilities reached the Kernel commit cutoff, so this is not BLOCKED_BY_EXISTING_TESTABILITY. L4 signed cancellation and terminal-record claims remain under the inherited Gate A requirement and require a separate user-authorized operation. No such action was performed here.
