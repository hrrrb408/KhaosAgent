# Scoped Repository Discovery Proof

Date: 2026-10-15

Branch: `codex/scoped-repository-discovery`

Base: `dc49d86eff68d97e9f384d80a68275eda4c64120` (merged PR #14)

## Result

The bounded discovery path passed its main proof on a disposable repository:
GLM-5.3-Flash proposed directory roots without receiving source paths in the
task prompt, read the discovered files, changed only `src/parser.py`, and
passed the task test. The baseline failed before the run; an independent
parent-selected sandbox verification then passed seven additional parser cases.
The signed product's deep signature verification passed.

The separate recheck of the original frozen Runner task did **not** produce a
repair. Its baseline failed and gold patch passed in separate parent-only
copies, but all three real-model attempts ended before a candidate edit. Those
attempts are recorded as failures, not as benchmark gains. No full benchmark was
run.

## Requirement audit

| Phase / requirement | Result | Evidence and boundary |
| --- | --- | --- |
| Phase 0: audit Host action/prompt, approval, `fs.read`/`fs.list`, scope filtering, and Seatbelt policy | Complete | Existing `WorkspaceReadScope` grants a directory subtree, filters ancestor listings, and rejects invalid relative paths. Kernel listing uses descriptor-relative, no-follow traversal; it emits only name/kind/size and enforces 128 entries and 4 KiB aggregate UTF-8 name bytes. Seatbelt grants a scoped directory as a subtree and a file as a literal; it omits unsafe or missing roots. No Kernel implementation or authority was changed. See [source map](#source-map). |
| Phase 1: approved directories can be listed/read; outside paths and canary remain hidden | Pass | `test_scoped_directory_discovery_hides_canary_and_symlink_targets` exercised the real macOS Seatbelt Runner and Kernel SDK with only `src` and `tests` in scope. It allowed the scoped source read, filtered the workspace-root listing, and observed nine denials covering unapproved files/directories, `../`, absolute paths, and symlink traversal. Canary filename/content were absent from tool output and its bytes were unchanged. The symlink entry contained no target. A real nested APFS mount was rejected by `test_snapshot_rejects_real_nested_apfs_discovery_source`. |
| Phase 1: refusal stops, list and result budgets hold | Pass with a capture limit | The final v4 product refusal run had one proposed list, zero Runner executions, zero Runner seconds, one denial, no retry, and no changes. The 67-entry overflow fixture encoded 4,876 bytes of listing metadata against a 1,399-byte stdout allowance; the approved Runner operation returned exit 1 and a 278-byte bounded task result. The model then proposed a second, different listing, which was cancelled. The parent record confirms no changes/canary output. The exact first tool-result text was not separately retained; the fixed overflow result is established by the trusted Launcher source, while the signed run establishes the nonzero bounded result and stopped follow-up. |
| Phase 2: real model discovers, reads, edits, tests | Pass on the synthetic task | The signed GLM-5.3-Flash Coding Plan product proposed `src` and `tests`, then requested the observed `src/parser.py`, `src/utils.py`, and `tests/test_parser.py`. The issue-only prompt named neither directories nor files and contained no patch. Each list/read/edit/test operation received a separate Launcher approval. Agent tool return codes were `[0, 0, 0, 0]`; the only changed path was `src/parser.py`. Parent baseline test returned 1; candidate test returned 0. A separate read-only Kernel/Seatbelt run returned baseline 1 and candidate 0 over seven additional cases. See [`real-glm-v4-coding.json`](real-glm-v4-coding.json), [`independent-parser-verification.json`](independent-parser-verification.json), and [`signed-product-v4.json`](signed-product-v4.json). |
| Phase 3: recheck a discriminating original task | Attempted; unsuccessful | The frozen `runner-exception-classification` baseline returned 1 and gold returned 0 in parent-only grader copies. Three real GLM attempts on the same task prompt produced no candidate edits and failed the hidden grader. Detailed blockers are below and in [`original-task-recheck.json`](original-task-recheck.json). The eight non-discriminating tasks were not counted as improvements, and the full benchmark was not forced. |

## Phase 0 findings

The pre-existing shell action accepts exact read roots, but its scoped OS rule
for a directory covers that whole subtree. A real shell probe showed that
`readlink` inside an approved source directory can reveal symlink-target text,
even though following that symlink to read its target is denied. Therefore the
Agent's discovery action uses a fixed Runner that calls the existing Kernel
`fs.list`; it does not run model-supplied `ls` or other directory-scanning
commands. Kernel `fs.list` omits symlink targets. The approval screen now states
that a directory root authorizes reading every descendant file. The observed
shell behavior is summarized in
[`shell-directory-probe.json`](shell-directory-probe.json). This evidence does
not claim that symlink-target text is hidden from every possible approved shell
command.

`WorkspaceReadScope` already supports directory roots, permits reads under
those roots, filters ancestor listings to only relevant entries, and rejects
root/traversal/absolute scope forms. Kernel `fs.read` and `fs.list` validate
paths against that retained scope. Snapshot listing uses descriptor-relative
lookup without following symlinks, verifies entries and mount identity, and
enforces existing entry/name bounds. The Seatbelt read policy is generated only
for existing regular-file or directory roots; a directory receives a subtree
rule and a file receives a literal rule. A nested APFS volume is rejected when
the workspace snapshot is formed. These existing controls are reused without
changing Kernel IPC or filesystem authority.

## Phase 2 signed-product run

The fixture was a fresh Git repository with `src/parser.py`, `src/utils.py`,
`tests/test_parser.py`, a workspace-root canary, and a symlink from the approved
source subtree to that canary. The user request described only the behavior:
trim whitespace from comma-separated tags and ignore empty tags. No source path,
file name, expected code expression, or gold patch was sent in the initial task.

GLM proposed `list(src, tests)`, read the observed source and test files, wrote
one scoped edit to `src/parser.py`, and ran the focused test. The parent verified
the original test failed, the final test passed, only the parser source changed,
and the canary stayed unchanged and did not appear by filename or contents in
Launcher output. The independent verifier ran from a separate baseline and
candidate snapshot, used no write scope, and passed seven additional cases.

The v4 app was signed locally and passed
`codesign --verify --deep --strict`. It used GLM-5.3-Flash through the existing
BigModel Coding Plan adapter; the independent Launcher data-sharing prompt was
approved for this disposable task, and each operation was separately reviewed.
This proves one synthetic coding task on this host. It does not establish
general model reliability, benchmark improvement, or distribution signing.

The refusal control on the same v4 build is separate: after the first
directory-list approval was cancelled, the record showed one proposal, no
command return codes, no Runner execution, no change, and no second proposal.
The Agent returned a stop explanation. The overflow control is also separate
from the coding-quality score.

## Phase 3 original-task recheck

The task was `runner-exception-classification`. Its fixed prompt and frozen
baseline were retained across the attempts. A parent-only control applied the
hidden tests to copies: baseline failed (return code 1) and gold passed (return
code 0). Neither hidden tests nor gold source entered a model workspace.

1. `discovery-01` failed during the first list request on an absent requested
   root; the then-current all-or-nothing list handling returned
   `runner_failed`. No shell command ran and no source changed.
2. `discovery-02` used the per-root list-error handling. GLM discovered paths
   and attempted to read three files whose combined size was 27,967 bytes.
   The real Runner failed at the existing 8 KiB process-output limit. A
   separate reproduction confirmed that reading a small file (2,841 bytes)
   and emitting a bounded 1,001-byte range succeeded. In the full-read failure,
   the recorded error context included `output_limit` and a cleanup
   `PermissionError(EPERM)`; the underlying cleanup denial was not isolated.
   There was no write or candidate edit.
3. `discovery-03` used the v4 bounded-read prompt. One list command returned
   nonzero, after which the Host ended with `agent_host_invalid_response`. The
   original response shape/cause was not retained, so no more specific cause is
   claimed. There was no write or candidate edit.

The independent grader returned 1 for each candidate. This recheck did not
prove that the original repository task can be repaired with this harness. It
did identify two remaining problems in the original-task path: safely
recoverable oversized reads currently surface as `runner_failed`, and one v4
Host continuation failed protocol decoding for an unknown reason. The bounded
synthetic task remains the successful proof for this goal; the original-task
results remain failed evidence.

## Trust-boundary and change accounting

| Item | Delta |
| --- | --- |
| Runtime production code | +101 / -20 lines across Host, protocol, and trusted Launcher |
| Trusted production code | +84 / -9 lines (net +75): AgentHost protocol +21/-3; Trusted Launcher +63/-6 |
| Untrusted Host production code | +17 / -11 lines (net +6) |
| New architecture concepts | One bounded AgentHost `list` proposal kind; no new subsystem |
| New trusted processes | 0 |
| New Kernel IPC operations | 0; existing Runner-to-Kernel `fs.list`, `process.exec`, and commit are reused |
| New persistent runtime state | 0 |
| New dependencies | 0 |
| Removed duplication / abstractions | Shared Launcher helpers now enforce the same result-stream allowance and Runner-source byte bound for shell and list paths |

Trusted Launcher code is required to turn the untrusted Host's path proposal
into a fixed, reviewable invocation, preserve the existing per-operation
approval/continuation rules, and keep combined listing output inside the
existing result budget. That enforcement cannot live only in the untrusted
Host. The existing Kernel `fs.list` already enforces scoped descriptor-based
access and no-follow behavior, so no new Kernel authority or implementation was
needed. A model-supplied shell listing would use the broader OS subtree grant
and can expose symlink-target text; the fixed listing Runner avoids that
discovery path.

## Validation

The canonical command `python3 -m unittest discover -s tests -v` passed all 331
tests in 677.262 seconds on 2026-10-15. This includes both new regressions, the
AgentHost protocol probe, real macOS Seatbelt execution, the real nested APFS
mount rejection, and the headless signed-product authentication check. The
default suite did not open an interactive Picker. `git diff --check` passed
before the report was added; it is rerun before commit.

## Source map

- [AgentHost action and prompt](../../khaos/macos/AgentHost.swift)
- [AgentHost wire protocol](../../khaos/macos/AgentHostProtocol.swift)
- [Trusted Launcher bridge and approval UI](../../khaos/macos/TrustedWorkspaceLauncherMain.swift)
- [Workspace read scope and listing](../../khaos/kernel/workspace_snapshot.py)
- [Seatbelt workspace read policy](../../khaos/kernel/macos_seatbelt.py)
- [Scoped Runner attack/regression](../../tests/test_launcher.py)
- [Nested mount regression](../../tests/test_workspace_snapshot.py)
- [Normative ABI](../../docs/KERNEL_ABI.md)
- [Threat-model evidence](../../docs/SEED_THREAT_MODEL.md#2026-10-15-scoped-repository-discovery)
