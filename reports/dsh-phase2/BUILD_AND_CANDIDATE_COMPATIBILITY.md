# DSH Phase 2: Build and Candidate Compatibility

Date: 2026-10-20

## Build separation

The production macOS Seed build remains on `khaos/macos/AgentHost.swift` and
`tools/build_macos_seed.py`. This experiment does not change the production
builder, production AgentHost, Kernel ABI, Kernel authority, workspace scope,
or production dependency set.

`tools/build_dsh_xpc_acceptance_app.py` builds a disposable signed acceptance
app. It starts from the PR #41 base `b08ab11e01663d2b26304cb541efb5361dea0417`,
requires a clean descendant source SHA, snapshots the sources, replaces only
the test app's AgentHost implementation, and signs the resulting bundle. The
override starts the pinned Node runtime inside the signed AgentHost XPC service.
It is not a production entry point and is not included in a production build.

The DSH source pin is `687f282e8625c6b8d11ff58211a90524be2e4317`. The test
bundle includes Node.js `v22.19.0` for macOS arm64, the bundled DSH runtime,
the Node license, DSH license, and DSH third-party notices. The Node executable
has the test bundle's `allow-jit` entitlement for V8; it receives no network
client entitlement. The test AgentHost retains App Sandbox. The signed attack
run measures actual bundle size and Node RSS rather than inferring cost from
source size.

The build record binds the exact Khaos source SHA, PR #41 base SHA, DSH SHA,
Node archive SHA-256, bundled runtime digest, test-only source hashes, and
signature identity. A test result is valid only for the exact SHA and build
record printed in that result.

## Capability path

The DSH Cordis adapter is an untrusted proposal bridge. It sends bounded
`argv`, `readScope`, and `writeScope` to the existing AgentHost action shape.
The Trusted Launcher still presents the existing approval UI, submits the
request over the authenticated Kernel path, and records the Kernel result.
The Kernel retains the current exact-scope and changeset checks. No DSH or
Cordis value grants authority.

The deterministic coding acceptance performs `Read → Edit → Test` using three
separately approved operations. The edit uses the existing constrained Runner
path. The signed lifecycle acceptance exercises the existing Candidate B
preview parser and fixed edit script; it does not add a new edit API or
permission.

## Candidate compatibility

Ordinary DSH/Cordis tools can be registered and removed inside the untrusted
AgentHost runtime. `ctx.plugin()` is only a Cordis registration event; it is
not Khaos admission, evaluation, owner approval, or activation. Unloading the
capability adapter unregisters its tool and prevents later submissions from
that tool instance. The adapter also checks its closed state after an awaited
Launcher result, so an in-flight late result is rejected after unload. Unload
cannot undo a Kernel operation that was already approved or committed.

The current Khaos Candidate ABI does not host a complete DSH Plugin runtime.
Any generated plugin that needs Khaos capabilities must continue through
Khaos Candidate admission, isolated evaluation, explicit owner approval, and
trusted activation. This experiment does not add a DSH Candidate ABI, expand
Plugin data visibility, or map Cordis lifecycle state to trusted lifecycle
state. Plugin-owned data and remote-model data flows retain their existing
boundaries.

## Evidence state

- Pinned DSH adapter tests: 9/9 passed on DSH SHA
  `687f282e8625c6b8d11ff58211a90524be2e4317`. The regression test confirms
  DSH's tool `ContentBlock[]` is unwrapped before the fixture inspects the
  structured Launcher result. The added Cordis lifecycle test confirms
  duplicate registration, unload, late-result, post-unload, and terminal-task
  behavior against the real pinned `ToolRuntime`.
- Signed Cordis lifecycle acceptance passed at Khaos source SHA
  `81923b77e0c632291cdc317e396a62edca75fba1`; see
  `cordis-plugin-lifecycle-81923b7.json`. The app, AgentHost XPC, Kernel XPC,
  and Snapshot Broker shared Team ID `UBAP6LN5AM` and certificate SHA-1
  `81E5B3D53290732C30A9D823874EBAB6E947AB55`. Deep signature verification and
  Node process-group cleanup passed. The check requested no Picker, proposal,
  or Runner approval, so it does not establish workspace-operation or XPC
  recovery behavior.
- DSH AgentHost runtime bundling: passed; output has no retained non-Node
  imports. Bundle SHA-256 is recorded by the build script at each signed run.
- Signed standalone runtime packaging smoke: `PASS`; app size 111,028,546
  bytes, Node RSS 55,590,912 bytes, Node and app Team ID `UBAP6LN5AM`, zero
  non-system Node dylibs, App Sandbox enabled, network-client entitlement
  absent, and Node's `allow-jit` entitlement present. The standalone signed
  app completed a real DSH adapter roundtrip and an intentional child
  termination. Its hostile OS probe was deliberately removed; this smoke test
  is not XPC isolation evidence.
- The real signed AgentHost XPC hostile-plugin attack passed on exact Khaos
  source SHA `a2765389989d7c4290eb754b459f2a516990d155`. Its record is
  `signed-xpc-attack-a276538.json`; it bundles the DSH runtime and Node
  `v22.19.0`, verifies deep signature, and records the measured app size and
  Node RSS. The attack's OS-enforcement results are detailed in
  `SECURITY_ACCEPTANCE.md`.
- The signed Read → Edit → Test app also built at exact source SHA `a276538`,
  but the owner could not select the disposable workspace. The run reached the
  Picker and timed out after 600 seconds with no workspace selection or Runner
  request. It is preserved as
  `failed_attempts/coding-read-edit-test-a276538.failed.json`, not as a
  completed workflow.
- Signed cancellation, Node crash/recovery, AgentHost XPC crash/recovery,
  coding completion, and fake-result acceptance remain incomplete. The
  workspace and crash-recovery commands require actual user Picker and
  approval actions; no click is simulated by these scripts. Cordis
  `plugin-lifecycle` is a separate non-interactive signed check. Preserved
  failed attempts are under
  `reports/dsh-phase2/failed_attempts/`.
- Production build separation is source-checked and will be rechecked in the
  final diff and Security Freeze report.
