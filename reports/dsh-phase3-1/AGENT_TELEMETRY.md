# AgentLoop Telemetry

## Correlation chain

Phase 3.1 emits bounded structured events from the real DSH runtime. Each event is bound to the trial ID, DSH Session ID, benchmark task ID, monotonically increasing per-session event sequence, timestamp, and where applicable Agent turn, step, Model Call ID, Tool Call ID, and operation sequence.

For a submitted coding operation the recorded chain is:

MODEL_REQUEST_STARTED → MODEL_RESPONSE_RECEIVED → DSH tool output accepted → TOOL_CALL_PARSED → TOOL_ARGUMENT_VALIDATED → TOOL_PROPOSAL_LOWERED → LAUNCHER_PROPOSAL_SUBMITTED → Launcher approval event → Kernel operation event → LAUNCHER_TERMINAL_RESULT_DELIVERED → TOOL_RESULT_DELIVERED → SESSION_CONTINUITY_CHECK → AGENT_NEXT_TURN_STARTED.

The Launcher task ID, request ID, approval digest, invocation digest, Kernel outcome, Runner status, commit status, return code, and result digests link the DSH operation to the signed UI and Kernel record. The evaluator validates identity, digest equality, and event order. Session continuity is checked against the exact tool-result content and error bit stored in DSH Session; it is not inferred from a Launcher log line.

## Data limits

The telemetry schema is allowlisted and capped at 256 events per session. It records IDs, operation names, byte counts, file counts, digests, status categories, return codes, durations, and measured token counts where available. It does not record API keys, full prompts, file contents, credentials, or general plugin state.

Real-model data remained local. The model was a CPU-only llama.cpp child inside the network-denied signed AgentHost. The trial records report zero local TCP connections and no API-key value in the logs.

Full signed raw JSON and compressed Launcher logs are retained in this worktree under reports/dsh-phase3-1/raw with file mode 0600 and directory mode 0700. The committed reports carry their SHA-256 values and derived metrics, not repeated raw transcripts.

## Session evidence

Across the eight signed real-model trials:

- 32 semantic tool calls were parsed.
- 32 arguments were validated.
- 32 proposals were lowered and submitted.
- 32 terminal results were delivered to DSH Session.
- 32 of 32 results were observed in the next Agent turn.
- Session continuity was 32/32 (100%).
- There were zero model output-shape errors and zero semantic argument rejections.
- The Agent stopped after its final turn in every trial; no post-terminal tool call was observed.

Task C is the direct failure-repair proof. In both C trials, the first public test operation returned code 1 from the Runner. The exact failure result reached DSH Session and the next model turn. The model then proposed an edit; the signed Launcher and Kernel executed it; the next public test returned code 0; independent hidden verification passed. The two sequences were [1, 0].

The two Task D proposals were denied by the Codex experimental operator after review found that the proposed edit allowed whitespace-only names to normalize to an empty name. The in-scope edit request was structurally valid, so it is counted as an operator denial for task correctness, not as an unauthorized proposal. The denial result reached DSH Session, which made a final model turn and terminated without another tool call.

## Evaluator correction record

Raw evidence remains immutable. Two scoring defects were corrected through explicit reassessment sidecars:

- A1: the initial evaluator compared the Launcher result digest with the different DSH-normalized result digest. The archived Launcher digest is present and matches across terminal delivery and Session delivery. A1 is PASS after reassessment; the original JSON remains unchanged. Original evidence SHA-256: 992e8f9cf66d77ae8f17bcc27b7e3e7cf5f60bc66495ff7957a233c34457063b. Reassessment: reports/dsh-phase3-1/stage-b-a1-reassessment.json.
- D1: the initial evaluator counted a manually denied in-scope edit as unauthorized and used only continuable results as its Session-continuity denominator. The corrected evaluator distinguishes operator denial from unauthorized proposal, counts every terminal delivery, and checks that no tool call follows a terminal non-continuable result. D1 remains FAIL because the edit was rightly denied and hidden verification failed on the unchanged fixture. Original evidence SHA-256: 966f56746394c6eaf8f1685782870ca9ca5fc23932161f8a7b2785b2e2683401. Reassessment SHA-256: 32fc844d8d4ccd46e0f8745512a8744c4409eea9004d69131d6b6fb6d988d337.

The evaluator correction is analysis code only. It did not alter the model, prompts, task fixture, hidden tests, signed app, or raw evidence.
