# Cleanup Manifest Dry Run

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
