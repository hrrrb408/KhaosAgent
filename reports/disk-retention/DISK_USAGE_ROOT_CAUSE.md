# Khaos Disk Usage Root Cause

Audit date: 2026-10-24
Baseline: local read-only audit `KHAOS_DISK_USAGE_AUDIT.md`; M-Disk.1 refresh
Scope: Khaos / DSH experimental artifacts only. No large file was removed, moved, truncated, or rehashed.

## Finding

The approximately 40 GB reported drop is **high-confidence explained, but not historically proven**. Two failed signed-model trials left about 37.507 GB of scratch directories, close to the reported change. A third failed trial left another roughly 18.754 GB. All three apps include a separate 18,556,689,568-byte `agent-model.gguf` copy with the same build-record SHA-256:

`fadc3e5f8d42bf7e894a785b05082e47daee4df26680389817e2093056f088ad`

The builder copies the source model into each app. The runner's old exception path wrote a `.failed.json` and detached `TemporaryDirectory` cleanup, retaining the whole scratch directory. This directly accounts for repeated model copies after interrupted or failed trials.

No historical `df` or APFS baseline was found for the moment the owner observed the 40 GB change. The three directories are therefore the strongest measured source, not proof of the exact time-series delta.

## Current disk and APFS state

| Measure | 2026-10-24 refresh |
|---|---:|
| Data volume used (`df`) | about 549.9 GB |
| Data volume available (`df`) | about 418.8 GB / 390 GiB |
| APFS container ceiling | 994.66 GB |
| APFS space used by volumes | 576.21 GB |
| APFS not allocated | 418.45 GB |
| Data-volume APFS snapshots | none listed |
| Time Machine local snapshots | none listed |

The System and Data `df` views share the same APFS container and must not be added. Container use includes other APFS volumes. `st_blocks` and `du` are allocation estimates; neither reports exclusive APFS extents.

## Measured candidate totals

The exact 27 temporary scratch roots in the private manifest currently account for:

| Group | Count | Logical bytes | `st_blocks` bytes |
|---|---:|---:|---:|
| Failed signed model trials | 3 | 56.238 GB | 56.261 GB |
| Unmapped smaller scratch | 24 | 3.044 GB | 3.174 GB |
| Manifest total | 27 | 59.281 GB | 59.435 GB |

The three GGUFs themselves total 55.670 GB logical. The private manifest also protects the upstream DSH checkout and model sources; it does not include them as cleanup candidates. The earlier broad audit measured about 62.123 GB of nominal candidates when adding the DSH checkout and one Node directory. Those figures are not independent physical reclaim estimates.

Across the explicitly audited locations, there are seven 18 GB-class GGUF files: four Phase 3 model files with the same recorded SHA (one protected source app and three scratch copies), and three Qwen-named files whose contents were not rehashed. Six signed apps contain models. The Qwen source and both Qwen apps remain protected. No second copy of any model was made for this audit.

## Other relevant findings

- All 27 exact scratch roots had `lsof` state `CLEAR` at manifest capture. No Khaos, AgentHost, KernelProduction, `llama-cli`, `swiftc`, or `xcodebuild` process was observed in the current process check. No process was stopped.
- The previous audit found empty Xcode DerivedData and SwiftPM build directories, no current-repository `build`, `dist`, `.build`, or `node_modules` at its bounded depth, and about 14.1 GiB of mixed-purpose user caches. Those caches are not safe bulk-cleanup candidates.
- The 20 temporary `khaos-snapshot-*` directories and two extracted Node directories were not given exact paths in the audit report used for this manifest. They remain outside the cleanup manifest.
- No confirmed-unused file was found. Historical large files deleted: **0**.

## Reclaim estimate

For the 27 scratch roots, the nominal allocation is about 59.435 GB by `st_blocks`. APFS-exclusive bytes are **UNKNOWN** because clone/shared extents were not measured. The safely authorized reclaim is **0 GB**. Even after a future owner approval, the actual returned capacity must be checked from a before/after APFS reading.
