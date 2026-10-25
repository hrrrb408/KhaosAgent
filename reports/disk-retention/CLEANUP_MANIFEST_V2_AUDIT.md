# M-Disk.1.1 Cleanup Manifest V2 Audit

Date: 2026-10-24
Mode: owner-only manifest, read-only exact-candidate Dry Run
Source V1 SHA-256: `0ef426ef069c0c8ed8a40183a411a4b580aeed7d3c3ccebc8e68f5b3ba75c131`

## Manifest and Dry Run

Manifest V2 was newly captured from the current filesystem after dependency mapping, evidence archiving, and signed acceptance. Its metadata was compared with the pre-acceptance V2 snapshot. It is owner-only and is not committed to GitHub. Its exact local location is provided in the owner handoff, not in this public report.

```text
Manifest V2 SHA-256: 9f67da45231da9c85a36597e27bf7a400dd5fff95291df9dbc4417b84fc353f5
Manifest checksum sidecar SHA-256: `77746d534cf68018beea699d12bc879f9413856570508b4ac669784749fa9bc3`
Manifest checksum sidecar: MATCH
Dry Run result SHA-256: 78521525eed63cbd85b986c01aecce3154576469a596713b4500be846f0f320e
Post-canonical Dry Run SHA-256: `5eef8ab180130fc1dcbb13602ea8d90e3e46aba333956d6ffee60339f5955a16`
Mode: DRY_RUN_READ_ONLY
Candidates checked: 27
READY_PENDING_OWNER_APPROVAL: 24
REFUSE: 3
Mutations performed: 0
APFS-exclusive reclaim: UNKNOWN
```

The audit utility exits with status `2` when candidates are refused. That is the intended fail-closed result here: 24 exact candidates passed the non-destructive checks and remain owner-gated; three unresolved candidates were refused. It is not reported as an all-candidates-clean result.

The refused candidates are the three small Phase 3.2.1 result fixtures with no exact source/build identity. Each refusal includes `candidate_classification_not_safe`, `rebuild_not_proven`, and `consumer_dependency_unresolved`. Their combined size is 38,392 logical bytes / 135,168 `st_blocks` bytes, but missing provenance is sufficient to keep them.

## Disk accounting

| Measure | Value |
|---|---:|
| 27 roots, logical | 59,281,473,944 bytes (59.281 GB) |
| 27 roots, `st_blocks` | 59,434,573,824 bytes (59.435 GB) |
| 24 ready roots, logical | 59,281,435,552 bytes |
| 24 ready roots, `st_blocks` | 59,434,438,656 bytes |
| APFS shared/cloned extents | Not measured |
| Actual exclusive reclaim | `UNKNOWN` |
| Historical bytes released | `0` |

The `st_blocks` totals are allocated-block estimates, not APFS-exclusive reclaim. Multiple model-bearing Apps may share APFS extents; no 59 GB reclaim promise is made. All three model-bearing Scratch roots are ready only for an exact owner decision. The protected original model source is excluded.

## Disk snapshot

The post-canonical 2026-10-24 sample reported a 926 GiB Data volume with 513 GiB used and 388 GiB available. The APFS container ceiling was 994.7 GB, with 577,539,485,696 bytes in use and 417,123,098,624 bytes not allocated. The Data `df` view and APFS container view overlap and must not be added. `tmutil listlocalsnapshots /` returned no local snapshots. No matching Khaos AgentHost, KernelProduction, llama.cpp, Swift compiler, or Xcode build process was observed after the suite.

The post-canonical Dry Run revalidated all 27 exact entries against the same manifest SHA. It reported 24 `READY_PENDING_OWNER_APPROVAL`, three `REFUSE`, all process-reference checks `CLEAR`, `mutations_performed: 0`, and null estimated reclaim. Exit code `2` is expected for a fail-closed result containing refusals. The final JSON and prior post-acceptance JSON are both retained as separate owner-only evidence files.

The historical approximately 40 GB change has no saved before/after measurement. Three failed model Apps explain a plausible large share, but do not prove the exact time-series delta. The root-cause report remains a high-confidence explanation, not measured attribution.

## Authorization

```text
Historical deletion performed: NO
Owner cleanup approval: PENDING
Manifest V2 exact path and SHA required: YES
Fresh identity, fingerprint, active-reference and evidence checks before future deletion: REQUIRED
```

This report and the Draft PR do not grant cleanup authorization. A future cleanup must name exact candidates and bind owner approval to this Manifest V2 SHA; any changed identity requires a new manifest.
