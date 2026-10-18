# Trusted edit preview security audit

## Existing renderer and limits

The A3 report-local `CandidateBPreview.swift` renders a proposed replacement block, escapes control/bidi/zero-width characters and returns `PREVIEW_INCOMPLETE` on its byte limit. This is useful renderer code and is reused by the nontrusted harness under `prototype/`.

The renderer accepts three `String` values. It does not parse an XPC request, identify the fixed Runner wrapper, validate Candidate B argv or scopes, compute the Kernel invocation digest, or control the trusted approval button. Its tests establish renderer behavior only. The signed Launcher still displays raw argv and the request digest without a Candidate B preview.

## Required trusted derivation

For the current test-only shell fixture, a future reviewed Launcher implementation must start from the actual immutable `WorkspaceRunRequest` and request ID that it will submit. It must:

1. Check `runnerSourceSHA256`, and recognize the exact `agentRunnerSource(argv:)` wrapper rather than searching for a marker substring.
2. Decode the wrapper's argv as a bounded, canonical string array and verify it re-encodes to the exact source bytes.
3. Verify the test-only executable, `-I -B`, `-c`, fixed edit script identity, exact argument count and canonical JSON payload with exactly `type`, `path`, `oldText`, `newText`.
4. Reject duplicate/unknown fields and malformed JSON. Do not normalize a path into a different authorization name; require the exact read and write scope to each be `[path]`.
5. Enforce the existing argument limits and total rendered preview limit without truncation. Permit empty `newText`; require nonempty `oldText` for unique-match replacement.
6. Render the decoded values and preserve the exact `requestID`, bookmark, `WorkspaceRunRequest` and invocation digest through the user's decision and Kernel submission.

The Launcher must not open/read workspace content to enrich the preview. It must label the view as a proposed replacement, not a full-file Diff or commit promise. The Runner continues to match the old text in the private snapshot; Kernel continues to validate and commit the complete changeset.

## Approval surface

The primary view should show file, replacement, exact read/write scopes and the existing request digest. A scrollable expanded view should expose the actual executable, complete argv, fixed script identity, decoded old/new values and digest. Visible escaping must apply to both preview and raw-detail rendering. Oversize details must be rejected before approval rather than hidden.

The Cancel/Run once controls must remain separate. Run once must not be the default keyboard action; Escape and window close must deny. An incomplete required preview must leave Run once unavailable while preserving enough bounded raw details to explain the rejection.

## Offline nontrusted coverage

`prototype/ApprovalCancelHarness.swift` models a test-only fixed request, validates a canonical wrapper/argv/payload and uses the existing renderer. Its standalone tests cover request digest mutation, exact scope, fixed script, exact JSON fields, duplicate fields, traversal, empty replacement, multiline/Unicode, control/bidi/zero-width escaping, incomplete overflow and complete details. It performs no workspace/file/process/XPC operation.

This model uses a synthetic request digest and test-only script identity. It is **not** the production `WorkspaceRunRequest` parser and does not prove digest binding, UI completeness, fail-closed approval, signed reviewability or B38. The Swift source is outside the app build and the Security Freeze inventory.
