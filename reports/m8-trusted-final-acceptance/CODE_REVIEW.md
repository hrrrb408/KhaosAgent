# M8.5.2A.6 Trusted Code Review

## Scope

- PR #39 base: `12c75d75c1464aabd631b092e07903631f692ff6`
- Reviewed PR #39 head: `3dfa14b5daf94b2f58926398506e0aba693c631f`
- Reviewed paths: the trusted Launcher preview/cancellation implementation, its signed product builder path, the XPC command client, the task record and the focused probes/tests. The incremental fix in this acceptance adds only Candidate B string canonicalization in `TrustedEditApproval.swift`.

## Findings and disposition

1. **Python/Swift Candidate B string encoding mismatch — fixed.** Python `json.dumps(..., ensure_ascii=True, separators=(",", ":"))` emits ASCII `\\uXXXX` escapes and UTF-16 surrogate pairs. The old parser re-serialized through Foundation, which emitted raw Unicode. That rejected valid Python-produced Chinese/emoji requests and accepted a noncanonical raw-Unicode spelling. The trusted parser now requires Python's exact canonical JSON string form. It does not loosen script identity, argument count/size, path validation, exact read/write scope, Runner source digest, or invocation digest checks.
2. **Preview/request binding — preserved by inspection.** The Launcher encodes the workspace invocation once, hashes those bytes for the approval view, stores the same `Data` in `frozenRequest`, and submits that exact data after approval. The complete view includes argv, decoded old/new text, scopes, Runner source digest, Request ID, and invocation digest. A real signed UI check is pending operator interaction.
3. **Cancellation binding — preserved by inspection.** The command handle owns the authenticated workspace XPC connection and binds Task ID, workspace session ID, Request ID, and connection identity. Cancellation uses that handle and connection. A cancellation acknowledgement does not replace the original Kernel result; no automatic retry is added.
4. **Terminal reporting — preserved by inspection.** The Launcher records approval, cancellation, Kernel result, Runner execution state, changeset counts, and commit outcome. In particular, an accepted cancellation can still be reported alongside a successful committed result; this does not imply rollback.

## Review limits and residuals

- Static review and headless probes do not prove the signed UI's visual, keyboard, scrolling, or cancellation timing behavior. B32 and B34 require deterministic stage synchronization before they can be treated as signed acceptance.
- `isCandidateBLike` deliberately errs toward an incomplete trusted preview for Python `-c exec(...)` requests. That can reject an ordinary command using this shape; it does not grant execution or bypass review. No classification change was made because weakening malformed Candidate B detection would require a separate adversarial case set.
- Structured Edit remains `NOT_STARTED`; this change defines the canonical input format for a future Host producer. It does not establish real-model coding reliability.
- Project Owner Review is still `PENDING`. This code review is not owner approval. Independent Code Owner review remains `NOT_PERFORMED` in single-maintainer mode.

## Change accounting

The acceptance fix changes the existing trusted Launcher preview source by +32/-5 lines (net +27) and changes no Kernel code. It adds no capability, ABI field, scope authority, IPC operation, trusted process, or persistent product state. The signed interactive evidence and final Security Freeze result are recorded in the companion reports after those checks run.
