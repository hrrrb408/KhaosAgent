# M-Disk.1 Final Decision

Date: 2026-10-24
Branch: `chore/khaos-experiment-artifact-retention`
Base: PR #46 exact HEAD `7ed01f726387755181cfbadad33967f35d9d2f72`

## Required status

```text
M-Disk.1 Engineering: PARTIAL
Disk Root Cause: HIGH_CONFIDENCE (the historical 40 GB delta is not time-series proven)
Large GGUF Copies: 7 observed in the prior bounded audit (4 recorded as the same model SHA; 3 Qwen files not rehashed)
Failed Scratch Candidates: 3 large, plus 24 unmapped smaller roots
Nominal Candidate Size: 59.281 GB logical / 59.435 GB by st_blocks for the 27 exact scratch roots
Estimated Reclaimable Space: UNKNOWN (APFS shared extents not measured)
Evidence Preservation: PASS for the 3 mapped large trials; PARTIAL for the remaining 24
Safe Cleanup Candidates: 0
Unresolved Candidates: 27
Dry Run: PASS (fail-closed; final 27 REFUSE, 0 mutations; result SHA-256 `184cd61f6f6b7412806aa32631dcdad86850c0ceff58c669ccd57d2cabcfd6a5`)
Historical Large Files Deleted: 0
Artifact Retention Hardening: PASS by code and unit tests; signed lifecycle execution not run
Disk Preflight: PASS by synthetic capacity tests; no large build run
Canonical Tests: PASS (449 tests, 826.008 seconds; UI/model flags and credentials cleared)
Security Freeze: PASS (default and exact PR #46 base `7ed01f726387755181cfbadad33967f35d9d2f72`)
Final-Head GitHub CI: PENDING
Draft PR: PENDING
Owner Cleanup Approval: PENDING
Production Kernel Changes: 0
```

## Decision

The principal leak mechanism is fixed in the experimental runner: failures no longer unconditionally detach cleanup after writing only a small failure record. The runner first creates bounded owner-only evidence, then checks evidence completeness, scratch identity/tree fingerprint, and open-process references before cleaning only its own invocation directory. The experimental builder also refuses a local-model build before signature verification or hashing when the output volume lacks a conservative free-space allowance.

The three historical failure packages are now preserved and SHA-verified outside their large App bundles. However, their full App rebuildability is not proven because the exact `pnpm 10.17.1` pinned by the builder is unavailable locally. The other 24 scratch directories have no established Trial/evidence map. No item is currently safe to authorize for cleanup. A later cleanup request must use a fresh manifest after those dependencies are resolved.

The post-test refresh reports 390 GiB (about 418.8 GB) available on the Data volume by `df`, and 418.45 GB not allocated in the APFS container; the Data `df` view and container view have different accounting boundaries and must not be added. There are no Data-volume or Time Machine local snapshots and no Khaos/AgentHost/KernelProduction/llama-cli/Swift/Xcode build process was observed. Keep Phase 3.2.2 large, unattended model runs paused until the Draft PR's exact-head CI is resolved and the team reviews the unresolved artifact dependencies. No model App or GGUF was built in this phase. No signed lifecycle run was performed; deterministic synthetic tests and the canonical suite passed.

The retention implementation itself is validated by 29 dedicated tests plus the 16 existing DSH builder/runner tests and the 449-test canonical suite (826.008 seconds). The three historical large trials now have separate, hash-checked small evidence packages, but pinned `pnpm 10.17.1` is unavailable and the other 24 scratch roots remain unmapped. This evidence does not make any historical artifact safe to delete.

## Architecture and dependency delta

```text
Production code delta: experimental Python tooling only
Trusted code delta: 0
New architecture concepts: 0; local experimental artifact policy only
New trusted processes: 0
New IPC operations: 0
New persistent production state: 0
New dependencies: 0
Removed duplication / abstractions: shared metadata inventory, manifest validation, and model-space preflight primitives
```

Security Kernel, Kernel ABI, workspace scope authority, production trusted runtime, and production dependencies remain unchanged.
