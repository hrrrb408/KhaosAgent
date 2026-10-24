# M-Disk.1.1 Scratch Dependency Closure

Date: 2026-10-24
Historical candidates: 27 (3 large + 24 small)
Original V1 manifest SHA-256: `0ef426ef069c0c8ed8a40183a411a4b580aeed7d3c3ccebc8e68f5b3ba75c131`
Final post-acceptance V2 manifest SHA-256: `9f67da45231da9c85a36597e27bf7a400dd5fff95291df9dbc4417b84fc353f5`
Final post-acceptance Dry Run SHA-256: `78521525eed63cbd85b986c01aecce3154576469a596713b4500be846f0f320e`

All 27 current roots were checked against V1 and V2 metadata: device, inode, logical bytes, allocated bytes, and tree fingerprint matched in all 27 cases. Reference checks were clear at capture, during archive, and during the V2 Dry Run. Exact local paths and filesystem identities remain only in the owner-only manifest.

## Candidate mapping

`READY` means V2 Dry Run status `READY_PENDING_OWNER_APPROVAL`; it is not deletion authorization. `UNRESOLVED` means `REFUSE`.

| Candidate ID | Trial | Provenance linkage | V2 result |
|---|---|---|---|
| `failed-scratch-oc6vn43u` | `phase32-stage-b-a-1` | DSH Phase 3.2 Stage B; Khaos `12ae44732ef591d5e5a0f6f56b820ecbdc730ea1` | READY |
| `failed-scratch-ootv2ew_` | `phase32-stage-b-a-2` | DSH Phase 3.2 Stage B; Khaos `566bc3ac251d86f096a4147fdb0953b7c195447f` | READY |
| `failed-scratch-omcze7ba` | `phase321-focused-task-a-01` | DSH Phase 3.2.1; Khaos `2a73f48d9291a11cbac3612410cbeb9e651cf540` | READY |
| `unmapped-scratch-1vuu1vf2` | `stage-a-3` | Signed-App build record; Khaos `12ae44732ef591d5e5a0f6f56b820ecbdc730ea1` | READY |
| `unmapped-scratch-4kf831q0` | `phase321-task-a-failure-04` | Signed-App build record; Khaos `2a73f48d9291a11cbac3612410cbeb9e651cf540` | READY |
| `unmapped-scratch-6ercgb0x` | `stage-a-5` | Signed-App build record; Khaos `7c653b5f980a668c63ea3f79a6959c792e63bbc9` | READY |
| `unmapped-scratch-938gpneu` | `stage-a-6` | Signed-App build record; Khaos `0e139f433104333e1028237220578982566937d6` | READY |
| `unmapped-scratch-b1wle79o` | `phase321-task-a-failure-03` | Signed-App build record; Khaos `1aa43b257153ec059eb13b8689df8cd595915000` | READY |
| `unmapped-scratch-dcukbc5i` | `stage-a-4` | Signed-App build record; Khaos `705918e4bcdb1fbfcc61268985117c27dbb610af` | READY |
| `unmapped-scratch-dm36vyve` | `stage-a-92` | Signed-App build record; Khaos `a9d25632cdf9b6f5df503b7f11bf2d83fbff216d` | READY |
| `unmapped-scratch-g1aqx0vu` | `phase321-task-a-failure-02` | Signed-App build record; Khaos `cdb8bbb5659ff28efb674913d3418397b222daff` | READY |
| `unmapped-scratch-g42te3ht` | `stage-a-7` | Signed-App build record; Khaos `0e139f433104333e1028237220578982566937d6` | READY |
| `unmapped-scratch-jj8qjcdc` | `stage-a-2` | Signed-App build record; Khaos `c9f8ba25b2117468c0be8d8d07e199c4af15a6b9` | READY |
| `unmapped-scratch-jzpg6y84` | `stage-a` | Signed-App build record; Khaos `2c1033c347bce80611e27d386696fb018955fa9e` | READY |
| `unmapped-scratch-n7mexjb_` | `stage-a-8` | Signed-App build record; Khaos `bc938d7f31eb7f3ac3ca0c3c0af515c5d030cc38` | READY |
| `unmapped-scratch-osjv07_5` | `stage-a-93` | Signed-App build record; Khaos `56c0549861d3ca8d90a5078955a05e3210beaf37` | READY |
| `unmapped-scratch-90w35gpd` | `stage-a-90` | Signed-App build record; Khaos `ccd4bb5d105ec3669783f6b80a4934f4a10b19ab` | READY |
| `unmapped-scratch-9eq8y0vq` | `stage-a-94` | Signed-App build record; Khaos `1ba889cf9114ac14bc47ca8cbcf6fd52640d67c3` | READY |
| `unmapped-scratch-xofn55s_` | `phase321-integrity-pass-01` | Signed-App build record; Khaos `2a73f48d9291a11cbac3612410cbeb9e651cf540` | READY |
| `unmapped-scratch-_yo_vtqo` | `stage-a-9` | Signed-App build record; Khaos `7bad0fc6e4c9f7d01593e1404232f92b82d6dade` | READY |
| `unmapped-scratch-x60i5ana` | `phase321-integrity-fake-success-01` | Result fixture only; no exact source/build record | UNRESOLVED |
| `unmapped-scratch-edk1hwuj` | `phase321-integrity-zero-tests-01` | Result fixture only; no exact source/build record | UNRESOLVED |
| `unmapped-scratch-bn09_1k9` | `phase321-integrity-import-error-01` | Result fixture only; no exact source/build record | UNRESOLVED |
| `unmapped-scratch-zg_70h27` | `stage-a-3` | Workspace identity marker → Gate A failed record; Khaos `5f20c6456c78f45f19f8649af1295cc16a0b4f5e` | READY |
| `unmapped-scratch-p9g3_r1e` | `stage-a` | Workspace identity marker → Gate A failed record; Khaos `fb7a94cb4251c34936ad22ec15ddf828791b29b0` | READY |
| `unmapped-scratch-n8koxwgs` | `stage-a-2` | Workspace identity marker → Gate A failed record; Khaos `5f20c6456c78f45f19f8649af1295cc16a0b4f5e` | READY |
| `unmapped-scratch-fzi7tckj` | `stage-a-91` | Workspace identity marker → Gate A failed record; Khaos `ccd4bb5d105ec3669783f6b80a4934f4a10b19ab` | READY |

The 17 small signed-App entries are linked through archived build records; the four workspace-only Gate A entries are linked by their unique workspace marker and corresponding failed record. This closes the mapping for 21 of the 24 small roots. The three tiny result-fixture roots contain records, but no exact source/build SHA was found; their provenance remains unresolved rather than inferred from their names and they remain refused by the final Dry Run.

## Evidence archive and consumers

The owner-only closure archive covers 27/27 candidates. All 195 copied evidence files match their recorded SHA-256 and size. The 27 deduplicated runtime input blobs also match their content digests. Archive metadata SHA-256 is `1aa76d1672b58fcd02c9ced1d5a35f9e2dc508ffdf04528493a7b1f5d105db9e`.

```text
Total private archive bytes: 44,810,313
Deduplicated model runtime inputs: 30,797,083 bytes
GGUF payload bytes copied: 0
Signed App bundles copied: 0
Historical candidates modified: 0
Candidate roots with active references: 0 observed
```

Public reports and PR contain no local candidate path, workspace content, canary text, or private session log. The three unresolved fixtures remain retained. The owner-only Manifest V2 contains exact paths, inode/device, fingerprints, and per-candidate archive bindings.
