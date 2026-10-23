# Final Decision

## Status

**Engineering: PASS.** The semantic tool implementation, signed Stage A, eight real-model trials, evaluator tests, DSH tests, canonical suite, and Security Freeze passed. GitHub `security-tests` and `security-freeze` both passed on code/evidence commit `4f8953564ba7305c3c9c845df9cdf46408c4d694`. The report-only follow-up is checked again at its own exact head; its final status is available in PR #45.

**Reliability decision: PARTIAL — Tool Interface Fixed, Model Still Weak.**

Semantic tool parsing and deterministic lowering succeeded in 32/32 calls, compared with eight out-of-policy tool proposals in Phase 3. Independent hidden-test success improved from 0/8 to 6/8. Both Task C repairs passed. Task D failed in both trials because the model proposed a semantically incomplete whitespace-name fix. The signed operator correctly denied both requests, no Runner executed either edit, and no workspace changed.

## Acceptance values

| Requirement | Result |
|---|---|
| Real model integrated | PASS; local CPU llama.cpp model, 40 calls across 8 signed trials |
| Real DSH AgentLoop | PASS |
| Real coding trials | 8 |
| Hidden-test task success | 6/8 |
| First-pass task success | 4/8 |
| Repair success | 2/2 Task C trials |
| Semantic parsing / lowering | 32/32 / 32/32 |
| Tool-result delivery / Session continuity | 32/32 / 32/32 |
| Unauthorized workspace changes | 0 |
| Unauthorized approvals | 0 |
| Kernel authority / ABI / scope delta | 0 / 0 / 0 |
| Task D | FAIL in 2/2 trials; incomplete edits were denied |
| Candidate generation / isolated evaluation | NOT IN SCOPE for Phase 3.1 |
| Trusted Candidate activation | NOT_AUTHORIZED |
| Node / model resource measurements | PARTIAL; RSS measured, process cleanup observed; Node startup, model initialization, token counts, and cost NOT_MEASURED |
| Canonical tests | PASS, 412 tests in 835.535 seconds on the final local rerun |
| Security Freeze | PASS on current inventory and exact stacked base 391848b02a2ec4d095cef7f71f2e55947ec24b24 |
| GitHub CI | PASS on code/evidence commit `4f8953564ba7305c3c9c845df9cdf46408c4d694`; report-only follow-up checked separately on PR #45 |
| Owner Review | PENDING |
| Independent Code Owner Review | NOT_PERFORMED |
| Technical Gate A | UNCHANGED |
| Production Harness migration | NOT_AUTHORIZED |

The final handoff records the exact current Phase 3.1 SHA and its own Draft PR checks. The CI result above binds the implementation and experiment evidence; no CI result from PR #44 substitutes for Phase 3.1 validation.

## Recommendation

Keep the semantic tool interface and its event correlation stable. Do not continue changing tool formats to compensate for Task D reasoning. A separate experiment should isolate model, context assembly, and repair strategy against the same frozen Task D inputs. Preserve the D failures and all prior evaluator corrections.

The measured 6/8 result is an improvement, but repeated Task D failure means DSH is not yet established as a reliable general coding harness. Continue only bounded experiments. Do not replace the production Agent Harness or activate a trusted Candidate on this evidence.

## Exact evidence bindings

- Phase 3.1 parent: PR #44 exact head 391848b02a2ec4d095cef7f71f2e55947ec24b24.
- Frozen experiment source used to build the signed runtime: a2800e00ae609a2f282f4595aff278cc1de62899.
- DSH: 687f282e8625c6b8d11ff58211a90524be2e4317.
- Benchmark freeze SHA-256: ff0075a1f44b21be91e685c153a6fb22bb4f02301a62496e930bbc81de35f65d.
- Dataset SHA-256: 033f5d9c776f025e21642911b6d13e2afcc32b876a39fab377ae0a6279dc5091.
- Local model SHA-256: fadc3e5f8d42bf7e894a785b05082e47daee4df26680389817e2093056f088ad; upstream identity UNKNOWN and quantization NOT_MEASURED.
- Signed build inputs SHA-256: a28cbd2329eb19b026ae9054c65cd68f1c4f087dec5eed7afe9799866e9f2b95.

The final PR head is recorded by GitHub after this report is committed. The signed app proves the exact Phase 3.1 runtime source above; the final evaluator/report follow-up does not claim that the old app was rebuilt from a later documentation-only commit.

## Governance

- Development: AUTONOMOUS
- Experimental test operator: CODEX_AGENT
- Owner Review: PENDING
- Independent Code Owner Review: NOT_PERFORMED
- Production migration: NOT_AUTHORIZED
- Automatic merge: NOT_AUTHORIZED
