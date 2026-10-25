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

- Builder tests after the terminal-result telemetry correction: 8 passed.
- Runner tests: 14 passed.
- Pinned DSH semantic-tool tests: 19 passed.
- DSH model bridge/lifecycle tests: 17 passed.
- Full canonical suite at `520d659903fce78b489452bb5316f349f163e33f`: 463 passed, 0 failed, 883.223 seconds.
- Default Security Freeze: passed at the same source SHA with 0 sensitive changes. Exact-base Security Freeze against `e27aed3ee3f40e7a008517ab7d8242bebe25a7c2`: passed with 5 declared sensitive changes; independent approval remains external.
- A corrected-source no-model app was built at `520d659903fce78b489452bb5316f349f163e33f` and passed deep/strict signature verification plus exact-source prebuilt validation. No `.gguf` file was present. A subsequent report-only commit moved `HEAD`, so the app's exact-source receipt requires a rebuild before it can be used for a trial on the final PR head.
- The first signed Trial A attempt approved one `fee.py` read, then the Host returned `invalid_request` because the experimental trace allowlist omitted the newly required `runtime_trial_id`. It made no workspace changes and invoked no model. The failed input and result remain preserved and are not reused as acceptance.
- The next signed attempt passed that request-trace decoder and completed one scoped read, but DSH terminal-result telemetry then failed the Host's independent telemetry allowlist. The Node event carried `runtime_trial_id`, while the experimental Swift Host/client telemetry filters omitted it; `DSHRuntimeProcess` failed closed with `invalid_frame`. It made no workspace changes and invoked no model. The event path is now covered by UUID validation at both telemetry boundaries; the corrected-source app has since been built and validated, but its signed trials were not started.
- Corrected signed Trial A and Trial B outcomes: not run. A separate Khaos acceptance app still had an open workspace Picker, and the test instructions prohibit opening a second Picker concurrently. No new workspace selection or Runner approval was made. The corrected app is preserved for a later trial; unit evidence does not count as signed acceptance.

## Review boundary

The experimental Launcher has a trusted behavior delta even though production trusted source is unchanged. Independent security review remains required and is not established by this audit or by green tests.
