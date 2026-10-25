# M-Disk.1.2/1.3 Signed Retention Safety Closure

Date: 2026-10-25
Branch: `chore/khaos-experiment-artifact-retention`
Khaos source under signed test: `cdc8f41867f7700ed482ae116e8486a2dc76a53e`
DSH: `687f282e8625c6b8d11ff58211a90524be2e4317`
Operator: `codex_agent`
Owner personally clicked: `NO`

## Signed identity and scope

All four runs used a locally signed `org.khaos.Seed` app. The recorded deep signature check passed; Team ID was `UBAP6LN5AM`, Node was `v22.19.0`, and no GGUF was bundled. Each run used a new invocation-owned disposable workspace and one synthetic command that printed a fake success marker then exited `1`. The signed UI approval was reviewed against the displayed task, request digest, executable and empty read/write scopes. Each Kernel record returned `output`, committed an empty changeset, and reported the actual Runner exit code `1`.

The real signed Launcher → Kernel → Runner execution is the execution evidence. Archive failure, identity substitution and process-reference results were injected by the experimental retention driver after that real result; they are not Kernel operations or Kernel enforcement claims.

| Scenario | Task / request / invocation digest | Retention result | Owner-only evidence SHA-256 |
|---|---|---|---|
| Evidence archive failure | `cfb04a2d-b8f8-4547-a27a-2b312633083e` / `ec5d2a466ec34cb19414a039dc24e8ec` / `adaad58956c1ba04d1450ba25225973a909e82294b2941001a576878acf20d69` | Injected archive interruption produced `INCOMPLETE`; automatic cleanup refused with `evidence_capture_incomplete`. The test-owned fixture was disposed only after the refusal and evidence capture were recorded. | `fb700db833e20a4dd8d89bd5d21ec22b4b4763ea6d5223aab0a89c25a64c342f` |
| Scratch identity substitution | `7e5ecb0c-81ff-40ad-9888-7e12c73def0f` / `b09d055c1539414bbebec4cc215fb5cb` / `90ada011f504971ebb1cc37048a7839223ed4c36cd694832d9578df6fae7e432` | Inode/path substitution refused as `scratch_identity_changed`; replacement marker remained unchanged. Test-owned originals and replacement were later disposed by identity-bound fixture cleanup. | `75485d383368048c4a388b5ea728330ac63f2929c11f66b9b60944a592a590f3` |
| Active process reference | `bad47a90-c394-4498-94c4-3ba86af2db2c` / `bafd2e3260b5438898cd6c6144bd4f81` / `99b3025d6f82b2726968b28515f9b475d4508907fc28dfe8320bb49f390146ee` | `lsof` reported PID `10988`; cleanup refused as `scratch_open_reference_referenced`. The synthetic process exited normally (`0`); no process was forcibly terminated. | `cd5a2e1328bcb814f7ea0073e090503d9f7890d55fa0fcd1109264d8a3ab0687` |
| Unknown process reference | `f1f261e5-c73c-4824-8783-095e8e3ec337` / `f1de9b395d524e758f200226e44ee04c` / `3d6b393cdf77f1e52d867cdd2696d8faaca0e2359370edc6d443ae8df2c153b5` | Controlled `UNKNOWN` injection refused as `scratch_open_reference_unknown`. A unit test also injects an actual `lsof` subprocess `OSError` and verifies `UNKNOWN` blocks cleanup. | `99ba0c4e47f23a1937e423563e511bab46c99fb079c901fc2da9d0b789ce8322` |

For every scenario, the test record states `historical_mutations: 0`, `historical_paths_accessed: false`, `forced_termination: false`, and `model_or_GGUF_bundled: false`. The runner result and cleanup decision were stored separately. A later cleanup of the test's own small temporary fixture does not change the recorded refusal at the retention decision point.

## Result and boundaries

```text
Signed Retention Lifecycle: PASS for the four exercised fault scenarios
Evidence Archive Failure: PASS (controlled post-run fault; cleanup refused)
Scratch Identity Substitution: PASS (replacement preserved)
Active Process Reference: PASS (real lsof reference; no kill)
Unknown Process Reference: PASS (controlled unknown + subprocess-error unit test)
Cross-Trial Cleanup: 0 observed
Historical Paths Accessed or Mutated: 0
Kernel Authority / ABI / Workspace Scope Delta: 0
```

This closes the signed lifecycle gap for those four conditions. It does not claim signed coverage of every possible crash/cancellation point, nor does it make historical artifact paths durable. Existing canonical tests continue to cover other runner lifecycle and security cases.

The implementation changes only experimental Python tooling and tests. No trusted code, production dependency, Kernel RPC, ABI, production AgentHost or sandbox policy changed. The signed runs prove the existing trusted path was exercised; retention checks remain in the untrusted experimental runner and are not part of the Kernel TCB.
