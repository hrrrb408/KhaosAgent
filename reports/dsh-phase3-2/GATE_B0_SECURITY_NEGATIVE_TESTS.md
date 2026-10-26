# Gate B.0 Security Negative Tests

**Unit/evidence-validator status:** `PASS` in focused tests.

**Signed multi-workspace acceptance:** `NOT_PROVEN`; both observed trial records have an overall `FAIL` verdict.

## Coverage

| Required behavior | Evidence | Result |
|---|---|---|
| Independent workspace identities and ordinary file edits without changing directory identity | `test_workspace_identity_manifest_is_owner_only_and_hash_bound` | PASS |
| Trial/manifest/marker replay across workspaces | `test_workspace_identity_marker_replay_and_directory_inode_replacement_are_refused`; `test_workspace_identity_loader_rejects_workspace_manifest_replay_and_replacement` | PASS |
| Workspace directory inode replacement | `test_workspace_identity_marker_replay_and_directory_inode_replacement_are_refused` | PASS |
| Marker modification and symlink replacement | `test_workspace_identity_loader_rejects_workspace_manifest_replay_and_replacement` | PASS |
| Stale approval, changed session, unknown binding state, stale result, and result digest mismatch | `test_workspace_identity_evidence_joins_runtime_trial_approval_and_result` | PASS |
| Require terminal evidence emitted by the parent Trusted Launcher | `test_workspace_identity_evidence_joins_runtime_trial_approval_and_result` | PASS |
| Join the trusted raw-text digest with DSH terminal and tool-result delivery digests | `test_workspace_identity_evidence_joins_runtime_trial_approval_and_result`; semantic fixture digest matcher test | PASS |
| Refuse missing, wrong-source, replayed, or mismatched result evidence | `test_workspace_identity_evidence_joins_runtime_trial_approval_and_result`; `test_signed_workspace_trial_pair_rejects_reused_authority_and_missing_scope_refusal` | PASS |
| Refuse an invalid owner-owned cross-workspace canary setup | `test_cross_workspace_symlink_setup_rejects_invalid_canary_and_records_only_hash` | PASS |
| Refuse failed prebuilt signature or mismatched signed receipt identity | `test_prebuilt_app_signature_and_identity_mismatches_fail_closed` | PASS |
| Keep the runtime overlay generic and independent of a workspace path | `test_workspace_runtime_overlay_is_path_independent_and_experimental_only` | PASS |
| Validate the bounded runtime-trial result trace and parent terminal-event injection | Builder overlay tests | PASS |

The focused builder and runner modules passed 9 and 14 tests. The pinned DSH semantic-tool suite passed 19 tests, and its model-bridge/lifecycle suite passed 17 tests. Generated Launcher and experimental Host Swift passed syntax parsing. The canonical suite passed all 464 tests in 843.146 seconds. Default Security Freeze passed with `sensitive changes=0`; the exact PR #47 base check passed with `sensitive changes=5`.

## Signed UI evidence

One signed no-model app was reused with two separately selected workspaces and retained the same app-tree digest. Trial A approved the intended `fee.py`/`test_public.py` reads, the bounded `fee.py` edit, reread, and public test run. The Runner operations succeeded; the public and independent hidden tests passed, and only the intended source file changed. The formal trial still failed because the parent Launcher terminal digest record was missing from captured stderr.

Trial B approved one `fee.py` read attempt against the owner-staged cross-workspace symlink. The Runner returned 1, no canary was disclosed, and the workspace remained unchanged. The evidence recorded a denial signal, but exact refusal correlation was false and the one-operation task ended incomplete. The formal trial failed and does not establish the signed cross-workspace refusal result.

The new result-correlation instrumentation and evaluator tests are source/unit evidence only; the new behavior has not been exercised by a signed app. No model was invoked and no `.gguf` was copied. Independent review remains pending.
