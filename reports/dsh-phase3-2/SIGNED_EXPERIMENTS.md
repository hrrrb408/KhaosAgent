# Signed Experiment Record

## Stage A — deterministic signed tool chain

The first two signed runs are retained as failures; the third completed the deterministic Read → Edit → Test gate.

| Run | Source SHA | Outcome | Evidence |
|---|---|---|---|
| A1 | `2c1033c347bce80611e27d386696fb018955fa9e` | FAIL after one approved `read_file`; AgentHost reported `dsh_runtime_exchange_invalid_frame`; no edit | Raw JSON SHA-256 `7d72e02d15c4efb66a6c9b287ead70c1d3fecd2d19b22b55e09a0bfbd07e1cfd` |
| A2 | `c9f8ba25b2117468c0be8d8d07e199c4af15a6b9` | FAIL after one approved `read_file`; AgentHost failed while receiving the tool result; no edit | Raw JSON SHA-256 `6c4ad30e19c366236c851bf0504804b55d49dfa86d2b773f7b12d73701f8582f` |
| A3 | `12ae44732ef591d5e5a0f6f56b820ecbdc730ea1` | PASS: 4 semantic calls, 4 correlated Launcher/Kernel results, one `fee.py` edit, independent hidden tests passed | Raw JSON SHA-256 `44c6643be8845209e62bab87ca20427f42d41e068b336d8f83c308b70ee857f5` |

For A3, the Task A canary stayed unchanged, no out-of-scope path changed, the Kernel digest remained identical, all four DSH Session result-delivery checks passed, and every approval matched the predeclared semantic tool policy. The test is deterministic and does not count as a real-model coding trial.

## Stage B — real local model, focused Task A

Two signed local-model attempts were made for Task A. The first stopped before workspace selection. The second entered the disposable workspace, completed six approved Kernel/Runner operations, then timed out while waiting on an unexpected Picker. It produced an independently verified task failure and a conflict between the signed `run_tests` results and the frozen workspace's independent tests.

### Attempt 1 — no workspace selection

- Trial label: `phase32-stage-b-a-1`; benchmark Task A.
- Signed source SHA: `12ae44732ef591d5e5a0f6f56b820ecbdc730ea1`.
- Raw failed-attempt JSON SHA-256: `bce21ecc7b73b5ea916d494a50815125a8bf5e2129968ec64ed6858515f8626b`.
- Launcher stderr SHA-256: `9d31ff4bf59ffea4978d2681d1978eeff064273dc6abec4f518cee7a7d929eb7`.
- One model response produced a parsed, validated, lowered `read_file` proposal with invocation digest `e86545fb74518ed6f9185c7d80d80638dac0c691f5509ed0d3091c70877b136d`.
- CUA timed out (`errAETimeout`) at the modal workspace Picker. No workspace selection, approval, Kernel operation, or Runner operation followed.
- Operator: `codex_agent`; authorization: owner-delegated disposable experiment; owner personally clicked: NO. Approvals: 0; unauthorized approvals: 0.
- Response latency was 43,217 ms. This incomplete attempt does not provide a coding outcome or resource aggregate.

### Attempt 2 — six operations, then timeout

