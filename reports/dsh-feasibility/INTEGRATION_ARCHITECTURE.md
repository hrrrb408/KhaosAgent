# Khaos × DeepSeek Harness integration architecture

## Scope and pinned inputs

This spike is based on Khaos PR #40 at `707395146bbaf6be9ac6f58ae1f538e443b064a8`, stacked on PR #39 at `dee62b20dc1acbd64b009d47c29dc3f42ba9fdde`. On 2026-10-20 both PRs were open Drafts; PR #39 was based on `feature/m8-5-2a4-trusted-approval`, PR #40 on `feature/m8-5-2a5-trusted-ui-cancel-implementation`, and `main` was `27ef0b4787f807fc76ffd7ba9cdb467ffc9a2f27`.

DeepSeek Harness was tested at `687f282e8625c6b8d11ff58211a90524be2e4317` (MIT). The signed runtime used the official macOS arm64 Node.js `v22.19.0` archive whose SHA-256 is `1c3a9e78da501bbc1f0c99fbbb69bb7c722bc7a9bf30128b21ea502f3905892a`. The full Node dependency tree was installed only in `/tmp/khaos-dsh-687f282`; it was not added to the Khaos checkout.

## Executed path

```text
Deterministic DSH AgentLoop + Cordis capability tool
              │ bounded JSONL proposal/result over stdio
              ▼
Node 22 child of the untrusted AgentHost XPC service
              │ AgentHostProtocol v9 / AgentHostActionOutput
              ▼
Existing Trusted Launcher → real approval UI
              ▼
Existing KernelProduction XPC → Seatbelt Runner → snapshot validation
              │ original bounded tool result
              ▼
AgentHost XPC → DSH tool result → next DSH model turn → final response
```

The test-only DSH tool accepts exactly `argv`, `readScope`, and `writeScope`, with bounds matching the existing AgentHost contract. It cannot call the Kernel, encode an approval, or submit `workspace.run`. The test-only Swift AgentHost replacement translates a proposal through the existing `AgentHostActionOutput.encodeAction`; the normal Launcher, its UI, existing XPC identities, Kernel ABI, Runner sandbox, and commit path remain in place. No Kernel RPC or authority field was added.

The actual signed run used a deterministic DSH model adapter. It proposed one read-only command against `fixture.txt`. The real Launcher displayed the command, workspace, exact readable file, empty write scope, and request digest. After the owner explicitly delegated the UI action, Codex clicked `Run once` through the UI. The Launcher submitted the original request to the real Kernel, which executed the Runner and returned its bounded result. DSH consumed that tool result and produced the final response. This is a real signed product-path roundtrip, not the headless mock-port test.

## Test-only packaging boundary

`tools/build_dsh_xpc_acceptance_app.py` snapshots the exact pinned Khaos sources, substitutes only `khaos/macos/AgentHost.swift` in the temporary source snapshot, bundles Node and the DSH entry point inside the test AgentHost XPC, signs the Node child with only the JIT entitlement it needs, then re-signs and verifies the enclosing product. The temporary build record labels the source policy `dsh-test-agenthost-override` and records all replacement and runtime hashes.

The normal `tools/build_macos_seed.py` path was also run after the test build. Its signed production-check app retained the original AgentHost source SHA-256 `685b92cec3427540d643c9fb7f0ac62235526a7fc4af09438cfe6b8edd6a7e1b`, had no test override field, and contained zero Node binaries. The production builder, production Launcher, Kernel, manifest, and ABI were unchanged. No environment variable enables the test Host in a production build.

## DSH lifecycle and boundaries

The DSH AgentLoop and Cordis runtime initialized from the pinned upstream packages. The adapter test registered and removed the capability tool, returned a bounded Launcher result to DSH, rejected an oversized scope before submission, stopped forwarding after a terminal result, forwarded DSH's abort signal to its port, and did not retry an uncertain bridge failure. In the signed XPC acceptance run, the DSH task completed after one tool result and the temporary Host process exited with the application.

`Cordis Plugin Loaded` remains distinct from `Khaos Candidate Admitted and Activated`. This spike did not expose Candidate lifecycle operations to DSH and did not implement Candidate installation, activation, evaluation, or rollback through DSH. The signed acceptance used one bundled test plugin; loading arbitrary on-disk plugin modules in the signed XPC product remains unverified.

## Change accounting

| Area | Result |
|---|---:|
| Production code delta | 0 files / 0 lines |
| Trusted code delta | 0 files / 0 lines |
| Kernel authority / ABI / workspace-scope delta | 0 |
| New trusted process, IPC operation, or persistent state | 0 |
| Test-only experiment and build code | 11 files / 2,076 lines |
| New production dependency | 0 |
