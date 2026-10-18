# M8.5.2A — Signed Runner Edit Feasibility

Status: **IN PROGRESS — Gate A NOT PROVEN**
Evidence refreshed: 2026-10-18
Baseline: PR #33 head `1d1457f43f788d30f6fa4f48890b900ef9406c07`

## Gate decision

| Requirement | Current result | Evidence boundary |
|---|---|---|
| Signed Runner edit feasibility | PASS for exact positive and denial cases; overall Gate A NOT_PROVEN | v8 displayed and received one approval for the exact `tags.py` staged replacement. The signed task record and parent assertions verify one call, exit 0, exact final bytes/mode, `added=0/modified=1/deleted=0`, no temp, unchanged canary, one changed path, and focused retest. Refusal v2 verifies one denial and zero Runner calls. |
| Temporary-file cleanup | PASS for the successful signed path and tested headless failure cases; other signed failures NOT_PROVEN | v8 left no temp entry. Headless pre-replace failures leave the target unchanged; injected cleanup failure leaves a temp only in the private snapshot and the Kernel rejects the complete changeset. |
| Single-file changeset | PASS for the tested signed and headless positive paths | v8 used exact `readScope` and `writeScope` `tags.py`; parent verification found only `tags.py` modified and `added=0/modified=1/deleted=0`. |
| Failure atomicity | PASS for tested edit-stage outcomes | Pre-replace injected failures leave the target unchanged; a post-replace exception returns nonzero but commits only the fully replaced target, and the final state is verified. This is not a claim of general workspace transactionality. Signed-product confirmation remains outstanding. |
| Existing scope enforcement | PASS for refreshed regression cases | The tests below exercise real macOS sandbox and Kernel rejection paths. They do not substitute for the pending end-to-end edit. |
| Signed user refusal | PASS | Refusal v2 displayed the exact proposal, recorded one denial and zero Runner executions, left source/canary/workspace unchanged, and stopped the Agent task. |
| Security compatibility | CONDITIONAL | No runtime source was changed. Current-tree and exact-base Security Freeze checks pass; independent Code Owner approval remains NOT_PROVEN. |

Phase 2 is not authorized by this evidence. No production `edit` Action has been added.

## Signed-product attempts

The v6 run did not reach the `tags.py` approval. CUA bound to a no-argument Launcher instance, which completed its ordinary unique-file Kernel writeback smoke check in the disposable fixture. The Agent workspace picker was then cancelled. The test record shows zero approved calls and zero Runner command return codes. Its temporary fixture was removed at teardown; no repository file changed.

The v7 run bound to the Agent's actual workspace picker and showed the exact `tags.py` proposal. The signed task record reported one approval, one execution, exit code 0, and a 139-byte result, but the parent test failed before checking final state because it looked for the stdout marker in the Agent's final response. That assertion has been corrected to validate actual Runner stdout.

The parent test then failed because it searched the Agent's **final response** for `EDIT_APPLIED`, although that marker was present in Runner stdout. The probe now validates the bounded Runner stdout and echoes the marker in its final response.

The v8 run exercised that correction in the signed product. The user authorized one local deterministic replay. The Launcher displayed the complete script and JSON arguments, exact scopes, and request digest `ac7c277dc46bc43aef330f48e8fe569612779c2ff78ad129022820189a0d1ce1`; one **Run once** decision resulted in one Runner execution. The Task Record reports `task_completed`, exit code 0, and a 139-byte bounded result. Parent checks verified final source SHA-256 `8db3b1d5a79058bc0db32f9904c38162c6384ff813d41ab45b9db2348a264a63`, mode `0640`, the exact `tags.py` changeset, no temporary entry, preserved canary, and focused test exit 0. Deep strict code-signature verification also passed. The disposable fixture was removed at teardown. Full evidence is `gate-a-signed-runner-v8.json`.

The signed refusal v1 assertion recorded the required denial and unchanged fixture, but the enclosing test then failed because the refusal mode was missing from the safe cleanup list for the exact empty PluginStore scaffold created by the signed XPC service. The test now cleans only that exact empty scaffold. Refusal v2 passed the complete outer signed-product test, including the XPC request-attack checks. It recorded one proposal, one denial, zero Runner executions, unchanged `tags.py` and canary, a clean workspace, and terminal `task_cancelled`. Evidence is `gate-a-signed-refusal-v2.json`.

The v8 acceptance record confirms that `codesign --verify --deep --strict` passed for its transient product. The app bundle and workspace were removed at teardown, so the signing identifier, Team ID, designated requirement, and current bundle path were not retained for this report.

The Launcher displays one proposal with:

- `argv` using `python3 -I -B -c` and a fixed replacement script; `oldText` and `newText` are JSON-decoded arguments, not interpolated into executable source;
- target `tags.py`, with `readScope=["tags.py"]` and `writeScope=["tags.py"]`;
- request digest `ccb5fbfd1458f94afc8eaaf27797b62e426b2fe31f63a39a42bc176cb797c171`.

The proposal replaces the unique text `value.split(",")` with `[part.strip() for part in value.split(",") if part.strip()]`. The Launcher displayed the approval alert, but no user decision arrived before the UI driver timed out after 632 seconds. The app process and temporary app bundle then exited. The v4 report records one reviewed proposal, zero approved calls, and zero command return codes. No Runner operation executed and no workspace change is recorded. That approval request was independent of the unrelated M8.4 a-02 read approval and expired with the app instance.

