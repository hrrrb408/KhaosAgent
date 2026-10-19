# Active Task Cancellation Acceptance

## Launcher flow

The responsive task panel appears after the user approves the operation and before
the Launcher establishes the authenticated Kernel path or starts
`workspace.run`. If cancelled while setup is in progress, the Launcher records the
cancel request and registers it on the handle before `start`; the handle then
prevents submission. The pre-start cancellation state is protected by the handle's
lock and serial request queue.

After submission, the handle retains the original authenticated XPC connection and
request ID. Cancellation is sent on that exact connection. A `cancel_accepted`
reply updates progress but does not close the task; the Launcher waits for the
original `workspace.run` result. There is no retry path. Runner elapsed time starts
at actual submission, not while connecting or preparing the broker.

Host-response waits use the same responsive panel. Cancelling invalidates that
task's Host connection and makes the pending completion one-shot; late replies are
discarded. Normal user turns retain the existing Host session, while cancellation
or a failed Host turn starts a fresh session for the next task.

## Outcome mapping

| Observed result | Task record interpretation |
|---|---|
| Cancel before `workspace.run` submission | `not_submitted`, `not_started`, `not_committed`; no Runner launch |
| Kernel `process_cancelled` | `not_committed`; no claim of rollback after live commit |
| Kernel `commit_rejected` | `rejected` |
| Kernel `commit_outcome_uncertain` | `uncertain`; no retry |
| Completed Kernel output | committed changeset and actual Runner return code, including nonzero |
| Original XPC result unavailable after submission | Runner and workspace outcome `unknown`; no retry |

The JSON Task Record binds Task ID, Request ID, workspace session, unique XPC
connection token, invocation digest, scopes, approval, cancellation request/result,
Kernel result, Runner execution/return code, changeset counts, and commit outcome.
It does not persist stdout/stderr or workspace file contents.

## Automated evidence

`test_launcher_workspace_command_cancellation_is_task_and_connection_bound` uses
a local fake XPC service and passed. It verifies cancellation before `start` and
during broker setup prevent `workspace.run`; wrong-task identity is rejected; the
submitted invocation bytes are unchanged; active cancellation uses the same XPC
connection and Request ID; exactly one cancellation is sent; and the original
`process_cancelled` reply arrives separately from `cancel_accepted`.

This is client coordination evidence, not signed-product acceptance. B32 (approved
then cancelled before Runner), B34 (commit cutoff), and B39 (signed terminal
consistency) remain `NOT_PROVEN` until the separate interactive signed acceptance
is authorized and completed. The earlier one-use replay did not exercise this code.
