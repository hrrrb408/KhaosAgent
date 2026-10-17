# M8.1 — Action Contract root-cause analysis

## Verdict

**Action Contract Root Cause: PARTIALLY_PROVEN.** The M8.0 run ended at the
Agent Host's exact-key Action shape gate with `invalid_model_output_shape`.
The run artifacts do not contain the rejected JSON, its missing or extra key
names, or a per-attempt correction event. The specific defect in that model
response remains **NOT_PROVEN**. Static control flow makes a correction-response
shape failure the likely terminal path, but the M8.0 record does not directly
attribute the stored error to `initial` versus `correction`.

No M8.1 remote model call was made. Historical evidence stays unchanged.

## Call path and boundaries

```text
Launcher user/tool_result frame
  → AgentHostProtocol frame validation
  → AgentHostSession state and bounded context construction
  → BigModelSession.complete (provider response JSON, finish reason, size)
  → model content JSON parse
  → exact ten-key comparison
  → AgentAction field-type decode
  → Host context/action semantic validation
  → AgentHostProtocol reply to Launcher
  → existing Launcher review and trusted Kernel operation
  → bounded tool_result marked as untrusted data
  → next Host turn (only when Launcher says can_continue)
```

The Host does not approve an operation or assign Kernel scope. It returns a
typed proposal to the existing Launcher. Tool results return through the same
Launcher path; the Host labels them untrusted and treats `can_continue` as
Launcher control data. The Kernel and ABI were not changed. Source references:
[AgentHost.swift](../../khaos/macos/AgentHost.swift) and
[AgentHostActionOutput.swift](../../khaos/macos/AgentHostActionOutput.swift).

The BigModel provider response has separate failure points: request/auth/rate
limit/timeout; malformed or unexpected provider response; `finish_reason ==
length`; empty or oversized model content; invalid model JSON; non-object or
wrong-key-set shape; and field-type decode. After decode, Host semantic checks
reject unsupported action types, incompatible fields, invalid scopes/arguments,
post-tool actions when continuation is denied, prohibited evolution routing,
and repeated failed commands. These errors do not represent Kernel execution
failures.

## M8.0 and M7 evidence

M8.0's formal GLM-5.3 run used one original coding task. It recorded six
approved, read-only Runner operations, all with return code 0; it recorded no
source changes, no model-run test, and an empty candidate diff. The final
Agent Host status was `invalid_model_output_shape`; the independent hidden test
returned 1. Thus the run proves a terminal shape rejection after successful
read-only work. It does not show the rejected fields or prove whether output
shape, context, model planning, or schema design caused the response.

M7 provides two separate records for the same original task. `planning-v2-01`
and `m7-2-context-01` each recorded one approved `list tests`, return code 0,
1,541 bounded result bytes, no source edit, no model test, and hidden-test exit
1. Their terminal Host categories differ: `invalid_agent_action` and
`invalid_agent_action_wire_contract_after_correction`. The rejected model
payloads were not retained, so their exact fields are also NOT_PROVEN. Neither
M7 category should be relabeled as M8's shape failure.

The full M8.0 report bundle is present on the still-open [PR #27 at its recorded
head](https://github.com/hrrrb408/KhaosAgent/tree/5acf90bcc0ff02e764e84150ebcebe91536ebc26/reports/experiments/m8-glm53-coding-baseline):

| Artifact | State on PR #27 head |
| --- | --- |
| `REPORT.md` | Present |
| `benchmark-result.json` | Present |
| `comparison.json` | Present |
| `experiment-config.json` | Present |
| `evidence/agent-events.jsonl` | Present |
| `evidence/run.json` | Present |
| `evidence/grade.json` | Present |
| `security-audit.json` | Present |

These files are not in this M8.1 checkout because PR #27 is not merged into
`main`; their absence here is an expected branch relationship, not missing
historical evidence. M8.1 neither checks out the experiment as its base nor
changes that PR.

## Correction analysis

The existing BigModel path allows one correction only for model-output format
categories. It asks for one raw JSON object with the same ten keys and types,
does not submit or execute the rejected action, caps the correction at 1,024
tokens and the existing request deadline, and runs the corrected action through
the same Host validation and Launcher response path. There is no second
correction. Non-format provider errors such as timeout, authentication, and
incomplete response are not retried. The existing offline probe verifies the
single-correction contract and refusal text.

The original M8.0 evidence predates the new structured attribution and does not
record whether correction was requested or which correction check failed. The
stored terminal shape code plus current code path supports this inference: an
initial shape failure is eligible for the one correction; a terminal shape
failure can then arise if that corrected response also fails the shape gate.
This is not a recovered M8.0 response or a new model observation.

## Context and coding progression

Custom BigModel history is kept under an 8 KiB byte budget. The helper preserves
the system/original task and pins recent success/failure observations while it
trims older entries. A failed bound is a distinct context-budget error. Tool
results are inserted as explicitly untrusted text, and the trusted `ok` and
`can_continue` flags are described separately. The current product's BigModel
request is JSON-object mode; it does not request a provider-enforced ten-field
schema. These are static code facts, not evidence that the M8 context was
trimmed or that context caused the observed output.

Six successful read-only operations without an edit show that the run did not
reach a source-change or test-execution phase. Because the run terminated at
Action shape and the rejected response was not retained, this does not prove
planning failure, lack of write-scope comprehension, or inability to code. The
hidden-test failure measures the unchanged workspace and must remain separate
from Action Contract Reliability.

## Conclusions and next step

Proven: M8.0 terminated with an exact Action shape rejection after six approved
read-only operations; no code change or test execution occurred; the Host has a
strict ten-key gate and at most one format correction; no record exposes the
rejected keys. Inferred: the final shape status most likely came from the
correction response. NOT_PROVEN: which response fields were absent/extra, the
initial error subtype, a causal role for context, the schema's effect on GLM
quality, and coding reliability.

The next smallest step is to use the new opt-in Host diagnostic during a
separately authorized model run, then compare initial and correction categories
without preserving response text. Keep the existing Action Contract until such
evidence establishes a concrete defect. Any further remote run requires
separate authorization for the provider and data flow.
