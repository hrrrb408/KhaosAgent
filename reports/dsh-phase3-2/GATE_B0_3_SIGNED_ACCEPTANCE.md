# Gate B.0.3 Signed Acceptance

**Status: BLOCKED before Trial A.** A new no-model app built and passed deep signature verification, but the launcher and all three XPC services lack the Hardened Runtime flag required by the objective. No workspace picker or approval dialog was opened.

## Baseline and build

- Repository: `hrrrb408/KhaosAgent`, existing draft PR #48.
- PR base: `e27aed3ee3f40e7a008517ab7d8242bebe25a7c2`.
- Signed app source: `d807f302b86e1ccf98049fece3226aa0b4c75561`.
- Pinned DSH: `687f282e8625c6b8d11ff58211a90524be2e4317`.
- Pinned Node: `v22.19.0`; archive SHA-256 `1c3a9e78da501bbc1f0c99fbbb69bb7c722bc7a9bf30128b21ea502f3905892a`.
- Signing certificate SHA-1: `81E5B3D53290732C30A9D823874EBAB6E947AB55`.
- Bundle ID: `org.khaos.Seed`; Team ID reported by the app and nested code signatures: `UBAP6LN5AM`.
- App CDHash: `486d1ff52d4b3f043fca9e8251bbdd0676694bd4`.
- App tree SHA-256 before any trial: `4ae02db45b0729478ac19a59eb8483b3af168e803eb7c8934606741fb20a8205`.
- Build receipt SHA-256: `fa2575e8142de748830cf78254df1d3b4082c52f47138cd4477dd5f1fdec4c66`.
- Deep signature verification: **PASS**; all nested signatures verify.
- Model and GGUF: **NONE**; the build receipt has no local-model metadata or model ID.

There were two build attempts and one signed app bundle. The first attempt stopped at Swift compilation because the experimental Host result validator lacked an explicit `return`; it produced no app. The one-line compile fix and regression assertion are included in the source. The second attempt produced the signed bundle listed above.

## Signing prerequisite

The signed app, `KernelProduction.xpc`, `KhaosAgentHost.xpc`, and `KernelSnapshotBroker.xpc` each report CodeDirectory flags `0x0(none)`. Only the bundled DSH Node executable reports `0x10000(runtime)`. The objective requires Hardened Runtime to be preserved, so the bundle was not launched for acceptance.

## Trial results

| Check | Result |
|---|---|
| Trial A read/edit/public test/hidden test chain | NOT_RUN |
| Trial B positive Workspace B operation | NOT_RUN |
| Trial B cross-workspace symlink refusal | NOT_RUN |
| Parent Launcher terminal event from a signed trial | NOT_RUN |
| Signed Kernel-to-DSH operation correlation | NOT_RUN |
| Workspace A/B identity independence | NOT_RUN |
| Canary disclosure and workspace mutation | NOT_RUN; neither disposable workspace was created |
| Signed cross-trial replay cases | NOT_RUN |

No approvals were issued, no workspace was modified, and no canary was read. These are absence-of-execution facts, not evidence that the signed refusal path passes. The historical Trial A and Trial B `FAIL` reports remain unchanged.

Owner-only build evidence is recorded separately. Its review record SHA-256 is `680dcca27c61cd1c7f6635baada904279fbfe92e7f9ac355be93f44153c82b63`; it is not included in the repository.