Attempts `gate-a-signed-runner.json` and `gate-a-signed-runner-v2.json` are preserved as aborted before any Runner operation; the first was interrupted while the deterministic model fixture returned invalid JSON. `gate-a-signed-runner-v3.json` is preserved as a fixture assertion failure with zero reviewed or approved proposals and zero command return codes. `gate-a-signed-runner-v4.json` is `failed` after timing out while waiting for a UI decision. None of these is a successful signed Runner edit.

## Refreshed real-OS regression evidence

These checks ran in the current M8.5.2 worktree on macOS. They use disposable fixtures and do not count as the pending signed-product operation.

| Command / test group | Result | What it supports |
|---|---:|---|
| `test_macos_seatbelt.py -k sandboxed_python_edit_test_retest_use_exact_file_scopes` | 1 passed, 1.958 s | Existing exact-file-scope edit/test/retest behavior. The fixture uses direct `Path.write_text`; it does **not** validate same-directory staged replacement. |
| `test_macos_xpc_sandbox.py -k staged_edit_probe_runs_through_kernel_and_commits_one_file` | 1 passed, 6.943 s | The exact deterministic probe proposal ran through `run_workspace_command` with the real macOS Seatbelt Runner and Kernel commit path. It changed only `tags.py` `(added=0, modified=1, deleted=0)`, preserved mode `0640`, left no `.khaos-edit-*` entry, preserved the canary, denied an unscoped canary read, and passed the focused retest. It is not the signed XPC product run. |
| `test_macos_xpc_sandbox.py` focused staged-edit happy/failure cases | 2 passed, 26.851 s | The exact deterministic proposal ran through real macOS Seatbelt and Kernel commit logic. Success changed only `tags.py`, preserved mode `0640`, left no temp entry, preserved the canary, denied an unscoped read, and passed the focused retest. Injected create, `write`, `fsync`, and pre-replace failures left the target unchanged; injected cleanup failure caused complete changeset rejection; a post-replace exception returned nonzero while only the target was committed. These are not signed XPC product results, and injected errors are deterministic fault injection rather than OS-originated errors. |
| `test_seed_app_builds_and_authenticates_its_kernel_service` in the default invocation | 1 passed, 46.416 s | The default signed product build and Kernel/XPC identity path passed. No M8.5.2 UI flag was supplied, and no workspace Picker or Runner operation ran; this does not substitute for the signed edit request. |
| `test_launcher.py` focused commit, scope, link, cancellation, termination, retarget and post-commit cases | 11 passed, 57.851 s | Existing Kernel/Runner fail-closed and lifecycle behavior, including whole-changeset out-of-scope rejection. |
| `test_launcher.py -k fixed_command_reads_only_scoped_files_and_denies_link_escape` | 1 passed, 3.685 s | Real Seatbelt read-scope checks for canary, symlink, hardlink, rename, and filesystem-supported case/Unicode aliases. Alias subchecks are conditional on the filesystem presenting that alias. |
| `test_macos_seatbelt.py -k process_read_scope_blocks_moves_of_unreadable_baseline_entries` | 1 passed | An unreadable baseline entry cannot be moved into scope. |
| `test_macos_seatbelt.py -k write_scope_metadata_cannot_follow_unreadable_aliases` | 1 passed, 1.673 s | Write-scope metadata checks do not follow unreadable aliases. |
| `test_workspace_changes.py` focused snapshot and cross-process replacement-race cases | 9 passed, 14.635 s | Existing symlink-scan race, parent detach, destination/temp-name/temp-metadata races, and restoration behavior. |
| `test_workspace_snapshot.py` bounded read/write scope path cases | 2 passed | Root, traversal, absolute and invalid scope paths are rejected by the existing path/scope validator. |
| `test_launcher.py -k scoped_directory_discovery_hides_canary_and_symlink_targets` | 1 passed, 3.255 s | Scoped discovery hides the canary and symlink targets, including traversal/absolute discovery requests in the fixture. |
| `python3 -m unittest discover -s tests -v` | 381 tests discovered; exit 0; 708.963 s process duration | Full canonical suite passed on the final test harness. |

The headless real-OS tests prove the successful staged-replacement path and the listed injected-failure states through the real Seatbelt Runner and Kernel commit implementation. Signed v8 proves the positive XPC Runner path, and refusal v2 proves the denied path. OS-originated I/O faults and the required edit-specific signed traversal/alias/race/cancellation/termination matrix remain NOT_PROVEN.

## Required evidence still missing

Before Gate A can pass, complete the remaining target-specific adversarial cases from the objective: traversal, absolute/empty paths, symlink leaf/ancestor, hardlink and Unicode/case aliases, rename race, TOCTOU, out-of-scope sibling, hidden canary, unreadable baseline, cancellation, termination, nonzero exit, and changeset rejection. Preserve the distinction between a command return code and final committed workspace state.

The changed protected files are test-only: `tests/macos_xpc_probe/AgentHostSandboxModelProbe.swift` and `tests/test_macos_xpc_sandbox.py`. The exact-base declaration and hashes have been updated. The latest full canonical suite completed with 381 tests, exit 0, in 708.963 seconds. `python3 tools/check_security_freeze.py` and `python3 tools/check_security_freeze.py --base 1d1457f43f788d30f6fa4f48890b900ef9406c07` pass after the final metadata update.
