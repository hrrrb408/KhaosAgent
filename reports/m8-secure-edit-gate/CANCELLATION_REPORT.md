# Candidate B Cancellation and Termination Report

## L3 results

| Stage | Synchronized observation | Result and final state |
|---|---|---|
| After target read, before temp creation/replacement | Fixed script writes `source-read-marker` after reading `tags.py`; parent cancellation callback observes it. | Kernel returns `process_cancelled`; live target and canary remain original; no temp is present. |
| After private-snapshot replacement, before commit | Parent sees the expected replacement in the private snapshot while the Runner is held after `os.replace`. | Kernel returns `process_cancelled`; live target remains original, canary unchanged, no temp. This proves cancellation at this pre-commit point only. |
| Runner killed before replacement | Parent waits for the read marker and sends SIGKILL to the identified Runner PID. | Kernel returns `runner_failed`; Runner and command PIDs are gone; live target/canary unchanged; no temp. |
| Runner killed after replacement | Parent waits for a marker written after `os.replace` and kills the identified Runner PID. | Kernel returns `runner_failed`; Runner and command PIDs are gone; private replacement is not committed; live target/canary unchanged; no temp. |

The canonical suite and all 15 focused staged-edit tests passed. Cancellation callbacks observe the actual private snapshot; assertions inspect the live workspace separately.

## Not established

- The signed Launcher case “approved, then cancelled before Runner start” was not run. Historical v2 is a user denial before execution, not post-approval cancellation.
- Cancellation at the Kernel commit cutoff or after a completed live commit was not exercised. The report makes no rollback claim after the commit boundary.
- Signed lifecycle capture for cancellation and termination remains BLOCKED_PENDING_APPROVAL. No additional signed operation was run under the one-use positive replay authorization.
