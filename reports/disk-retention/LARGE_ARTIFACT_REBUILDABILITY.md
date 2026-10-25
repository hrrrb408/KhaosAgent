# M-Disk.1.1 Large Artifact Rebuildability

Date: 2026-10-24
Scope: three historical model-bearing failed Scratch roots; no full App was rebuilt.

## Per-trial result

| Candidate ID | Trial | Khaos source SHA | Build-input record SHA-256 | Model SHA-256 | Logical / allocated bytes | Result |
|---|---|---|---|---|---:|---|
| `failed-scratch-oc6vn43u` | `phase32-stage-b-a-1` | `12ae44732ef591d5e5a0f6f56b820ecbdc730ea1` | `58eb6db6534886181d0b2c32c620530c98c5c86431659a28605be1468e6b2e92` | `fadc3e5f8d42bf7e894a785b05082e47daee4df26680389817e2093056f088ad` | 18.746 / 18.754 GB | `BUILD_PATH_VERIFIED` |
| `failed-scratch-ootv2ew_` | `phase32-stage-b-a-2` | `566bc3ac251d86f096a4147fdb0953b7c195447f` | `175afeda8621308c12b0e3c149ac19a4002f1f18518394b49b0d2f4086ea3577` | `fadc3e5f8d42bf7e894a785b05082e47daee4df26680389817e2093056f088ad` | 18.746 / 18.754 GB | `BUILD_PATH_VERIFIED` |
| `failed-scratch-omcze7ba` | `phase321-focused-task-a-01` | `2a73f48d9291a11cbac3612410cbeb9e651cf540` | `688540ffe8c3ce8db464021b5ca961e45ea22af25e6bea64080ed9716adb59af` | `fadc3e5f8d42bf7e894a785b05082e47daee4df26680389817e2093056f088ad` | 18.746 / 18.754 GB | `BUILD_PATH_VERIFIED` |

Totals for these roots: `56,237,832,203` logical bytes and `56,260,804,608` bytes by `st_blocks`. Each build record binds an 18,556,689,568-byte model copy. These are nominal file measurements, not APFS-exclusive reclaim.

## Verified build inputs

- Khaos source commits and per-App build records are present and hash-bound.
- All historical source revisions inspected use the actual `pnpm 11.28.5` pin, Node `v22.19.0`, and DSH `687f282e8625c6b8d11ff58211a90524be2e4317`.
- The DSH lockfile hash is unchanged by a frozen offline install. The build uses the correct Node `.tar.xz` archive and verified executable.
- The source model App remains protected. Its current metadata matches the earlier audit; no model bytes were reread. The historical model SHA comes from signed build records.
- Two llama.cpp runtime binaries match recorded identities. The third candidate's required runtime files and notices are preserved in the owner-only closure archive.
- Swift 6.4, macOS SDK 27.0, and the signing identity used by the small signed builds are available.
- Historical builder, AgentHost, Kernel, XPC, entitlements, and bundle configuration hashes are retained in each original build record. Small signed builds exercised the current builder path but were not byte-for-byte rebuilds of historical bundles.

## Rebuildability boundary

All three candidates reach `BUILD_PATH_VERIFIED`: exact inputs are locatable and a small signed App built through the pinned path. They do not reach `FULL_REBUILD_PROVEN`; no complete App with the 18.56 GB model was generated. `pnpm 10.17.1` was not used because it is not the source pin. No model copy was produced to re-test the already recorded model bytes.

This level is sufficient for the current retention policy's pending-owner gate, but not a full historical rebuild claim. The three candidates are only `READY_PENDING_OWNER_APPROVAL` in Manifest V2. Actual APFS reclaim remains `UNKNOWN`.
