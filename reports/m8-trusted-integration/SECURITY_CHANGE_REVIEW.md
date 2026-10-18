# M8.5.2A.5 Security Change Review

## Authorization and affected boundary

Owner authorization covers only Trusted Launcher preview/cancellation behavior,
its minimal request adapter, related tests, and Security Freeze governance inputs.
The preview parser and approval UI belong in the trusted Launcher because this is
where the human sees the exact request before it is sent to Kernel. Cancellation
belongs there because the Launcher owns the authenticated XPC connection and the
user's cancellation event. AgentHost or Runner code cannot supply approval evidence
or select another task's connection.

## Preserved invariants

- No automatic approval; every Runner action still requires a separate Launcher
decision.
- Candidate B preview is derived from the exact Runner source, argv, scope, and
frozen invocation submitted to Kernel.
- Preview failure disables execution and cannot fall back to ordinary approval for
a wrapper-like malformed request.
- The invocation is frozen before approval; no argv, scope, or bookmark is replaced
after approval.
- Cancellation is bound to Task ID, workspace-session ID, Kernel Request ID, and a
unique connection token. The implementation retains and reuses the same actual
authenticated `NSXPCConnection` for `workspace.run` and `cancelWorkspaceCommand`.
- Cancellation acknowledgement and the original Kernel result are separate.
  `process_cancelled`, `commit_rejected`, `commit_outcome_uncertain`, completed
  commits, and unavailable replies retain distinct outcomes. No automatic retry is
  added.
- No Kernel endpoint method, operation version, ABI field, capability, Seatbelt
  rule, scope grant, trusted process, external data recipient, dependency, or
  persistent product state is added.
- `AgentHostProtocol` names and reuses the existing 128-byte scope path bound; the
  accepted request set is unchanged.

## Testing boundary

The new cancellation probe uses a local fake XPC endpoint to prove client-side
identity and connection coordination, exact invocation bytes, pre-submission
behavior, and separation of the cancellation acknowledgement from the original
terminal reply. Existing repository tests exercise real Kernel/Runner commit and
cancellation behavior. These checks do not substitute for the signed-product UI
acceptance of B32/B34/B39.

The new preview probe covers the fixed eight-argument parser, malformed source,
wrong script/argv/scope/path, canonical JSON, path and argument bounds, complex
Unicode/control characters, request digest binding, and ordinary command
classification. It does not prove practical reviewability in a signed interactive
Launcher window.

The user authorized one earlier deterministic signed replay, which completed before
this implementation was finalized. Its evidence is preserved at
`staged-edit-signed-replay.json`; it is protocol feasibility evidence only and does
not exercise this new UI or cancellation path. No further interactive Runner
operation and no remote model call were performed.

## Governance status

- Development Authorization: `OWNER_AUTHORIZED`
- Independent Code Owner Review: `NOT_PERFORMED — SINGLE_MAINTAINER_MODE`
- Owner Review: `PENDING`
- Security Freeze: current-tree and exact-base checks passed; see `REGRESSION_REPORT.md`.
