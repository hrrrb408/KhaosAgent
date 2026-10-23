# DSH Phase 2: Signed XPC Security Acceptance

Date: 2026-10-23

## Scope and result

The hostile Cordis plugin ran inside the real signed Khaos AgentHost XPC with
the pinned DSH runtime and Node.js v22.19.0. It attempted direct and child
process workspace reads and writes, dummy credential access, Kernel binary
write access, localhost and external TCP connections, and an over-limit
workspace scope proposal.

Result: PASS at Khaos source SHA
5abf5d34426304b77a0773c1b30eb8814f5aa44c, PR #41 base
b08ab11e01663d2b26304cb541efb5361dea0417, and DSH SHA
687f282e8625c6b8d11ff58211a90524be2e4317. The exact signed evidence is
[signed-xpc-attack-5abf5d3.json](signed-xpc-attack-5abf5d3.json).

Observed enforcement:

- Direct and child-process workspace reads and writes were denied. Starting a
  child process itself was allowed; its protected file operations remained
  denied.
- Dummy credential access was denied, and no credential-like environment key
  was present.
- Writes to the published signed Kernel binary were denied.
- Localhost and external TCP attempts returned EPERM; the parent observed zero
  local TCP connections.
- The oversized scope proposal was blocked before Launcher submission.
- External canaries and the Kernel hash were unchanged. Deep bundle signature
  verification passed, with Team ID UBAP6LN5AM for the app and all three XPC
  services.
- The signed app measured 198,808,888 bytes. Node RSS during the attack was
  52,871,168 bytes. The process scan found no Node process after XPC teardown.
  XPC service stderr is not captured by this harness, so Node spawn/stop event
  counts are null and are not treated as evidence.

This run requested no workspace Picker or Runner approval. It proves the
bounded hostile-plugin case in this signed macOS build; it does not prove
arbitrary same-UID host tampering, all macOS configurations, real-model
reliability, or production AgentHost replacement.

## Historical failures

All failed attempts remain retained under failed_attempts/. The most recent
harness-discovery failures were:

- cancellation-b32-97e192c.failed.json: the builder passed a
  CompletedProcess to JSON decoding instead of decoding stdout. The builder
  fix and regression tests are included in the current source.
- node-crash-recovery-2044205.failed.json: the actual DSH child crash and
  subsequent read succeeded, but the verifier expected an obsolete stop-reason
  string. The verifier now checks the observed dsh_runtime_failed event and
  verifies process cleanup.
- xpc-crash-recovery-c98dbfc.failed.json: the actual XPC failure and recovered
  read occurred, but the verifier expected an obsolete output string. The
  verifier now checks the observed xpc_transport_failure event.

These are FAILED_ATTEMPT records, not signed security passes. They are
preserved alongside earlier fixture and build failures.
