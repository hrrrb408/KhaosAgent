# Candidate B Race and TOCTOU Report

## Deterministic synchronization points

All fixtures use a marker visible to the parent test process. The parent acts only after the fixed Runner has reached the recorded stage; tests do not use random concurrency loops.

| Race | Trigger | Kernel / Runner result | Final state |
|---|---|---|---|
| Read-to-replace target swap | `Path.read_text` returns the original source, writes a marker, then pauses. Parent replaces snapshot `tags.py` with a symlink to an unscoped canary before the fixed script resumes. | The fixed script's `os.replace(temp, tags.py)` replaces the symlink entry, rather than following it. Kernel accepts a one-path `tags.py` changeset. | `tags.py` has expected replacement bytes (SHA-256 `8db3b1d5a79058bc0db32f9904c38162c6384ff813d41ab45b9db2348a264a63`); canary hash remains `0b6ba3c1ade1071adfd0088da2fd0fb0ab3bb522405ddb593d70c192d04836cd`; temp absent. |
| Parent rename to external symlink | After `src/tags.py` is read, parent renames snapshot `src` and installs `src` as a symlink to an external synthetic directory. | Fixed edit fails with a nonzero result or the existing Kernel rejects the unsafe snapshot/changeset. | Live `src/tags.py`, workspace canary and external target retain their original bytes; live workspace contains only its original entries. |
| Commit-time live target race | Parent observes the expected replacement in the private snapshot, then writes `synthetic concurrent live edit\n` to the live target before commit. | Kernel returns `commit_rejected`. | The concurrent live content remains; its SHA-256 is `286f31c80aa7c8368f2e909416760de7d48ba768391b50b5f914b60465e68bd8`; canary unchanged; no temp. |
| Deterministic temp-name collision | Runner fixture creates a symlink at the exact `.khaos-edit-` name and fixes the random-name source. | The private snapshot contains the collision entry; Kernel rejects the complete changeset with `commit_rejected`. | Live target and canary unchanged; no collision entry committed. |

The earlier target-swap case also replaces `tags.py` with a canary symlink before the script opens it. The fixed script's read is denied and neither canary nor target is changed. This is distinct from the read-to-replace race above.

## Boundary

L3 establishes the observed behavior for these synchronized fixtures. It does not establish a general transaction guarantee beyond the Kernel's tested changeset boundary. No test claims a parent rename cannot occur; the test proves the specific external-link race does not produce an external write or live unauthorized commit. The live commit-race fixture deliberately leaves the concurrent writer's data in place, rather than claiming rollback.
