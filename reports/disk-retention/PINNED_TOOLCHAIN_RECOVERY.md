# M-Disk.1.1 Pinned Toolchain Recovery

Date: 2026-10-24
PR: #47, Draft
Starting HEAD: `5b2ef3eedaaa59392b6e710f87b4556c02cf8960`

## Result

The requested `pnpm 10.17.1` is **not the historical source pin**. Inspection of 18 distinct Khaos source revisions and the exact DSH checkout found `pnpm 11.28.5` in the shared signed-runtime probe; the acceptance builder imports that pin. No `pnpm 10.17.1` was installed or substituted. The earlier M-Disk.1 statement that the builder required 10.17.1 is corrected here; its report remains a dated historical snapshot.

| Input | Verified value | Evidence |
|---|---|---|
| Historical pnpm pin | `11.28.5` | Exact source pin and executable `--version` |
| pnpm release archive SHA-256 | `809b67a5e31e4fab0342c5bf069072dd597f9fec6714b3375cf15b25125f213e` | Official archive checksum |
| pnpm executable SHA-256 | `65cb7439d9b023b95d0e19d843adf14e0654426ef85ad4ecd33d58849315f669` | Standalone executable |
| Node | `v22.19.0` | Runtime reports exact version |
| Node archive SHA-256 | `1c3a9e78da501bbc1f0c99fbbb69bb7c722bc7a9bf30128b21ea502f3905892a` | `.tar.xz` archive used by builder; matches official `https://nodejs.org/dist/v22.19.0/SHASUMS256.txt` over HTTPS |
| Node executable SHA-256 | `0d005c18e095027ca8f9fe1cc1126f767ee4ad7b004f4d6fb781ec4228a7c5d1` | Extracted executable |
| DSH | `687f282e8625c6b8d11ff58211a90524be2e4317` | Clean checkout |
| DSH lockfile | `4637cca3b89c4c8d5a147321710e597aa62ec2444a3772ab542be5690893dfe4` | Unchanged before/after install |
| DSH package manager declaration | `pnpm@11.28.5` | Exact `package.json` |
| Frozen offline install | `PASS` | `pnpm install --frozen-lockfile --offline --ignore-scripts`; lock unchanged |
| Swift / SDK | Apple Swift `6.4` / macOS SDK `27.0` | Local toolchain |
| Signing identity | available; SHA-1 `81E5B3D53290732C30A9D823874EBAB6E947AB55` | Used by signed fixtures |

The verified values are recorded in owner-only `PINNED_TOOLCHAIN_VERIFICATION.json` (SHA-256 `26e55e025a0fabf091b59bdd87cc040dd30164323c392587c50e68c9aa1d113c`). The exact DSH checkout remained clean. The package install used `--ignore-scripts`; it did not edit the lockfile or global package-manager installation.

## Model and large-build boundary

Prior signed build records bind the model payload SHA-256 `fadc3e5f8d42bf7e894a785b05082e47daee4df26680389817e2093056f088ad` and size `18,556,689,568` bytes. Its protected source App still matches the prior device/inode/size/mtime metadata. The model payload was not rehashed in this phase. No GGUF or complete model App was copied or rebuilt.

Two previously recorded llama.cpp runtime identities were verified. The third historical runtime existed only inside its candidate App; its executable, required libraries, and notices were archived as deduplicated small inputs. Small signed acceptance Apps built successfully from the clean source worktree at the recorded Phase 3.2.2 HEAD; each was 199,182,311 bytes and contained no model. Deep bundle signature verification passed. This verifies the small signed build path and inputs; it does not prove a full historical model App rebuild. The Node archive checksum was compared with the official Node distribution checksum file; its GPG signature was not independently verified.

```text
Requested pnpm 10.17.1: UNAVAILABLE / NOT A SOURCE PIN
Historical source pin pnpm 11.28.5: VERIFIED
Node v22.19.0 and exact DSH checkout: VERIFIED
Large model bytes rehashed: 0
Full large model Apps rebuilt: 0
Small signed App deep signature: PASS
```

The small verification run left a 32 MiB clean detached source worktree and a 24 MiB verified Node toolchain/archive directory under temporary storage. They are not among the 27 historic candidates and were intentionally retained; this phase did not clean them.
