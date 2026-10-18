# Regression Report

## Commands and results

| Command | Result |
|---|---|
| `python3 -m unittest discover -s tests -p test_macos_xpc_sandbox.py -k staged_edit -v` | PASS — final rerun: 15 tests, 135.355 seconds. |
| `python3 -m unittest discover -s tests -v` | PASS — 394 tests, 804.143 seconds. |
| `python3 tools/check_security_freeze.py` | PASS — current-tree inventory verified, 0 sensitive changes relative to no base. |
| `python3 tools/check_security_freeze.py --base 6724d5ac5e52e1c157f3701f30009ed81b55fb90` | PASS — exact PR #34 head; 4 sensitive paths correctly bound by the declaration. |

The 381-test PR #34 baseline increased by 13 tests. The final suite included the new real-macOS staged-edit attack cases and the existing Kernel/XPC, Seatbelt, cancellation, lifecycle and workspace-commit regressions. No tests were skipped in the 15-test target-specific group on this host; the case and Unicode aliases existed on the tested APFS volume.

After the 394-test full-suite run, two unused local setup variables were removed from the temp-failure test. The affected test passed again in 20.805 seconds, and the complete 15-test staged-edit group passed again on the final test file. The removal did not change test behavior; the full 394-test suite was not rerun after that cleanup.

The canonical suite completed on macOS and emitted its expected App Sandbox/APFS probe diagnostics. The signed positive replay is separate from the canonical suite and is not counted as a model-quality test.

No repository-defined formatter, linter, or packaging command was found in the checked project configuration paths. No guessed lint or formatting command was run.
