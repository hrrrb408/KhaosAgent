# Signed Product Acceptance Report

Date: 2026-10-18

## Final deterministic run

The signed macOS Seed product acceptance completed successfully with the deterministic Agent Host model probe. Evidence is preserved at reports/m8-action-reliability/coding-loop-deterministic-accepted-03.json. Command:

KHAOS_RUN_PRODUCT_CODING_LOOP_UI=1 KHAOS_CODING_LOOP_EVIDENCE_PATH="$PWD/reports/m8-action-reliability/coding-loop-deterministic-accepted-03.json" python3 -m unittest discover -s tests -p test_macos_xpc_sandbox.py -k test_seed_app_builds_and_authenticates_its_kernel_service -v

Result: exit code 0, one test passed in 472.667 seconds. Evidence status is passed and model_mode is deterministic-model-probe; provider is null.

The run captured seven approved no-op operations followed by a final response. The coding fixture had six approved operations with return codes [1,1,1,0,0,0], changed only tags.py, preserved the unscoped canary, and passed the parent-process focused retest. A separate safe read was approved and the out-of-scope write was canceled; the workspace remained unchanged. Workspace Picker cancellation produced zero approvals and zero executions. The tool budget ended at eight approved and executed calls with no ninth approval. In the Host termination case, the in-scope crash-marker.txt write persisted, the Runner return code was 1, the Agent Host process exited, and the terminal outcome was agent_host_terminated with restarted_host_rejected_stale_tool_result.

The test also preserved an invalid-JSON terminal case as terminal_outcome_not_captured with zero Runner operations. It is not counted as task success.

## Preserved failed and incomplete attempts

Earlier evidence files remain in this directory and are not overwritten: coding-loop-deterministic.json (non-TTY input closed), coding-loop-deterministic-rerun.json (a default-launch smoke marker contaminated the denial fixture), coding-loop-deterministic-final.json (aborted after an accidental default-app interaction), and coding-loop-deterministic-verified.json (aborted after the Picker returned the parent directory). coding-loop-deterministic-accepted.json and coding-loop-deterministic-accepted-02.json also failed in the Host termination phase: the UI state read delayed release of the test gate until after the command completed, so the terminal outcome was task_cancelled instead of the required agent_host_terminated. Those failures were caused by acceptance orchestration and are retained as history. The corrected accepted-03 run clicked the reviewed command and released the gate immediately; its result is independently recorded above.

The app was launched from its signed bundle through Launch Services. This result proves the deterministic signed product path exercised in this test. It does not measure GLM-5.3, local-model coding quality, or general coding reliability.