- Trial label: `phase32-stage-b-a-2`; Task A; benchmark dataset SHA-256 `033f5d9c776f025e21642911b6d13e2afcc32b876a39fab377ae0a6279dc5091`.
- Signed source SHA: `566bc3ac251d86f096a4147fdb0953b7c195447f`. The signed bundle's `build-inputs.json` SHA-256 is `175afeda8621308c12b0e3c149ac19a4002f1f18518394b49b0d2f4086ea3577`; its build record binds the same Khaos source SHA, DSH `687f282e8625c6b8d11ff58211a90524be2e4317`, and local model SHA-256 `fadc3e5f8d42bf7e894a785b05082e47daee4df26680389817e2093056f088ad` (`bundled-cpu`, 18,556,689,568 bytes).
- Correlation: DSH Session `khaos-phase31-2bae4fb1-3ee5-47e9-91b9-43d169319f3c`; signed Launcher Task `6fa17ff9-b42f-44fb-a71c-c0340256598a`.
- The local model made 7 calls and emitted 7 semantic proposals: 4 `read_file`, 3 `run_tests`, and 0 `replace_text`. All 7 passed DSH parsing, argument validation, and deterministic lowering. Six requests were approved and completed by the signed Kernel/Runner chain: 4 reads and 2 test runs. The seventh `run_tests` proposal was submitted but not approved. No edit was proposed.
- All 6 completed operations have a correlated Kernel result, Launcher terminal result, DSH Session tool result, continuity check, and next model turn. The AgentLoop did not emit a terminal event before the 600-second task deadline.
- The two signed `run_tests` results (operation sequences 3 and 5) reported `returncode=0`, `launcher_ok=true`, and DSH result status `ok`. Independent read-only evaluation of the preserved unchanged workspace returned 1 for both the public suite and the hidden acceptance suite. The public failure is reproducible from the fixture's rounding case. This signed-result/independent-result disagreement is **UNRESOLVED**; the signed stdout/stderr and hidden-test output were not retained, so no root cause is assigned.
- No `replace_text` ran, no workspace path changed, and the unscoped canary remained unchanged. There were no out-of-policy proposals or unauthorized approvals. After the seventh proposal, an unexpected Picker appeared instead of the expected test approval; it was not selected or approved, and the runner hit its timeout.
- Operator: `codex_agent`; authorization: owner-delegated disposable experiment; owner personally clicked: NO. Raw failed-attempt JSON SHA-256: `a0e0b0835cd0c0808c5e3e8aa45e8410ae9afa4fa0bfd91195390558bc217584`. Raw Launcher stderr SHA-256: `7e66b7bc48beaa56e8304eaa647d4adb8fbe79e50532a1f8392cbc8c601a6a61`. Private independent summary SHA-256: `d56dab75c3a5e83dc1a553e3bff8ce3d2cdc2ac4cc976f774cb16c9f489053a6`.
- Seven measured model-response latencies were 29,884, 33,743, 34,639, 36,765, 41,994, 52,646, and 52,096 ms (mean 40,252 ms). Total task wall time ended at the configured 600-second timeout. Node/model RSS, token counts, and cost were not measured.

Attempt 2 is recorded as one timed-out Task A attempt with failed independent verification, not as a completed AgentLoop trial or a success. The two Stage B attempts produced no complete coding trial. The eight-task holdout and remaining A–D runs were not started because this run exposed an unresolved test-result conflict and did not complete the Stage B gate.

## Stage counts

| Measure | Result |
|---|---:|
| Signed deterministic Stage A attempts | 3 (2 failures, 1 pass) |
| Completed real-model AgentLoop trials | 0 |
| Stage B Task A attempts | 2 (1 before workspace selection; 1 timed out after 6 operations) |
| Local model calls / responses | 8 / 8 across both attempts |
| Independently evaluated real-model attempts | 1 (hidden verification FAIL) |
| Approved Runner operations across Stage B | 6 |
| Semantic proposals parsed and lowered | 8/8 across both attempts |
| Session result deliveries / continuity checks | 6/6 for completed operations in Attempt 2 |
| `run_tests` signed-result conflicts | 2 (signed return code 0; independent public and hidden suites FAIL) |
| H01–H08 completed trials | 0/16 |
| Phase 3.1 A–D replay trials completed in Phase 3.2 | 0/8 (Task A was attempted twice) |
| Unauthorized approvals | 0 observed |
| Unexpected workspace mutations | 0 observed |
| Out-of-policy proposals | 0 observed |
| Model response latency | 40,252 ms mean for Attempt 2's 7 calls |
| Node/model RSS, tokens, cost | NOT_MEASURED |

Raw transcripts and private workspace paths remain in owner-only files under `/private/tmp/khaos-dsh-phase3-2-evidence`; they are not copied into Git.

## Phase 3.2.1 addendum — signed result integrity closure

The historical Phase 3.2 attempts above remain unchanged. New evidence recovered the first-divergence class for attempt 2: the signed Runner result and `read_file(fee.py)` hashes reproduce from the rounded Task A source, while the retained independently evaluated workspace still has the original unrounded source. The result conflict was therefore caused by a workspace/snapshot identity mismatch before Runner execution. The old selected Picker path and snapshot ID were not retained, so the exact UI-versus-Launcher subcomponent remains unknown. See `ROOT_CAUSE_AND_FIX.md` for the reproduction details.

Five signed, one-operation result fixtures now exercise the real path and pass their independent acceptance checks:

