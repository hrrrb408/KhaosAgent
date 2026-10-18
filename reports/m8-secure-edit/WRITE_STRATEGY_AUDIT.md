# M8.5.2A — Single-File Write Strategy Audit

Status: **interim; Gate A remains NOT PROVEN**
Baseline: `1d1457f43f788d30f6fa4f48890b900ef9406c07`

## Existing execution semantics

The trusted Launcher lowers a shell proposal to a bounded `workspace.run` request with the proposal's read and write scopes. After approval, it invokes the Kernel and returns the bounded result. Its Runner source calls `process_exec(tuple(ARGV))` and then calls `workspace_commit()` even when the executed command returns nonzero. Therefore an exit status of 1 is not evidence that a changed private Snapshot was discarded. Error handling and reports must inspect the committed changeset and final target contents.

The Kernel's existing exact-path `workspace_write_scope` validates the complete changeset before live writeback. A same-directory temporary entry is still a distinct changed path. With `writeScope=["tags.py"]`, a leftover temporary file must cause whole-changeset rejection rather than justify widening scope to the parent directory. The v8 signed operation and parent assertions verified one modified path under this exact scope and no committed temporary entry.

## Strategy comparison

| Strategy | Assessment |
|---|---|
| Directly truncate/write the target | Rejected for the structured edit adapter. A write error can leave a partial target, and the Launcher may commit snapshot changes after a nonzero command result. Prevalidating the replacement bytes alone does not remove this risk. |
| Same-directory staged replacement | Candidate strategy. Build the complete replacement bytes first, create a random exclusive temp beside the target, write and flush it, then replace the target. On pre-replace failure, clean the temp; if cleanup fails and the temp remains, exact-scope changeset validation must reject it. The signed v8 product exercised the successful path; signed failure injection remains NOT_PROVEN. |

The deterministic probe proposes a fixed Python script that treats `path`, `oldText`, and `newText` as arguments. It rejects a non-regular target, missing or repeated old text, and no-op replacement. It creates a random same-directory temp with exclusive creation, writes and `fsync`s the complete bytes, then calls `os.replace`. The script temporarily sets and restores `umask` to apply the original permission bits. The v8 signed run verified successful replacement, preserved mode, no temporary residue, exact final content and changeset, and a successful parent focused test for this one input.

## Failure-state requirements

- Before replacement, the target must remain byte-for-byte unchanged; a temporary file must be removed, or its presence must cause the Kernel to reject the complete changeset before live mutation.
- After replacement, an exception or nonzero exit may still result in a committed target. The result must be classified from the actual committed changeset and final file state, never from the exit code alone.
- A successful edit must leave only the target path in the committed changeset and no temporary entry.
- Preserve and verify the target's supported metadata. The proposed script sets basic permission bits; this alone does not prove preservation of ACLs, extended attributes, ownership metadata, or other filesystem metadata.
- Cancellation and process termination must be evaluated against final target state and private-snapshot cleanup, not just process status.
- No directory scope expansion is permitted to make temporary-file handling pass.

## Current evidence and limits

The refreshed `test_sandboxed_python_edit_test_retest_use_exact_file_scopes` passes, but performs direct writes and does not test staged replacement. A headless test feeds the exact deterministic probe proposal through `run_workspace_command` on the real macOS Seatbelt Runner and Kernel commit path; it passes with one modified target, preserved mode `0640`, no temp residue, an unchanged canary, a denied unscoped read, and a successful focused retest. A second test injects temp-create, write, fsync, pre-replace, cleanup, and post-replace failures. Before-replace faults leave the target unchanged; cleanup failure causes whole-changeset rejection; a post-replace exception returns nonzero while the exact target replacement is committed and inspectable. This proves those headless real-OS states, but not signed XPC product behavior or OS-originated failures. The default signed product/XPC identity smoke test passes without running a workspace operation. The existing Launcher and WorkspaceChanges suites pass the focused exact-scope, link, cancellation, process-death, snapshot-race, and changeset-race cases listed in `RUNNER_FEASIBILITY.md`.

The signed v4 request expired without a decision. In v7, the exact replacement returned code 0 and one modified path, but the harness failed before final-state checks. In v8, the corrected signed invocation received one fresh user authorization and passed the parent checks for final content, permissions, no-temp cleanup, canary preservation, exact path, and focused test. Signed refusal passed in v2. Signed failure injection and target-specific adversarial cases remain open. Do not implement or ship the production `edit` Action until all Gate A requirements have a complete evidence-backed disposition.

The latest canonical suite passed with 381 tests in 708.963 seconds after the refusal harness and cleanup fix. Both current-tree and exact-base Freeze checks pass after the final governance metadata update. Independent Code Owner approval remains NOT_PROVEN.
