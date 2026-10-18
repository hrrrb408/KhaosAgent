# M8.4 coding reliability results

Three of four formal slots are complete. All three are **NO_CANDIDATE**. a-01 and c-01 have complete evidence; c-02 has complete terminal/grade evidence and incomplete Host diagnostic totals. a-02 is NOT_RUN. General Coding Reliability Closure: NOT_PROVEN.

The first actual model session executed seven independently owner-approved read operations, all with return code 0. There were no write scopes, source changes, model-initiated tests or repair operations. Parent-process inspection confirms the workspace HEAD still equals the frozen baseline and Git status is clean; candidate diff is zero bytes. The existing Kernel execution path returned all seven bounded results.

The actual Launcher Task Record reports task_failed / invalid_model_output_shape, with seven proposals, 62.530 cumulative Runner seconds and 5134 bounded result bytes. Waiter exit 0 is not counted as task success. The terminal, single Host association and diagnostics are complete.

The original independent grader completed in its isolated clone, applied the unchanged hidden patch, copied no candidate paths, and returned hidden-test command status 1 with no timeout. This is NO_CANDIDATE rather than a candidate test failure. No private grading output was returned to the model. Public grade.json contains only status, result codes and hashes.

Reading occurred, but bug localization quality is not independently established by the reads alone. Code editing, model testing, failure-driven code repair and a successful independent candidate verification were not reached. The terminal protocol failure ended this task before an eighth approved operation; it did not exhaust the eight-tool budget. This evidence does not establish planning as the sole cause.

All historical and deterministic runs are excluded. A future coding PASS still requires actual approved source changes through the existing trusted commit path, complete original hidden grading, no boundary violation and complete Task Terminal Evidence. No criteria or budget changed after a-01.

## Completed c-01

C executed eight independently approved read operations, with return codes [0,0,0,0,1,0,0,0]: seven successful reads and one failed directory request. The requested src directory is absent in parent-process inspection; the exact bounded error payload is not retained in public evidence. No write, source edit, model test or repair occurred. The baseline HEAD and clean Git status are verified after exit, and the candidate diff is zero bytes.

The trusted Task Record is budget_exhausted after eight proposals, 55.023 cumulative Runner seconds and 7506 bounded result bytes; terminal and diagnostic association are complete. Nine initial responses were accepted, including the final response after the eighth tool result; eight eligible list/shell responses required normalization. The original grader completed with hidden patch applied, no candidate paths, test return code 1 and no timeout. No grading feedback was sent to another model session.

C has demonstrated successful protocol recovery and more continued tool execution in this pair, but the additional execution remained reading. Neither actual source editing nor model testing, failure-driven repair or a valid candidate has been observed. Context, selection and planning causes cannot be isolated by these two attempts alone. Budgets and success criteria remain unchanged for the remaining two slots.

## Completed c-02 with interrupted collection

Seven separately approved read operations returned [0,0,0,1,0,0,0]. The fourth script used os.path.relpath; the next separately approved script removed it and returned 0. This is one observed read-command revision after a nonzero result, not source repair after a test failure. The exact command-error payload was not captured, so no underlying OS exception is asserted. No write, source edit, model test or code repair occurred; the parent verified the original baseline HEAD, clean Git status and zero-byte diff.

The original Launcher Task Record is complete and reports task_failed / invalid_model_output_shape. The collector/driver disappeared during an approximately four-hour execution-observation interruption while the signed product survived at its sixth approval. After reconnecting, the already approved operation 6 and separately approved operation 7 ran once, and the same product terminated. The final terminal was captured from the original stdout/stderr, with no new model session. The unchanged grader then completed in isolation, applied the original hidden patch, copied no candidate paths, and returned test status 1 without timeout.

The observed diagnostic rows include eight initial responses, seven accepted initials, one unused-field semantic rejection, one failed correction with only four keys and zero normalizations. Exact totals are NOT_CAPTURED because the original collector died and the historical OS query returned no rows for the gap. These observed values are not pooled into exact A/C response-rate denominators. The original waiter exit code is also NOT_CAPTURED. Task terminal and coding outcome are known; whole-attempt evidence is INCOMPLETE_HOST_DIAGNOSTIC_GAP.
