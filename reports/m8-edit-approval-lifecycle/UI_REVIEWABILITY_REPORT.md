# Approval UI reviewability report

## Observed

`approveReviewedRequest` builds its approval details from the actual `WorkspaceRunRequest`: raw argv, read scope, write scope, and invocation SHA-256. `approvalDetailsView` installs a vertically resizable `NSTextView` inside an `NSScrollView`; source does not impose a content-length truncation. Cancel and Run once are explicit buttons.

## Not established

The request is displayed as shell argv. Candidate B's nested JSON strings are not decoded into a readable change preview. No signed UI run observed multiline, Unicode, escaped, bidi/control, near-limit, or oversized parameters; no test observed scrolling to the final byte, focus/key behavior, or whether the Diff and request digest remained understandable together. There is no `PREVIEW_INCOMPLETE` state and no rule disabling approval when a required review cannot complete.

Do not claim the current UI truncates the argv. The gap is that a scrollable raw command is not evidence that the proposed code change can be understood. The report-local prototype does not close the signed UI gap.

## Status

Existing UI Sufficient: **NO** for a clear Candidate B Diff review.

Complex Approval Reviewability: **NOT_PROVEN**.
