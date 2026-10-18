# Evidence Corrections

## Historical refusal label

The immutable `reports/m8-secure-edit/gate-a-signed-refusal-v2.json` contains `structured_edit_proposed: true`. The actual reviewed action was a test-only `type=shell` proposal using the fixed staged-replacement script; it was not a production Structured Edit action. The old JSON is preserved byte-for-byte (SHA-256 `f07a2dd6ac77f0df9dacb74fb3498b3311ada0bf60bd5b04b066cddac8a8d1fd`). The current harness names this evidence `staged_edit_shell_proposal_observed` and records `production_structured_edit_available: false`. No new signed refusal JSON was generated because repeating the UI action was not authorized or necessary.

## Test-only and terminal labels

- The deterministic model probe creates a Shell proposal; its result is not a production edit action.
- The parent process runs the focused tests. The report does not call that a model-initiated test run.
- A `task_completed` Launcher terminal record means the task reached that terminal state. It does not mean a coding objective, test suite, or hidden-test result was verified.
- The one-use signed replay used the deterministic test probe, not a real language model; it supplies no real-model coding reliability evidence.

## Temp-write injection typo

The inherited `write_failure` snippet contained `ndef fail_temp_write`, causing Python syntax failure before the injected writer was installed. An earlier nonzero-return assertion therefore did not prove that temp writing was reached, although it did prove no live mutation for that syntax-failure path. This branch corrects it to `def`, prints `INJECTED_TEMP_WRITE_FAILURE` inside the actual write hook, and asserts that marker before recording B08 PASS. The full corrected 15-test group and 394-test suite passed.
