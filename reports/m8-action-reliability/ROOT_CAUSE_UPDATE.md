# M8.3 Root Cause Update

Date: 2026-10-18

## Established evidence

M8.2 Attempt 02 used the real GLM-5.3 provider. Its seven approved Runner commands each returned 0, but the attempt did not edit source or run model-selected tests. The Launcher task record ended with invalid_model_output_shape. Sanitized Agent Host diagnostics from the adjacent run window report that both the initial response and the single correction omitted text. Those diagnostics have no formal Attempt ID and do not preserve the action JSON or its type, so the field-level attribution remains PARTIALLY_PROVEN; they do not prove that the omitted field was the exact response that produced the final task record.

AgentAction in khaos/macos/AgentHostActionOutput.swift has ten required fields: type, text, argv, readScope, writeScope, pluginID, candidateDigest, generation, pluginInput, and evolutionGoal. BigModelSession requests response_format=json_object. That asks the provider for a JSON object but does not declare these ten required keys or their types. AgentHost then checks the exact key set before JSONDecoder, and both the initial prompt and format correction require the same ten-field object. A missing key therefore fails before Action semantic validation; only one correction is allowed.

The evidence supports a narrow protocol mismatch: the model-facing contract requires an irrelevant empty text field for list and shell actions, while the observed diagnostics report that field missing. It does not establish that this mismatch explains every M8.2 coding failure. The actual Attempt 02 type and payload are unavailable, so only a bounded compatibility rule can be justified.

## Boundaries

The model output contract is distinct from trusted Launcher and Kernel authority. The change is confined to the untrusted Agent Host parser. It does not alter Action validation, Launcher approval, workspace scopes, Kernel ABI, or the Kernel's enforcement. No remote model call was made during M8.3.

## Conclusion

Candidate C addresses the specific missing-text shape when the action type is list or shell. It rejects missing text for final text, Plugin, and evolution actions, and it rejects every other shape mismatch. The M8.2 diagnosis remains partially proven; real-model coding reliability remains NOT_PROVEN.
