# Gate B.0 Implementation Audit

**Date:** 2026-10-25
**Implementation:** Experimental signed DSH acceptance path only.

## Change summary

The builder now creates a generic signed app whose receipt has no trial or workspace identity. At runtime, the experimental Trusted Launcher binds a fresh trial to the actual user-selected security-scoped workspace session. It records the canonical workspace digest, device/inode, and marker identity, and checks them around approval and Kernel result handling. The external owner-only manifest and marker are correlation evidence; neither grants access. The existing Kernel still receives the bookmark, exact scopes, request ID, and approval-bound invocation.

The runner can reuse a prebuilt app only after deep/strict signature and signer checks, current source and builder receipt checks, the pinned DSH and no-model mode checks, and generic runtime-binding receipt validation. The bundle is checked before and after a trial and is not modified. Fresh Trial, Task, Workspace Session, and request identifiers plus result-digest joins prevent evidence from one task being accepted as another task's result. Cancellation and failed identity checks invalidate the experimental binding.

## Security boundary

The change does not alter the production Kernel, ABI, workspace scopes, production trusted runtime, dependency set, or production IPC. Runtime binding supplements the existing Picker/bookmark and Kernel approval/scope enforcement. DSH cannot select or authorize a directory on its own. The code-level audit and unit tests establish the experimental verifier behavior; real macOS Picker/XPC/Kernel/Runner outcomes require the separate signed acceptance report.

## Required change accounting

```text
Production code delta: 0
Trusted code delta: 0 in production; experimental signed Launcher overlay behavior changed
New architecture concepts: 1 experimental per-trial workspace identity binding; none in production
New trusted processes: 0
New IPC operations: 0
New persistent state: none in production; bounded owner-only disposable trial marker/manifest
New dependencies: 0
Removed duplication / abstractions: removed trial-specific path-bound identity injection; no new forwarding abstraction
```

## Verification to date

- Builder tests after the trace-schema correction: 8 passed.
- Runner tests: 14 passed.
- Pinned DSH semantic-tool tests: 19 passed.
- DSH model bridge/lifecycle tests: 17 passed.
- Full canonical suite before the trace-schema correction: 462 passed, 0 failed. A final canonical run after the correction is pending.
- Default and exact-base Security Freeze checks: passed before the trace-schema correction; reruns are pending.
- A pre-correction signed app passed deep/strict signature and prebuilt-app validation. A fresh app built from the corrected source is pending.
- The first signed Trial A attempt approved one `fee.py` read, then the Host returned `invalid_request` because the experimental trace allowlist omitted the newly required `runtime_trial_id`. It made no workspace changes and invoked no model. The failed input and result remain preserved and are not reused as acceptance.
- The next signed attempt passed that request-trace decoder and completed one scoped read, but DSH terminal-result telemetry then failed the Host's independent telemetry allowlist. The Node event carried `runtime_trial_id`, while the experimental Swift Host/client telemetry filters omitted it; `DSHRuntimeProcess` failed closed with `invalid_frame`. It made no workspace changes and invoked no model. The event path is now covered by UUID validation at both telemetry boundaries; a fresh signed build is pending.
- Corrected signed Trial A and Trial B outcomes: pending; unit evidence does not count as signed acceptance.

## Review boundary

The experimental Launcher has a trusted behavior delta even though production trusted source is unchanged. Independent security review remains required and is not established by this audit or by green tests.
