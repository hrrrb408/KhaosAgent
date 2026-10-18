# Trusted Candidate B Preview Acceptance

## Implementation

The Launcher parses the actual `WorkspaceRunRequest.runnerSource` generated from
the untrusted proposal. It verifies the canonical outer Runner wrapper, complete
eight-item argv, `python3 -I -B -c`, exact fixed script identity, separate
canonical JSON strings, relative target path, exact one-file read/write scopes,
and all byte/depth limits. The path and replacement are escaped for review; bidi,
format, zero-width, control, line-separator and paragraph-separator scalars are
rendered visibly. The preview marks trailing LF explicitly and never claims to be a
full-file diff.

The short view shows the workspace, target, “Proposed Replacement,” exact scopes,
the fact that current workspace text was not read, and the request SHA-256. The
scrollable detail view shows the executable, all argv values, fixed-script/source
hashes, request ID, decoded old/new text, scopes, workspace path, and digest. The
complete frozen invocation digest is computed before approval; the same invocation
bytes are submitted afterward.

## Automated evidence

`test_trusted_candidate_b_preview_parser_is_bound_and_fails_closed` passed. Its
Swift probe checks the accepted fixed request; malformed and mutated wrappers;
wrong argv count, script, executable, flags, path, and scope; invalid parameter
JSON; maximum and over-limit path lengths; oversized argv and outer wrapper;
multiline, Unicode, CRLF, control, bidi and zero-width text; empty `newText`; and
the SHA-256 of a real encoded `WorkspaceRunRequest` invocation. An ordinary command
continues to classify as an ordinary request.

The focused test does not click the signed Launcher's Run once, Cancel, or details
buttons. The signed UI proof for complex approval content and refusal remains
`NOT_PROVEN` pending a separately approved signed-product acceptance.

## Scope of claim

This protects the fixed Candidate B eight-argument replacement shape. It does not
make every possible shell command that changes a file use this preview, and it does
not implement the model-facing structured Edit action. No current workspace read,
diff fetch, or new read permission is introduced by preview rendering.
