# Diagnostic Contract Fix

Date: 2026-10-18

## Change

The evidence Observer now accepts the current stage values emitted by AgentHostModelDiagnosticStage in khaos/macos/AgentHostActionOutput.swift. It preserves the existing sanitized event envelope and stores the stage name only when it is in the allowlist.

| Previous Observer name | Current Host name |
| --- | --- |
| model_content_size | model_content |
| model_json_syntax | action_json |
| host_action_validation | agent_action_validation |
| context_budget | context |

provider_request, provider_response, action_shape, action_field_types, and harness_state were already aligned. The Launcher-side host-response=invalid filter also recognizes the current client failure stages: xpc_transport_failure, host_returned_nil, launcher_reply_decode_failure, and unexpected_reply_type. Existing legacy aliases remain accepted so historical captures can still be interpreted.

The Host diagnostic output itself was not changed. Event contents remain bounded and sanitized; raw model content, unrecognized fields, unknown stages, and oversized events are excluded.

## Validation

The added Observer coverage verifies every current Host diagnostic stage, event and error categories, raw-content redaction, unknown-stage filtering, oversize rejection, current Launcher response stages, and retention of the action_shape evidence shape. The canonical suite result is recorded in OFFLINE_TEST_REPORT.md.

Runtime TCB delta: zero.
