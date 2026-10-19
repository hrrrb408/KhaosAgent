# Regression and Security Freeze Report

## Focused checks

- Production Launcher bundle build and the default signed Kernel XPC attack test: PASS. The test completed without Picker/UI acceptance or Runner start (47.475 seconds on the isolated rerun).
- `test_trusted_candidate_b_preview_parser_is_bound_and_fails_closed`: PASS (2.171 seconds).
- `test_launcher_workspace_command_cancellation_is_task_and_connection_bound`: PASS (1.249 seconds).
- `git diff --check`: PASS.
- The first signed-app build attempt caught two non-exhaustive test-probe switches after `cancelledBeforeSubmission` was added. Both probe mappings were updated, and the focused signed-app test then passed.

## Canonical suite

The canonical suite ran with `KHAOS_RUN_*`, `KHAOS_BIGMODEL_*`, and `*_EVIDENCE_PATH` variables removed so opt-in interactive and remote-model acceptances remained disabled:

```text
python3 -m unittest discover -s tests -v
Ran 398 tests in 833.887s
OK
```

The full suite includes real-OS Runner, workspace snapshot/commit, XPC peer-identity, and signed-product default source-digest checks. The `B34_POST_COMMIT_EVIDENCE` lines come from isolated automated workspace fixtures. No interactive signed-product Runner acceptance and no remote model call were run.

## Security Freeze

- `python3 tools/check_security_freeze.py`: PASS; `sensitive changes=0` after manifest verification.
- `python3 tools/check_security_freeze.py --base 12c75d75c1464aabd631b092e07903631f692ff6`: PASS; `sensitive changes=16` declared and reviewed.
- The two checks were rerun after the final Security Change Declaration and manifest digest update.

## Signed acceptance boundary

No new interactive signed-product Runner operation was run. The separately authorized earlier deterministic replay is preserved in `staged-edit-signed-replay.json`; it is protocol-feasibility evidence only and does not exercise this implementation's preview or cancellation UI. B32/B34/B38/B39 signed UI acceptance therefore remains `NOT_PROVEN`.

No GLM-5.3 or other remote model was called.
