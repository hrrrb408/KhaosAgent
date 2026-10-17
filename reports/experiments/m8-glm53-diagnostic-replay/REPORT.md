# M8.2 GLM-5.3 Diagnostic Replay — Stopped Before Runner Execution

**Experiment status:** INCOMPLETE_STOPPED_BEFORE_RUNNER_EXECUTION
**Formal replay attempts:** 1 of 1 authorized
**Action Contract root cause:** NOT_PROVEN
**Coding Reliability:** NOT_PROVEN

The signed preflight gates passed and the user authorized one M8.2 replay. The signed Launcher's remote-data prompt was approved. The model returned an initial response that the Host accepted as a valid list proposal. The Launcher then requested workspace selection; that selection was cancelled before any workspace content was read or any Runner operation was approved or executed.

The one formal attempt is consumed. No retry or fallback was made. The post-cancellation Host exchange is NOT_PROVEN because no response marker was captured. Therefore this run proves the initial response was accepted, but it does not establish the completed task's behavior or resolve the M8.0 failure.

## Environment and PR dependency

- Branch: experiment/m8-2-glm53-diagnostic-replay, based on exact PR #28 head fd21764381546140249d94fcf53f9737bc9d212f.
- PR #27 and PR #28 remain open and untouched.
- Separate PR #29 remains draft and unmerged; its base is PR #28.
- PR #29 head before this evidence update: 8feff6a3348ec56a28c98ca3a0c5b5e2b1f25e42.
- Product: /Users/huangruibang/Applications/Khaos-M8.2-GLM53-Diagnostic-Ready.app; provider bigmodel-coding-plan, model glm-5.3, endpoint https://open.bigmodel.cn/api/coding/paas/v4/chat/completions.
- The Launcher still displays BigModel GLM-5.3-Flash Coding Plan, stale relative to the selected model.
- Exact-SHA hosted security-freeze and security-tests checks passed for the pre-evidence-update PR head.

## Credential-source deviation

The user had explicitly asked to reuse the existing Hermes credential. The temporary replay launcher instead requested a secret through hidden Terminal input. The Hermes .env was not loaded by that launcher. The supplied value was not retained, so its equality to the Hermes credential cannot be verified. The endpoint configured in Hermes matched the experiment endpoint, but that does not prove the key was the same.

This was an execution deviation. No credential value is included in repository artifacts. Because the authorized one-attempt replay has already reached the remote model, it was not repeated to correct the credential source.

## Diagnostic-transport preflight

The signed experiment product passed deep signature verification, builder verification, and Launch Services bootstrap authentication for the Kernel and Snapshot Broker. The bounded Host diagnostic flag is enabled only in the experiment product; the ordinary builder remains default-off.

The previously authorized stderr-redirection probes did not capture XPC Host stderr. The diagnostic path was changed to the existing bounded, redacted OS unified-log event. A disposable signed NSXPC fixture reused the exact Agent Host executable code from the signed product, preserved its App Sandbox and network-client entitlements, and supplied the opt-in flag through the per-service XPC environment. A signed Launcher-identity client sent a synthetic tool_result without a pending proposal. The Host returned invalid_request and emitted one 104-byte event, below the 512-byte limit, without synthetic canary text. No API request or workspace access occurred. This proves the signed Host diagnostic transport, not model behavior. The event remains separately recorded in [diagnostic-events.jsonl](diagnostic-events.jsonl).

The focused diagnostics test passed (1 test in 1.862 seconds), the canonical suite passed (341 tests in 696.520 seconds), and both Security Freeze checks passed before replay. Exact PR #28-head CI had passed security-freeze and security-tests. Independent Code Owner approval remains NOT_PROVEN in single-maintainer mode.

## Frozen inputs and request configuration

- Task: runner-exception-classification.
- Prompt SHA-256: 7a86c99de62538d4c514cb0f5fa1dd31d747701be60f03c12d4a2420736810a2.
- Workspace baseline: 7b6af61b3925b28ef105ea521c49424344de04c5.
- Hidden-test patch SHA-256: 185ea8ada844d790c0d716b2d7d921c8c4e739b238baa5d1b7b325e6fc446e16; contents were not sent to the model. It was applied only to the isolated grading copy.
- Frozen request settings and budgets remained unchanged: temperature 1, top-p 0.95, reasoning max, thinking enabled with clear_thinking=false, JSON object response, non-streaming, 32,768 output tokens, 600-second timeout, and the original one-correction policy. Tool and Runner budgets were not increased.

