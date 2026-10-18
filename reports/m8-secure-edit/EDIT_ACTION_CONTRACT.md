# M8.5.2 — Proposed Edit Action Contract

Status: **NOT IMPLEMENTED — Gate A is not proven**
Evidence refreshed: 2026-10-18
Baseline: PR #33 head `1d1457f43f788d30f6fa4f48890b900ef9406c07`

## Candidate model-facing shape

The reviewed Candidate B shape is a strict four-field JSON object:

```json
{
  "type": "edit",
  "path": "example.py",
  "oldText": "return old_value",
  "newText": "return new_value"
}
```

This is a design target only. The production AgentHost parser has not been changed and does not accept this Action.

## Required validation if Gate A passes

- Require exactly these four keys; reject unknown or missing keys.
- Require `type` to equal `edit`; require the remaining values to be strings.
- Reject empty or invalid path/text inputs, no-op replacement, absent match, and more than one match.
- Enforce bounded UTF-8 sizes using existing protocol limits; do not raise the current action, context, or tool budgets.
- Accept only one explicit relative target path. Derive `readScope` and `writeScope` from that exact target; never accept model-supplied scopes for this action.
- Treat `oldText` and `newText` as data passed in `argv`. Never interpolate either value into executable source.
- Lower the validated intent to exactly one existing `AgentShellProposal`. The Launcher still displays and separately approves the actual `argv`, scopes, workspace, and request digest.

Numeric limits and final error strings remain unspecified until an implementation can bind to the existing protocol ceilings. This report does not authorize changing those ceilings.

## Gate boundary

M8.5.2A has not yet demonstrated the complete signed Runner path. The implementation gate therefore remains closed. No production Edit Action or Host parser change is present in this branch.
