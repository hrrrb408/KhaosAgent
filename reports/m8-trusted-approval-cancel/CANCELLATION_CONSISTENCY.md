# Active task cancellation consistency review

## Current cancellation boundary

The existing Kernel Workspace XPC endpoint already exposes `cancelWorkspaceCommand(version, requestIDHigh, requestIDLow)`. The service accepts cancellation only when both the active request ID and `NSXPCConnection.current()` match the connection that submitted the active run. A successful `cancel_accepted` says cancellation was delivered; it does not say Runner cleanup or the operation has finished. The service retains its active slot until the Worker and snapshot cleanup finish. The final run reply is authoritative.

Launcher currently has no active-task cancel action. `runInKernel` calls the synchronous `KernelWorkspaceClient.request`, which creates the connection, waits on a semaphore and invalidates it after the reply. The AgentHost XPC request also blocks on a semaphore. The main Agent loop is synchronous. A second XPC connection cannot cancel the first connection's request, and closing the app/connection loses the terminal reply. A user-visible control therefore needs a retained same-connection request handle and a responsive AppKit wait path.

## Required request identity

Use an ephemeral task identity distinct from the Kernel request ID. Bind the current task to exactly one active operation tuple: task identity, request ID, authenticated XPC connection object, and the already selected workspace session/bookmark. A cancel click and every asynchronous completion must compare that tuple to the still-active task. Do not let a stale task's cancel or late Host reply affect a newer task. No approval grant or cancellation state needs to persist after the session ends.

While an approval dialog is open, its Cancel/close action invalidates the task and prevents `workspace.run` submission. Immediately before submission, check that the task is still active. There is no reusable approval token; no late button response may recreate the task.

During Runner execution, send the existing `workspace.cancel` on the original authenticated connection. Keep waiting for the original `workspace.run` response. Never signal the process group from Launcher. If the final XPC reply is lost, retain unknown outcome and do not retry automatically.

## Result mapping

| Observed event/result | User-facing task state | Workspace statement |
|---|---|---|
| Cancel clicked; no Kernel response yet | Cancellation requested / waiting | No terminal claim |
| `cancel_accepted` | Cancellation request accepted / waiting for Kernel result | No terminal claim |
| `process_cancelled` | Execution cancelled | Kernel confirms no writeback for this request |
| Successful `WorkspaceResult` with changes | Execution finished | Kernel-reported changeset committed, even if a late cancel was requested |
| Successful `WorkspaceResult` with zero changes | Execution finished | No changes were committed |
| `commit_rejected` | Execution rejected | Kernel confirms the changeset was not committed |
| `commit_outcome_uncertain` | Outcome uncertain | Explicitly uncertain; never say rollback or unchanged |
| `process_not_active` from a late/mismatched cancel | Cancellation not accepted; await run result if active client still has it | No terminal claim from the cancel reply |
| XPC interruption with no final run reply | Terminal result unavailable | Outcome unknown until independently inspected; no automatic retry |

The report and UI must distinguish a command's nonzero return code from commit status: an exit-1 operation can still have a committed in-scope changeset. The Launcher Task Record should contain a closed terminal category, cancel-requested/accepted facts, actual Kernel result and changeset counts. It must not fabricate final hashes. Signed acceptance can independently hash the disposable fixture in the parent process.

## Agent Host lifecycle

AgentHost is untrusted and receives no workspace authority. Launcher must stop accepting output for a canceled task by comparing the local task identity before it consumes any late response. Whether to add cooperative AgentHost model cancellation remains a review question: `AgentHostClient` currently waits synchronously, and connection invalidation alone does not prove model computation stopped. A new AgentHost IPC operation would be a nonzero IPC delta and must be separately justified. It cannot determine workspace outcome.

The offline cancellation harness tests exact task/request/connection matching and the result mapping. It does not exercise the current XPC service or signed UI, so Signed Cancellation Consistency remains **NOT_PROVEN**.
