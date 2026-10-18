# Approval request binding

## Existing binding

In `TrustedWorkspaceLauncherMain.runAgentTool`, Launcher builds the `WorkspaceRunRequest`, creates one `requestID`, then calls `KernelWorkspaceXPC.encodeInvocation(request:requestID:bookmark:)`. The SHA-256 of those encoded bytes is displayed in `approveReviewedRequest`. After the user selects Run once, the same `requestID`, request object, and selected workspace bookmark are passed through `runInKernel` to `KernelWorkspaceXPC.submit`.

This is source-level evidence that the displayed digest and executed request use the same constructed request. The prior B38 and A2-REPLAY-01 reports record one short signed observation; they do not prove complex payload display, correctness of a decoded Diff, or a cancellation race.

## Missing binding

There is no production `EditIntent` or Candidate B parser in Launcher. Therefore the new report-local prototype's output is not bound to the signed invocation digest. A Host-generated Diff must never be added as trusted approval content without trusted-side validation. The next trusted design must parse a narrowly versioned fixed script and its complete JSON argv from the actual `WorkspaceRunRequest`, produce the preview from those parsed values, and continue displaying the digest and all raw parameters. Any shape mismatch must fall back to ordinary shell review or fail closed for a review-required Edit.

## Verdict

Current request-to-execution digest binding: PASS for the existing shell path at source level and the historical short signed case.

Candidate B preview-to-request binding: NOT_PROVEN. The prototype does not claim it.
