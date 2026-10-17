# M8.2.1 Security Audit

## Boundary review

The change touches only an external evidence-capture script, its frozen experiment driver, documentation, and test/governance inputs. It does not modify any runtime product source, Kernel permission model, Seatbelt policy, XPC identity, workspace scope enforcement, Snapshot Broker, Changeset validation, Plugin admission, activation approval, Action ABI, or trusted IPC.

**Runtime TCB delta: 0.** No new trusted process, IPC operation, runtime capability, dependency, or production persistence was introduced.

## Data minimization

The observer reads existing product logs but emits only allowlisted event names, fixed stage/error codes, known Action field names, bounded counts, status classes, file hashes, and truncation flags. It discards raw final text, prompt, workspace/result text, unknown event suffixes, unknown keys, and credentials. Unit tests place synthetic secret canaries in those channels and assert they do not appear in output.

Input parsing is bounded to the final 256 KiB of each source file; full-file hashes are computed incrementally. Truncation makes the summary incomplete. Per-line and per-event limits, a 27-event Host diagnostic cap, and a 128-event live cap bound output. Attempt IDs are validated; summary files are create-only.

The preserved M8.2 raw run directory contains sensitive experiment/grader evidence and remains untracked and unstaged. The PR reports hashes and sanitized facts only.

## Authority and execution

The new capture process has no authority to invoke the Kernel or approve operations. It observes existing logs and waiter process liveness. It does not change action classification, tool-call budget, approval decisions, scope, timeout, cwd, environment, or sandbox configuration.

Process exit is not accepted as task success. `agent_final_response_observed` is true when a Launcher Task Status/Record carries `final_response` or when a bounded `Khaos:` marker is present; the marker count is separate. A text marker without a Launcher task status/record remains an unknown task outcome. Host or Launcher termination is reported only when the test/driver separately observed the relevant process termination. Conflicting terminal records fail closed.

## Security Freeze governance

The changed tests and `AGENTS.md` are protected inputs. This change must carry a fresh declaration bound to the exact PR #29 base SHA, update their exact hashes in `security/tcb-manifest.json`, recompute the manifest digest in `security/freeze-baseline.json`, and pass both current and base-aware checks. These baseline edits document a reviewed test/governance change; they do not conceal a runtime TCB delta.

Independent Code Owner approval remains an external review requirement and is not self-certified by this report.

## Validation status

Focused capture tests pass (27 tests); the signed-product deterministic UI acceptance passes; the canonical macOS suite passes with 368 tests; and both current and exact-base Security Freeze checks pass. GitHub `security-tests` and `security-freeze` pass on PR #30 implementation SHA `3b651d2f6c6b69a4162a8b9ef8ec77a6bbef92a2`. The report-only follow-up creates a new head that must receive its own checks. Runtime TCB delta is zero, and no remote model call was made.
