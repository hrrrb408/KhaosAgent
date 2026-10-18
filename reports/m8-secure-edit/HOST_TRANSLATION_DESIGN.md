# M8.5.2 — Host Translation Design

Status: **test-probe design only; production translation NOT IMPLEMENTED**
Baseline: PR #33 head `1d1457f43f788d30f6fa4f48890b900ef9406c07`

## Translation target

If Gate A passes, the untrusted AgentHost should validate the four-field `edit` intent and lower it to the existing `AgentShellProposal` type. The translated proposal contains one fixed Python command plus the validated target, old text, and new text as separate JSON-encoded arguments. Its scopes are exactly `readScope=[path]` and `writeScope=[path]`.

The fixed script should reject non-regular files, missing or duplicate old text, and no-op replacements. It should build the complete replacement bytes before touching the target, create a random exclusive temporary file in the same directory, write and `fsync` it, then replace the target. It should remove a pre-replacement temporary file on failure. If cleanup fails, the existing exact-path changeset validator must reject the whole changeset; scope must not be broadened to accommodate the temp file.

## Existing probe boundary

The current deterministic probe in `tests/macos_xpc_probe/AgentHostSandboxModelProbe.swift` emits this kind of fixed Shell Proposal for a test fixture. This is build/test code, not the production AgentHost. `tests/test_macos_xpc_sandbox.py` exercises it through the existing real macOS Seatbelt Runner and Kernel commit path. No trusted Launcher policy, Kernel code, ABI, XPC operation, sandbox policy, scope enforcement, or production Agent Action changed.

## Result handling

The existing Launcher runs `process_exec(tuple(ARGV))` and calls `workspace_commit()` even when the command returns nonzero. Therefore a return code alone is not a safe outcome classifier. Any production adapter must use the returned bounded result together with the actual committed changeset and subsequent file read/test evidence. Pre-replacement failure must leave the target unchanged; post-replacement errors may still commit the complete target replacement.

## Gate status

The headless real-OS probe passes, and the signed v8 positive staged-replacement flow passed its parent-side final-state and focused-test assertions. Signed refusal v2 also passed with no Runner execution. The required edit-specific signed adversarial matrix remains NOT_PROVEN. This design must not be integrated into production until Gate A has a complete evidence-backed disposition.
