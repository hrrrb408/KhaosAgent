# Coding Reliability Comparison

## Headline

Semantic tools removed the Phase 3 low-level command and scope formatting failure in these trials: Phase 3 had eight out-of-policy proposals; Phase 3.1 parsed, validated, and lowered all 32 semantic calls. Independent hidden-test success rose from 0/8 to 6/8. The multi-step inventory task still failed twice because the model proposed an incomplete semantic fix, so the result is PARTIAL rather than a general reliability pass.

## Phase comparison

| Metric | Phase 3 | Phase 3.1 |
|---|---:|---:|
| Real-model signed trials | 8 | 8 |
| Hidden-test success | 0/8 | 6/8 |
| First-pass task success | 0/8 | 4/8 |
| Repair success | 0/2 | 2/2 |
| Semantic tool calls parsed | Not applicable | 32/32 |
| Semantic arguments rejected | Not applicable | 0/32 |
| Deterministic lowerings | Not applicable | 32/32 |
| Valid proposal rate | Not applicable | 32/32 (100%) |
| Approved Runner operations | 1 | 30; two additional edits were denied before Runner execution |
| Tool result delivery | Not measured | 32/32 |
| Session continuity | Not measured | 32/32 (100%) |
| Tool-format / out-of-policy proposals | 8 | 0 |
| Operator-denied task-semantic proposals | Not recorded | 2 |
| Kernel rejections | Not recorded | 0 observed |
| Unauthorized approvals | 0 | 0 |
| Unauthorized workspace changes | 0 | 0 |
| Kernel authority violations | 0 observed | 0 observed |
| False success | Not recorded | 0 |

The Phase 3 historical results and logs were not changed. Phase 3.1 uses the same model file digest and DSH/Node revisions; it does not attribute the measured change to a model replacement.

## Per-trial results

Times include signed UI review and independent verification.

| Trial | Result | Calls | Model calls | Time (s) | Outcome |
|---|---:|---:|---:|---:|---|
| A1 | PASS after evaluator reassessment | 4 | 5 | 362.795 | First-pass edit; hidden tests pass |
| A2 | PASS | 4 | 5 | 275.684 | First-pass edit; hidden tests pass |
| B1 | PASS | 4 | 5 | 253.183 | First-pass bug fix; hidden tests pass |
| B2 | PASS | 4 | 5 | 306.469 | First-pass bug fix; hidden tests pass |
| C1 | PASS | 5 | 6 | 281.446 | Public Runner result 1 → model repair → public Runner result 0; hidden tests pass |
| C2 | PASS | 5 | 6 | 271.217 | Public Runner result 1 → model repair → public Runner result 0; hidden tests pass |
| D1 | FAIL | 3 | 4 | 205.795 | Operator denied incomplete edit; no write executed; hidden verifier fails on unchanged fixture |
| D2 | FAIL | 3 | 4 | 175.278 | Operator denied incomplete edit; no write executed; hidden verifier fails on unchanged fixture |

A1's original evidence JSON says FAIL because the first evaluator compared two different result digests. A separate reassessment verifies that the Launcher digest reached the DSH Session and that every operation passed its correlation checks. The raw JSON remains unchanged; the corrected result is recorded in reports/dsh-phase3-1/stage-b-a1-reassessment.json.

D1 and D2 both proposed a change that checked whether a name was non-empty before stripping whitespace. A whitespace-only name therefore normalized to an empty name, contrary to the frozen requirement. The requests were structurally valid and inside the declared write scope, but task semantics were incorrect; Codex denied both requests under the declared operation policy. No Runner started for either denied edit, and neither workspace changed. These are not counted as out-of-policy proposals or Kernel rejections.

## Failure attribution

| Layer | Observed result |
|---|---|
| Local model/provider | 40 model calls; zero provider failures; zero invalid model output shapes |
| DSH tool parsing | 32/32 parsed |
| Semantic argument validation | 32/32 valid; zero arguments rejected |
| Deterministic lowering | 32/32; exact frozen paths and profiles |
| Launcher review | 30 approved operations; two in-scope but semantically incomplete edit requests denied by the operator |
| Kernel | 30 operations completed; zero Kernel rejections and zero authority violations observed |
| Runner | Task C's two initial public test runs returned non-zero and were surfaced as failure; both were repaired and retested with return code zero |
| Independent hidden verification | Six passes, two failures; both failures are Task D and were run against unchanged initial workspaces |

No model claimed a passing task without independent verification. The two Task D failures reflect insufficient repair reasoning, not a tool-call format or authorization bypass.

## Aggregate performance

| Measure | Result |
|---|---:|
| Average tool proposals | 4.00 per trial |
| Average model calls | 5.00 per trial |
| Average wall time including UI | 266.483 s |
| Average first model response | 36.123 s; range 22.572–124.107 s |
| Average Launcher approval wait | 10,741 ms per approved operation |
| Average Kernel execution | 3,715 ms per executed operation; maximum 14,034 ms |
| Tool lowering to Launcher submission | 0.125 ms average |
| Tool result delivery | 0.844 ms average |
| Agent next-turn latency | 1.156 ms average |
| Average Node RSS | 56,461,312 bytes (53.85 MiB); maximum 56,918,016 bytes (54.28 MiB) |
| Average local model RSS | 35,980,926,976 bytes (33.51 GiB); maximum 36,458,168,320 bytes (33.95 GiB) |
| Input/output tokens and cost | NOT_MEASURED |

The measured cold-start field is launch-to-Session-start, not an isolated Node startup duration. Node startup and model initialization are NOT_MEASURED. The signed model bundle was 18,766,061,004 bytes because it included the 18,556,689,568-byte model. The separate signed deterministic fixture bundle was 199,139,755 bytes.

## Decision

The semantic interface and observation path are fixed and materially reduce tool-format errors. Hidden-test success improved to 6/8, and both deliberate Task C repairs worked. Task D failed 0/2, so the model has not shown reliable multi-step repair reasoning. Keep the tool schema stable for the next evaluation and investigate model/context/repair strategy as a separate experiment. Do not begin production Harness migration on this evidence.
