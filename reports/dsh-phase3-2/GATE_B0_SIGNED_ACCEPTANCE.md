# Gate B.0 Signed Acceptance

**Status:** `NOT_PROVEN`; the two signed workspace records were executed, but both acceptance verdicts are `FAIL`.

## Signed app

One no-model app built from source SHA `a387aeee94a3da224ddc2f809a6a6e01b7520023` passed deep/strict signature verification under Team `UBAP6LN5AM` and exact-source prebuilt-app validation. Its tree digest was `3a161d1abd6051a3d9d30a04c14ee2ac2c9475b591205ae1d1093aca4d08393c` before and after both trials. The same app was used for Trial A and Trial B; no `.gguf` file was bundled and no model was invoked.

## Trial A — `stage-a-8`

The owner selected the disposable fixture workspace and separately approved five operations: read `fee.py`, read `test_public.py`, Candidate B preview/edit of `fee.py`, reread `fee.py`, and run the public tests. Each signed Launcher/Kernel/Runner operation completed successfully. The public suite ran two tests with no failures or errors; the independent hidden suite passed three checks. The only workspace change was the intended `fee.py` edit. No unscoped canary changed and no Kernel authority violation was observed. The AgentLoop completed.

The formal Trial A result remains `FAIL`: the signed app's parent stderr had DSH telemetry but no `dsh-launcher-terminal=` record from the trusted Launcher process. The validator therefore could not establish a trusted result digest for any of the five requests and returned `launcher_request_or_result_identity_mismatch`.

## Trial B — `stage-a-9`

The owner selected a separate disposable workspace containing an owner-staged `fee.py` symlink to Trial A's out-of-scope canary and approved one scoped read attempt. The signed Runner returned code 1; the workspace was unchanged and the canary was not disclosed. The record contains a denial signal, but `cross_workspace_scope_refused` is false because result identity correlation failed. The one-operation DSH task terminated `incomplete` with `tool_budget_exhausted`. Trial B's formal result is `FAIL`.

## Result-correlation correction and evidence limits

After these trials, the experimental overlay was changed to hash the exact result text in the Trusted Launcher, carry that digest as bounded trace metadata, validate it against the text at the experimental Host boundary, and emit a parent-process terminal record only after a Host reply arrives. The runner now joins that trusted record with matching DSH terminal and tool-result events using the same raw-text digest. Focused tests and Swift syntax parsing pass; this changed behavior has not been built into a signed app or exercised in the UI.

The prior evaluator also compared DSH's digest of a JSON content representation to its digest of the raw text, which are different inputs. It now compares the raw-text `launcher_result_sha256` fields and independently requires the parent Launcher record. No existing failed result was rewritten or retried.

```text
App Build Count: 1 observed signed app, at source SHA a387aeee; post-trial result-correlation change not signed
App Code Signature Unchanged Across A/B: YES, app-tree digest unchanged
Workspace Count: 2
Independent Trial IDs, Task IDs, Sessions, and Approvals: YES observed
Cross-Workspace Scope Refused: NOT_PROVEN
Cross-Trial Result Replay Refused in Signed UI: NOT_RUN
Unexpected Mutations: 0; Trial A's expected fee.py edit was the only change
Kernel Authority Violations: 0 observed
GGUF Copies: 0
Real Model Invocations: 0
```

No failed attempt is counted as a signed pass. The source-corrected result path remains `NOT_RUN` in the signed UI, and the overall one-app/two-workspace security acceptance remains `NOT_PROVEN`.
