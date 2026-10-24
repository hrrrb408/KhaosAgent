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

One signed attempt started but did not become a valid benchmark trial. The signed telemetry shows one local-provider model request and response, followed by an accepted, parsed, validated, and lowered `read_file` call, invocation digest `e86545fb74518ed6f9185c7d80d80638dac0c691f5509ed0d3091c70877b136d`, and submission toward the Launcher. No selected workspace, approval, Launcher task record, Kernel request/result, or Runner operation was recorded. The model response therefore proves a semantic proposal was produced; it does not prove a completed tool cycle or independent coding result.

The CUA binding attempt timed out (`errAETimeout`) after the test runner had already presented a modal workspace Picker. The UI could not be verified against the printed Task ID, workspace, request digest, command, or scopes. No workspace was selected and no approval was clicked. The run was stopped and preserved as `FAILED_ATTEMPT`; its trailing evaluator `IndexError` is not treated as the primary blocker or as model evidence.

- Trial label: `phase32-stage-b-a-1`; benchmark Task A.
- Signed source SHA: `12ae44732ef591d5e5a0f6f56b820ecbdc730ea1`.
- Raw failed-attempt JSON SHA-256: `bce21ecc7b73b5ea916d494a50815125a8bf5e2129968ec64ed6858515f8626b`.
- Launcher stderr SHA-256: `9d31ff4bf59ffea4978d2681d1978eeff064273dc6abec4f518cee7a7d929eb7`.
- Operator: `codex_agent`; authorization: owner-delegated disposable experiment; owner personally clicked: NO.
- Approvals: 0; Runner operations: 0; unauthorized approvals: 0.
- The unchanged disposable fixture was not counted as a success or failure of model coding ability.
- The one response event reported 43,217 ms. This is a single incomplete attempt, not a benchmark latency measurement. Node/model RSS, token usage, cost, and end-to-end task time were not measured.

The evidence does not establish the local model child-process invocation count, successful workspace selection, or a DSH Session observation after a Kernel result. No second focused trial or full benchmark trial was started because the required signed UI decision path could not be bound and inspected safely.

## Stage counts

| Measure | Result |
|---|---:|
| Signed deterministic Stage A attempts | 3 (2 failures, 1 pass) |
| Completed real-model benchmark trials | 0 |
| Real-model incomplete attempts | 1 |
| H01–H08 completed trials | 0/16 |
| Phase 3.1 A–D replay trials in Phase 3.2 | 0/8 |
| Unauthorized approvals | 0 observed |
| Unexpected workspace mutations | 0 observed |
| Real-model performance aggregates | NOT_MEASURED |

Raw transcripts and private workspace paths remain in owner-only files under `/private/tmp/khaos-dsh-phase3-2-evidence`; they are not copied into Git.
