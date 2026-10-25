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
Final-Head GitHub CI: PENDING at this report revision (PR #47 exact-head checks are authoritative)
Draft PR: OPEN / DRAFT (#47; base PR #46 head `7ed01f726387755181cfbadad33967f35d9d2f72`)
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

## M-Disk.1.1 update — 2026-10-24

This section is the current follow-up result. The preceding M-Disk.1 entry is retained as its dated historical snapshot.

```text
M-Disk.1.1 Engineering: PARTIAL
Pinned pnpm 10.17.1: NOT THE HISTORICAL SOURCE PIN
Historical pnpm 11.28.5: VERIFIED; frozen offline install unchanged
Large Scratch Rebuildability: BUILD_PATH_VERIFIED (small signed App only; no full model App rebuild)
Large Scratch Dependency Mapping: 3 / 3
Small Scratch Dependency Mapping: 21 mapped / 3 unresolved, among 24 examined
Signed Retention Lifecycle: PARTIAL
Successful signed scenario groups: 6 (Read/Edit/Test, Runner failure, import error, Node recovery, cancellation, XPC recovery)
Signed refusal/timeout evidence: 2 (cancelled Picker; bounded approval timeout)
Signed-only lifecycle gaps: archive failure, identity substitution, live/unavailable reference refusal (unit-tested only)
Evidence Preservation: PASS for completed runs and timeout; incomplete preflight failure retained
Manifest V2 SHA-256: 9f67da45231da9c85a36597e27bf7a400dd5fff95291df9dbc4417b84fc353f5
Post-acceptance Dry Run SHA-256: 78521525eed63cbd85b986c01aecce3154576469a596713b4500be846f0f320e
Post-canonical Dry Run SHA-256: 5eef8ab180130fc1dcbb13602ea8d90e3e46aba333956d6ffee60339f5955a16
Dry Run: 24 READY_PENDING_OWNER_APPROVAL / 3 REFUSE / 0 mutations
Nominal Candidate Size: 59,281,473,944 logical bytes / 59,434,573,824 st_blocks bytes
Actual APFS Reclaim: UNKNOWN (shared extents not measured)
Historical Files Deleted: 0
Data Volume: 926 GiB total / 513 GiB used / 388 GiB available
APFS Container: 994.7 GB ceiling / 577,539,485,696 bytes in use / 417,123,098,624 bytes not allocated
Local Snapshots: none observed
Canonical Tests: PASS (449 tests, 818.730 seconds; exit 0)
Canonical Log SHA-256: ee147f60598dcd94a669ee8a29c572e106e90b4b137b76553cde11565a842a12
Focused Tests: PASS (retention 29, builder 6, runner 10)
Security Freeze: PASS (default sensitive changes 0; exact PR #46 base check 4 cumulative declared sensitive paths)
Exact-head GitHub CI: PENDING final report commit
PR #47: OPEN / DRAFT; exact base 7ed01f726387755181cfbadad33967f35d9d2f72
Owner Cleanup Approval: PENDING
Kernel Authority / ABI / Workspace Scope / Production Runtime / Production Dependencies Delta: 0
Production Harness Migration: NOT AUTHORIZED
Historical cleanup: NOT AUTHORIZED; performed: NO
Phase 3.2.2 large real-model Gate B/C: KEEP PAUSED pending exact-head CI and lifecycle-gap closure or explicit acceptance
```

The requested pnpm 10.17.1 did not match the actual historical source pin. Exact-source audit established 11.28.5 and verified its executable, Node 22.19.0 archive checksum, DSH commit, and unchanged lockfile through a frozen offline install. A small deterministic signed App was built and deep signature verification passed. All three large build paths are `BUILD_PATH_VERIFIED`, not `FULL_REBUILD_PROVEN`; no GGUF was recopied.

All 27 historic roots remain unchanged in a post-acceptance metadata comparison; the post-canonical Dry Run revalidated every exact root and found all process-reference checks clear. The V2 Dry Run identifies 24 exact cleanup candidates, including all three large Apps, but all remain pending separate owner approval. Three tiny result fixtures lack source/build linkage and are refused. `st_blocks` is not APFS-exclusive space; expected physical reclaim is not measurable from this audit.

The signed lifecycle is partial. A clean-worktree XPC recovery run proved a committed edit remained recorded across one result-delivery transport failure and a fresh task then read the edited file. An earlier XPC attempt stopped at a cancelled workspace Picker and did not reach a Kernel operation; a separate bounded approval-timeout run approved nothing and preserved its failure evidence. A recovery build rejected from the dirty report worktree never launched an App and left a small incomplete-evidence Scratch retained. Archive failure, identity substitution, and live/unavailable-reference refusal have unit coverage only.

The full canonical suite passed 449 tests in 818.730 seconds. The two post-acceptance and post-canonical Dry Runs each checked 27 candidates, returned 24 pending owner approval and three refused, and performed zero mutations. The post-canonical output has null estimated reclaim and expected exit code 2 because three entries are refused. Current disk availability is 388 GiB on the Data volume and 417.1 GB not allocated in the APFS container; these overlapping views are not additive. Between the pre-canonical and post-canonical APFS samples, container in-use capacity rose by 62,234,624 bytes (about 59.4 MiB); that interval change is not attributed solely to the tests. No local snapshots were found. Historical files remain untouched.

The M-Disk.1.1 follow-up delta from starting HEAD `5b2ef3eedaaa59392b6e710f87b4556c02cf8960` is documentation only: nine report files and no source, test, security declaration, manifest, or runtime changes. The overall PR #47 still contains its prior experimental Python retention tooling and tests; it does not change production Kernel authority or runtime. A 32 MiB clean detached build worktree and a 24 MiB verified Node toolchain/archive directory remain under temporary storage outside the 27 historical candidates; they were not cleaned. One separate 24 KiB incomplete-evidence preflight Scratch is retained for diagnosis. Keep large Phase 3.2.2 Gate B/C model runs paused until exact-head CI is green and remaining signed lifecycle gaps are closed or explicitly accepted. No cleanup or production-migration authorization is inferred.

## M-Disk.1.2/1.3 follow-up — 2026-10-25

The signed retention checks that were previously missing have now been exercised using four one-shot locally signed macOS UI runs. The runs used a synthetic fake-success command with an actual exit code of `1`; each went through the existing Trusted Launcher, Kernel and Runner. Archive failure, directory identity substitution, a real `lsof` process reference, and an injected unknown reference all caused cleanup refusal. A separate unit test verifies that an `lsof` process-launch error is `UNKNOWN` and blocks cleanup. The acceptance driver is experimental test code and does not add Kernel authority.

```text
M-Disk.1.3 Engineering: PARTIAL
Signed Retention Lifecycle: PASS (four bounded signed scenarios)
Evidence Archive Failure: PASS (controlled incomplete archive; cleanup refused)
Scratch Identity Substitution: PASS (replacement unchanged)
Active Process Reference: PASS (lsof found one synthetic PID; no force-kill)
Unknown Process Reference: PASS (controlled unknown; lsof OSError unit test refuses)
Historical Large Scratch Present: 0 / 3
Historical Large Scratch Ready: 0 / 3 (all current target paths missing; cause unknown)
Historical Evidence: preserved in independent owner-only closure archive; legacy capture-manifest hash binding mismatch disclosed
New Owner Manifest SHA-256: 7241ce17046e58d0c8fd0451f226e95c2453bc0510ec1978a94c72f1334f08dc
Exact Three-Candidate Dry Run SHA-256: a061f03b712b0f54e7b3a32eda16625e5aa3df77dedc0d48de265c0435cde79d
Dry Run: PASS (3 REFUSE / 0 READY / 0 mutations; expected exit 2)
Last recorded size of missing roots: 56,237,832,203 logical / 56,260,804,608 st_blocks bytes
Actual APFS-exclusive reclaim: UNKNOWN; no current target is actionable
Historical removals performed by this run: 0; disappearance cause of the three roots: UNKNOWN
Original model source: present by metadata, 18,556,689,568 bytes; content not reread or hashed
Current disk: Data 926 GiB total / 455 GiB used / 446 GiB available; APFS 515,315,507,200 bytes in use / 479,347,077,120 not allocated
Local snapshots: none observed
Canonical Tests: PASS (454 tests, 854.760 seconds)
Focused Retention Tests: PASS (34 tests)
Security Freeze: PASS (default; exact PR base 7ed01f726387755181cfbadad33967f35d9d2f72)
GitHub CI: SHA-specific; the previously pushed HEAD `1fefb70c35f3d843c1ec69ca2cfd8ce4e9478510` passed `security-tests` and `security-freeze`. This report update creates a new HEAD, whose checks must be read from PR #47 before delivery.
PR #47: OPEN / DRAFT; exact base 7ed01f726387755181cfbadad33967f35d9d2f72
Owner Cleanup Approval: PENDING / NOT ACTIONABLE for missing paths
Kernel Authority / ABI / Workspace Scope / Production Runtime / Production Dependency Delta: 0
Independent Code Owner Review: NOT PERFORMED
Production Harness Migration: NOT AUTHORIZED
Phase 3.2.2 Gate B/C: CONDITIONAL; not started by this task
```

The three target directories that were present in the prior Manifest V2 are now absent. This run did not delete, move, traverse or mutate their contents; the cause and timing of their disappearance cannot be established from available records. The prior report showed 388 GiB available and 417,123,098,624 bytes not allocated in the APFS container. Current availability is approximately 58 GiB higher, which is correlated but not proof of the missing Scratch roots' contribution. The reported historical ~40 GB change remains unattributed.

The final owner-only manifest contains exactly those three candidate IDs, retains their last-known identities, records the current missing state, and refuses all three. Its Dry Run confirms zero ready candidates and zero mutations. The manifest is **not a deletion authorization**, and there is no actionable approval request while these paths are missing. If an artifact with a similar name is found again, it requires a new identity-bound audit. The original GGUF and historical evidence archives remain protected.

The current source diff remains limited to experimental Python retention tooling, tests, security test-inventory metadata and reports. No production trusted code, Kernel ABI, workspace authority, production AgentHost, sandbox policy or production dependency changed. CI results do not carry across commits; use the live PR #47 checks for the current exact HEAD. No real-model Gate B/C run was started.
