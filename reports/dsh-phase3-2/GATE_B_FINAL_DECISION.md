# Phase 3.2.2 Gate B — Final Decision

## Decision

**Phase 3.2.2 Gate B: BLOCKED.** The required real-model experiment is `NOT_RUN`: the inspected signed app failed deep strict trust verification (`CSSMERR_TP_NOT_TRUSTED`), and no valid signing identity was available in the current user keychain search list. The local shell toolchain also does not match the frozen Node and pnpm versions. No signing or trust bypass was attempted.

## Required result format

```text
Phase 3.2.2 Gate B: BLOCKED
Gate B: NOT_RUN
Real Model Invocations: 0
Task A Trials Started: 0 / 2
Task A Trials Completed: 0 / 2
Task A End-to-End Success: 0 / 2
Independent Public Tests: NOT_RUN / NOT_RUN
Independent Hidden Tests: NOT_RUN / NOT_RUN
AgentLoop Terminal: NOT_RUN / NOT_RUN
No-Progress Recovery: NOT_RUN
Kernel → DSH Correlation: NOT_RUN
Unresolved Kernel Results: 0 (no operations submitted)
Workspace Identity: NOT_RUN
Unexpected Workspace Mutations: 0 observed
Unauthorized Approvals: 0
Model SHA: fadc3e5f8d42bf7e894a785b05082e47daee4df26680389817e2093056f088ad
Signed App SHA: e467021676ede58181d9c151d51102039df352adb60ff8da71a9198805f6044b (Candidate CDHash; trust failed; not accepted for execution)
Task Wall Time: 0 seconds (no trial started)
Model Calls: 0 / 0
Peak Memory: NOT_MEASURED
Disk Growth: 0 net free-space change measured; 0 model/app/trial-scratch copy bytes; one-build preflight passed
Artifact Retention: PARTIAL (owner-only preflight retained; no trial artifacts created)
Historical Deletions: 0
Canonical Tests: PASS (457 tests in 855.134 seconds; host-level run)
Security Freeze: PASS (default inventory and exact PR #47 base)
Exact-Head GitHub CI: PENDING when this report commit was created; current head status is tracked on PR checks
Gate C Readiness: BLOCKED
Production Harness Migration: NOT_AUTHORIZED
New Draft PR: https://github.com/hrrrb408/KhaosAgent/pull/49
```

The model hash and size, llama.cpp runtime hash, license hash, DSH commit, and active freeze digest match the frozen records. Disk preflight permits one build, but no build or inference started because the signature trust gate failed first. The global Node and pnpm versions differ from the frozen pins; the exact archived Node binary and archive were not revalidated.

The canonical suite's initial sandboxed invocation was blocked by host-operation `EPERM` errors. The same canonical command then passed all 457 tests under host-level macOS access; test opt-ins remained unset. Security Freeze passed both default inventory and the exact PR #47 base. The user keychain search-list hash was unchanged after tests, and the valid code-signing identity count remained zero.

The existing requested branch name is already used by open Draft PR #48 at head `dddc84a8d994a15771ff8bd2d2aeeeb839be1762`. That branch and PR were left untouched. This attempt uses a distinct sibling branch from exact PR #47 head `e27aed3ee3f40e7a008517ab7d8242bebe25a7c2`.

## Change and authority accounting

- Production code delta: `0`.
- Trusted code / Kernel authority / ABI / workspace-scope authority delta: `0`.
- Production dependencies and runtime changes: `0`.
- Trial workspaces, model inference calls, approvals, and Runner operations: `0`.
- Historical artifact deletions: `0`.
- Production Harness migration: `NOT_AUTHORIZED`.
- Gate C: `BLOCKED`; it was not run.

This decision is limited to preflight. It makes no claim about Task A coding correctness, live scope enforcement, AgentLoop completion, Kernel result delivery, or Gate C readiness.