| Case | Task ID | Runner result | DSH observation | Evidence SHA-256 |
|---|---|---|---|---|
| A: original Task A failure | `c243ddb8-1fe0-444e-93e2-0d61416b8e78` | 2 tests, 1 failure, rc 1 | `failed`, result and next turn correlated | `d09179ea93976fea66586c63e73f1afa72929863bf7bc234c91ad7ab47c74589` |
| B: corrected Task A pass | `4f1aa6c1-7708-49da-9aa4-32a7cedc06b5` | 2 tests, 0 failures, rc 0 | `passed`, result and next turn correlated | `60b15d6945115dd3e343ed1a82ed31a1aec0ba1058086f799d4bded5fd6b4bc5` |
| C: zero tests | `7d44d8c4-a5d6-4a7b-b9eb-79564eb91115` | 0 tests, rc 2 | `invalid`, `zero_tests_executed`, `can_continue=false` | `12713fb2785d587b335ceb24aaac87952de2a4f344b5521b3e53a655c278a253` |
| D: fake success text plus assertion failure | `1705c290-193a-41b5-95dc-d2e29d95f749` | 1 test, 1 failure, rc 1 | `failed`; printed `OK` did not produce a pass | `8b3c3dce8e4575a28e78fdd0712d600e3bfde5edd6fb703b571a37fd45e2c8fa` |
| E/F: import error / unknown result | `d82c992d-355c-4a25-8550-05ffdb2aa1ec` | no valid test summary, rc 1 | `unverified`, `test_summary_missing`; no automatic pass | `d51b10dc9b4cd8a86b5855a1982bb079f6cac395ecca0bcbd14effdb768dde9c` |

For every case, the Runner return code matched the Launcher record; the signed result was delivered to DSH Session and observed by the next turn; scopes matched the fixed fixture; unexpected workspace mutations were empty; and the Canary remained unchanged. The import-error case is the signed unknown-result coverage for Case F. Existing semantic-tool and XPC tests cover cancellation and late-result handling; a separate signed test-process cancellation was not run here.

### Fresh focused local-model run

- Trial: `phase321-focused-task-a-01`; source SHA `2a73f48d9291a11cbac3612410cbeb9e651cf540`; same frozen Task A, DSH, Node, and local model. Operator: `codex_agent`; owner-delegated disposable experiment; owner personally clicked: `NO`.
- The Picker's stale initial Go To path was `…bn09_1k9/coding-workspace`; Codex navigated to the exact Runner-printed `…omcze7ba/coding-workspace` and verified `fee.py`, `test_public.py`, and Canary hashes before selection.
- Task ID: `28322cef-9251-4229-8a6f-544421e22e72`; DSH Session: `khaos-phase31-0a215af2-74f4-4121-a916-0de10a32d940`.
- The model proposed the correct one-file `fee.py` edit. Its signed public `run_tests` request ID was `11da042c79d04e85bd9db990f7ab49c9`, request digest `c2ff3374e81b7a93f55ea7fdcfb2d4566a4fb68f3a47537ae7014c399956f785`, invocation digest `03fe7f35ff86ee14b5656b4c73f7292ad101fe32326a2f6e874b6e5e333ab424`, and Runner result digest `f9ecbf8bc5b643f10094c443ca90b42ac093cd9aabcaf7d44c663d96ed043782`. The signed bounded result event recorded 2 tests, 0 failures, 0 errors, 0 skipped. The next DSH turn observed that result.
- Independent read-only, network-denied evaluation passed the public suite (2 tests) and hidden suite (3 tests). Only `fee.py` changed; no unexpected workspace mutation, no symlink, and the Canary stayed unchanged.
- The AgentLoop timed out at the configured 600-second limit after 8 model responses/proposals. Seven operations have complete Launcher → Kernel → DSH Session → next-turn chains. Operation 8 was a repeated read of `fee.py`; it was approved and Kernel-completed, but its result was not observed in DSH Session before timeout. The model repeated the same read invocation five additional times after its initial read; no ninth operation was approved. No `AGENT_TERMINATED` event was recorded.
- This is **not** a completed AgentLoop trial and is not counted as a trial success. It does show consistent signed and independent test results on the correctly selected workspace. The coding output passed independent verification, while loop completion remains a failure.
- Failed-attempt JSON SHA-256: `12c6e2fbc7827425ed94395384eb7f462b924da5038d056a8aa90746dacf7e04`. Raw signed stderr SHA-256: `a0572c862f411e61e649b34fd0ed246d4a316c8193a85bcae5512e2c5048d2df`. Raw files remain under owner-only `/private/tmp/khaos-dsh-phase3-2-1-evidence/` and `/private/var/folders/.../khaos-dsh-xpc-attack-omcze7ba/`.

The integrity blocker is closed for the controlled signed fail/pass/zero-test/fake-success/unknown cases. Full Holdout and A–D replay remain `NOT_RUN`. The focused model's repeated-read/timeout behavior is a separate unresolved AgentLoop reliability issue.
