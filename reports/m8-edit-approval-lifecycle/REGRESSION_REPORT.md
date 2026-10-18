# Regression report

Base PR #36 HEAD: `9c111de6053bde6e83483724e45ce5bc337f10ec`.

| Check | Result |
|---|---|
| Report-local Candidate B preview Swift compile and probe | PASS; `candidate-b-preview-prototype=PASS` |
| Canonical `python3 -m unittest discover -s tests -v` | PASS; 396 tests in 815.406 s |
| `python3 tools/check_security_freeze.py` | PASS; sensitive changes=0 |
| `python3 tools/check_security_freeze.py --base 9c111de6053bde6e83483724e45ce5bc337f10ec` | PASS; sensitive changes=0 |
| Staged `git diff --check` | PASS |
| Opt-in interactive signed-product UI acceptance | NOT RUN; it requires a separate interactive approval flow and was not needed to validate the report-local prototype |

The canonical suite includes non-interactive signed-product and disposable-fixture checks, including the existing staged-edit commit and late-cancellation cases. These are repository test fixtures; they do not constitute a new interactive M8.5.2 approval replay. No existing test was deleted or modified, and no real-model request was made.
