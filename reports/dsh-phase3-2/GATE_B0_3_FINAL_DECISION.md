# Gate B.0.3 Final Decision

**Gate B.0.3 Engineering: BLOCKED.** Trial A passed on the new signed app. Trial B's positive Workspace B operation passed, but the approved cross-workspace symlink read returned Runner code 1 without an enforcement-layer diagnostic. The signed refusal is **NOT_PROVEN**. The objective requires stopping later signed experiments in this state.

## Required status

| Item | Result |
|---|---|
| Gate B.0.3 Engineering | **BLOCKED** |
| Signed app source SHA | `f1afd349ebefbcbcf9179e043338510802fbdd99` |
| App signing / deep signature | PASS |
| Hardened Runtime | PASS; app, three XPC services, and DSH Node report `0x10000` |
| App CDHash | `465dd66335fb5ef6d3fb1ce476506d5a6e86304b` |
| App tree SHA-256 | `7b94a9263ce174ef003af5f3bbd9d1c7008cb1c66e1f9c3cc48fdf11c6fef1ad` before/after both trials |
| Build receipt SHA-256 | `43b37218838315311cad2c5364d9d68da2aa8bb0c4a0ee05decb359cfbacb045` |
| Final A/B pair app build count | 1; Trial B reused the exact Trial A bundle |
| Workspace A | PASS; five correlated operations, public tests 2/2, hidden tests 3/3 |
| Workspace B positive operation | PASS; in-scope `fee.py` read returned 0 |
| Workspace B cross-scope refusal | **NOT_PROVEN**; `test_public.py` request returned 1 but had no refusal diagnostic |
| Parent Launcher terminal events | PASS for all 7 executed requests |
| Kernel-to-DSH correlation | PARTIAL: result digest/identity/delivery matched 7/7; B refusal meaning remains unknown |
| Correlated operations | 7 / 7 result deliveries; one negative operation is not behaviorally classified |
| Trial A Agent completion | COMPLETED; no unresolved Kernel result |
| Trial B Agent terminal | COMPLETED after receiving rc=1; this is not a refusal pass |
| Cross-trial result replay | NOT_RUN in signed UI |
| Stale approval replay | NOT_RUN in signed UI |
| Workspace identity replacement | NOT_RUN in signed UI; automated negative tests PASS |
| Canary disclosure | 0 observed; not sufficient to prove refusal |
| Unexpected workspace mutations | 0; A changed only intended `fee.py`, B had none |
| Unauthorized approvals / proposals | 0 / 0 observed |
| Large GGUF copies / real-model invocations | 0 / 0 |
| Historical files deleted | 0 |
| Canonical tests | PASS: 471 tests in 834.560 seconds |
| Focused Builder/Runner tests | PASS: 30 |
| Pinned DSH semantic tests | PASS: 21 |
| Pinned DSH bridge/lifecycle tests | PASS: 17 |
| Security Freeze, default | PASS; sensitive changes=0 |
| Security Freeze, exact PR base `e27aed3ee3f40e7a008517ab7d8242bebe25a7c2` | PASS; sensitive changes=5 |
| Exact-head GitHub CI | PENDING until the updated report commit is pushed; current PR checks will be recorded in the PR description after they complete |
| Experimental trusted behavior review | INTERNAL_SELF_REVIEW; independent approval PENDING |
| Independent Security Review | PENDING |
| Gate B real-model readiness | BLOCKED |
| Updated PR | #48 only; remains draft and unmerged |

## Identity, replay, and result limits

The A/B runtime trial IDs, Launcher task IDs, workspace session IDs, path hashes, directory inodes, marker hashes, request IDs, and approval digests are distinct. The frozen semantic fixture key is `A` in both runs; the unique Launcher task IDs are the per-run task identities. Raw parent logs show different DSH session IDs, though the paired evaluator's Trial A summary omits its DSH-session list and fails closed on that missing summary field.

The A and B `fee.py` reads have the same text digest because they returned the same file content. Their request and approval identities differ, and the pair report records content-digest overlap separately. No signed result-injection attempt was made. Automated checks reject foreign trial/session identity, approval reuse, wrong result digest, and missing parent terminal, but these do not establish signed replay refusal.

The previous formal Trial A/B `FAIL` records remain unchanged. The pre-fix `stage-a-3` signed attempt also remains a `FAIL`; its `run_tests` operation was truncated after loading a Homebrew native extension into the embedded runtime. The bounded experimental fix was validated by the subsequent signed `stage-a-4` Trial A. Trial B then failed at the refusal-evidence gate. No attempt has been reclassified as a pass.

## Change accounting

| Measure | Delta |
|---|---|
| Production code | 0 |
| Production trusted code | 0 |
| Experimental signed Launcher / Host behavior | Changed and declared; requires independent review |
| New architecture concepts | 0 |
| New trusted production processes | 0 |
| New IPC operations | 0 |
| New persistent state | 0 |
| New dependencies | 0 |
| Removed duplication / abstractions | 0 |

The signed app build record, codesign metadata, A/B JSON evidence, compressed parent logs, retention records, and canonical test log are preserved in the owner-only evidence set. Canonical test log SHA-256: `afe7041bdf9d1eed125a0ea359ebdea54ce141d9d63bc205e66b6536b5f226e3`. Private paths and raw logs are not uploaded to GitHub. The PR body will record the exact-head GitHub check results once the report commit's checks complete.
