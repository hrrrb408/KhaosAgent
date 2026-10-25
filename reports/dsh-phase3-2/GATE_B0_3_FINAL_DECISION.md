# Gate B.0.3 Final Decision

**Gate B.0.3: BLOCKED at the signed-app prerequisite.** One validly signed no-model bundle was built from the corrected source, but its launcher and three XPC services lack the required Hardened Runtime flag. Trial A/B and signed replay checks were not started.

## Required status

| Item | Result |
|---|---|
| Gate B.0.3 Engineering | BLOCKED |
| Signed App Source SHA | `d807f302b86e1ccf98049fece3226aa0b4c75561` |
| App Signing / Deep Signature | PASS |
| Hardened Runtime | FAIL for app and three XPC services; present only on bundled Node |
| App CDHash | `486d1ff52d4b3f043fca9e8251bbdd0676694bd4` |
| Successful signed bundle count | 1 (two build attempts; the first failed before signing and produced no bundle) |
| Workspace A | NOT_RUN |
| Workspace B positive operation | NOT_RUN |
| Workspace B cross-scope refusal | NOT_PROVEN; NOT_RUN |
| Parent Launcher terminal events | NOT_RUN |
| Kernel-to-DSH signed correlation | NOT_RUN; synthetic evaluator tests pass |
| Correlated signed operations | 0 / 7 required fixture operations |
| Trial A Agent completion | UNKNOWN / NOT_RUN |
| Trial B security terminal | NOT_RUN |
| Signed cross-trial result replay | NOT_RUN; synthetic binding mismatch refused |
| Signed stale approval replay | NOT_RUN; synthetic pair check refused |
| Signed workspace identity replacement | NOT_RUN; automated test refused |
| Canary disclosure | 0 observed; cross-workspace trial NOT_RUN |
| Unexpected workspace mutations | NOT_RUN; no trial workspace was created |
| Unauthorized Kernel operations | NOT_RUN; no trial operation was submitted |
| Large GGUF copies / real-model invocations | 0 / 0 |
| Historical files deleted | 0 |
| Canonical tests | PASS; `python3 -m unittest discover -s tests -v`, 467 tests in 862.580s |
| Security Freeze | PASS against default and PR #48 base `e27aed3ee3f40e7a008517ab7d8242bebe25a7c2` |
| Exact-head GitHub CI | PENDING final PR update |
| Experimental trusted behavior review | PARTIAL; signing prerequisite blocks runtime review |
| Independent Security Review | PENDING |
| Gate B real-model readiness | BLOCKED |
| Updated draft PR | #48 only; no merge |

Focused acceptance validation also passed: 26 Python acceptance tests, 20 pinned DSH semantic tests, and 17 pinned DSH bridge/lifecycle tests. The full canonical suite included a headless signed product bundle check; it does not exercise the blocked multi-workspace UI acceptance.

## Change accounting

| Measure | Delta |
|---|---|
| Production code | 0 |
| Production trusted code | 0 |
| New architecture concepts | 0 |
| New trusted processes | 0 |
| New IPC operations | 0 |
| New persistent state | 0 |
| New dependencies | 0 |
| Removed duplication or abstractions | One RC-only refusal heuristic replaced by explicit refusal evidence; no production abstraction changed |

The historical signed Trial A/B `FAIL` reports are preserved. The new signed build does not reverse those outcomes. The immediate follow-up is to resolve the Hardened Runtime signing discrepancy under the existing review and freeze process, then rebuild once and run the required acceptance on that compliant bundle.
