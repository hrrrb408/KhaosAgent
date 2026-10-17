# M8.1 — Failure attribution

The table separates retained M8.0 observations from what source code can
classify on a future run. `NOT_OBSERVED` means this was not the terminal M8.0
failure; it does not claim the stage is impossible in another run.

| Failure class | Current attribution | M8.0 evidence / limit |
| --- | --- | --- |
| Provider request failure | Provider request/auth/rate-limit/timeout stage | Not recorded as M8.0's terminal status |
| Provider response failure | Provider response JSON/HTTP shape or incomplete `finish_reason` stage | Not recorded as M8.0's terminal status |
| Model content JSON failure | Non-JSON content stage, distinct from provider response parsing | Not recorded as M8.0's terminal status |
| Action shape failure | Exact key-set mismatch or non-object JSON | **Observed terminal code:** `invalid_model_output_shape`; exact shape details NOT_PROVEN |
| Action field-type failure | Exact keys decode but a value has the wrong Swift type | Not reported as M8.0's terminal code |
| Agent Action semantic failure | Host rejects unsupported type, unused fields, invalid action fields, post-tool action, evolution conflict, or repeated failed command | No action payload/error breakdown in M8.0 evidence |
| Harness state failure | Task/task-result transition or tool-call budget rejection | Not reported as M8.0's terminal code |
| Tool execution failure | Runner returns nonzero, timeout, cancellation, or Kernel error | Six M8.0 operations returned code 0; no such failure recorded |
| Context handling failure | History exceeds the bounded context or cannot retain required entries | No context trim/size event retained; causal role NOT_PROVEN |
| Coding quality failure | Required source change/test/hidden-test outcome is absent or incorrect | M8.0 changed no source, ran no model test, and hidden test exited 1; coding completion is NOT_PROVEN |

The existing terminal string is preserved as evidence. It is not reclassified
as a provider, context, or coding-capability failure. The correction-response
attribution remains a code-path inference; M8.0 lacks initial/correction event
records. The M7 `invalid_agent_action` and
`invalid_agent_action_wire_contract_after_correction` records remain distinct
from this M8 shape category.

## New opt-in classification map

The Host-only diagnostic maps failure outcomes to fixed stages:

| Stage | Examples |
| --- | --- |
| `provider_request` | `model_provider_failed`, `model_provider_timed_out`, auth/rate-limit/rejection |
| `provider_response` | `invalid_model_response`, `incomplete_model_response` |
| `model_content` | empty/oversized model content |
| `action_json` | `invalid_model_output_json` |
| `action_shape` | `invalid_model_output_shape`, with bounded key counts |
| `action_field_types` | `invalid_model_output_field_types` |
| `agent_action_validation` | Host's action/context checks |
| `harness_state` | task/tool-result transition or call-budget rejection |
| `context` | history budget failure |

Provider completion JSON parsing and model content JSON parsing are separate
stages. `finish_reason == "length"` maps to `incomplete_model_response`, while
the timeout maps to `model_provider_timed_out`. A Launcher refusal/cancellation
continues to be represented by the existing trusted `can_continue=false`
control; it is not inferred to be a Runner command failure.

Coding Reliability Closure remains **NOT_PROVEN**. A successful parsed action or
successful tool call alone does not establish source repair, a passing hidden
test, or complete task execution.
