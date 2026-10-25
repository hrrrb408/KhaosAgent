# M-Disk.1.4 — Historical Scratch Disappearance

Date: 2026-10-25  
Investigation: bounded, read-only; no historical path was modified.

## Timeline

The last retained observation that all three exact roots still existed is the M-Disk.1.1 post-test dry run at `2026-10-24T15:32:56.505129Z` (SHA-256 `5eef8ab180130fc1dcbb13602ea8d90e3e46aba333956d6ffee60339f5955a16`). It reports all three as `READY_PENDING_OWNER_APPROVAL` and their device/inode and recorded sizes match Manifest V2.

The first retained record that all three exact roots were missing is the M-Disk.1.2 preliminary manifest at `2026-10-25T05:16:03.681113Z` (SHA-256 `a8351397ef65026b8ed1b18f53edf90efb79869748a81e65288dff9a30e1877c`). The persisted interval is **13 hours, 43 minutes, 7.175984 seconds**. The later owner manifest and dry run again report all three missing/refused, with zero mutations.

| Candidate | Trial | Last recorded identity | Last proven present | First persisted missing | Current state |
|---|---|---|---|---|---|
| `failed-scratch-oc6vn43u` | `phase32-stage-b-a-1` | device `16777234`, inode `275041024` | `2026-10-24T15:32:56.505129Z` | `2026-10-25T05:16:03.681113Z` | Missing |
| `failed-scratch-ootv2ew_` | `phase32-stage-b-a-2` | device `16777234`, inode `275116381` | `2026-10-24T15:32:56.505129Z` | `2026-10-25T05:16:03.681113Z` | Missing |
| `failed-scratch-omcze7ba` | `phase321-focused-task-a-01` | device `16777234`, inode `275239038` | `2026-10-24T15:32:56.505129Z` | `2026-10-25T05:16:03.681113Z` | Missing |

Exact paths and full tree fingerprints remain in the owner-only manifest and M-Disk.1.4 evidence snapshot. The V2 manifest SHA-256 is `9f67da45231da9c85a36597e27bf7a400dd5fff95291df9dbc4417b84fc353f5`; its sidecar verifies. The latest 3-candidate manifest SHA-256 is `7241ce17046e58d0c8fd0451f226e95c2453bc0510ec1978a94c72f1334f08dc`; its sidecar verifies. The final dry-run SHA-256 is `a061f03b712b0f54e7b3a32eda16625e5aa3df77dedc0d48de265c0435cde79d` and reports 3 refused, 0 ready, 0 mutations.

## Deletion-source evidence

The machine boot time is `2026-10-25T04:22:11Z`, within the persisted disappearance interval and 53m52.681113s before the first missing manifest. The bounded exact-name Unified Log query over the interval timed out after 30 seconds with no output; the result is `EVIDENCE_NOT_AVAILABLE`. `last reboot` has no earlier record because its `wtmp` history begins later that day. No elevated permissions were used.

The current bounded process-name check found no process command line containing any of the three exact candidate paths. This is present-time evidence only. The M-Disk.1.2/1.3 owner records state that their runs did not access or mutate historical paths; their signed tests used new invocation-owned scratch directories. The latest owner dry run remains a refusal, not a deletion request.

| Candidate explanation | Finding |
|---|---|
| Khaos Runner cleanup | No call path found that reads the historical manifest and passes one of these roots to cleanup. Not found in the inspected code path. |
| Python `TemporaryDirectory` finalizer | Each recorded driver revision detaches its finalizer on the failed-attempt retention path. This explains retention after failure, not the later disappearance; a later invocation cannot select the prior path. No deletion event is recorded. |
| Codex task cleanup | No target-specific cleanup record. The later signed runs used newly created paths. Historical action remains unknown. |
| macOS temporary-directory maintenance | Plausible: the roots were in the user's temporary area and a reboot falls inside the interval. No matching system event is available to prove it. |
| Manual or other process | No direct evidence either way. |

**Conclusion: `Historical Scratch Disappearance: UNKNOWN`.** The candidate roots had a last recorded total of 56,237,832,203 logical bytes and 56,260,804,608 `st_blocks` bytes. Those are historical figures, not current APFS-exclusive reclaimable space. The earlier free-space increase is correlated with their absence but does not identify the remover or prove how much space their removal reclaimed.

The current Data volume sample is about 926 GiB total, 455 GiB used, and 446.7 GiB available. The APFS container reports 514.9 GB in use and 479.7 GB not allocated; these views overlap. No local snapshots were listed. Relative to the prior M-Disk.1.3 sample, current free capacity is higher by only about 350 MiB, which does not explain or attribute the earlier change.

Owner-only timeline snapshot: `m-disk-1-4-20261025/M-DISK-1-4_TIMELINE_SNAPSHOT.json`, SHA-256 `6fd3a6af5d69e79acb27497cab95db4fc5b0308695453fe1c04757c147ac9b79`. Its addendum binds the 15:32:56Z post-test dry run. The addendum's `correction_utc` initially copied the source event timestamp into the audit-time field; the original was preserved and a separate correction record (SHA-256 `6bfa1f21e6da72ec18d68cbd157eef7305c5c9bba43ff4c333d0d6460b1e54ac`) records the actual addendum creation time. This timestamp-field correction does not change the source event time or the disappearance interval.
