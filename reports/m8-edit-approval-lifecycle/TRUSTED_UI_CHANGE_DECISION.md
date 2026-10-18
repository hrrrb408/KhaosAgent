# Trusted UI change decision

Existing UI Sufficient: **NO** for Candidate B Diff review.

Trusted UI Change Required: **YES** to deliver a request-bound Diff, complete-parameter expansion, explicit incomplete state, and fail-closed approval behavior.

Independent Security Review: **NOT_PROVEN**.

Trusted Code Delta: **0** in this change. A future implementation would be **NONZERO** because the review decision and displayed Diff must be derived inside Trusted Launcher.

Authority Expansion: **NO** proposed. No scope, Kernel capability, approval grant, IPC authority, or sandbox permission needs to change.

## Smallest proposed review surface

1. Add a bounded pure parser/renderer in a narrowly scoped Launcher file for one exact fixed Candidate B script/version and complete argv shape.
2. Reuse `approveReviewedRequest` and `approvalDetailsView` to display the derived replacement preview, exact paths/scopes, request digest, and expandable raw execution parameters.
3. Render visible escapes for control/bidi characters. If the preview is malformed or over budget, display `PREVIEW_INCOMPLETE` and disable Run once for that review-required request.
4. Add tests for request mutation, exact parameter projection, oversize/incomplete handling, denial, and the signed display path.

Affected protected file expected: `khaos/macos/TrustedWorkspaceLauncherMain.swift`; a new `khaos/macos/` Swift source would also be protected. No Kernel/ABI/IPC change is proposed. The implementation requires a fresh declaration and manifest review plus independent security review before it is started. This PR contains only a report-local prototype.
