# Regression Report

## Focused validation

| Check | Result |
|---|---|
| Candidate B staged_edit group, including B14 and B34 late-cancel tests | PASS — 17 tests in 155.590 seconds |
| B34 broker cancellation tests | PASS — 2 tests in 3.001 seconds, including READY-before-ACCEPT cancellation |
| B38 AgentHostActionOutput serialization probe | PASS — 1 test in 2.046 seconds |
| Security Freeze, current tree | PASS — verified; sensitive changes=0 |
| Security Freeze against PR #35 exact head 9dac79839da1d2d7c1c29027136f85eb85c28bce | PASS — verified; sensitive changes=5 |

The two focused test-input changes are listed in the freeze declaration and manifest. The five exact-base sensitive paths are the declaration, manifest, baseline digest, AgentHostActionOutput test probe, and test_macos_xpc_sandbox.py. The unchanged production TCB inventory remains intact.

## Canonical suite

Command: python3 -m unittest discover -s tests -v

Result: PASS — 396 tests in 819.551 seconds, zero failures.

The signed-product opt-in UI tests and remote-model acceptance tests were not invoked. The default product-bundle authentication test ran without opening a workspace Picker. No remote model or API key was used.

## Final-tree and remote checks

The Security Freeze checks are rerun after the final declaration text update. Changed-path and Runtime TCB audits are recorded in COMPLETION_AUDIT.md. GitHub PR checks remain separate evidence and are reported from the exact pushed head.
