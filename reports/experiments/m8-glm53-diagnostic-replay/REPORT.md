# M8.2 GLM-5.3 Diagnostic Replay — Two Authorized Attempts, No Candidate

**Experiment status:** NO_CANDIDATE_PRODUCED; ATTEMPT_02_FINAL_HOST_OUTCOME_NOT_CAPTURED
**Formal replay attempts:** 2 of 2 explicitly authorized
**Action Contract root cause:** NOT_PROVEN
**Coding Reliability:** NOT_PROVEN

The original attempt stopped at workspace selection before Runner execution. The user later authorized exactly one additional replay. Attempt 02 reused the Hermes credential, received signed Launcher approval for the displayed BigModel data flow, selected the prepared disposable workspace, and completed seven separately approved tool operations. All seven returned code 0. The workspace stayed clean and no candidate code was produced. The final Host completion marker was not captured, so a successful app-process exit is not treated as task success.

The hidden grader was run once for attempt 02. It applied the frozen patch to an unchanged baseline copy, copied zero candidate paths, and the test command returned 1. This is baseline-failure evidence, not a coding-quality result for GLM-5.3.

## Environment and PR dependency

- Branch: experiment/m8-2-glm53-diagnostic-replay, based on exact PR #28 head fd21764381546140249d94fcf53f9737bc9d212f.
- PR #27 and PR #28 remain open and untouched.
- Separate PR #29 remains draft and unmerged; its base is PR #28.
- PR #29 head before this evidence update: 1250043596cf630c9508e238c79c200ff1fb02ef.
- Product: /Users/huangruibang/Applications/Khaos-M8.2-GLM53-Diagnostic-Ready.app; provider bigmodel-coding-plan, model glm-5.3, endpoint https://open.bigmodel.cn/api/coding/paas/v4/chat/completions.
- The Launcher displays BigModel GLM-5.3-Flash Coding Plan, stale relative to the selected model.
- Exact-SHA hosted security-freeze and security-tests checks passed on the previous PR #29 head; the canonical suite ran 341 tests in 833.316 seconds. Exact-SHA checks for this report update are recorded after the final report commit.

## Credential source

Attempt 01 did not use the requested Hermes credential source: its temporary launcher requested a secret through hidden Terminal input. The value was not retained, so its equality to Hermes cannot be verified.

For attempt 02, the one-time launcher loaded GLM_API_KEY from /Users/huangruibang/.hermes/.env, verified the configured base URL matched the experiment endpoint, and passed the key only in the signed app's Authorization-header environment. The value was not printed or written to evidence. This corrected the source for attempt 02; it does not retroactively verify attempt 01.

## Diagnostic-transport preflight

The signed experiment product passed deep signature verification, builder verification, and Launch Services bootstrap authentication for the Kernel and Snapshot Broker. The bounded Host diagnostic flag is enabled only in the experiment product; the ordinary builder remains default-off.

A disposable signed NSXPC fixture reused the exact Agent Host executable code from the signed product, preserved its App Sandbox and network-client entitlements, and supplied the opt-in flag through the per-service XPC environment. A signed Launcher-identity client sent a synthetic tool_result without a pending proposal. The Host returned invalid_request and emitted one 104-byte event, below the 512-byte limit, without synthetic canary text. No API request or workspace access occurred. This proves the signed Host diagnostic transport, not model behavior. The synthetic event is separately recorded in diagnostic-events.jsonl.

Attempt 02's OS unified-log capture stream was active but recorded zero matching real-attempt action-diagnostic events. See attempt-02-host-diagnostics.json. The synthetic preflight event remains separate from both model attempts.

## Frozen inputs and request configuration

- Task: runner-exception-classification.
- Prompt SHA-256: 7a86c99de62538d4c514cb0f5fa1dd31d747701be60f03c12d4a2420736810a2.
- Workspace baseline: 7b6af61b3925b28ef105ea521c49424344de04c5.
- Hidden-test patch SHA-256: 185ea8ada844d790c0d716b2d7d921c8c4e739b238baa5d1b7b325e6fc446e16; contents were not sent to the model and were applied only to isolated grading copies.
- Frozen request settings and budgets remained unchanged: temperature 1, top-p 0.95, reasoning max, thinking enabled with clear_thinking=false, JSON object response, non-streaming, 32,768 output tokens, 600-second timeout, and the original one-correction policy. Tool and Runner budgets were not increased.
- The second replay was a separately authorized formal attempt, not an automatic retry or fallback. The total authorized limit is two; no third attempt was made.

## Attempt 01 evidence

The signed remote-data prompt was approved. The model returned an initial response that the Host accepted as a valid list proposal. The Launcher then requested workspace selection; that selection was cancelled before any workspace content was read or any Runner operation was approved or executed.

- Formal attempt: m8-2-glm53-01.
- Model requests: at least 1; exact count after cancellation NOT_PROVEN.
- Task text was sent after approval; no workspace content was sent.
- Approved tool operations: 0. Runner operations: 0. Changed paths: none.
- The post-cancellation Host exchange is NOT_PROVEN because no response marker was captured.
- Hidden grading failed against the unchanged baseline copy, with zero candidate paths and test-command return code 1. This is not a coding-quality result.
- No retry or fallback occurred within attempt 01.

