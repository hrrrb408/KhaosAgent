# Signed Cancellation and Terminal-Outcome Acceptance

## Signed-product disposition

| Requirement | Result | Evidence boundary |
|---|---|---|
| B32: cancel after approval and before Runner start | `NOT_PROVEN` | No signed stage-synchronized run established approval, cancellation, zero Runner starts, and the terminal Task Record together. The current B38 review fixture is a pre-execution user refusal and is not B32. |
| B34: cancel at the commit cutoff and report the true result | `NOT_PROVEN` | There is no signed cancel-at-cutoff Task Record. L3 cutoff probes do not exercise the signed Launcher/XPC terminal mapping. |
| B39: Task Record matches Kernel operation outcome | `NOT_PROVEN` for signed cancellation | A historical positive replay is complete, and offline refusal/Kernel outcomes are separate. No signed cancellation record joins the Launcher Task Record to the original Kernel terminal reply. |

## Executed headless evidence

- Focused command: `python3 -m unittest discover -s tests -p test_macos_xpc_sandbox.py -k test_launcher_workspace_command_cancellation_is_task_and_connection_bound -v`; one test passed.
- The command client binds cancellation to its Task ID, workspace session, Request ID, and original authenticated XPC connection. Pre-submission cancellation prevents `workspace.run`; cancellation acknowledgement is not substituted for the original command result.
- The full canonical suite includes Candidate B cancellation before and after private replacement, commit-race, and late-cancel tests. Its final result is recorded in `REGRESSION_REPORT.md`.
- The L3 `B34_POST_COMMIT_EVIDENCE` record reports `WorkspaceCommandResult`, Runner return code 0, one modified `tags.py`, no temporary entries, and unchanged `unscoped-canary.txt`. Initial `tags.py` SHA-256 was `476ac287f5ed529f016a1ba705a336abb57f38156da8a097a2a0ddbed2e5f164`; final was `8db3b1d5a79058bc0db32f9904c38162c6384ff813d41ab45b9db2348a264a63`. The canary SHA-256 remained `0b6ba3c1ade1071adfd0088da2fd0fb0ab3bb522405ddb593d70c192d04836cd`. A late cancellation was issued after the live target already held the committed replacement; the committed result remained authoritative.

These are L3 process/Kernel tests. They do not prove the signed Launcher/XPC UI lifecycle.

## Signed UI attempts and synchronization gap

- `signed-candidate-b-review-final3.json` preserves a failed signed attempt. The exact disposable workspace was selected, but the harness remained at its explicit “press Return here” terminal gate; it timed out after 637.431 seconds. It did not reach the Candidate details or cancellation stages, so it is not acceptance evidence.
- `signed-candidate-b-review-final4.json` and its log preserve the controlled rerun. B38 passed: the user opened the full details, scrolled to the bottom, and denied with Escape. The Task Record shows `kernel_result=not_submitted`, `runner_execution=not_started`, `commit_outcome=not_committed`, and the same request digest as the review. This is a refusal result, not B32 active cancellation or B34 commit-cutoff evidence.
- Earlier failed attempts are retained as `signed-candidate-b-review.json`, `signed-candidate-b-review-final.json`, and `signed-candidate-b-review-final2.json`; their failure states are described in `SIGNED_UI_ACCEPTANCE.md`.

The existing signed test harness does not expose a deterministic barrier at the post-approval/pre-`workspace.run` point or at the commit cutoff. Do not infer B32/B34 from ordinary refusal, delay a UI action in an unsynchronized run, or treat L3 evidence as signed proof.

## Narrowest safe harness to close B32/B34/B39

Add a test-only synchronization channel to the disposable signed acceptance fixture at the existing Launcher-to-XPC submit boundary and the existing Kernel commit/result boundary. It must not change the production build, authority, ABI, scope policy, or trusted lifecycle behavior. The fixture should pause at a named stage, let the user operate the actual signed Task Progress UI, then resume the same Task ID and XPC connection. Record the original Kernel reply, Runner count, changed paths and hashes, and final Launcher Task Record in one run. For B32, prove no `workspace.run` or Runner start after cancellation. For B34/B39, exercise cancellation on both sides of the real commit cutoff and require the final UI record to agree with the original Kernel result. Each cancellation action remains manual.
