# Gate B.0 Signed Acceptance

**Status:** `BLOCKED`; corrected one-app/two-workspace UI acceptance has not started.

## Signing and prebuilt validation

The corrected-source no-model app built at `520d659903fce78b489452bb5316f349f163e33f` passed deep/strict signature verification under Team `UBAP6LN5AM` and the runner's exact-source prebuilt-app policy. Its app tree digest before any trial was `cfa5f75d08e629a3753d203844beda4f8002149028a22d87aa9f7a4643fd3521`. The bundle contains no `.gguf` file. This establishes one signed app build, not a signed workspace operation or an accepted two-trial pair. A subsequent report-only commit changed `HEAD`; because the signed receipt pins the exact Khaos SHA, this prepared app cannot be reused for a trial at the new head. A new acceptance app must be built once from the final source SHA before Trial A and reused unchanged for Trial B.

## Preserved attempts

- An earlier `stage-a-2` launch reached the signed workspace-picker request but selected no workspace. It performed zero operations and is a failed attempt.
- Trial A `stage-a-3` used the pre-correction app. The owner selected a disposable workspace and approved one scoped `fee.py` read. The Kernel/Runner request completed with return code 0, the workspace and canaries remained unchanged, and no model was invoked. The Host then returned `invalid_request`. The runtime identity was verified before approval, after approval, and after the Kernel result, but the Launcher result digest could not be joined to a delivered DSH result; the trial is `FAIL`.
- Trial A `stage-a-5` used a fresh app built from `c9350d0`. It completed one scoped `fee.py` read with return code 0, but stopped before DSH result delivery with `dsh_runtime_exchange_invalid_frame`. It made no workspace changes and invoked no model; the app tree remained stable. The runtime identity was verified at all three Launcher checkpoints.
- Static inspection identified both causes. First, the signed experimental Launcher attached `runtime_trial_id` to its bounded tool-result trace while the experimental protocol overlay rejected that required field as an unknown key. After that was corrected, DSH emitted `LAUNCHER_TERMINAL_RESULT_DELIVERED` telemetry containing the same runtime trial ID, but the experimental Swift Host and Launcher-client telemetry allowlists omitted it. `DSHRuntimeProcess` therefore rejected the telemetry frame. The Host and client telemetry filters now allow the field only on that terminal event and validate its UUID shape. A corrected-source signed app was built and validated; its workspace trials have not started.
- The failed workspaces, apps, logs, and reports remain preserved; they are not reused.
- No corrected-source trial was launched. During preparation, a separate Khaos acceptance app had an open “Choose Khaos Workspace” Picker. The repository acceptance instructions prohibit running another Khaos Picker concurrently. The Gate B app was left unlaunched, so no workspace was selected and no operation approval was issued for it. In addition, per-operation workspace access approvals require action-time confirmation; the general task authorization is not recorded as a substitute for those UI approvals.

## Corrected signed trials

The corrected-source app build and exact-source validation passed. Trial A was not started, and Trial B has not started. Consequently, these acceptance values remain unproven:

```text
App Build Count: 1 corrected-source no-model app prepared; no accepted trial pair
App Code Signature Unchanged Across Accepted Pair: NOT_PROVEN
Workspace Count: NOT_PROVEN for corrected trials
Independent Trial IDs: NOT_PROVEN
Independent Workspace Sessions: NOT_PROVEN
Independent Approvals: NOT_PROVEN for corrected trials
Cross-Workspace Scope Refused: NOT_PROVEN
Cross-Trial Result Replay: NOT_ATTEMPTED_IN_SIGNED_UI
Unexpected Mutations: 0 in the failed stage-a-3 attempt only
Kernel Authority Violations: 0 observed in the failed stage-a-3 attempt
GGUF Copies: 0
Real Model Invocations: 0
```

No failed attempt is counted as a signed pass. After the existing Picker is resolved and the action-time confirmations are obtained, build one no-model app from the final source SHA, use it for Trial A's coding fixture, then reuse that exact verified app for Trial B's cross-workspace symlink refusal fixture. Each trial still requires a fresh user-selected workspace and independent approvals. No real model was invoked.
