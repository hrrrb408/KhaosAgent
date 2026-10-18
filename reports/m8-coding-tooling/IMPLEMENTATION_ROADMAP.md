# Implementation roadmap

## M8.5.1 boundary

This phase is research-only. It adds offline prototypes/tests and documentation, with no production action change, trusted code, model call, prompt budget change or benchmark modification. The current recommendation is Candidate B with conditional security compatibility.

## Future implementation gates

### Gate 1: Host action shape

In a separate implementation change, add a strict edit-only shape to untrusted AgentHost parsing. Preserve all current action bounds and add no call, timeout, result or context budget. Test missing and extra keys, wrong types, empty path/oldText, invalid UTF-8 representation, path length, content size and malformed JSON. Lower only to the existing AgentShellProposal form.

Expected files: khaos/macos/AgentHost.swift, khaos/macos/AgentHostActionOutput.swift, and the existing AgentHost action-output probe/test. No production Launcher or Kernel file should change.

### Gate 2: Fixed edit adapter

Pass path, JSON-encoded oldText and JSON-encoded newText as separate printable single-line argv values to a fixed Python script; decode the text with `json.loads` and never generate Python source from model strings. Require one exact unique oldText match. Reject target absence, changed target text, duplicates, no-op edits, unsupported encoding and any encoded argv value above 4 KiB before touching the snapshot. Bound the model-facing fields using the exact nested JSON wire representation; JSON escaping can expand multiline content.

Choose a same-directory staging/replace approach only after a signed Runner test proves it works under the current Seatbelt policy and does not leave an out-of-scope temporary in the final changeset. Test interruption before and after replacement, nonzero exit, cleanup failure, newline preservation, Unicode, BOM, and a write failure. If no safe strategy fits the current process.exec path, defer implementation and propose a separate trusted design review; do not add Kernel ABI here by default.

### Gate 3: Existing approval and scope path

Build a deterministic Host probe that sends the edit through the ordinary Launcher once-only approval. Confirm the prompt displays the exact target, script, arguments and one-file read/write scopes. Denial must execute nothing. Approve a disposable fixture and verify the Kernel accepts the in-scope diff and rejects an out-of-scope sibling or hidden canary. Do not rely on lexical path rejection for security.

Use real macOS adversarial tests for traversal, symlink leaf and ancestor, hardlink/alias, rename races, stale source, scope widening, malformed paths and sandbox failure. Preserve existing tests and freeze governance. Test that the adapter cannot inspect a test path outside the target read scope.

### Gate 4: Deterministic coding-loop acceptance

Only after Gates 1–3, add a deterministic Model Probe fixture with a failing test, scoped inspection, one edit, a correction if required, and a focused retest. Keep the existing eight-call and byte budgets. Review each operation independently. Capture actual command return codes and changeset, and keep this acceptance separate from M8.4 outcomes. Do not modify the original benchmark.

### Gate 5: Separately authorized real-model evidence

A later experiment must preregister the task and input digest, provider/model, endpoint, output limits, scopes, call budget, candidate grading and stopping rules. Obtain separate authorization for external data transmission and for that experiment. Preserve deterministic Model Probe evidence separately. Do not treat a new tool's offline success as evidence of model improvement.

## Expected change accounting for a later B implementation

- AgentHost intelligence delta: new shape and fixed lowering.
- Trusted code delta: 0 if and only if the existing shell proposal, Launcher approval, Kernel ABI and changeset gate remain unchanged.
- New processes, IPC operations, persistent state and dependencies: 0.
- Action protocol: changes inside the untrusted model-facing Host schema; no AgentHostProtocol or Kernel ABI change.
- Required evidence: Host parser tests, full canonical suite, security freeze checker, real macOS Runner adversarial tests, then deterministic signed-product acceptance.
- Stop condition: any need to add a trusted permission, bypass Launcher review, expand scopes, or alter Kernel policy returns the work to architecture review.
