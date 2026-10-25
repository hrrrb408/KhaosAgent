# Cleanup Manifest Dry Run

The first section is the M-Disk.1 V1 snapshot and is preserved as historical evidence. The current M-Disk.1.1 V2 result is at the end.

Mode: `AUDIT + DRY RUN ONLY`
Manifest SHA-256: `0ef426ef069c0c8ed8a40183a411a4b580aeed7d3c3ccebc8e68f5b3ba75c131`
Post-canonical dry-run result SHA-256: `184cd61f6f6b7412806aa32631dcdad86850c0ceff58c669ccd57d2cabcfd6a5`
Local result: owner-only JSON beside the manifest; exact paths are not included in this report.

## Result

| Result | Count |
|---|---:|
| Exact candidates checked | 27 |
| `READY_PENDING_OWNER_APPROVAL` | 0 |
| `REFUSE` | 27 |
| Mutations performed | 0 |
| Estimated APFS-exclusive reclaim | `UNKNOWN` |

The 3 large candidates were refused because local rebuildability is not proven: the builder requires `pnpm 10.17.1`, and currently available local commands are 11.28.5 and 11.25.0. The other 24 scratch roots were refused because their trial and evidence dependencies remain unmapped. All 27 had a clear process-reference check, but that alone does not make a candidate safe.

The dry-run output has `estimated_reclaimable_bytes: null`. Its current logical/allocated inventory describes nominal candidate size; it does not assert how many APFS extents are exclusive. The manifest sidecar binds the exact metadata snapshot but is not an independent trust anchor.

The final scope-refined read-only dry run was repeated after the 449-test canonical suite. It again refused all 27 candidates, reported zero mutations, and retained `UNKNOWN` APFS-exclusive reclaim. The owner-only result SHA-256 is recorded above.

## Authorization gates still open

No candidate may be deleted based on this dry run. Before a later owner decision, each large trial needs a verified pinned build-tool path and a successful deterministic rebuild-input check; each small scratch needs a Trial/evidence/consumer mapping. Then create a fresh manifest, rerun all identity and `lsof` checks, preserve new evidence as needed, and bind any owner authorization to the new exact manifest SHA. This PR implements no cleanup execution command.

## M-Disk.1.1 V2 follow-up

The preceding sections are the V1 historical snapshot and are intentionally unchanged. The exact-source pin is `pnpm 11.28.5`; the prior `10.17.1` claim was a report error. Following signed acceptance, a fresh owner-only V2 manifest superseded the prior V2 snapshot for current eligibility. After the canonical suite, the same exact manifest was checked again with a separate read-only result; the original post-acceptance Dry Run was preserved.

| Evidence | SHA-256 | Result |
|---|---|---|
| Manifest V2 | `9f67da45231da9c85a36597e27bf7a400dd5fff95291df9dbc4417b84fc353f5` | 27 roots; post-acceptance metadata compared to prior V2 |
| Post-acceptance Dry Run | `78521525eed63cbd85b986c01aecce3154576469a596713b4500be846f0f320e` | 24 `READY_PENDING_OWNER_APPROVAL`, 3 `REFUSE`, 0 mutations |
| Post-canonical Dry Run | `5eef8ab180130fc1dcbb13602ea8d90e3e46aba333956d6ffee60339f5955a16` | Same 24/3 split; all references clear; 0 mutations |

Both Dry Runs report `UNKNOWN` APFS-exclusive reclaim and null estimated reclaimable bytes. The post-canonical command exits `2` because three candidates are refused; this is the expected fail-closed result. The manifest and Dry Run evidence are owner-only and contain the exact candidate paths; the PR contains no local paths.
