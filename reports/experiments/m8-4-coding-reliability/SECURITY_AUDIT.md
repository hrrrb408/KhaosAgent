# M8.4 security audit

Runtime TCB delta: **0**. No Launcher, Kernel, ABI, Seatbelt, XPC identity, workspace scope, snapshot, changeset, admission, activation or rollback source changed. final-integrity.json compares all 34 runtime TCB manifest entries against exact PR base f5631de1b5ebb056af28bbd145757b6f76053154 and verifies their current source hashes. Only two untrusted Host source files differ under khaos.

The Host adds opt-in fixed response/normalization/acceptance events. They contain event and initial/correction labels, not argv, paths, model text or workspace data. Normalization remains followed by full type/semantic/wire validation; accepted events occur only after that validation. The existing external observer filters payload fields, bounds events to 128 and exposes overflow as incomplete capture. The builder configures the existing Host-only diagnostic environment before signing, default off. Signed originals were not modified afterward. No runtime trusted code was needed; experiment observation belongs outside authority enforcement.

Both A/C signed products passed deep strict verification, builder verification, Launch Services Kernel/Broker bootstrap, actual signed Host diagnostic transport and parser probes. Trusted unsigned executables match; 3081 other packaged trusted files match byte-for-byte. Two signed executable containers differ only as separately recorded signatures/build identities; unsigned copies match. Network-client entitlement exists only on untrusted Host and is not restricted by macOS to the provider hostname. No stronger network guarantee is claimed.

Four fresh data consents and 29 distinct per-operation owner approvals were checked against exact request/review hashes. All write scopes were empty; no automatic approval, authority expansion, model test or source change occurred. Parent inspection found all four workspaces unchanged and clean. No boundary violation was observed. A/c invalid model outputs retained fail-closed validation. c-02 recovery continued the original product and resumed only an external diagnostic reader, without replay or repeated operations. Its missing Host totals and waiter status stay NOT_CAPTURED.

Frozen prompt, baseline, hidden patch, gold patch, preparer and grader remain unchanged, including the actual private dataset copies. Hidden/gold content stayed outside model workspaces. Hermes credentials were reused without being printed or archived; raw model/command/grading data remain outside Git in the owner-only experiment directory. Public evidence contains reviewed fixed metadata and hashes.

## Validation and governance

The prior canonical preflight passed 379 tests in 677.619 seconds, exit 0 (after the earlier 376-test pass). Six focused production A/C and bookkeeping tests, 32 observer tests and four builder tests passed. Deterministic tests exercise strict missing text, bounded compatibility, missing scopes, extra fields, invalid actions/types, unchanged correction limits, diagnostic on/off parity, user refusal with zero execution and actual normal Task Record capture. The existing zero-tool Launcher omission remains unknown and preserved. Synthetic evidence is excluded from model success statistics.

The final post-experiment canonical rerun passed 379 tests in 710.353 seconds, exit 0. Its log hash and current/exact-base Freeze outcomes are recorded in validation.json. The sensitive-change declaration lists nine build/test/governance paths and updates only six build/test manifest hashes; all runtime TCB entries remain intact. Final CI must pass for the exact submitted PR head; see live PR checks and delivery verification in the PR body. Independent Code Owner approval remains **NOT_PROVEN**, regardless of tests or CI. Security Acceptance: **CONDITIONAL**. No merge is authorized.

## TCB growth accounting

| Item | Delta |
| --- | --- |
| Production code delta | Untrusted Host +40/-4; external observer +42/-2; build-governance builder +13/-4 |
| Trusted code delta | 0 runtime files / 0 lines |
| New architecture concepts | 0 |
| New trusted processes | 0 |
| New IPC operations | 0 |
| New persistent state | 0 product state; bounded external experiment artifacts only |
| New dependencies | 0 |
| Removed duplication / abstractions | Reuse existing parser, diagnostics, launcher, preparer, observer and grader; no new production abstraction |
