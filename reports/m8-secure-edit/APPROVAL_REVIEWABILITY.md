# M8.5.2 — Approval Reviewability

Status: **PARTIAL; broad edit-input reviewability NOT_PROVEN**
Evidence refreshed: 2026-10-18

## Existing Launcher presentation

The trusted Launcher constructs a review string containing the selected workspace path, every proposed `argv` element, and the SHA-256 digest of the encoded Kernel invocation. It places that text in a selectable, non-editable scroll view and labels the alert to review the complete request. The same `AgentShellProposal` supplies the invocation and the displayed `argv`/scopes, so the intended reviewed values are the values passed to Kernel.

The fixed feasibility probe is bounded by the existing proposal checks: at most the existing argument/scope counts, each argument must pass the existing `reviewable` check, and the test asserts a maximum 1,024-byte Runner script argument and a maximum 4,096-byte argument. In v8, the actual signed Launcher displayed the workspace, complete argv including fixed script and JSON-escaped old/new values, exact `tags.py` read/write scopes, and digest `ac7c277dc46bc43aef330f48e8fe569612779c2ff78ad129022820189a0d1ce1`. The user authorized this exact local request; the Launcher recorded one **Run once** decision.

## What was and was not demonstrated

The v4 request expired without a decision. The v7 request executed but its parent test failed before final workspace checks because the harness looked for `EDIT_APPLIED` in the final Agent response instead of validating Runner stdout. The probe now validates the actual stdout marker. In v8, the corrected signed flow passed the parent checks for the exact committed path, file bytes and mode, temp cleanup, canary, and focused test.

The approval content includes the fixed script as an `argv` value and JSON-escaped text arguments. The v8 prompt supports review of this one short fixed replacement; refusal v2 displayed the same request and denied it without execution. The UI uses a scroll view; this avoids truncating the view to its initial viewport, but does not by itself prove that long or visually confusing source is practically reviewable. Inputs near the argument limit, multiline/Unicode material, and explicit display truncation have not been tested.

## Gate decision

Approval Reviewability: **PASS for display of the v8 fixed replacement; PARTIAL** for the complete contract; **NOT_PROVEN** for broad edit-input reviewability. Do not claim that all structured edits are fully reviewable.
