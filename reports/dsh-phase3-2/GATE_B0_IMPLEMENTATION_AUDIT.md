# Gate B.0 Implementation Audit

**Date:** 2026-10-25

**Implementation:** Experimental signed DSH acceptance path only.

## Change summary

The experimental builder now produces a generic signed app with no trial or workspace identity in its receipt. At runtime, the experimental Trusted Launcher binds a fresh trial to the actual user-selected security-scoped workspace session. It records the canonical workspace digest, device/inode, and marker identity, and checks them around approval and Kernel result handling. The owner-only manifest and marker are correlation evidence; neither grants access. The existing Kernel still receives the bookmark, exact scopes, request ID, and approval-bound invocation.

The runner reuses a prebuilt app only after deep/strict signature and signer checks, current source and builder receipt checks, pinned DSH/no-model checks, and generic runtime-binding receipt validation. The bundle is checked before and after each trial and is not modified. New Trial, Task, Workspace Session, and request identifiers plus result-digest joins keep evidence separate. Cancellation and failed identity checks invalidate the experimental binding.

The signed trials exposed a terminal-result evidence defect. The correction now computes the SHA-256 of the exact UTF-8 `AgentToolOutcome.text` in the Trusted Launcher, includes it in bounded trace metadata, checks it against the received text at the experimental Host boundary, and writes a trusted parent-process terminal event only after an AgentHost reply arrives. The runner joins that raw-text digest to DSH terminal and tool-result events. The prior evaluator compared the JSON-content `result_sha256` to the raw-text `launcher_result_sha256`; the corrected evaluator compares like-for-like raw-text digests.

## Security boundary

Production Kernel source, ABI, workspace scopes, production trusted runtime, dependencies, production processes, IPC operations, and persistent state are unchanged. Runtime binding supplements the existing Picker/bookmark flow and Kernel approval/scope enforcement. DSH cannot select or authorize a directory. The signed evidence failures are retained, and the new terminal-result trace behavior has not been exercised in a signed app.

## Required change accounting

```text
Production code delta: 0
Trusted code delta: 0 in production; experimental signed Launcher overlay behavior changed
New architecture concepts: 0 production; existing experimental per-trial workspace binding and result correlation strengthened
New trusted processes: 0
New IPC operations: 0
New persistent state: none in production; existing bounded owner-only disposable trial marker/manifest only
New dependencies: 0
Removed duplication / abstractions: none; reused KernelWorkspaceXPC.sha256Hex for result correlation
```

The result hash and terminal event are non-authoritative evidence fields. They cannot change the Kernel's scope, approval, execution, or result.

## Verification

- Focused builder tests: 9 passed.
- Focused runner/evidence tests: 14 passed.
- Pinned DSH semantic-tool tests: 19 passed.
- Pinned DSH model bridge/lifecycle tests: 17 passed.
- Generated Launcher overlay and experimental Host Swift syntax parsing passed.
- Canonical suite: 464 passed in 843.146 seconds (`python3 -m unittest discover -s tests -v`).
- Default Security Freeze passed with `sensitive changes=0`.
- Exact PR #47 base Security Freeze passed with `sensitive changes=5`.
- Final-head PR CI: pending push of this revision.
- Independent security review of the experimental Launcher behavior remains pending and is not established by tests or CI.

## Signed trial record

One signed app at source SHA `a387aeee94a3da224ddc2f809a6a6e01b7520023` was reused unchanged for Trial A `stage-a-8` and Trial B `stage-a-9`. Trial A completed the five expected operations, passed the two public tests and three independent hidden checks, and changed only the intended `fee.py`; its evidence verdict was still `FAIL` because request results could not be joined to a trusted parent terminal digest. Trial B received a nonzero Runner result and disclosed no canary or changed the workspace, but its exact cross-workspace refusal correlation was false and its AgentLoop ended incomplete at the one-operation budget. Both signed results remain failed evidence; the instrumentation correction above was made afterward and is not signed-tested.