See attempt-01-summary.json and attempt-01-launcher-events.jsonl.

## Attempt 02 evidence

The user authorized exactly one additional replay after attempt 01 stopped. The signed Launcher displayed the BigModel GLM-5.3 endpoint and the task/workspace data categories, and the user authorized sending them. The prepared isolated workspace for attempt 02 was selected.

Seven local tool proposals were separately approved in the Launcher: two list operations and five shell operations. They inspected the tests and Khaos source areas, returned code 0, and produced 7,109 aggregate bounded result bytes. No model test command ran. The workspace remained clean, with no changed paths or candidate edits.

- Formal attempt: m8-2-glm53-02; exact start and end timestamps were not captured. The hidden grading completed at 2026-10-17T15:39:18.763849Z.
- Task text and bounded workspace results were transmitted only after signed Launcher approval and only for approved scopes.
- Hermes .env supplied the API key; its value was neither printed nor retained.
- Approved local tool operations: 7 total (2 list, 5 shell); all seven returned code 0.
- Runner shell operations: 5; cumulative Runner time NOT_CAPTURED.
- Model request count: at least 7 observed tool proposals; exact provider request count NOT_PROVEN.
- Agent Host action-diagnostic events: 0 matching real-attempt events.
- The Launch Services waiter returned 0. No final Host completion marker was retained, so this is not evidence that the task completed successfully.
- Candidate changes: none; the disposable workspace is clean.
- Hidden grading: hidden patch applied to the isolated baseline copy; 0 candidate paths copied; test command returned 1. Raw grader output and hidden patch contents are excluded from the PR evidence.

The sanitized sequence is in attempt-02-launcher-events.jsonl. Raw run files, including the grader copy and its logs, remain in the untracked run directory and are not staged.

## Independent hidden grading

Both formal attempts were graded independently against an unchanged frozen baseline copy because neither produced candidate paths. In each grading run the hidden patch was applied only to the isolated grader copy and the test command returned 1.

This records that the unchanged baseline fails the hidden test. It is not a coding-quality result for either M8.2 attempt. Raw grader output and hidden patch contents are not included in this report or PR evidence.

## Historical comparison and attribution

M7 GLM-5.3-Flash completed one approved list operation and ended with invalid_agent_action_wire_contract_after_correction. M8.0 GLM-5.3 completed six approved operations and ended with invalid_model_output_shape. Neither retained the rejected response fields.

M8.2 attempt 01's initial list proposal was accepted but the run stopped before workspace access. Attempt 02 had seven accepted tool proposals with successful return codes but produced no candidate and has no captured final Host completion marker. No action-shape rejection was observed in those seven proposals, but the full task outcome and terminal cause remain NOT_PROVEN.

Therefore:

- The historical M8.0 rejected fields and exact cause remain NOT_PROVEN.
- The observed M8.2 proposals did not reproduce a tool-shape rejection.
- Full-task non-recurrence is NOT_PROVEN because attempt 01 stopped early and attempt 02 has no captured final Host marker or candidate.
- No Action Contract, correction, context, planning, or code-understanding fix is justified by these incomplete/no-candidate outcomes.
- Coding Reliability remains NOT_PROVEN.

See comparison.json and failure-attribution.json.

## Validation

Before the model attempts:

- Focused Agent Host diagnostics probe: PASS, 1 test.
- Canonical suite: PASS, 341 tests.
- Security Freeze base-aware check: PASS, four declared protected changes.
- Security Freeze current inventory: PASS; independent Code Owner approval remains NOT_PROVEN.
- Signed product deep signature and builder verification: PASS.
- Launch Services Kernel and Snapshot Broker peer authentication: PASS.
- Frozen input integrity checks: PASS.
- Signed Host synthetic OS unified-log capture: PASS, one bounded 104-byte event; it was not a model event.

For attempt 02, the workspace was clean at start and after task termination; seven approved tool operations returned code 0; the one hidden grader run failed against the unchanged baseline with zero candidate paths. No production source was changed by this evidence update.

After recording the new evidence, report JSON/JSONL parsing, git diff --check, and both Security Freeze checks are rerun. Exact-SHA hosted CI for the resulting PR #29 head is recorded after commit and push. Full statuses are in validation.json.

## Change accounting

Production code delta on the experiment branch: untrusted AgentHost.swift selects GLM-5.3 for the replay; untrusted AgentHostActionOutput.swift emits the existing bounded and redacted diagnostics through opt-in OS unified logging. This follow-up changes only experiment reports and sanitized evidence.

Trusted code delta: 0.
New architecture concepts: 0.
New trusted processes: 0.
New IPC operations: 0.
New Khaos-owned persistent state: 0; macOS may retain opt-in bounded OSLog records under platform policy.
New dependencies: 0; OSLog is a system framework.
Runtime TCB delta: 0.
Removed duplication / abstractions: 0.
