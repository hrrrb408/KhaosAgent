# Cancellation state mapping

This maps the source behavior without adding production enums or IPC fields.

| Lifecycle fact | Existing Khaos representation | What the product can currently claim |
|---|---|---|
| Cancellation requested | No active Agent-task cancel control/event in the Launcher loop | Not available through the current coding UI. Picker dismissal and approval denial happen before Kernel execution. |
| Cancellation accepted | Kernel XPC has a request-id/connection-bound cancellation path, documented in `docs/KERNEL_ABI.md`; current Launcher `runInKernel` does not wire a user cancel signal to it | No signed product “cancel accepted” event is exposed for an Agent task. |
| Runner started/finished | Runner time and successful command return codes are accumulated; failures may have no return code | No distinct structured start/finish record. |
| Commit started | Internal Kernel stage only | Not exposed in the Launcher task record. |
| Commit succeeded | Successful `WorkspaceResult` contains return code and added/modified/deleted counts; bounded result is sent to Host | Actual success/counts are available to the Launcher/Host. No rollback is implied by a later signal. |
| Commit rejected | `commit_rejected` survives `safeWorkspaceErrorCode` | Task stops with the exact code in bounded error text; no command return code is fabricated. |
| Commit outcome uncertain | `commit_outcome_uncertain` survives `safeWorkspaceErrorCode` | Exact uncertainty code is retained, but the user-facing status is generic “stopped”; no unchanged-workspace claim is made. |
| Task terminal recorded | `Launcher task status` plus a stdout “Launcher task record” line | Informational line only; it is not a durable typed record with final workspace hash or commit stage. |

Agent Host receives `tool_result` with `ok`, `can_continue`, and bounded text. Its prompt explicitly prohibits inferring a return code or unchanged workspace from refusal/cancellation/failure. There is no structured Agent Host field for Kernel commit outcome.
