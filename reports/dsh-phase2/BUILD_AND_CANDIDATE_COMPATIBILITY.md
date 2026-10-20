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
that tool instance. It cannot undo a Kernel operation that was already
approved and committed.

The current Khaos Candidate ABI does not host a complete DSH Plugin runtime.
Any generated plugin that needs Khaos capabilities must continue through
Khaos Candidate admission, isolated evaluation, explicit owner approval, and
trusted activation. This experiment does not add a DSH Candidate ABI, expand
Plugin data visibility, or map Cordis lifecycle state to trusted lifecycle
state. Plugin-owned data and remote-model data flows retain their existing
boundaries.

## Evidence state

- Pinned DSH adapter tests: 7/7 passed on the pinned source tree.
- DSH AgentHost runtime bundling: passed; output has no retained non-Node
  imports. Bundle SHA-256 is recorded by the build script at each signed run.
- Signed standalone runtime packaging smoke: `PASS`; app size 111,028,546
  bytes, Node RSS 55,590,912 bytes, Node and app Team ID `UBAP6LN5AM`, zero
  non-system Node dylibs, App Sandbox enabled, network-client entitlement
  absent, and Node's `allow-jit` entitlement present. The standalone signed
  app completed a real DSH adapter roundtrip and an intentional child
  termination. Its hostile OS probe was deliberately removed; this smoke test
  is not XPC isolation evidence.
- Signed XPC attack, cancellation, Node crash/recovery, and coding acceptance:
  `NOT_RUN` until their individual signed acceptance commands complete. The
  coding and lifecycle commands require actual user Picker and approval
  actions; no click is simulated by these scripts.
- Production build separation is source-checked and will be rechecked in the
  final diff and Security Freeze report.
