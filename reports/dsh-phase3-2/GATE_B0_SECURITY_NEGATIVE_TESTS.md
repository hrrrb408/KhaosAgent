# Gate B.0 Security Negative Tests

**Unit and evidence-validator status:** `PASS` on the corrected source.
**Real signed enforcement:** the first signed attempt exposed a trace-schema mismatch; a fresh signed acceptance is pending. Unit tests are not substituted for signed UI evidence.

## Coverage

| Required behavior | Unit/evidence test | Result |
|---|---|---|
| Create independent workspace identities and allow ordinary file edits without changing directory identity | `test_workspace_identity_manifest_is_owner_only_and_hash_bound` | PASS |
| Refuse Trial A manifest or marker when used for another workspace/trial | `test_workspace_identity_marker_replay_and_directory_inode_replacement_are_refused`; `test_workspace_identity_loader_rejects_workspace_manifest_replay_and_replacement` | PASS |
| Refuse workspace directory inode replacement | `test_workspace_identity_marker_replay_and_directory_inode_replacement_are_refused` | PASS |
| Refuse marker modification and symlink replacement | `test_workspace_identity_loader_rejects_workspace_manifest_replay_and_replacement` | PASS |
| Refuse stale approval, changed session identity, unknown binding state, stale result, and result digest mismatch | `test_workspace_identity_evidence_joins_runtime_trial_approval_and_result` | PASS |
| Refuse a cross-workspace symlink fixture that is not a valid owner-owned canary | `test_cross_workspace_symlink_setup_rejects_invalid_canary_and_records_only_hash` | PASS |
| Refuse reused approval across a two-trial evidence pair; require cross-workspace refusal evidence | `test_signed_workspace_trial_pair_rejects_reused_authority_and_missing_scope_refusal` | PASS |
| Refuse a failed prebuilt signature and an app with mismatched signed receipt identity | `test_prebuilt_app_signature_and_identity_mismatches_fail_closed` | PASS |
| Keep app overlay generic and independent of workspace path | `test_workspace_runtime_overlay_is_path_independent_and_experimental_only` | PASS |
| Require the runtime trial identity in the experimental tool-result trace schema | `test_experimental_tool_result_trace_requires_runtime_trial_identity` | PASS |

The protected builder and runner modules contain 7 and 14 tests respectively. Their focused tests passed, and the complete canonical suite passed with 462 tests. The two-trial evidence evaluator additionally rejects shared app-tree changes, repeated approvals, repeated sessions/results, missing scope refusal, or a model invocation when the pair contract requires none.

## Evidence boundary

These tests exercise manifest parsing, identity/evidence joins, source overlay generation, and fail-closed pair validation with synthetic workspaces and injected evidence. They do not prove that the signed macOS Launcher, Picker, Kernel XPC, or Runner enforces the same behavior in a real operation. The first signed run did prove that an unrecognized extra trace field fails closed, but it did not deliver the result to DSH. A corrected signed app must complete both disposable-workspace trials, including the intentional cross-workspace scope denial. Any signed case not completed remains `NOT_PROVEN`.
