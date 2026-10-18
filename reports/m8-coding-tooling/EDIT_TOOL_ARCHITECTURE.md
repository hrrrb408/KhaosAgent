# Candidate edit architecture

## Decision

Recommend B, a single-file structured edit intent, for a later implementation experiment. This is a design recommendation, not a production feature. It removes the model's need to author a Python edit script and lets a deterministic adapter reject repeated or absent targets. It does not explain the M8.4 coding failures.

Recommended model-facing shape:

- type: edit
- path: one observed, existing workspace-relative file
- oldText: non-empty exact UTF-8 text
- newText: UTF-8 replacement text

The Host accepts exactly those fields for an edit action. It rejects missing, extra, oversized or invalid fields; it does not infer a path, widen scope, create or delete files, or bundle multiple files.

## Lowering through the existing execution path

AgentHost treats the model action and all content as untrusted. It does not write a file. A deterministic Host adapter converts the request into an existing shell proposal:

argv = [python3, -I, -B, -c, fixed_edit_script, path, json(oldText), json(newText)]
readScope = [path]
writeScope = [path]

The local constrained action grammar currently permits eight argv entries; this exact proposal uses eight. Raw source fragments commonly contain newlines, while the existing Runner proposal accepts only printable single-line argv values. The Host must JSON-encode oldText and newText as separate argv strings, and the fixed script must decode them with `json.loads`. This keeps model text out of generated Python source and reconstructs multiline text without shell quoting. The path remains a separate argv value and scope entry.

After encoding, every argv value must remain within the existing 4 KiB argument bound; the path must remain within the existing 128-byte scope-path bound. Reject an over-budget value before submitting a proposal. The 4 KiB limit is on the encoded argv item, not a 4 KiB allowance for each source fragment; JSON escaping can expand text. The new model-facing action grammar must also bound its fields so the decoded request and lowered AgentHostProtocol frame remain within existing limits. Derive that field cap from the actual serialized representation and reject before Launcher submission. No call, timeout, result, context, or IPC budget is raised.

The fixed script reads bytes, requires strict UTF-8, counts exact oldText occurrences, and refuses unless the count is exactly one. It computes the full new byte sequence before writing. To avoid a direct in-place truncation on failure, the production candidate must stage a same-directory temporary and atomically replace the target, then clean up any unused temporary. That write strategy is a feasibility gate, not a proven property: a real signed Runner test must establish how Seatbelt, the private snapshot, and changeset collection handle the temporary and a failure before or after replacement. If this cannot be proven without trusted changes, defer B or request a separate trusted design review.

The existing Launcher reviews each proposal independently. It already displays argv, read paths and committable paths, then requires a one-time decision. A B proposal would therefore display the fixed script, its path, and JSON-escaped old/new text arguments, with one exact read path and one exact write path. The current UI does not show a semantic source diff; escaped multiline arguments may be difficult to review and must be tested. The Launcher then emits the current workspace.run request. The Kernel retains the selected scopes, executes the Runner under its existing sandbox, validates the complete changeset, and rejects out-of-scope changes before live mutation.

## Failure behavior

The edit adapter may return plain, bounded Runner output such as TARGET_NOT_FOUND, NO_MATCH, AMBIGUOUS_MATCH, INVALID_ENCODING or NO_CHANGE. These are untrusted command results, not new Kernel error codes. It must not retry, search elsewhere, create a missing file, broaden scope, or mark completion.

APPROVAL_DENIED, SANDBOX_REJECTED, OUT_OF_SCOPE and EXECUTION_FAILED describe outcomes of existing layers. Do not add trusted ABI error cases for the edit feature.

Exact oldText is a local precondition. If the target text changed, return NO_MATCH. If unrelated portions of the file changed while that exact oldText remains unique, B cannot detect that with this four-field shape. The current read result does not provide a trusted snapshot token to the model. A whole-file digest would add a new field and a digest-provenance design; do not add one casually. Keep this limitation explicit in any implementation.

## Architecture delta if approved later

Likely untrusted Host changes:
- AgentHost.swift: add the edit instruction, constrained action grammar and fixed translation.
- AgentHostActionOutput.swift: validate the new exact shape and lower it into the existing AgentShellProposal.
- Host action-output probe/tests: prove malformed and over-budget edit intents fail before Launcher submission, and that the generated argv and scopes are deterministic.

No new Kernel operation or ABI field is required if the Host produces the existing shell proposal. TrustedWorkspaceLauncherMain remains unchanged and continues to review argv and exact scopes. AgentHostProtocol remains unchanged and continues to carry only the existing shell/list request forms. Kernel, Seatbelt, XPC identity, Snapshot Broker and changeset enforcement remain unchanged. Estimated first implementation is roughly 80–140 production Host lines plus focused Host tests; this estimate must be replaced by an actual diff and duplicate-logic review before implementation.

M8.5.1 itself changes none of these production files. Current statuses are Runtime TCB Delta 0, Kernel ABI Delta 0, Trusted Launcher Delta 0 and Production Implementation NOT_STARTED.
