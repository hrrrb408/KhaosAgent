# Cancellation and commit consistency report

## Current product behavior

The coding loop waits synchronously while `runAgentTool` presents approval and submits `runInKernel`; it has no user Cancel action connected to `workspace.cancel`. Thus there is no signed product path in which a user cancels an already-approved Agent operation. A declined approval stops before Runner and says the command was not executed; that is refusal, not cancellation.

When the Kernel returns an error, the Launcher preserves `process_cancelled`, `commit_rejected`, and `commit_outcome_uncertain`. Agent Host receives a bounded stop result and is told not to infer that no file changed. The Launcher does not issue a false “rolled back” statement. For `commit_outcome_uncertain`, however, the visible status is generic and the task record lacks a typed workspace outcome, so clarity is incomplete.

## Evidence

The inherited B34 tests cover pre-commit, READY-before-ACCEPT, late post-commit cancellation, and an uncertain commit at L3. The observed L3 result and final hashes agree for those fixtures. They are not signed Launcher/XPC task-cancellation records. A Host process exit also does not prove final workspace state.

## Disposition

No source-level false rollback was found. Signed Cancellation Consistency remains **NOT_PROVEN** because the product has no active-task cancellation route and no signed record covering a cancellation/commit race. This is a product capability/evidence gap, not a demonstrated Kernel transaction bug.

Minimum next step: separately review a trusted Launcher cancellation control bound to the active request id, then add signed B32 and B34 acceptance hooks that record Runner execution, Kernel result, final workspace hash, Launcher record, and Host result. Do not change Kernel commit authority or infer workspace state from the user's cancel label.
