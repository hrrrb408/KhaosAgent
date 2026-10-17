# Terminal Test Matrix

All offline parser/observer cases use synthetic inputs and are not counted as model coding success. The signed-product deterministic probe also reports `synthetic=true` for its task summaries.

| Scenario | Unit coverage | Signed-product coverage | Expected evidence |
|---|---|---|---|
| Final response after seven successful tools | Seven proposals, approvals, executions, results, accepted Host replies, Task Status and Task Record | Seven separately approved `/usr/bin/true` calls then deterministic final response | `task_completed`, seven zero return codes, synthetic marker |
| Task terminal says final response without text marker | Task Status/Record maps to final response while text-marker count remains zero | Signed seven-call scenario produced this exact output shape | `agent_final_response_observed=true`, `agent_final_response_marker=0`, `task_completed` |
| Initial Action shape rejection | Host event has fixed error/stage/key counts | Local llama probe rejects malformed output before Host Action parsing | `local_model_invalid_output` observed; no Task Record means outcome stays unknown; zero Runner calls |
| Correction requested and accepted | Independent event count | Not forced by the terminal observer | Correction event does not itself mark task complete |
| Correction rejected again | Error code and correction attribution | Synthetic summary/parser case | Launcher `task_failed` Task Record plus bounded correction events |
| Invalid JSON / malformed response evidence | JSON-stage event and error code are retained; raw output is discarded | Deterministic local-model rejection path | Local error observed, no Task Record; outcome is unknown, never inferred from waiter exit |
| Tool result then Host continuation | Proposal, approval, execution, returned result and Host reply have separate counters | Normal workflow includes repeated reviewed tool calls | No early terminal classification |
| Workspace Picker cancelled | Synthetic status and task record | Picker cancellation flow | `task_cancelled`, zero approvals/executions |
| Tool approval denied | Synthetic denial marker | Read approved once, deny next write | `task_cancelled`; no execution after denial |
| Tool budget exhausted | Eight-call boundary | Eight approved deterministic no-op calls; ninth is not approved | `budget_exhausted` |
| Agent Host termination | Process observation required by unit case | Kill signed Host during approved Runner operation and verify task stop/process exit | `agent_host_terminated`; not confused with task completion |
| Launcher waiter exits zero without terminal record | Explicit unit case | Snapshot after waiter completion | `terminal_outcome_not_captured` |
| Final text marker without Task Status/Record | Explicit unit case | Not needed in product flow | Final response observed; task outcome remains unknown |
| Capture process stops without terminal marker | Explicit unit case | Live observer exits on waiter completion or its hard wait bound | Unknown, never successful |
| Truncated input | Snapshot case hashes full file and records truncation | N/A | Observed class may remain, `evidence_complete=false` |
| Conflicting or duplicate terminal markers | Explicit unit case | N/A | Unknown, fail closed |
| Multiple attempts | Separate IDs and summaries | Per-task summary file | No cross-attempt state reuse |
| Hostile/unknown event text | Explicit canary case | Captured stderr is summarized through the allowlist | Canary and unknown fields absent |
| Event flood | 300 synthetic events | N/A | At most 128 live events plus one summary |

The exact signed-product invocation is the repository's documented deterministic coding acceptance command in `AGENTS.md`. It also exercises the existing hostile README, scope-denied canary, misleading test output, write denial, picker cancellation, budget boundary, and Host crash scenarios. The new seven-call case specifically covers the M8.2-adjacent final-response path without making a remote model request.
