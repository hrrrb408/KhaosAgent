# Signed acceptance plan

No opt-in interactive signed product acceptance operation was performed in this phase. The canonical suite separately ran its non-interactive signed product-bundle authentication/invalid-request check and disposable Runner fixtures. Existing one-time approvals are not reusable. No real GLM call, benchmark replay, or real user file is permitted.

## A. Preview acceptance

Build a signed fixture app after the trusted UI design is independently approved. Use a disposable fixture and a deterministic proposal. Before any Run once choice, record what the UI shows, exact argv/scopes/request digest, derived preview bytes, scroll/expansion completeness, control/bidi rendering, and the user's refusal. For overflow or parser mismatch, verify `PREVIEW_INCOMPLETE` and no executable approval path. A preview-only/refusal run should not execute a Runner.

## B. Cancellation acceptance

After a separately reviewed Launcher cancel path exists, test B32 cancellation after approval but before Runner start and B34 cancellation synchronized before and after the Kernel commit cutoff. Independently observe Runner count/process state, Kernel return/error, exact fixture hashes, Launcher terminal record, and Agent Host result. Include `commit_outcome_uncertain`; never treat Host exit or cancel request as proof of unchanged workspace.

## C. Security boundary acceptance

Verify exact request/scope binding, one independent decision per action, denial/no-run, stale approval/no-run, no widening, no unauthorized commit, unchanged Kernel ABI, and deep signature. Signed Runner operations need their own fresh per-operation approval. Do not automate a person clicking Approve/Cancel.

## Gate

No acceptance here lowers inherited B01–B39 L4 conditions. PR #36's short positive and historical refusal do not substitute for complex review, B32, B34, or a signed uncertain-outcome record.
