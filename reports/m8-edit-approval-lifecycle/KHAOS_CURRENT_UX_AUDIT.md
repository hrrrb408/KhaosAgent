# Khaos current UX and lifecycle audit

Audited PR #36 HEAD `9c111de6053bde6e83483724e45ce5bc337f10ec` source, not filenames alone.

## Approval path

`AgentHostActionOutput.swift`/`AgentHostProtocol.swift` accept `shell` and `list` proposals, not a production structured `edit` action. Candidate B argv cases are synthetic B38 fixtures. `TrustedWorkspaceLauncherMain.runAgentTool` validates argv and scopes, creates one `WorkspaceRunRequest`, then creates a request id and encodes the invocation with the selected workspace bookmark. The approval digest is SHA-256 of that invocation. `approveReviewedRequest` shows the proposal argv, readable paths, committable paths, and digest; on approval, `runInKernel` receives the same request id and same `WorkspaceRunRequest`.

`approvalDetailsView` uses a vertically scrolling `NSTextView`. This proves a scrollable raw-detail control exists; it does not prove a person can inspect complex encoded old/new text accurately. The UI does not recognize Candidate B's fixed script, decode its JSON parameters into a Diff, expose a separate complete-argument view, or mark an incomplete preview.

## Result and cancellation path

After execution, `agentResult` returns the Kernel's return code, added/modified/deleted counts and bounded output. Kernel error codes including `process_cancelled`, `commit_rejected`, and `commit_outcome_uncertain` are preserved by `safeWorkspaceErrorCode`. `runAgentTool` turns an error into a stop result without inventing a return code; Agent Host is instructed not to infer that a command ran or that the workspace is unchanged.

The task loop has no active-task Cancel control or cancellation handler wired into `runInKernel`. Picker cancellation and declining the approval are pre-execution paths; they are not post-approval Runner cancellation. The printed “Launcher task record” is a bounded stdout line containing proposal count, successful command return codes, elapsed Runner time, result bytes, and a stop reason. It is not a structured durable record of commit outcome or final workspace hash.

## Reusable evidence

`reports/m8-secure-edit-final-gate/B38_APPROVAL_REVIEWABILITY.md` records synthetic argument round-trips and the exact short signed approval binding. `B34_COMMIT_CUTOFF_CANCELLATION.md` records L3 cancellation outcomes and the absence of signed Task Record evidence. This audit adds no new product observation.
