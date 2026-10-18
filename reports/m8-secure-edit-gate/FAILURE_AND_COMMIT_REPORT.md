# Candidate B Failure and Commit Semantics

## Staging failures

The fixed Staged Replacement was run with exact `tags.py` read/write scope. The corrected fixture now emits an injection marker from each actual hook, preventing a generic syntax or startup failure from being counted as the tested fault.

| Fault | Hook observed | Runner result | Changeset and live state |
|---|---|---|---|
| Temp create | `INJECTED_TEMP_CREATE_FAILURE` | Nonzero | Empty changeset; original target; no temp or canary change. |
| Temp write | `INJECTED_TEMP_WRITE_FAILURE` | Nonzero | Empty changeset; original target; no temp or canary change. |
| `fsync` | `INJECTED_TEMP_FSYNC_FAILURE` | Nonzero | Empty changeset; original target; no temp or canary change. |
| Pre-replace | `INJECTED_PRE_REPLACE_FAILURE` | Nonzero | Empty changeset; original target; no temp or canary change. |
| Cleanup failure | Parent observed the orphan `.khaos-edit-*` entry in the private snapshot before commit | Kernel `commit_rejected` | Live target and canary unchanged; snapshot discarded. |
| Exception after successful replace | Replacement hook completed before raising | Nonzero | Kernel committed exactly one modified `tags.py`; final bytes match expected replacement; no temp. A nonzero Runner result does not imply “no edit.” |

## Whole changeset and scope

- Adding `hidden-canary.py` or modifying `unscoped-canary.txt` beside the valid edit reached the private snapshot and caused a whole-changeset `commit_rejected`; live target and canaries stayed unchanged.
- The attempted hidden-canary deletion was denied by the real OS sandbox before it entered the changeset. The fixed `tags.py` edit then completed as the sole modified path. This proves OS-level denial for that operation; it is not described as a Kernel deletion-rejection event.
- A deterministic temp-name symlink collision entered the private snapshot and was rejected as a complete changeset. No collision entry reached the live workspace.
- The commit-time concurrent edit was preserved when the Kernel rejected the stale snapshot.

All outcomes are derived from the real Runner/Kernel result plus final workspace bytes and entry lists, not from command return code alone. The L3 tests do not add a production edit capability.
