# Experimental Artifact Dependency Audit

Audit date: 2026-10-24
Private cleanup manifest SHA-256: `0ef426ef069c0c8ed8a40183a411a4b580aeed7d3c3ccebc8e68f5b3ba75c131`

Exact local paths and Device/Inode values are intentionally kept in the owner-only manifest, not committed here.

## Three failed signed-model trials

Each trial's exact scratch root is present and has no open `lsof` reference. Its build record binds the same 18,556,689,568-byte model SHA, pinned DSH and Node archive, Khaos source commit, signing certificate SHA-1, Swift/SDK versions, and embedded XPC binary hashes.

| Trial | Khaos source SHA | Original failure JSON SHA-256 | Build-inputs SHA-256 | Evidence index SHA-256 |
|---|---|---|---|---|
| `phase32-stage-b-a-1` | `12ae44732ef591d5e5a0f6f56b820ecbdc730ea1` | `bce21ecc7b73b5ea916d494a50815125a8bf5e2129968ec64ed6858515f8626b` | `58eb6db6534886181d0b2c32c620530c98c5c86431659a28605be1468e6b2e92` | `09710a10d173f2288f1893197b8b83ce2ef42fd47c104355e2f8aa3410e60b8e` |
| `phase32-stage-b-a-2` | `566bc3ac251d86f096a4147fdb0953b7c195447f` | `a0e0b0835cd0c0808c5e3e8aa45e8410ae9afa4fa0bfd91195390558bc217584` | `175afeda8621308c12b0e3c149ac19a4002f1f18518394b49b0d2f4086ea3577` | `28b693846178246e128676a42644381d8714c9511f50b927a6290b243ed6b00f` |
| `phase321-focused-task-a-01` | `2a73f48d9291a11cbac3612410cbeb9e651cf540` | `12c6e2fbc7827425ed94395384eb7f462b924da5038d056a8aa90746dacf7e04` | `688540ffe8c3ce8db464021b5ca961e45ea22af25e6bea64080ed9716adb59af` | `b77ed629fa2f04edcb1641bd37a9b20dd5ee36ce3281cee10f15258cdb8a4e6e` |

For each, the owner-only evidence archive contains the original failure JSON, exact build-input record, bounded compressed Launcher stdout/stderr, task text, and non-canary synthetic workspace files. Each original JSON and build-input SHA was verified after copying. The archive excludes the signed `.app`, model, and canary contents. Total archive size is about 2.06 MB. The scanned logs, task text, and build-input records had no matches for the checked API-key, bearer-token, credential-like, home-path, or private-temp-path patterns. This is a bounded pattern scan, not a general secret detector.

The evidence supports the historical failure conclusions without retaining the full signed App. However, exact App rebuildability is **not proven** yet: the builder requires `pnpm 10.17.1`, while the locally available commands report `11.28.5` and `11.25.0`. Khaos commits, the clean DSH checkout at `687f282e8625c6b8d11ff58211a90524be2e4317`, the matching Node archive SHA, the signing identity, and Swift 6.4 / macOS SDK 27 are present. No alternate package-manager version was downloaded and no rebuild was attempted. Therefore these three items remain `UNRESOLVED`, not `SAFE_CANDIDATE`.

## Remaining scratch and protected artifacts

The other 24 exact scratch roots total 3.174 GB by `st_blocks`. They have no `lsof` reference, but their trial IDs, evidence records, and consumers were not mapped. They are `UNRESOLVED` and refused by dry run.

The pinned DSH checkout is a Git repository root and an input needed for future builds; it is protected inventory, not a cleanup candidate. The Node archive is likewise retained. The three Qwen model files and their two signed apps remain protected because their contents were not rehashed. The Phase 3 model source app remains protected and was not rehashed in this audit; its previously recorded model SHA and current inode/size/mtime identity are unchanged from the earlier audit.

No candidate reached `SAFE_CANDIDATE`. No file is confirmed to have no use. A later cleanup decision would require restoring or otherwise verifying the pinned package manager, rerunning a deterministic build-input check, capturing a fresh manifest, rechecking open references, and owner approval bound to that exact manifest SHA.
