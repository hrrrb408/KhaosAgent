# M-Disk.1.2 Large Scratch Pre-Cleanup Audit

Date: 2026-10-25
Scope: only the three named model-bearing historical Scratch candidates. No other historical artifact was inventoried or authorized in this phase.

## Source and last-known identity

Manifest V2 was read-only verified against its sidecar: SHA-256 `9f67da45231da9c85a36597e27bf7a400dd5fff95291df9dbc4417b84fc353f5`. The prior snapshot recorded these exact roots as ready pending owner approval, with a clear process-reference result at that earlier capture. The current recheck found all three exact paths missing. Current device/inode, tree fingerprint and process-reference state therefore cannot be re-established. The cause and time of disappearance are unknown; this audit did not remove or move them.

| Candidate | Trial | Khaos source SHA | Last-known logical bytes | Last-known allocated bytes | Current path |
|---|---|---|---:|---:|---|
| `failed-scratch-oc6vn43u` | `phase32-stage-b-a-1` | `12ae44732ef591d5e5a0f6f56b820ecbdc730ea1` | 18,745,900,491 | 18,753,556,480 | Missing; refuse |
| `failed-scratch-ootv2ew_` | `phase32-stage-b-a-2` | `566bc3ac251d86f096a4147fdb0953b7c195447f` | 18,745,949,072 | 18,753,605,632 | Missing; refuse |
| `failed-scratch-omcze7ba` | `phase321-focused-task-a-01` | `2a73f48d9291a11cbac3612410cbeb9e651cf540` | 18,745,982,640 | 18,753,642,496 | Missing; refuse |
| **Total, last recorded** |  |  | **56,237,832,203** | **56,260,804,608** | **0/3 present** |

Exact absolute paths and old device/inode/fingerprint values are in the owner-only manifest, not this public report. The table's allocated numbers are prior `st_blocks` totals, not APFS-exclusive extents.

## Evidence and rebuild inputs

The owner-only closure archive manifest remains hash-valid at `1aa76d1672b58fcd02c9ced1d5a35f9e2dc508ffdf04528493a7b1f5d105db9e`. Each of the three candidate archives' seven listed files was checked against its recorded size and SHA-256 (21 files total). The per-trial evidence-index and source-failure record hashes also matched the V2 records. Build-input records retain each Khaos source revision, the common DSH SHA, Node `v22.19.0`, pnpm `11.28.5`, signing identity and build parameters. Rebuildability remains `BUILD_PATH_VERIFIED`; the complete historical 18.56 GB App was not rebuilt.

One provenance inconsistency was found: in all three per-trial evidence indexes, the recorded `diagnostic_capture.capture_manifest_sha256` does not match the saved `diagnostics/capture-manifest.json` bytes. The independent closure archive's seven file-level hashes per candidate, including task, build inputs and raw result captures, verify. The mismatch is retained as an explicit limitation and was not repaired in place. The candidates remain refused regardless.

The original model source remains present in its protected signed app bundle. Its current file size is `18,556,689,568` bytes and matches the existing signed build records; this audit used metadata only and did not reread or hash the model. Do not delete or move it.

## Current disk snapshot and interpretation

At the post-regression sample, `df -h` reported a 926 GiB Data volume with 455 GiB used and 446 GiB available. `df -k` reported 468,112,384 KiB available (479,347,081,216 bytes). The APFS container reported 515,315,507,200 bytes in use and 479,347,077,120 bytes not allocated. No Time Machine local snapshots were listed. The container and volume accounting views overlap and must not be added.

The previous report recorded 388 GiB available and 417,123,098,624 bytes not allocated. The new samples therefore show about 58 GiB more available capacity, while the three candidate paths are now missing. This correlation does **not** prove those Scratch roots caused the change, identify who removed them, or measure APFS extents. No exact attribution of the owner's reported ~40 GB loss is supported by these samples.

## Cleanup decision

```text
Historical candidates in requested scope: 3
Current roots present: 0
Current identities revalidated: 0
READY_PENDING_OWNER_APPROVAL: 0
REFUSE: 3 (target path missing; disappearance cause unknown)
Historical mutations by this run: 0
Actual reclaim attributable to this run: 0 bytes
Potential APFS reclaim from these absent targets: UNKNOWN / not actionable
```

The prior snapshot's 56.26 GB nominal allocation is historical accounting only. Since the roots are absent, it is not a current deletion estimate. A future owner decision cannot authorize deletion against this missing-target manifest; if a target reappears, create a new exact audit and bind any authorization to that new identity.
