# Security Regression

## Authority and architecture delta

| Area | Phase 3.1 delta |
|---|---|
| Production code | 0 |
| Trusted runtime code | 0 |
| Kernel authority | 0 |
| Kernel ABI / IPC operations | 0 |
| Workspace scope authority | 0 |
| Production AgentHost / trusted runtime | 0 |
| New trusted processes | 0 |
| New persistent runtime state | 0 |
| Production dependencies | 0 |
| Experimental dependencies | 0; existing pinned DSH, Cordis, Node, and Python are reused |

The only protected-tree change is a build-governance digest refresh for the experimental signed-acceptance test that verifies the active Task ID is visible in the approval UI. The test remains classified as build-governance, not runtime TCB. The updated security declaration binds the test and manifest changes to the exact stacked base 391848b02a2ec4d095cef7f71f2e55947ec24b24. It does not approve production migration or substitute for review.

## Freeze evidence

After the manifest refresh:

- python3 tools/check_security_freeze.py: PASS; verified, zero sensitive runtime changes.
- python3 tools/check_security_freeze.py --base 391848b02a2ec4d095cef7f71f2e55947ec24b24: PASS; four declared protected governance paths, no runtime TCB or authority changes.

The actual Phase 3.1 Draft PR is stacked on PR #44's exact head 391848b02a2ec4d095cef7f71f2e55947ec24b24; GitHub's base-check workflow therefore checks that exact stacked head. PR #44 itself remains based on PR #43 at fd6747abd9ba785f784126dd848112cffa782163. This distinction is retained so a check against the stacked code base is not confused with the upstream target of PR #44.

The initial freeze invocation correctly failed because the protected test file had changed without refreshing its inventory digest. The fix updates only that existing test entry, the manifest's own baseline digest, and the fresh security declaration. No TCB hash or runtime security expectation was relaxed.

## Signed experiment evidence

Stage A used the real signed experimental app, AgentHost XPC, Trusted Launcher, Kernel, and Seatbelt Runner. It completed Read → Edit → Test on a disposable workspace with independent hidden verification. The canary remained unchanged, the workspace contained only the expected source edit, the Kernel digest was unchanged, and the app deep signature verified.

The eight real-model trials used the same signed build and local-only CPU model. Every actual workspace operation went through the signed Launcher UI and Kernel. Codex reviewed each operation against the frozen task policy: 30 were approved and executed; two in-scope but incomplete Task D edits were denied before Runner execution. Operator attribution is codex_agent / Owner-delegated disposable experiment / Owner Personally Clicked: NO. There were zero unauthorized approvals, zero out-of-scope proposals after corrected evaluation, zero unexpected workspace mutations, zero Kernel rejections, and zero Kernel authority violations observed.

The AgentHost and local llama.cpp child had no remote model route. Trial telemetry observed zero TCP connections and the API key was absent from retained logs. The model received only the frozen synthetic coding task and scoped workspace data.

## Adversarial coverage

The semantic-tool tests reject absolute, traversal, unlisted, overlong, permission-shaped, and symlink-alias paths before Launcher submission. They reject invalid edit parameters and hidden-test profiles, lower no model-controlled scopes, enforce the public test profile, and verify cancellation, unload, duplicate IDs, terminal state, and result continuity.

The canonical macOS suite additionally passed real XPC / Kernel / Runner checks including:

- hard-link and symlink targets preserving canaries;
- parent rename to symlink after read;
- path spellings and out-of-scope targets;
- a readable but non-writable target rejected at commit;
- snapshot reads that do not follow symlinks;
- hard links to files outside the workspace rejected;
- XPC peer identity, caller authority, scope, and Runner-source digest checks.

These inherited tests validate the existing enforcement path. No claim is made that an adapter path pre-check alone enforces symlink or inode security.

## Validation record

- Evaluator correction tests: 9 passed.
- DSH Model Bridge tests: 14 passed.
- Pinned DSH sandboxed Vitest suite: 21 passed.
- Canonical Khaos suite: 412 passed in 835.535 seconds on the final local rerun; exact pushed-head CI remains a separate check.
- Signed Stage A semantic workflow: PASS.
- Security Freeze: PASS after the test-only manifest correction.

## GitHub CI failure retained

The first `security-tests` run for report-only head `272089a3387e978a5be35913da2e38ed2a8d0df0` failed once in `test_xpc_sandbox_scope_peer_identity_and_service_container_identity`. The nested Kernel result was `sandbox_unavailable_probe_snapshot` during the cancellation probe, so the test did not reach its expected cancellation terminal. The same XPC test and all 412 canonical tests passed locally; the previous code/evidence head also had both GitHub checks green. There were no runtime-code changes between those heads. This points to an intermittent snapshot setup failure, but the precise environmental cause is not proven.

The focused local rerun passed (1 test, 112.870 seconds). The failed GitHub log and focused rerun record are retained locally with owner-only permissions and indexed by SHA-256. The full CI retry result for the final report head remains authoritative in PR #45; the failed attempt is not erased by a later retry.

Full raw trial JSON and compressed UI logs remain owner-only under reports/dsh-phase3-1/raw. The PR carries a hash-bound index and reports rather than repeated transcripts or local temporary paths.
