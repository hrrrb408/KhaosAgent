# M8.5.2A.4 implementation audit

## Verified baseline

Audit date: 2026-10-18 UTC. Current branch started from PR #37's exact HEAD `02b8277c8c8b96d8679a1d064e23595d87dab657`; PR #37 is OPEN/Draft and its base is PR #36 HEAD `9c111de6053bde6e83483724e45ce5bc337f10ec`. `origin/main` is `27ef0b4787f807fc76ffd7ba9cdb467ffc9a2f27`. The worktree was clean before this report-only change.

| PR | State | Head | Base | CI at audit | Reviews |
|---|---|---|---|---|---|
| #33 | OPEN / Draft | `1d1457f43f788d30f6fa4f48890b900ef9406c07` | `experiment/m8-4-glm53-coding-reliability` @ `23d00c762af04b20b46f818fc611bcd5db16a211` | security-freeze PASS; security-tests PASS | none |
| #34 | OPEN / Draft | `6724d5ac5e52e1c157f3701f30009ed81b55fb90` | `research/m8-5-1-coding-tool-architecture` @ `1d1457f43f788d30f6fa4f48890b900ef9406c07` | both PASS | none |
| #35 | OPEN / Draft | `9dac79839da1d2d7c1c29027136f85eb85c28bce` | `feature/m8-5-2-minimal-secure-edit` @ `6724d5ac5e52e1c157f3701f30009ed81b55fb90` | both PASS | none |
| #36 | OPEN / Draft | `9c111de6053bde6e83483724e45ce5bc337f10ec` | `test/m8-5-2a1-secure-edit-gate-closure` @ `9dac79839da1d2d7c1c29027136f85eb85c28bce` | both PASS | none |
| #37 | OPEN / Draft | `02b8277c8c8b96d8679a1d064e23595d87dab657` | `test/m8-5-2a2-final-gate-resolution` @ `9c111de6053bde6e83483724e45ce5bc337f10ec` | security-freeze PASS; security-tests PASS at run `39145858255` (16m28s) | none |

No PR in this stack is merged. Each reports `reviewDecision` empty and `latestReviews=[]`.

## Independent review gate

`.github/CODEOWNERS` routes `/khaos/macos/`, `/tests/`, `/docs/`, and security files to `@hrrrb408`. `docs/SECURITY_FREEZE.md` records that the repository has one writable owner who cannot approve their own change. The current branch protection API reports required approvals `0` and `require_code_owner_reviews=false`; this is not independent approval. No independent security review is evidenced on PR #37.

Therefore this branch may contain the design and report-local, nontrusted harness only. Trusted Launcher changes and protected test changes are **BLOCKED_PENDING_SECURITY_REVIEW**. This is the governance path required by the objective; user authorization for the overall task does not waive it.

## Current execution paths

- `AgentHostProtocol.decodeReply` accepts `shell`, `list`, Plugin and evolution replies. There is no production `edit` action. `AgentHostActionOutput` likewise has no structured edit output.
- `TrustedWorkspaceLauncherMain.runAgentTool` builds the exact `WorkspaceRunRequest` from the Host's shell argv and scopes. `agentRunnerSource(argv:)` embeds argv in its fixed Runner source. Launcher creates a single request ID, encodes the invocation with the selected bookmark, and displays the invocation digest. After Run once, it submits that same request and ID through `runInKernel`.
- `approveReviewedRequest` shows argv, read/write scope and digest in an `NSAlert` with a scrollable detail view. It does not decode a Candidate B replacement preview. Approval denial returns before Kernel submission.
- `runAgentSession`, `AgentHostClient.request` and `KernelWorkspaceClient.request` synchronously wait for XPC replies. The Agent session is called from `main`; the workspace client waits on a semaphore and invalidates its connection in `defer`. No active task cancel control or UI event path is wired during those waits.
- `KernelWorkspaceService.cancelWorkspaceCommand` already checks both the active request ID and the exact submitting `NSXPCConnection`. `cancel_accepted` confirms delivery only. The workspace request remains active through cleanup; the final `workspace.run` reply carries the terminal result. No new Kernel ABI operation is necessary.
- `safeWorkspaceErrorCode` preserves `process_cancelled`, `commit_rejected` and `commit_outcome_uncertain`. The Launcher Task Record is a stdout summary of proposal count, command return codes, cumulative Runner time, result bytes and stop reason. It does not identify the commit result or provide a final workspace hash. Agent Host receives `ok`, `can_continue` and bounded text; its prompt forbids inferring workspace state.

The complete source references and request/response mapping are documented in [TRUSTED_CHANGE_REVIEW.md](TRUSTED_CHANGE_REVIEW.md) and [CANCELLATION_CONSISTENCY.md](CANCELLATION_CONSISTENCY.md).
