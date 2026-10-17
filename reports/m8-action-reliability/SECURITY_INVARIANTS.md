# Security Invariants and TCB Accounting

Date: 2026-10-18

## Invariants preserved

- Missing text is normalized only after the parser sees the exact ten-field target minus text and a legal type of list or shell.
- text actions still require an explicit text field. Plugin and evolution actions still require it too.
- readScope, writeScope, argv, Plugin identity and digest, generation, pluginInput, and evolutionGoal are never defaulted by this change.
- Unknown keys, wrong JSON types, malformed JSON, unsupported types, and oversized inputs remain rejected.
- The normalized AgentAction goes through the existing Host semantic validator and the existing AgentHostProtocol reply encoder.
- User approval, Launcher-visible scope, Kernel scope enforcement, process separation, remote data flow, and Kernel ABI are unchanged.
- A denied action still stops the task; normalization does not create a retry or authority path.

The compiled adversarial probe covers missing sensitive fields, unknown keys, wrong types, invalid action types, incompatible Plugin and evolution fields, traversal scope strings, refusal, untrusted tool results, and size limits. The signed deterministic product acceptance additionally exercises the real product approval and Runner path, a scope-denied canary, user denial, the eight-call budget, Picker cancellation, and Agent Host termination during a scoped failing command.

## TCB accounting

Production code delta: 34 insertions and 12 deletions in untrusted Agent Host parsing; 7 insertions and 6 deletions in the evidence Observer. Net runtime Host change: +22 lines. The Observer is not shipped runtime code.

Trusted code delta: zero files and zero lines. AgentHostActionOutput is model-input handling in the untrusted Host; Launcher and Kernel did not change. The signed TCB manifest retains the same runtime entries as the exact PR #30 base.

New architecture concepts: none.

New trusted processes: none.

New IPC operations: none.

New persistent runtime state: none.

New dependencies: none.

Removed duplication or abstractions: no duplicate parser or runtime schema implementation was added. A, B, and C exist only as offline comparison branches in a test probe.

This evidence supports preservation of the current authority path for the tested cases. It does not establish new or broader security guarantees, and the real-model coding reliability result remains NOT_PROVEN.
