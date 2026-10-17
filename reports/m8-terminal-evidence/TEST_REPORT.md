# M8.2.1 Test Report

## Offline observer tests

Command:

```bash
python3 -m unittest discover -s tests -p test_agent_terminal_capture.py -v
```

Result: **PASS, 27 tests**. Coverage includes terminal/status parsing, seven successful tools followed by final response, final-response recognition through Task Status/Record without a `Khaos:` text marker, rejection of success claims embedded in stop text, Action-shape and correction attribution, user cancellation/denial, budget exhaustion, process-exit separation, missing/conflicting/truncated evidence, attempt isolation, raw-text canaries, event bounds, and snapshot/live CLI behavior.

The test itself uses only synthetic data and makes no model request.

## Signed-product deterministic acceptance

The updated documented opt-in command is:

```bash
KHAOS_RUN_PRODUCT_CODING_LOOP_UI=1 \
KHAOS_CODING_LOOP_EVIDENCE_PATH="$PWD/coding-loop-deterministic.json" \
python3 -m unittest discover -s tests \
  -p test_macos_xpc_sandbox.py \
  -k test_seed_app_builds_and_authenticates_its_kernel_service -v
```

This product acceptance requires manual workspace selection and individual tool approvals. Its deterministic seven-call scenario expects seven `/usr/bin/true` Runner results followed by a final response and terminal summary. The acceptance evidence must report `synthetic=true`; it is excluded from real-model quality claims.

Before the seven-call case, it sends one deterministic malformed local-model response through the signed product. The local model guard reports `local_model_invalid_output` before a Launcher Task Record is emitted; the summary must remain `terminal_outcome_not_captured`, record zero Runner operations, and avoid treating waiter exit code zero as success. The local product probe cannot reach BigModel's JSON/Action shape stages because it validates the complete Action before returning; synthetic bounded diagnostic tests separately verify `invalid_model_output_json`, `invalid_model_output_shape`, and failed correction attribution.

**Result: PASS** on macOS. The signed product was built and launched by the acceptance test; all manual UI decisions were reviewed against their exact argv and scope before approval. Runtime: 614.930 seconds. Sanitized evidence: [`signed-product-deterministic-attempt-05.json`](signed-product-deterministic-attempt-05.json).

The report confirms:

- malformed local-model output produced `local_model_invalid_output`, zero Runner operations, and no Launcher Task Record; its task outcome remained unknown despite waiter exit code zero;
- seven approved `/usr/bin/true` calls with empty read/write scopes were followed by `task_completed`; the Launcher status/record carried `final_response` while the `Khaos:` marker count was zero;
- the existing coding workflow made six reviewed calls, recorded return codes `[1, 1, 1, 0, 0, 0]`, changed only `tags.py`, and passed the parent-process retest;
- the denial, Picker cancellation, eight-call budget, and Host-termination checks passed. The ninth approval was not presented; the scoped Host-crash writeback was verified and both Host and command processes exited.

This is deterministic probe evidence, not model coding-quality evidence.

## Canonical and governance checks

| Check | Result |
|---|---|
| `python3 -m py_compile` for changed Python files | PASS after capture changes |
| Focused terminal capture suite | PASS, 26 tests |
| `python3 -m unittest discover -s tests -v` | PASS, 368 tests in 667.614s on macOS |
| `python3 tools/check_security_freeze.py` | PASS, current inventory verified |
| `python3 tools/check_security_freeze.py --base 3cdf26e1933dbcf9896dcd83a0cb6e05eadff92b` | PASS, 7 exact sensitive paths declared |
| `git diff --check` | PASS |
| `python3 -m py_compile reports/benchmark/dataset-v1/capture_agent_events.py reports/tool-planning/run_frozen_recheck.py` | PASS |
| GitHub PR #30 checks at implementation SHA `3b651d2f6c6b69a4162a8b9ef8ec77a6bbef92a2` | PASS: `security-tests` (13m20s) and `security-freeze` (4s) |

The full suite is 27 tests above the 341-test baseline; the increase is the new terminal-capture test module. No benchmark task corpus, scoring rules, or hidden tests changed. The external capture/recheck scripts changed to produce attempt-scoped evidence. No real GLM or other remote model call was made for M8.2.1. PR #30 is an open Draft stacked on the exact PR #29 base. The exact checks above cover the implementation SHA; this report-only follow-up will trigger another exact-head run, which will be recorded by the final PR status.
