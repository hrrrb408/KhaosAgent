# Signed Product Acceptance Report

## New one-use positive replay

- Report label: `m8-5-2a1-signed-positive-replay-01` (descriptive label; not an embedded product attempt ID).
- Evidence: `gate-a-signed-runner-replay.json`, SHA-256 `f8dbb965666f2c8c6c235b93b27a31c3afa011ed981cb7c5d079417438c745d8`.
- Run window: 2026-10-18 12:39:39–12:46:57 UTC.
- Source `HEAD` was PR #34 head `6724d5ac5e52e1c157f3701f30009ed81b55fb90`; the only uncommitted source edit was the test harness, plus untracked reports. Production sources were unchanged. The evidence JSON does not persist a product-binary digest or an explicit build-commit field.
- Product verification: deep strict code-signature check passed.
- Proposal: test-only `type=shell`, deterministic fixed replacement, exact `readScope=["tags.py"]`, `writeScope=["tags.py"]`; request digest shown in approval UI: `17f3d3b5dcf7f29269a262a738c048f32ca6628769e3872cadb5059b01117f7e`.
- Approval: one human Run once decision. This is the single separately authorized signed action in this branch.
- Runner: one execution, return code 0, bounded stdout marker `EDIT_APPLIED`.
- Kernel changeset: added 0, modified 1, deleted 0; changed path exactly `tags.py`.
- Final target SHA-256: `8db3b1d5a79058bc0db32f9904c38162c6384ff813d41ab45b9db2348a264a63`.
- Canary: unchanged. Temp entries: 0. Target mode: preserved.
- Parent focused test: return code 0. Task Record and terminal record present; terminal class `task_completed`.
- Provider is null; no remote model or API key was used.

## Historical signed evidence

- Positive v8 remains PASS for its exact short fixture and has not been overwritten.
- Refusal v2 remains PASS for one displayed/denied proposal, zero Runner executions, unchanged workspace and complete `task_cancelled` terminal record. It has not been repeated.
- See `BASELINE_AUDIT.md` for evidence-file hashes and narrow scopes.

## Interpretation

The positive replay verifies one approved signed execution of the exact short fixed replacement. The refusal verifies one pre-execution denial. Neither record proves all Gate A adversarial cases, long-payload reviewability, signed cancellation/termination behavior, or coding quality. `task_completed` is not a coding-objective verification result.
