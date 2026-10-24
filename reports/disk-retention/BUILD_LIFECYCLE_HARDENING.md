# DSH Build Lifecycle Hardening

## Changes

`tools/build_dsh_xpc_acceptance_app.py` now validates a local model's type, link count, and size using filesystem metadata, then checks the output volume before `local_model_inputs()` verifies the App signature or hashes the GGUF. The threshold is one model copy plus 2 GiB staging allowance plus 10% headroom. It fails with `INSUFFICIENT_DISK_SPACE` before reading the model contents. The normal build record stores the preflight result. No full model App was built in this task.

`tools/run_dsh_xpc_attack_acceptance.py` now preserves bounded failure evidence outside the invocation scratch before it considers cleaning that scratch. Evidence includes compressed Launcher logs, task text, build inputs, bounded non-canary workspace files, and cancellation control events when present. It redacts the exact configured API key from copied payloads and excludes the complete signed App and model. Owner-only permissions and exclusive file creation prevent accidental evidence overwrite.

The runner records the scratch root's Device/Inode and includes the exact local path, logical/allocated bytes, and tree fingerprint in the owner-only retention record. Automatic cleanup requires a complete capture, a matching root and tree fingerprint, no evidence-write error, no owned Node cleanup error, no live `lsof` reference, and no explicit `--preserve-scratch`. If any check is unknown or fails, it detaches the finalizer and retains the scratch. The process check never kills an unrelated process.

`tools/audit_experimental_artifacts.py` is a read-only exact-manifest dry-run. It validates paths and file metadata, rejects Git repository roots, protected model/evidence paths, hard links, escaping symlinks, repeated/nested candidates, changed identity/size, unresolved evidence or rebuild status, and active or unknown process references. It reports logical bytes and allocated bytes separately and leaves APFS-exclusive reclaim unknown. There is no destructive CLI mode.

## Evidence from this task

- The three failed-run evidence packages were captured and digest-checked in an owner-only evidence directory (about 2.06 MB total), with no GGUF or signed App copied.
- The exact manifest contains 27 scratch roots. `lsof` was clear for each at capture and again during dry run.
- Dry run returned `REFUSE` for all 27 because the three large entries lack verified local `pnpm 10.17.1` rebuild support and the other 24 lack Trial/evidence/consumer mapping.
- Manifest nominal scratch size is 59.281 GB logical and 59.435 GB by `st_blocks`; APFS-exclusive reclaim remains unknown. No large files were cleaned.
- The disk preflight unit tests use tiny synthetic files and injected capacity values. No local model file contents were read by those tests.
- The new retention tests passed 29/29; existing DSH builder and runner suites passed 6/6 and 10/10. The final canonical `python3 -m unittest discover -s tests -v` suite passed 449 tests in 826.008 seconds, with all UI/model flags and credentials removed from that test process.
- Security Freeze passed both its default check and the exact-base check against PR #46 HEAD `7ed01f726387755181cfbadad33967f35d9d2f72`.

## Boundaries and remaining work

Changes are confined to experimental build/acceptance tools, a read-only audit utility, tests, and reports. No signed DSH lifecycle run or large-model build was performed. The production Security Kernel, Kernel ABI, workspace authority, production AgentHost, signatures, entitlements, sandbox, and dependencies are unchanged.

The failure capture is deliberately bounded. Oversized logs/workspaces, missing required files, unsupported filesystem entries, or incomplete cancellation evidence keep the scratch for manual review. A large historical scratch cannot be cleaned on the basis of its name or failure status alone.
