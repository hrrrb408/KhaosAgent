# B38 — Approval Reviewability

## Synthetic offline coverage

The Swift AgentHostActionOutput probe now round-trips synthetic Candidate-B-shaped argv through encodeAction and decodeReply, and checks that argv plus read/write scopes are unchanged. Cases cover short ASCII; multiline Python text; Unicode; quotes and backslashes; JSON escapes; oldText at the current per-argument byte limit; newText at that limit; and a 32-argument frame near the existing 64 KiB frame limit. It rejects a 4097-byte argument, a 33rd argument, raw newlines in argv, bidi U+202E, and NUL. No real project text, signed Runner, or remote model is used.

The current limits are AgentHostProtocol.maximumArguments=32, maximumArgumentBytes=4096, and maximumFrameBytes=65536. A 4094-byte ASCII edit value encodes as a 4096-byte JSON string argument. The probe verifies nested JSON round-tripping for oldText/newText and preserves the exact argv and scopes delivered to the Launcher. Existing path and workspace tests cover traversal and out-of-scope denial; those generic security tests are supporting evidence, not a signed Candidate B path review.

## Launcher binding and signed evidence

TrustedWorkspaceLauncherMain displays the full argv, readable paths, committable paths, and SHA-256 of the encoded invocation. The same WorkspaceRunRequest and request ID used to construct that digest are passed to the Kernel submission after approval. This is static wiring evidence. The authorized signed replay observed the exact short ASCII argv, scopes, digest, one Run once approval, and one matching Runner execution. It did not contain long or multiline text.

No signed UI test observed complete scrolling, truncation behavior, or whether a person can accurately inspect long, multiline, Unicode, escaped, and near-limit content before deciding. No approval control was automated. No Trusted Launcher UI was changed.

## Status

Offline serialization and bounds: PASS for the synthetic cases above. Signed reviewability of the exact short operation: PASS. Complex signed content reviewability: NOT_PROVEN; APPROVAL_REVIEWABILITY_BLOCKED for production readiness. This does not establish that the current UI truncates the payload. The original L4 requirement remains unchanged.
