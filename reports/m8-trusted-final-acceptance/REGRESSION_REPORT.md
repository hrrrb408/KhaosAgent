# Regression and Security Freeze Results

## Executed checks

| Check | Result | Evidence |
|---|---|---|
| Canonical suite: `python3 -m unittest discover -s tests -v` | PASS — 398 tests in 879.378 seconds | `canonical-full-suite.log` |
| Focused Python/Swift compatibility: `python3 -m unittest discover -s tests -p test_macos_xpc_sandbox.py -k test_trusted_candidate_b_preview_parser_is_bound_and_fails_closed -v` | PASS — 1 test | Cross-language fixture JSON and the canonical suite log. |
| Focused cancellation binding: `python3 -m unittest discover -s tests -p test_macos_xpc_sandbox.py -k test_launcher_workspace_command_cancellation_is_task_and_connection_bound -v` | PASS — 1 test | Canonical suite log. |
| Signed complex review/refusal acceptance | PASS — 1 signed product test in 569.792 seconds | `signed-candidate-b-review-final4.json` and `.log`; exact outcome in `SIGNED_UI_ACCEPTANCE.md`. |
| `python3 tools/check_security_freeze.py` | PASS — `sensitive changes=0` | Re-run after code, manifest, and baseline updates. |
| `python3 tools/check_security_freeze.py --base 12c75d75c1464aabd631b092e07903631f692ff6` | PASS — `sensitive changes=17`; independent approval remains external | Exact PR base, not a moving branch head. |
| `git diff --check` | PASS | Re-run after evidence/report updates. |
| `python3 -m py_compile tests/test_macos_xpc_sandbox.py` | PASS | Re-run after fixture changes. |

No test was skipped or weakened. The canonical suite count remains 398; the change adds no new unittest method. The suite ran on macOS and included the real signed Kernel XPC source-digest rejection path.

## Security and architecture delta

- `TrustedEditApproval.swift` changed +32/-5 lines relative to original PR #39 head `3dfa14b5daf94b2f58926398506e0aba693c631f` to match Python canonical string encoding.
- PR #39 runtime-TCB manifest files changed +2116/-182 lines, net +1934, relative to exact PR base `12c75d75c1464aabd631b092e07903631f692ff6`.
- Kernel Authority delta: 0. Kernel ABI delta: 0. Workspace Scope Authority delta: 0.
- New architecture concepts: 0. New trusted processes: 0. New IPC operations: 0. New persistent state: 0. New dependencies: 0.
- Test-only probe/harness change: probe +89/-44 lines; Python test harness +40/-4 lines (net +36). It replaces duplicated staged-edit fixture encoding with one Python-compatible fixture helper and compares its complete argv against Python stdlib output.
- Security Freeze runs verify the declaration and manifest; they do not establish independent code-owner approval.

The signed refusal does not substitute for the separate B32/B34/B39 signed cancellation checks. Those remain `NOT_PROVEN` as documented in `CANCELLATION_ACCEPTANCE.md`.
