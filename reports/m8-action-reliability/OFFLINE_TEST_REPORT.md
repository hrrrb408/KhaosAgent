# Offline Test Report

Date: 2026-10-18

No remote-model request was made for this report. The compiled Swift comparison uses fixed synthetic JSON inputs.

## Focused commands

- python3 -m unittest discover -s tests -p test_agent_terminal_capture.py -v — passed, 30 tests.
- python3 -m unittest discover -s tests -p test_macos_xpc_sandbox.py -k test_agent_host_action_output_correction_is_single_and_format_only -v — passed, 1 test; compiles and runs the production parser plus the A/B/C probe.
- python3 -m unittest discover -s tests -p test_launcher.py -k test_invalid_command_is_rejected_before_kernel_launch -v — passed, 1 test.
- python3 -m unittest discover -s tests -p test_security_freeze.py -v — passed, 4 tests.
- python3 -m unittest discover -s tests -v — passed, exit code 0, 371 tests in 669.223 seconds.
- python3 tools/check_security_freeze.py — passed; current worktree sensitive changes=0, independent approval remains external.
- python3 tools/check_security_freeze.py --base 6c5791264f64f2d171ad23deabf47ae684fc7ac4 — passed; exact PR #30 base sensitive changes=5, all declared and reviewed by the freeze check.

## Evidence boundary

The focused comparison verifies deterministic parser acceptance and rejection, not remote model success. The signed product test is a separate deterministic acceptance and is recorded in SIGNED_PRODUCT_REPORT.md. The canonical full-suite command returned exit code zero. Current and exact-base Security Freeze checks both passed; independent Code Owner approval is not established by those checks.