## Attempt evidence

The captured Launcher event sequence is recorded in [attempt-01-launcher-events.jsonl](attempt-01-launcher-events.jsonl). It shows remote-data approval, an accepted list proposal, workspace-picker request, cancellation, and a cancelled list result.

- Formal task attempts: 1.
- Model requests: at least 1; the exact count after cancellation is NOT_PROVEN.
- Task text was sent after approval. No workspace content was sent.
- Workspace selection was cancelled before a listing or read.
- Approved tool operations: 0.
- Runner operations: 0; Runner time: 0 seconds.
- Candidate changes: none.
- No retry or fallback.
- OS unified-log capture was active, but it observed zero matching real-attempt action-diagnostic events. The initial list action was accepted; the zero-event result does not resolve the post-cancellation exchange.
- The earlier synthetic preflight event remains separate and is not model evidence. See [attempt-01-host-diagnostics.json](attempt-01-host-diagnostics.json) and [diagnostic-events.jsonl](diagnostic-events.jsonl).

The model accepted the first action shape. This is evidence against an initial-response shape failure for that response only. It is not evidence that the full task completed without a later shape or correction failure.

## Independent hidden grading

The grader applied the frozen hidden-test patch to an isolated copy of the frozen baseline. There were no candidate paths to copy. The test command returned 1.

This records that the unchanged baseline fails the hidden test. It is not a coding-quality result for GLM-5.3, because no candidate code was produced. Raw grader output and hidden patch contents are not included in the PR evidence.

## Historical comparison and attribution

M7 GLM-5.3-Flash completed one approved list operation and ended with invalid_agent_action_wire_contract_after_correction; M8.0 GLM-5.3 completed six approved operations and ended with invalid_model_output_shape. Neither retained the rejected response fields.

M8.2's first response was accepted as a list proposal, but the run stopped before workspace access and Runner execution. Its post-cancellation Host exchange is unresolved. Therefore:

- The historical M8.0 rejected fields and exact cause remain NOT_PROVEN.
- M8.2 did not reproduce the shape rejection in its initial response.
- Full-task non-recurrence is NOT_PROVEN.
- No Action Contract, correction, context, planning, or code-understanding fix is justified by this incomplete replay.
- Coding Reliability remains NOT_PROVEN.

See [comparison.json](comparison.json) and [failure-attribution.json](failure-attribution.json).

## Validation

Before the model attempt:

- Focused Agent Host diagnostics probe: PASS, 1 test.
- Canonical suite: PASS, 341 tests.
- Security Freeze base-aware check: PASS, four declared protected changes.
- Security Freeze current inventory: PASS; independent Code Owner approval remains NOT_PROVEN.
- Signed product deep signature and builder verification: PASS.
- Launch Services Kernel and Snapshot Broker peer authentication: PASS.
- Frozen input integrity checks: PASS.
- Signed Host synthetic OS unified-log capture: PASS, one bounded 104-byte event; it was not a model event.

After recording this outcome:

- git diff --check after report update: PASS.
- JSON and JSONL report artifacts parse: PASS.
- Security Freeze base-aware and current-inventory checks after report update: PASS.
- Exact-SHA hosted CI on commit 6a93d395c8a4bb70921520a6135ad8bc2e2dbc01: security-freeze PASS and security-tests PASS; the canonical suite ran 341 tests in 801.155 seconds.
- This follow-up records the completed check result and changes only report artifacts; exact-SHA checks for its resulting PR head are tracked on PR #29.

Full statuses are in [validation.json](validation.json).

## Change accounting

Production code delta on the experiment branch: untrusted AgentHost.swift selects GLM-5.3 for the replay; untrusted AgentHostActionOutput.swift emits the existing bounded and redacted diagnostics through opt-in OS unified logging. This evidence-only update changes no production source.
Trusted code delta: 0.
New architecture concepts: 0.
New trusted processes: 0.
New IPC operations: 0.
New Khaos-owned persistent state: 0; macOS may retain opt-in bounded OSLog records under platform policy.
New dependencies: 0; OSLog is a system framework.
Runtime TCB delta: 0.
Removed duplication / abstractions: 0.
