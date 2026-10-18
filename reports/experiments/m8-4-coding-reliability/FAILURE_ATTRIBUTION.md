# M8.4 failure attribution

## Formal a-01

Terminal evidence is complete: task_failed, invalid_model_output_shape, seven approved/executed read operations with return code 0, no source changes. There is no observed Runner execution failure, human denial, budget exhaustion or hidden-grader invocation failure in this attempt.

The fourth initial model response had seven of ten keys and omitted candidateDigest, generation and pluginInput. The existing one-correction-per-turn path recovered it and produced proposal 4. After operation 7, the eighth initial response had nine keys and omitted only text. Its correction contained only four keys, omitting text, pluginID, candidateDigest, generation, pluginInput and evolutionGoal; the Host rejected it and the Launcher saved the failed Task Record. No further proposal was approved or executed. Missing-text occurrence counts include both that initial response and its failed correction.

These fixed diagnostics establish the observed protocol failure stages. They do not expose the rejected action type or field values, so they do not prove C would accept the nine-key response. Seven successful reads establish tool execution, not correct localization or coding capability. No edit, model test or repair occurred; the coding outcome is NO_CANDIDATE. General coding reliability remains NOT_PROVEN; actual C protocol recovery is recorded separately below and the full registered comparison remains unfinished.

The long post-operation wait ended in actual shape-rejection evidence; it is not reported as a network timeout. Observation timeouts did not restart the process or repeat an operation. The original independent grader applied hidden tests to the unchanged baseline and completed with test return code 1. No hidden result was sent back to the model.

## Preserved preflight limitation

The deterministic zero-tool model returned text, but the existing Launcher prints neither Task Status nor Task Record when toolCalls is zero. The observer retained terminal_outcome_not_captured despite waiter exit 0. This is an existing terminal-evidence limitation, not failure to consume stdin, not a model protocol failure, and not task success. terminal-preflight-zero-tool.json preserves it. Separate signed one-operation normal and refusal preflights passed; no Launcher or success definition was changed. Formal zero-tool recordless outcomes remain incomplete.

Historical M8.2 attribution is background only and is excluded from all M8.4 denominators.

## Formal c-01

The actual terminal is budget_exhausted with complete evidence. Eight independently approved read operations executed, seven returning 0 and the src-directory request returning 1. Parent-process inspection confirms src is absent and the workspace remains at the clean baseline. Eight missing-text normalizations were fully accepted and bound to approvals/executions; there were no model shape failures or corrections. No source edit, model test or repair occurred. The original isolated grader completed with test return code 1 and no candidate paths. Coding outcome: NO_CANDIDATE.

This separates protocol and coding outcomes: C recovered eligible incomplete shapes and reached the eighth operation, yet still generated no code before the unchanged tool budget stopped the task. The observed path is insufficient to isolate planning, context, result truncation, localization or tool selection as a sole root cause. No extra budget, prompt hint or retry was introduced.
