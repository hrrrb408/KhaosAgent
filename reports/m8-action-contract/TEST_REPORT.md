# M8.1 — Validation report

## Results

| Check | Result | Evidence |
| --- | --- | --- |
| Focused compiled Action-output probe | PASS — 1 test, 1.459 s | Exact shape/type/size, hostile extra-key canary, diagnostics off/on and line bound, correction limit, Action validation, post-tool state, and sequencing assertions |
| Signed Seed bundle build/authentication regression | PASS — 1 test, 47.154 s | Builds and signs the current product, verifies Kernel XPC authentication and existing headless product attacks; no remote model call |
| Deterministic signed-product coding loop | PASS — 1 selected acceptance test | Fixed local model probe; coding workflow, explicit denial, Picker cancellation, 8-call budget, and Agent Host exit during an approved Runner operation all passed. The parent retest returned 0, and the scoped write was committed after Host exit. No remote provider. |
| Canonical repository suite | PASS — 341 tests, 693.825 s | `python3 -m unittest discover -s tests -v`; includes the new compiled probe and real signed-product XPC authentication test |
| Security Freeze base comparison | PASS | `python3 tools/check_security_freeze.py --base 27ef0b4787f807fc76ffd7ba9cdb467ffc9a2f27`; five declared sensitive test/governance paths |
| Security Freeze inventory | PASS | `python3 tools/check_security_freeze.py`; current protected inventory verified |
| `git diff --check` | PASS | No whitespace errors |

## Interactive acceptance attempts

The first deterministic signed-product attempt stopped before workspace
selection because it was launched without a TTY and its test gate read closed
stdin. Its evidence records `status=failed` at
`single-user-task-coding-workflow`, with no completed security check and no
Picker selection or Runner operation. It is retained in the system temporary
directory and is not part of the passing result.

The TTY retry passed. The disposable coding fixture recorded six approved and
executed Runner calls with return codes `[1, 1, 1, 0, 0, 0]`; the scoped edit
survived the initial failed test, was corrected, and passed the parent retest.
The synthetic out-of-scope canary remained unchanged. Separate fixtures verified
that denial led to no next approval or write, Picker cancellation ran no
operation, the eight-call budget presented no ninth approval, and an approved
Runner write completed after the Agent Host was killed during that operation.
Both the command and Agent Host exited, and a restarted Host rejected the stale
tool result. These are deterministic product-path checks, not model-quality
evidence.

## Scope of these checks

The compiled probe tests parsing and diagnostics offline. The signed-product
checks exercise the locally signed bundle and existing Launcher/Kernel
boundaries with a deterministic local model. No real GLM call was made. These
results do not establish coding quality or hidden-test completion. The M8.0
benchmark, original prompt, hidden patch, and scoring input were not changed.
