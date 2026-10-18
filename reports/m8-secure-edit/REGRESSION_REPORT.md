# M8.5.2 — Regression Report

Status: **canonical suite PASS; signed staged-edit success PASS; complete Gate A NOT_PROVEN**
Baseline: PR #33 head `1d1457f43f788d30f6fa4f48890b900ef9406c07`

## Focused results

The focused headless staged-edit, Seatbelt, Launcher, workspace snapshot, alias, scope, cancellation, termination, and changeset-race tests listed in `RUNNER_FEASIBILITY.md` passed. After the refusal harness and cleanup fix, the full canonical suite passed: 381 tests, exit 0, 708.963 seconds. The focused `test_agent_host_model_probe_follows_coding_results_not_output_claims` also passed separately before the full run.

The v7 signed product displayed and executed one approved `tags.py` replacement, but the parent assertion failed before final-state verification. The corrected v8 signed product acceptance passed: one independent Run once decision, one Runner call, exit code 0, `added=0/modified=1/deleted=0`, exact `tags.py` scope, final bytes and mode verified, no temp residue, canary unchanged, only `tags.py` changed, focused parent test passed, complete Task Record, and deep strict signature verification. Evidence is in `gate-a-signed-runner-v8.json`. Signed refusal v2 also passed: one proposal denied, zero Runner calls, unchanged source and canary, and a stopped task. The enclosing signed XPC request-attack checks passed. The target-specific signed path/alias/race matrix remains NOT_PROVEN.

Both Freeze checks passed:

```text
python3 tools/check_security_freeze.py
security-freeze: verified; sensitive changes=0; independent approval is external

python3 tools/check_security_freeze.py --base 1d1457f43f788d30f6fa4f48890b900ef9406c07
security-freeze: verified; sensitive changes=5; independent approval is external
```

The canonical command `python3 -m unittest discover -s tests -v` completed on the latest code with 381 discovered tests, exit code 0, and a 708.963-second process duration. `git diff --check` and both current-tree and exact-base Freeze checks are being refreshed after the final security metadata edits.
