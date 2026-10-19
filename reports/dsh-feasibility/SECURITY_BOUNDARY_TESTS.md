# Security boundary and signed acceptance evidence

## Actual signed Khaos tool roundtrip

The signed test app was launched through Launch Services. Its outer app, Launcher, AgentHost XPC, KernelProduction XPC, and Snapshot Broker retained their existing `org.khaos.Seed*` identities under team `UBAP6LN5AM`. The test AgentHost XPC still required the existing Launcher signing requirement. The test Node child had only `com.apple.security.cs.allow-jit`; the AgentHost XPC had `com.apple.security.app-sandbox` and no network-client entitlement.

The real UI showed this proposal:

```text
argv: python3 -I -B -c "from pathlib import Path; print(Path('fixture.txt').read_text())"
readScope: ["fixture.txt"]
writeScope: []
```

The approval dialog request SHA-256 exactly matched the Launcher Task Record's `invocation_sha256`.

| Evidence | Value |
|---|---|
| UI decision | `Run once`; clicked by Codex under the owner's explicit delegation |
| Task ID | `61fc3fe4-e423-4c5e-87bd-b75e36365ed0` |
| Request ID | `3cf126512ae54a00bbae5494ec755959` |
| XPC connection ID | `bc13297d-d08a-4d81-af58-aa5bed88142d` |
| Workspace session ID | `35ad2e22-9594-4ca6-9599-d5e69bffe7e2` |
| Frozen invocation / approval SHA-256 | `a4291222bf4cd63b7fad46ed18fbfdd31b9ec32836e3c80a28b22fac2f1adc09` |
| Launcher approval | `approved_ordinary` |
| Kernel result | `output` |
| Runner | `completed`, return code `0` |
| Commit outcome | `committed`, with 0 added / 0 modified / 0 deleted entries |
| Workspace entries after run | `fixture.txt` only |
| Fixture SHA-256 before and after | `be8c63f4d2f7921580f5b9c34996445ef7c44c99c02dc7dbe3bebb503e3e9c7f` |
| DSH observation | Final DSH response included the actual bounded Khaos tool result and fixture output |

The approval actor must be represented accurately: the owner asked Codex to perform the UI action while observing on a phone; Codex selected the disposable folder and clicked `Run once` in the signed UI. The owner did not physically click the control. No approval boolean or result was synthesized in a test frame.

### Preserved failed attempt

The first signed integration attempt also received a real read-only approval and completed a Kernel `workspace.run` with return code `0` and an empty changeset. Its DSH result bridge failed with `dsh_invalid_result` because the test Host treated DSH's `AssistantMessage.content` (`ContentBlock[]`) as a string. The failure and execution result were preserved; the read-only fixture remained unchanged. The test bridge was corrected to join text blocks, then rebuilt and signed. The second attempt above completed the DSH result roundtrip. The first attempt is not counted as a pass.

## OS sandbox probe

The separate signed `KhaosDSHRuntimeProbe-Crash.app` ran the pinned DSH runtime and a hostile Cordis fixture under a real macOS App Sandbox. It observed:

| Probe | Observed |
|---|---|
| Node direct read of an unselected protected file | `EPERM` |
| Node direct write outside its container | `EPERM` |
| Node network connection | `EPERM` |
| Child process execution (`/usr/bin/true`) | Allowed |
| Child process read of protected file | Denied |
| Child process write outside its container | Denied |
| Credential-like environment variables | `0` |
| Intentional Node child termination and fresh child restart | Pass; parent survived |

This proves the reported OS restrictions for that signed App Sandbox probe. The hostile I/O and child-crash probes were not run from inside the Khaos AgentHost XPC service itself; do not attribute them to the actual XPC acceptance run.

## Adapter adversarial checks

The pinned DSH AgentLoop test exercised five cases: bounded tool proposal/result roundtrip, oversized-scope rejection before the Launcher port, no follow-up after terminal Launcher result, DSH abort propagation to the adapter port, and no retry after uncertain bridge failure. These tests use a mock port and prove adapter behavior only. They do not prove a signed cancellation or Kernel cancellation result.

## Explicitly not proven

- DSH's actual signed XPC child directly attempting protected workspace reads/writes or network access.
- Actual AgentHost-XPC child crash/restart and cleanup after XPC invalidation.
- Signed end-to-end DSH cancellation while a Khaos operation is pending, including Kernel/Launcher/DSH terminal consistency.
- Arbitrary external Cordis module loading under the signed XPC service.
- DSH-generated Candidate admission, activation, evaluation, or rollback.
- Real-model coding behavior.
- B32, B34, B39, or Technical Gate A. Their existing `NOT_PROVEN` status is unchanged.
