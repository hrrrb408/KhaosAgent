# Gate B.0 Signed Acceptance

**Status:** `PARTIAL`; corrected one-app/two-workspace acceptance is pending.

## Signing and prebuilt validation

A no-model app built from the earlier implementation passed deep/strict signature verification under Team `UBAP6LN5AM`. The runner also verified its signed receipt, exact source identity, and prebuilt-app policy. Its app tree remained byte-for-byte stable during the attempt. The subsequent signed UI attempt exposed an experimental trace-schema mismatch, so this pre-correction app is not used to claim acceptance after the correction.

## Preserved attempts

- An earlier `stage-a-2` launch reached the signed workspace-picker request but selected no workspace. It performed zero operations and is a failed attempt.
- Trial A `stage-a-3` used the pre-correction app. The owner selected a disposable workspace and approved one scoped `fee.py` read. The Kernel/Runner request completed with return code 0, the workspace and canaries remained unchanged, and no model was invoked. The Host then returned `invalid_request`. The runtime identity was verified before approval, after approval, and after the Kernel result, but the Launcher result digest could not be joined to a delivered DSH result; the trial is `FAIL`.
- Static inspection identified the cause: the signed experimental Launcher attached `runtime_trial_id` to its bounded tool-result trace while the experimental protocol overlay rejected that required field as an unknown key. The trace schema and a regression test are corrected. The failed workspace, app, logs, and report remain preserved; they are not reused.

## Corrected signed trials

The corrected-source app build and Trial A have not yet completed. Trial B has not started. Consequently, these acceptance values remain unproven:

```text
App Build Count: NOT_PROVEN
App Code Signature Unchanged Across Accepted Pair: NOT_PROVEN
Workspace Count: NOT_PROVEN
Independent Trial IDs: NOT_PROVEN
Independent Workspace Sessions: NOT_PROVEN
Independent Approvals: NOT_PROVEN
Cross-Workspace Scope Refused: NOT_PROVEN
Cross-Trial Result Replay: NOT_ATTEMPTED_IN_SIGNED_UI
Unexpected Mutations: 0 in the failed stage-a-3 attempt only
Kernel Authority Violations: 0 observed in the failed stage-a-3 attempt
GGUF Copies: 0
Real Model Invocations: 0
```

No failed attempt is counted as a signed pass. The corrected acceptance will use a newly built no-model app for one Trial A coding fixture, then reuse that exact verified app for Trial B's cross-workspace symlink refusal fixture. The two trials require fresh user-selected workspaces and independent approvals.
