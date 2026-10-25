# M-Disk.1.4 — Phase 3.2.2 Resumption Gate

**Decision: `CONDITIONAL`. Gate B/C were not started. No model or large signed App was rebuilt or launched.**

| Gate condition | Evidence / status |
|---|---|
| Signed retention refusal behavior | Four prior bounded signed fault scenarios passed: incomplete archive, identity substitution, active `lsof` reference and unknown reference. They used small invocation-owned fixtures and the existing Launcher → Kernel → Runner path. |
| Future evidence digest correctness | Fixed in the experimental capture writer; determinism, byte binding, tamper rejection, version compatibility and archive-file checks are covered by the focused tests in this change. |
| No historical deletion path in reviewed scope | `NOT_FOUND_IN_SCOPE`; current driver only passes its own new `TemporaryDirectory`. Historical cause remains `UNKNOWN`. |
| New run identity and isolation | Must use new disposable workspace and new evidence paths; do not reuse or depend on any missing historical root. |
| Large build capacity | The latest Data volume sample has about 446.7 GiB available. The existing builder has a preflight, but this audit did not rebuild the 18.56 GB model App or validate a fresh large-build capacity reservation. |
| Historical evidence separation | Old Capture Manifest bindings remain wrong and immutable. New trials must have new manifest, raw evidence and hashes independent of old records. |
| Independent result verification | Required again for the new trial; no model may announce its own success. |

The unresolved historical attribution is not evidence that current cleanup is unsafe, but it prevents an unconditional `READY` result. Before Gate B/C, the owner must accept that the old removal cause cannot be established. Then run only against fresh, disposable workspaces with fresh evidence IDs, keep the existing bounded write/tool/time budgets, verify disk preflight, and preserve the failing outputs and operation identities. A returned old path with a new inode must be treated as a new artifact and audited from scratch.

No experiment was performed as part of this gate assessment. `Production Harness Migration` remains `NOT_AUTHORIZED`.
