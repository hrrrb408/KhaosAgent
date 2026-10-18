# M8.4 Action Contract comparison

Real-model result: INCONCLUSIVE; completed formal denominators are A=1 and C=0; the three remaining slots are NOT_RUN. Deterministic results are excluded from this denominator.

The actual production parsers were compiled independently. A rejects a list/shell response missing only text. C accepts exactly that shape, fills the existing empty string, and preserves original semantic/wire validation. Both reject missing scopes, unknown fields, invalid type/action combinations, incompatible Plugin/evolution fields and denied continuation. Both retain the single-correction limit. Signed diagnostic probes observed A's shape failure and C's normalization plus acceptance; enabling diagnostics did not change output or acceptance.

After authorized runs, the comparison will tabulate received/accepted/rejected initial actions, shape and missing-text failures, corrections, normalizations applied/accepted, tool proposals/approvals/executions and complete terminals. Uncaptured values stay NOT_CAPTURED. No conclusion about actual GLM behavior follows from the current synthetic evidence.

## Completed a-01 observations

A received eight initial responses: six accepted and two rejected (6/8 initial acceptance). Two corrections were requested across different turns: one accepted and one failed. Three total shape failures occurred across ten observed initial/correction responses. Missing text appeared twice: once as the only missing key in a nine-key initial object, and once among six missing correction keys. Strict A applied zero normalizations. Seven proposals were independently approved and executed; no candidate was generated.

The recovered initial failure omitted candidateDigest, generation and pluginInput, which C would also reject structurally. The terminal initial failure omitted only text; its correction then omitted text plus five other required keys and failed. The diagnostics do not preserve the rejected type/value payload, so they cannot prove that the nine-key response would pass C's action-type, field-type or semantic checks. No paired counterfactual or reliability improvement is claimed. C has not run; the actual C normalization effect remains INCONCLUSIVE.

Exact denominators, statuses and bounded operation review summaries are in comparison.json and attempts/a-01/. Actual provider request count is NOT_CAPTURED; ten observed model responses are not relabeled as an exact HTTP request count.
