# M8.1 — Minimal Action diagnostics

## Activation and output

New model-failure events are disabled unless the Agent Host process receives
`KHAOS_AGENT_ACTION_DIAGNOSTICS=1`. They are fixed-format lines on Host stderr;
there is no upload, new file, trace store, database, or protocol field. Default
runtime behavior adds no new diagnostic lines. Existing payload-free rejection
diagnostics remain unchanged.

Each new line is at most 512 UTF-8 bytes. Event and stage labels are closed
enums; error codes are restricted to at most 64 lowercase ASCII letters,
digits, `_` or `-`. Shape records contain the expected/actual key counts,
whether the root is an object, missing names only from the predefined ten-key
Action list, and the count (not names or values) of unknown keys. Non-object
JSON has no missing-key list. No raw response, unknown key name/value, prompt,
argv, workspace path/content, tool result, API key, or provider token usage is
written.

One Host session accepts at most eight user turns; each task allows at most
eight tool calls, so at most nine model responses per task. Each model response
can produce no more than an initial failure, a correction-request event, and a
corrected outcome. The existing correction path permits only one correction.
That bounds these events to 216 per session (8 × 9 × 3). The first harness
state rejection is logged once per Host session, for an absolute ceiling of
217 new events and 111,104 diagnostic bytes. Existing trusted Launcher budgets
continue to bound tool work. The diagnostics do not change those budgets.

## Events and classification

| Event | Meaning |
| --- | --- |
| `initial_response_failed` | Initial provider/model/action/validation response failed; includes `attempt=initial` and fixed stage/error |
| `correction_requested` | Existing single correction is about to run; includes only the fixed rejection category |
| `correction_response_failed` | Corrected response failed a provider, model, Host, or task-state check |
| `correction_response_accepted` | Corrected response passed Host validation and returned an action reply |
| `harness_state_rejected` | A user/tool-result task transition was rejected; `attempt=none`, stage `harness_state`; first such event per session only |

Stages distinguish provider request, provider response, model content size,
model JSON syntax, exact shape, field types, Host action validation, harness
state, and context budget. An API `finish_reason` of `length` is reported as
`incomplete_model_response`; a timeout uses `model_provider_timed_out`. Neither
raw provider body nor raw model content is emitted.

## Authority and data-flow boundary

Diagnostics are computed by untrusted Agent Host code from Host-local parsing
results. They do not affect response acceptance, approval, capability, identity,
scope, budgets, Kernel behavior, or Launcher control. A shape mismatch remains
rejected and the same existing one-correction rule applies. A corrected action
still traverses the normal Host validation and Launcher review path. No new
model call is made by the diagnostic code.

## Offline checks

The compiled Host helper probe verifies default-off behavior; opt-in event
attribution; each JSON/shape/type/size class; missing-known-key reporting;
unknown-key count without unknown name/value; invalid error-code filtering;
512-byte line bounds; one format correction; and no retry for provider or
incomplete-response failures. Signed-product regression covers the unchanged
Launcher approval and workspace behavior; no synthetic result is scored as a
real model coding success.
