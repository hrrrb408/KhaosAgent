# Minimal Candidate B preview design

## Decision

Use a replacement-block preview, not a general patch engine and not a current-file diff. It renders the exact `path`, `oldText`, and `newText` extracted from the recognized fixed Candidate B request. It performs no workspace read. Label it “proposed replacement only”; the preview cannot establish that the current file still has one unique match or that a commit will succeed.

The trusted Launcher must recognize the exact fixed script and complete argv shape before it calls the view a Candidate B preview. A matching `python3` executable, a Host-supplied preview, or a marker string is insufficient. If parsing or rendering fails, show `PREVIEW_INCOMPLETE`, preserve full raw argv/scope/digest details, and disable Run once for that edit request. Do not silently truncate.

## View

Show target, exact read/write scope, request digest, and a compact line-prefixed old/new replacement block. Keep an expandable, scrollable detail view with actual executable, complete argv, scopes, and encoded parameters. Escape control and bidi formatting scalars visibly; preserve Unicode; show byte counts and line-ending facts. The digest and preview must be derived from the same immutable `WorkspaceRunRequest`/request id that will be submitted.

## Staleness and execution

Do not read the workspace to add context. The accepted Runner still performs its unique exact-match check in the Kernel snapshot; Kernel remains responsible for complete changeset validation and commit. If the snapshot differs from the parameter assumption, the Runner fails or Kernel rejects it; the preview must not promise the displayed change will be committed.

## Prototype boundary

`prototype/CandidateBPreview.swift` demonstrates a bounded replacement-block rendering rule. It is offline, report-local, and not linked into Khaos. It has no shell parser, no request digest binding, no approval surface, and no workspace access. Its PASS is only renderer behavior; it does not pass B38 or authorize production integration.
