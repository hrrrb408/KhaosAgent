# Trusted change review request

**Decision requested from an independent security reviewer:** review the two proposed, separate Trusted Launcher changes before any protected implementation begins. This file is a review request, not an approval. Independent review is currently **NOT_PROVEN**.

## Workstream A — Candidate B approval preview

### Proposed minimal implementation

1. Retain the existing `WorkspaceRunRequest`, request ID, `encodeInvocation` digest and `approveReviewedRequest` path.
2. Derive a preview only from the actual request's fixed Runner wrapper and its exact encoded argv. Validate the wrapper identity before decoding the argv; then validate the fixed test-only Candidate B script, exact argument count, four-field payload, path, bounded old/new text, and `readScope == [path]`, `writeScope == [path]`.
3. Show a proposed replacement, target, exact scopes and the same digest. Keep a scrollable full-details panel with executable, complete argv, fixed script identity, decoded values and digest. Escape controls, bidi and zero-width format characters visibly.
4. For a recognized Candidate B test request with malformed, changed, or over-budget parameters, show `PREVIEW_INCOMPLETE` and disable Run once. Preserve the bounded raw request details. Never fall back to shell approval for a request already classified as requiring preview.
5. Keep ordinary shell approval unchanged. Do not add a production structured `edit` action in this phase.

### Security rationale

The approval view influences the user's trusted decision, so request parsing and preview binding cannot live in untrusted Agent Host code. A Host-generated Diff is untrusted. The existing invocation digest is a useful trusted primitive but does not decode the actual request into a reviewable change. A small pure parser/renderer in the Launcher is smaller than a general patch engine. It needs no workspace read, file diff, fuzzy match, or additional capability.

### Classification design question

The current Host protocol has no structured `edit` kind or trusted “preview required” fact. The A4 test-only shell fixture can be recognized by its exact request/script shape; a Host-supplied marker cannot establish that property. The reviewer must decide how a future production Edit action can be distinguished without trusting a Host self-report. If that cannot be done while production Edit remains out of scope, the integration must remain test-only and this design issue stays open. Any recognized preview-required request that fails parsing must fail closed.

## Workstream B — active task cancellation

### Proposed minimal implementation

1. Add one ephemeral Launcher task identity and bind it to the current Kernel request ID, selected workspace session/bookmark digest, and the authenticated XPC connection that submitted the request. No durable approval record or second task manager.
2. Use the existing Workspace XPC `cancelWorkspaceCommand` through the same connection that submitted `workspace.run`. Keep that connection alive until the actual run reply arrives; do not treat `cancel_accepted` as a terminal result.
3. Make only the active wait nonblocking enough to keep the native UI responsive. Show “cancellation requested; waiting for Kernel” while waiting for the final result. Do not directly signal Runner processes or invent a Kernel status.
4. Dismissal of the pending per-operation approval stops before submission and invalidates that task context. Before any async continuation submits or accepts a Host reply, check the same active task identity. A stale callback cannot resume a canceled task.
5. Map the final Kernel result to a truthful task record: `process_cancelled` means no writeback; successful result means the reported changeset committed even if cancellation was requested late; `commit_rejected` means Kernel-confirmed rejection; `commit_outcome_uncertain` or lost terminal response stays explicitly uncertain.

### Security rationale

Only the trusted Launcher owns the user cancel action and the admitted request/connection identity. The Kernel already owns process cleanup and commit cutoff; no new Kernel authority or ABI is needed. `KernelWorkspaceClient.request` currently blocks and invalidates its connection after reply, so an asynchronous request handle that retains that same authenticated connection is the smallest plausible reuse. The exact AppKit responsiveness design needs review before implementation.

### Host work cancellation question

`AgentHostClient` also blocks while waiting for a model/tool reply. Canceling a Launcher task must cause late Host replies to be discarded by task identity. Whether the local Agent Host model computation itself must be cooperatively canceled, and whether that requires one new AgentHost XPC operation, must be decided in review. That would be a non-Kernel IPC delta and must be reported; no such operation is implemented here. Closing an XPC connection alone is not evidence that the Host stopped computing.

## Proposed delta and invariants

| Item | Proposed value |
|---|---|
| Protected runtime files | `khaos/macos/TrustedWorkspaceLauncherMain.swift`; likely `khaos/macos/KernelWorkspaceClient.swift`; a focused new Launcher preview helper only if the reviewer agrees it reduces complexity |
| Possibly affected trusted Host client/protocol | `khaos/macos/AgentHostClient.swift`, `AgentHostProtocol.swift` only if review requires cooperative model cancellation |
| Trusted runtime code delta | NONZERO if approved and implemented |
| Kernel authority / Kernel ABI | 0 / 0 |
| Workspace scope authority / sandbox / changeset validation | 0 / 0 / 0 |
| New processes / persistent state / third-party dependencies | 0 / 0 / 0 |
| New Kernel IPC | 0; reuse request-bound `workspace.cancel` |
| New AgentHost IPC | 0 in the base proposal; any addition requires separate justification/review |
| Approval authority | No expansion; one explicit decision per operation remains required |

Before approving implementation, review the exact diff against these invariants, the Security Freeze declaration/manifest update, and the adversarial test plan in `PREVIEW_SECURITY_AUDIT.md` and `CANCELLATION_CONSISTENCY.md`. The only current source of authority is the user's separately reviewed per-operation Run once choice plus the existing Kernel policy.
