# M8.5.2A.6 Trusted Code Review

## Scope and evidence boundary

- PR: [#39](https://github.com/hrrrb408/KhaosAgent/pull/39), Draft, branch `feature/m8-5-2a5-trusted-ui-cancel-implementation`.
- PR base: `12c75d75c1464aabd631b092e07903631f692ff6`.
- Reviewed source head: `e43c00912fb2129718e99fef8c16b7cb1a8d4025`.
- The signed Candidate B review attempt is separately tracked in `SIGNED_UI_ACCEPTANCE.md`; the user denied it after reviewing the full details. The agent made neither approval nor cancellation decisions.
- Reviewed production paths: `TrustedEditApproval.swift`, `TrustedWorkspaceLauncherMain.swift`, `KernelWorkspaceClient.swift`, `KernelWorkspaceXPC.swift`, `AgentTaskProgress.swift`, `AgentHostClient.swift`, and `AgentHostProtocol.swift`, plus the matching probes and tests.

## Findings and disposition

1. **Python/Swift Candidate B string encoding mismatch — fixed.** Python `json.dumps(..., ensure_ascii=True, separators=(",", ":"))` emits ASCII `\\uXXXX` escapes and UTF-16 surrogate pairs. The previous Foundation round-trip emitted raw Unicode, rejecting valid Python-produced Chinese/emoji requests while accepting an equivalent noncanonical spelling. `TrustedEditApproval.swift` now checks Python's exact canonical string encoding and decodes it without relaxing script identity, eight-argument shape, argument bounds, path validation, exact scopes, Runner source digest, or invocation digest binding.
2. **Preview/request binding — preserved by inspection and signed details view.** The Launcher constructs the workspace request once, hashes the frozen request bytes for the approval view, retains the same `Data`, and submits those bytes after approval. The signed details view exposes the actual argv, decoded old/new text, exact scopes, Runner source digest, Request ID, and invocation digest. The signed refusal Task Record's `invocation_sha256` matches the reviewed digest. The request was not submitted, so this does not establish an approved execution.
3. **Cancellation binding — preserved by inspection and headless probes.** The command handle owns the authenticated workspace XPC connection and binds Task ID, workspace session ID, Request ID, and connection identity. Cancellation uses that original handle and connection. An acknowledgement does not replace the Kernel's final reply, and the Launcher does not automatically retry.
4. **Terminal reporting — preserved by inspection and Kernel probes.** The Launcher records approval, cancellation, Kernel result, Runner execution state, changeset counts, and commit outcome separately. A nonzero Runner exit does not imply an unchanged workspace; an accepted late cancellation does not rewrite a successful committed result.
5. **Candidate B recognition — fail-closed tradeoff retained.** `isCandidateBLike` conservatively refuses to fall back to ordinary shell preview for ambiguous `python -I -B -c exec(...)` shapes. That may reject unrelated commands with this shape, but does not authorize execution. No classifier broadening was made without a separate adversarial case set.

## Review limits

- Signed B32/B34/B39 cancellation-to-Task-Record behavior is not proven. The existing signed acceptance flow has no deterministic stage barrier for the post-approval/pre-submit point or commit cutoff; headless tests are not signed product evidence. See `CANCELLATION_ACCEPTANCE.md`.
- B37 remains limited to the historical exact short approved request. The complex Candidate B details screen tests reviewability and refusal, not successful execution binding.
- Production Structured Edit remains `NOT_STARTED`. This fix defines a compatible input string representation; it does not add a production Host producer or show that a real model can generate reliable edits.
- This review is engineering review, not owner approval. Owner Review is `PENDING`; Independent Code Owner Review is `NOT_PERFORMED — SINGLE_MAINTAINER_MODE`.

## Change accounting

| Item | Delta |
|---|---:|
| Candidate B canonicalizer in the existing trusted Launcher, relative to the original PR #39 head `3dfa14b5daf94b2f58926398506e0aba693c631f` | +32 / -5 lines |
| PR #39 runtime-TCB manifest files, relative to PR base `12c75d75c1464aabd631b092e07903631f692ff6` | +2116 / -182 lines; net +1934 |
| Kernel Authority / Kernel ABI / Workspace Scope Authority | 0 / 0 / 0 |
| New architecture concepts / trusted processes / IPC operations / persistent state / dependencies | 0 / 0 / 0 / 0 / 0 |
| Test-only probe and harness refactor | Probe +89/-44 lines; Python harness +40/-4 lines; one Python-compatible encoding/staged-edit fixture replaces duplicated logic |

No Kernel, sandbox, changeset-validation, capability, or scope-enforcement production code changed in this acceptance.

```text
Production code delta: +32 / -5 lines in TrustedEditApproval.swift relative to original PR #39 head
Trusted code delta: +32 / -5 incremental; PR cumulative runtime TCB +2116 / -182 relative to PR base
New architecture concepts: 0
New trusted processes: 0
New IPC operations: 0
New persistent state: 0
New dependencies: 0
Removed duplication / abstractions: one duplicated staged-edit script/encoding fixture consolidated into shared test-only helpers
```
