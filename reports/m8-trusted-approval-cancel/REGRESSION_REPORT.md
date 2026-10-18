# Regression report

## Current branch and prototype

Base: PR #37 exact HEAD `02b8277c8c8b96d8679a1d064e23595d87dab657`.

| Check | Result |
|---|---|
| Report-local approval/cancellation harness compile and run | PASS; `m8-trusted-approval-cancel-nontrusted-harness=PASS` |
| Current PR #37 `security-freeze` | PASS on HEAD `02b8277c8c8b96d8679a1d064e23595d87dab657` |
| Current PR #37 `security-tests` | PASS at run `39145858255` (16m28s) |
| A4 branch canonical suite | PASS; `python3 -m unittest discover -s tests -v` ran 396 tests in 847.899 s on the exact PR #37 code baseline with only report-local files added |
| A4 freeze checks | PASS; default and `--base 02b8277c8c8b96d8679a1d064e23595d87dab657` both report sensitive changes=0 |
| A4 signed UI acceptance | NOT RUN; independent review gate not satisfied |

The harness is test-only Swift under `reports/`, is not packaged or imported by Khaos, and makes no filesystem, process, XPC or network call. It models a request digest and task identity; its PASS does not establish production request binding, runtime cancellation, signed UI behavior or Gate A. No tests under the protected `tests/` path were changed.
