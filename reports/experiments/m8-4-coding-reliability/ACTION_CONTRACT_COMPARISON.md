# M8.4 Action Contract comparison

Formal denominators: A=2, C=2. Exact Host metrics exist for both A attempts and c-01 only. c-02 diagnostic totals are NOT_CAPTURED; its observed events are lower bounds, not zeros or a complete rate denominator. Synthetic and historical results are excluded.

| Metric | A, both attempts | C, both attempts |
| --- | ---: | --- |
| Formal attempts | 2 | 2 |
| Initial accepted / received | 14/16 | NOT_CAPTURED; c-01 complete subset 9/9 |
| Total shape failures | 3 | NOT_CAPTURED; c-01 0, c-02 observed 1 |
| Missing-text shape failures | 2 | NOT_CAPTURED; c-01 0, c-02 observed 1 |
| Corrections accepted / requested | 1/2 | NOT_CAPTURED; c-01 0/0, c-02 observed 0/1 |
| Normalizations applied / accepted | 0/0 | NOT_CAPTURED total; c-01 8/8, c-02 observed 0/0 |
| Proposals / approvals / executions | 14/14/14 | 15/15/15 |
| Read executions / return-zero reads | 14/14 | 15/13 |
| Source modifications / model tests / code repairs | 0/0/0 | 0/0/0 |
| Candidates generated | 0 | 0 |
| Hidden-test PASS / grades completed | 0/2 | 0/2 |
| Complete Task Records | 2/2 | 2/2 |
| Complete Host diagnostics | 2/2 | 1/2 |
| Coding PASS / formal attempts | 0/2 | 0/2 |

Missing-text occurrences include eight recovered c-01 responses as well as rejected shapes; recovered occurrences are not failures. Each of those eight actual responses passed field/type/semantic/wire checks, became a proposal, received a separate owner approval and executed. Prefix snapshots bind normalization to acceptance and exact request hashes. Seven commands returned 0 and one returned 1. Strict A would reject each at its required-key gate. This establishes **OBSERVED bounded protocol improvement**.

A/a-01 accepted 6/8 initial responses. One three-missing-field initial response recovered through correction. Its terminal initial response missed only text, but rejected type/value payload is not retained, so acceptance by C cannot be established. The final correction omitted six fields and failed. Shape failures total three, missing text twice, accepted corrections 1/2. A/a-02 accepted 8/8 initials, needed no correction and completed its final response, without generating a candidate.

C/c-01 accepted 9/9 initial responses, normalized eight, used no correction and ended budget_exhausted after eight reads. The ninth response did not produce a ninth tool execution. C/c-02's observed eighth initial response failed existing unused-field semantic validation, followed by a four-key correction rejected at action_shape. This multi-missing-field correction is outside compatibility. Zero observed normalizations in c-02 cannot establish whole-attempt NOT_TRIGGERED because capture was interrupted.

Correction use fell to zero in c-01 relative to a-01, but this is not a paired replay of identical outputs. c-02 still demonstrates semantic and correction failure beyond the text rule. No newly accepted illegal action was observed; the real-model sample alone cannot prove absence of that risk. Production-parser/adversarial tests establish the bounded rule and unchanged rejection paths, with diagnostics on/off acceptance parity and the same single-correction limit.

Quantitative A/C Comparison Integrity: **NOT_PROVEN**. Full C response denominators are unknown. Even the complete subset (A 14/16 versus c-01 9/9) compares unequal stochastic samples. Fixed A,C,C,A order does not eliminate provider variability; the c-02 multi-hour interruption adds temporal confounding. No population failure-rate reduction is claimed. Actual HTTP request count is NOT_CAPTURED and is not inferred from tools or model response rows.

All four outcomes are NO_CANDIDATE. The observed difference is protocol recovery; source editing, model testing, test-driven code repair and coding success did not improve. With no coding success-rate difference, no numerical follow-up sample-size claim is justified. Any future study needs separate authorization and preregistered tasks, effect size and power; no additional calls are part of M8.4.
