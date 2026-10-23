# DSH Phase 2: Build and Candidate Compatibility

Date: 2026-10-23

## Build separation and pinned inputs

The production macOS Seed builder and production AgentHost remain
tools/build_macos_seed.py and khaos/macos/AgentHost.swift. The experimental
builder, tools/build_dsh_xpc_acceptance_app.py, snapshots a clean descendant
of PR #41 base b08ab11e01663d2b26304cb541efb5361dea0417 and replaces only the
disposable test app's AgentHost implementation. The production builder,
production AgentHost, Kernel ABI, Kernel authority, workspace scope, and
production dependencies are unchanged.

The signed experimental builds use DSH
687f282e8625c6b8d11ff58211a90524be2e4317, Node.js v22.19.0 for macOS arm64,
and the archive SHA-256
1c3a9e78da501bbc1f0c99fbbb69bb7c722bc7a9bf30128b21ea502f3905892a. The
runtime is built from the pinned DSH checkout and its frozen lockfile; pnpm
11.28.5 runs with install scripts disabled. The signed app includes the DSH
runtime, Node license, DSH license, and third-party notices.

At the final signed acceptance source SHA, the attack build measured
198,808,888 bytes for the app and 52,871,168 bytes for Node RSS. Node's
allow-jit entitlement supports V8. The test AgentHost does not receive a
network-client entitlement. XPC spawn/stop event counts are unavailable
because the XPC service stderr is not collected; process scans directly verify
cleanup. Team ID UBAP6LN5AM and signing certificate SHA-1
81E5B3D53290732C30A9D823874EBAB6E947AB55 were verified across the app and
Kernel, Snapshot Broker, and AgentHost XPC services.

The build record binds the exact Khaos source SHA, PR #41 base, DSH commit,
Node archive, runtime digest, source inputs, and signing identity. Each signed
result has its own build record and bundle signature evidence.

## Capability and Candidate boundary

The DSH Cordis adapter is untrusted. It submits bounded argv and scope values
to the existing Launcher shape; the Launcher presents existing approval UI,
and the Kernel retains validation and commit authority. A Manifest or Cordis
registration does not grant capability.

Ordinary Cordis tools can be registered and removed inside the untrusted
AgentHost runtime. The signed lifecycle probe verifies duplicate registration,
unload, late result, post-unload calls, and terminal-task calls. Unload cannot
undo an already approved or committed Kernel operation.

The current Khaos Candidate ABI does not host a complete DSH Plugin runtime.
Any generated code that needs Khaos capabilities still requires Candidate
admission, isolated evaluation, explicit owner approval, and trusted
activation. This experiment adds no DSH Candidate ABI, no Plugin data
visibility, and no authority mapping from Cordis state.

## Validation

- Pinned DSH adapter and Cordis lifecycle unit suite: 9/9 passed.
- Acceptance builder and runner regression tests: included in the canonical
  Khaos suite; both focused groups passed before the full-suite run.
- Signed XPC hostile-plugin attack, Cordis lifecycle, Read → Edit → Test,
  fake-result, B32 cancellation, pre-commit cancellation, post-commit
  cancellation, Node child crash/recovery, and AgentHost XPC crash/recovery:
  all passed at Khaos source SHA 5abf5d34426304b77a0773c1b30eb8814f5aa44c.
  Per-run evidence is in this directory.
- Canonical suite and Security Freeze exact-base results are recorded in
  FINAL_DECISION.md after their final-SHA runs.
