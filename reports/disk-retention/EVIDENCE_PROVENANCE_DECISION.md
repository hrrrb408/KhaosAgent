# M-Disk.1.4 — Evidence Provenance Decision

## Independent verification results

The owner-only Manifest V2 content and sidecar both match `9f67da45231da9c85a36597e27bf7a400dd5fff95291df9dbc4417b84fc353f5`. The final three-candidate manifest content and sidecar match `7241ce17046e58d0c8fd0451f226e95c2453bc0510ec1978a94c72f1334f08dc`; the preliminary missing-target manifest and sidecar also match `a8351397ef65026b8ed1b18f53edf90efb79869748a81e65288dff9a30e1877c`. The final dry run independently hashes to `a061f03b712b0f54e7b3a32eda16625e5aa3df77dedc0d48de265c0435cde79d`.

The independent closure archive manifest and sidecar match `1aa76d1672b58fcd02c9ced1d5a35f9e2dc508ffdf04528493a7b1f5d105db9e`. Each of the three historical trial archives has seven entries; every file's size and SHA-256 matches its record (**21/21**).

For each trial, the following also match their recorded values:

| Evidence relation | Result |
|---|---:|
| `evidence-index.json` bytes vs Manifest V2 index digest | 3/3 |
| `source-failure.json` bytes vs Manifest V2 failure-record digest | 3/3 |
| Diagnostic `build-inputs.json` vs index digest | 3/3 |
| Decompressed `launcher.stdout.gz` vs raw stdout digest | 3/3 |
| Decompressed `launcher.stderr.gz` vs raw stderr digest | 3/3 |
| Files listed inside saved Capture Manifest vs their saved diagnostic bytes | 18/18 |
| `capture-manifest.json` bytes vs index-declared digest | 0/3 |

The mismatch is exactly the one documented in `CAPTURE_MANIFEST_INTEGRITY_AUDIT.md`. The independent task, fixture, hidden acceptance, build input and raw-runner-result archives remain hash-valid. The evidence package's binding to its diagnostic file inventory is still incomplete because its Capture Manifest reference is wrong.

## Session / Launcher correlation limit

The hash-verified diagnostic stderr also contains parseable, sequence-ordered DSH telemetry. Trial A1 contains one session and one submitted proposal but no Launcher event or delivered result. Trial A2 contains seven proposals and six DSH result-delivery, continuity and next-turn event groups; its separate Launcher event stream contains six accepted approvals and six Kernel-operation start/completion groups. The focused Task A trial contains eight proposals and Launcher approval/operation groups, with seven DSH result-delivery, continuity and next-turn groups plus one public-test-result event. Each trace has one DSH session and one trial ID; the DSH `event_seq` values are monotonic.

These records show that the DSH session logged result observations and subsequent turns in A2 and the focused Task A trial. Within each DSH trace, trial IDs match the evidence index, event sequence numbers are contiguous, and the set of delivered tool-call IDs exactly matches the continuity-check and next-turn IDs; each result carries result digests, and the continuity/next-turn events record that a result was observed. They do **not** provide a shared request identifier across the DSH proposal/result events and the Launcher approval/Kernel events: the DSH events carry tool/operation/session IDs, while Launcher events carry Launcher task/request IDs. The captured stdout also contains no parsed Launcher task record. Therefore the exact per-operation mapping from a given Kernel result to a given DSH result event is **`NOT_PROVEN`** for these old archives. This correlation limit is independent of, and not caused by, the Capture Manifest hash bug.

## Decision on historical claims

No independently checked file contradicts a previously recorded Kernel result, Runner return code, or independent coding-evaluation outcome; no outcome was recomputed in this audit. The records themselves remain preserved and hash-verified within the limits above. Any claim that relies on the three `evidence-index.json` values to authenticate the exact Capture Manifest bytes or its full copied-file inventory is **`NOT_PROVEN`**. For the archived DSH trials, exact Kernel-result-to-session-result mapping is also **`NOT_PROVEN`** because the event streams lack a shared request ID. We therefore classify overall historical evidence integrity as `PARTIAL`, not fully verified and not evidence of tampering.

The missing 18GB-scale Scratch roots themselves cannot be reinspected. Their last recorded `st_blocks` total is not an APFS-exclusive reclaim measurement. No old evidence or manifest was rewritten. The M-Disk.1.4 timeline snapshot and addendum are new owner-only records; their hashes are listed in `HISTORICAL_SCRATCH_DISAPPEARANCE.md`.

```text
Historical Evidence Archive Integrity: PARTIAL
Independent Closure Archive Files: 21/21 VERIFIED
Index / Failure / Build / Raw Runner Bindings: VERIFIED
Saved Capture Manifest Internal File Digests: 18/18 VERIFIED
Historical Capture Manifest Byte Binding: 0/3 VERIFIED
Historical Conclusions Reversed by This Audit: NONE OBSERVED
Historical Capture-Manifest Inventory Assurance: NOT_PROVEN
Historical Kernel-to-Session Result Mapping: NOT_PROVEN FOR THE THREE ARCHIVED TRIALS
```

The owner-only verification record `m-disk-1-4-20261025/M-DISK-1-4_PROVENANCE_VERIFICATION.json` contains the exact per-file hashes and status checks; SHA-256 `9b8d98d6d036b7a3a5a42e2e15cb066bd100b1f3389255592b58f8f12df7dddb`.
