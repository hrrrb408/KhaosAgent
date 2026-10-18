# M8.4 build integrity

Group C source commit: db04df6c82ba11f1ba5f9d3156953b68a45c5e0a.
Group A source commit: 7f1399be6475a0e9db9893d557990565d0ff94c6.

A is a direct child of C with exactly nine lines removed from AgentHostActionOutput.swift: the reviewed missing-text normalization block. The AgentHost source, system/correction prompts, context implementation, protocol, Launcher, Kernel, Runner and builder are otherwise identical. Both use bigmodel-coding-plan, build version 1, the same signing identity, SDK, Python.framework and compiler configuration, and the same default-off diagnostic option explicitly enabled for these experiment builds. The per-file maps are build-sources-a.json and build-sources-c.json. Only the parser source hash differs.

Two independent signed products, GroupA.app and GroupC.app, passed deep strict codesign verification, the existing builder verifier and Launch Services bootstrap peer authentication. No signed product content was edited after signing. Signed and unsigned executable SHA-256 values and full build configuration are in build-integrity.json. Unsigned copies were made separately for comparison; originals were preserved.

The trusted Launcher, KernelProduction and KernelSnapshotBroker executable unsigned hashes are identical across groups. Of 3083 packaged Kernel/Broker files, 3081 are byte-identical; only the two signed executables differ, and their unsigned copies match. All entitlements are identical: only the untrusted Host has network-client permission. Signature/build-record identities are not claimed byte-identical.

Each original signed Host was copied unchanged into a disposable, separately signed preflight client. A synthetic tool_result with no pending proposal returned invalid_request and emitted one bounded 104-byte harness-state event in both groups. No API key, user turn, workspace content or model completion was involved. This verifies the actual signed Host/XPC diagnostic channel; it is not a formal model attempt. The signed parser probes additionally observed A's shape rejection and C's normalized acceptance, with diagnostics default-off and unchanged acceptance when enabled.

The first normal-terminal probe returned model text with zero tools. Existing Launcher code omits Task Record when toolCalls is zero; the observer correctly retained an unknown outcome despite waiter exit 0. terminal-preflight-zero-tool.json preserves this incomplete preflight. Separate one-operation product sessions now passed: the approved no-op saved task_completed and [0]; the denied operation saved task_cancelled with zero executions. Their synthetic summaries are terminal-preflight-normal.json and terminal-preflight-denial.json and are excluded from formal denominators. The Launcher is unchanged.
