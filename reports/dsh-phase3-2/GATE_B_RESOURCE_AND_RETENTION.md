# Gate B — Resource and Retention

## Frozen runtime preflight

| Input | Observed result |
|---|---|
| Active benchmark freeze | SHA-256 `8c9685aba296d83cb3dd522ff9e7957a3074837cefd746f310689bd29c567e43` |
| Holdout digest | `d163fd20cff2db44cb0dc5f5260542666b098bbce403a0aafd30fa8b3e46615d` |
| DSH commit | Upstream commit `687f282e8625c6b8d11ff58211a90524be2e4317` verified; local checkout not used |
| Node | `v22.19.0`; archive SHA-256 `1c3a9e78da501bbc1f0c99fbbb69bb7c722bc7a9bf30128b21ea502f3905892a` |
| Node binary | SHA-256 `0d005c18e095027ca8f9fe1cc1126f767ee4ad7b004f4d6fb781ec4228a7c5d1` |
| pnpm | `11.28.5`, executed under pinned Node |
| Candidate model | SHA-256 matches frozen value; size `18,556,689,568` bytes |
| Candidate app deep signature | FAILED: `CSSMERR_TP_NOT_TRUSTED` |
| Current code-signing identities | 0 valid identities |
| Canonical suite | PASS: 457 tests in 839.447 s; headless run, opt-in UI/model variables cleared |
| Security Freeze | PASS on default check and exact base `e27aed3ee3f40e7a008517ab7d8242bebe25a7c2`; sensitive changes `0` |

The Data volume had `475,136,000,000` available bytes at preflight. No app was built, no model was copied, and no trial workspace or trial output was created. Model/trial artifact growth: `0` bytes. Peak memory: `NOT_MEASURED`.

The first canonical-suite attempt inside the default outer Codex sandbox could not create APFS images because `hdiutil` reported that it could not start `hdiejectd` from a sandboxed app. The complete canonical command was rerun with only that outer sandbox restriction lifted; all 457 tests passed. Its owner-only log is `/private/tmp/khaos-gate-b-owner-only-20261025/canonical-suite.log` (mode `0600`).

The preflight stopped before artifact retention became a trial measure. No historical Scratch, model, or evidence file was deleted or modified. The owner-only preflight record is stored separately from this public report; it contains local paths and command outputs and is not committed.
