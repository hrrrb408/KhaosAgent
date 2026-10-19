# M8.5.2A.5 Implementation Audit

## Baseline

- Repository: `hrrrb408/KhaosAgent`
- Development branch: `feature/m8-5-2a5-trusted-ui-cancel-implementation`
- Parent PR #38: OPEN, Draft, exact head `12c75d75c1464aabd631b092e07903631f692ff6`
- PR #38 base PR #37 head: `02b8277c8c8b96d8679a1d064e23595d87dab657`
- Independent worktree: `/Users/huangruibang/.codex/worktrees/m8-5-2a5-trusted-ui-cancel/self-evolving-khaos`

## Candidate B execution contract

The production preview recognizes the fixed eight-argument request already used by
the deterministic signed Runner fixture:

```text
argv[0] python3
argv[1] -I
argv[2] -B
argv[3] -c
argv[4] exec(<canonical JSON string containing the fixed script>)
argv[5] workspace-relative target path
argv[6] canonical JSON string for oldText
argv[7] canonical JSON string for newText
```

The outer Runner source encodes the complete argv array as canonical JSON and
Base64, then passes it to the existing `process_exec` and `workspace_commit` SDK
facade. The fixed edit script SHA-256 is
`844abf29679477569fe00efa10ecb7cd314cea94fe8c4b2e2e1a95b381d55d79`. The Runner
source is separately SHA-256 checked against the actual request.

Each argv value is bounded to 4096 UTF-8 bytes. The Runner source is bounded to
10,240 bytes. The existing AgentHost protocol limits each scope path to 128 UTF-8
bytes; the preview reuses that named bound. The Kernel's generic scope validator
allows more bytes (up to 4095 for one path, accounting for its terminator) and at
most 64 components, but the Candidate B Launcher path does not widen the stricter
AgentHost bound. Read and write scope must each equal exactly `[path]`. The old
text must be nonempty; the new text may be empty. The fixed
script rejects non-regular targets, absent or repeated matches, and no-op
replacements before it stages a same-directory temporary and atomically replaces
the target.

The six-argument report-local prototype is not used as the production contract.
Ordinary command proposals that do not match Candidate B retain the existing
command approval path. This is a fixed-script preview, not a general policy that
all shell-shaped file edits must use a semantic edit preview; production structured
Edit is still `NOT_STARTED`. `AgentHostProtocol` now names its existing 128-byte
scope-path limit so the preview can reuse it; the wire protocol and accepted path
bound are unchanged.

## Production implementation

- `TrustedEditApproval.swift` validates the exact wrapped request, fixed script,
  canonical JSON parameters, path and scopes; renders proposed replacement text
  without reading the current workspace; and presents a scrollable complete detail
  view. Candidate-like malformed or oversized requests fail closed as
  `PREVIEW_INCOMPLETE`.
- `TrustedWorkspaceLauncherMain.swift` binds the preview to SHA-256 of the exact
  frozen `encodeInvocation` bytes, displays the approval before submission, then
  submits those same bytes without regeneration. It presents an active task panel
  before authenticated Kernel and Snapshot Broker setup, and records Task ID,
  Request ID, workspace session, connection token, invocation digest, scopes,
  approval, cancellation result, Runner result, changeset, and commit outcome.
- `KernelWorkspaceCommandHandle` retains the original authenticated XPC connection,
  request ID, and frozen invocation. It supports cancellation before submission,
  sends in-flight cancellation over that same connection, and waits for the original
  `workspace.run` result. `cancel_accepted` is not treated as the final result.
- `AgentTaskProgress.swift` keeps the Launcher responsive. Host cancellation
  invalidates that task's Host connection; ordinary turns reuse the same Host
  session, while cancelled or failed turns reset it so late replies cannot reactivate
  the ended task.
- `TrustedAgentRunnerSource` is the single source for the outer Runner wrapper; the
  previous duplicate wrapper builder was removed.

## Change accounting

Final counts and verification results are recorded in `COMPLETION_AUDIT.md` after
the full regression and Security Freeze runs.
