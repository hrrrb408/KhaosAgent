# Semantic Tool Implementation

## Result

The Phase 3.1 coding path exposes three DSH Cordis tools: **read_file**, **replace_text**, and **run_tests**. They lower a task intent to the existing bounded Launcher proposal port. They add no Kernel operation, capability, scope authority, or direct workspace access.

The implementation is in:

- experiments/dsh-feasibility/khaos-semantic-tools.ts
- experiments/dsh-feasibility/khaos-capability-adapter.ts
- experiments/dsh-feasibility/dsh-agenthost-runtime.ts

DSH remains pinned at 687f282e8625c6b8d11ff58211a90524be2e4317. The semantic plugin registers its tools in the existing Cordis Tool Registry and uses the existing AgentLoop and Session.

## Lowering contract

| Tool | Model supplies | Adapter lowers to | Scope |
|---|---|---|---|
| read_file | One path | Fixed Python read script using python3, -I, -B, -c and the path as a separate argv item | Read scope contains only that path; write scope is empty |
| replace_text | Path, non-empty old text, replacement text | Existing fixed Candidate B edit script with exactly eight argv items: python3, -I, -B, -c, fixed script, target path, canonical JSON old text, canonical JSON new text | Read and write scope contain only the same allowlisted path |
| run_tests | The literal public profile | Fixed Python test runner that loads the one declared source module and test_public.py; it does not discover directories or accept a command | Read scope contains only the source and test_public.py; write scope is empty |

No model-supplied argv, shell text, working directory, environment, read scope, write scope, hidden-test name, or extra path is accepted. The fixed edit script comes from the signed experimental build configuration, not the model or task message.

The adapter checks exact object keys, types, UTF-8 byte bounds, relative path syntax, declared file membership, non-empty unique old text, non-identical replacement text, canonical Python-compatible JSON strings, and the fixed public test profile. It rejects unpaired Unicode surrogates and over-limit values before submitting a proposal. These are untrusted input checks only. The Launcher and Kernel remain authoritative for the actual request, scope, approval, execution, and commit.

Runner success requires both a successful Launcher result and return code zero. A non-zero test result remains a failure in DSH Session and can drive a repair turn.

## Registry and lifecycle

The existing AgentLoop is configured for one tool call at a time. The semantic plugin changes tool visibility through the existing Cordis registry restriction API:

1. Read phase exposes read_file.
2. Edit phase exposes replace_text.
3. Verify phase exposes run_tests.
4. A failed public test exposes read_file and replace_text for a bounded repair.
5. Completion or a terminal Launcher result exposes no tools.

Each task has an eight-operation limit, a three-write limit, and a three-repair limit. Tool call IDs cannot be reused. Only one Launcher operation may be in flight. Plugin disposal unregisters the tools and closes the proposal session. A late Launcher result after disposal cannot be committed to DSH Session or replayed as a new operation. Cancellation reaches the pending proposal through the existing AbortSignal path; the Kernel result remains authoritative.

This does not create a second tool framework. The pre-existing raw capability tool remains available to non-benchmark probes; the benchmark coding path selects the semantic plugin and does not expose the raw capability tool to its model.

## Signed deterministic integration evidence

The signed Stage A fixture completed one disposable Task A workflow through the real signed AgentHost XPC and Launcher:

- Trial: stage-a-20; Khaos source: a2800e00ae609a2f282f4595aff278cc1de62899.
- Actual model invocation: NO; this was the required deterministic DSH fixture.
- Semantic calls: read_file, read_file, replace_text, run_tests.
- Launcher/Runner path: three actual Runner operations plus the existing Candidate B preview for the edit.
- Independent hidden verification: PASS.
- Unscoped canary: unchanged.
- Unexpected workspace changes: zero.
- Unauthorized proposals and approvals: zero.
- Kernel digest before and after: identical.
- Signed UI operator: codex_agent; owner personally clicked: NO.
- Deep bundle signature verified; Team ID: UBAP6LN5AM.

The complete local record is reports/dsh-phase3-1/raw/stage-a-signed-semantic-fixture.json, SHA-256 9537902982a3b1041629c1f4db5e8ec9ff9b66d5b5e4829cbfe29602fa3095eb. The raw directory is owner-only. The deterministic fixture proves the signed tool chain, not real-model capability; real-model evidence is reported separately.

## Component verification

- DSH Model Bridge tests: 14 passed.
- Isolated pinned-DSH Vitest suite: 21 passed across two test files, with no /Users reads and no external network.
- Signed deterministic Stage A: PASS as described above.

No production AgentHost, Security Kernel, Kernel ABI, workspace authority, or production dependency was changed for this feature.
