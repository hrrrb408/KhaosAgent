# Action Schema Candidate Comparison

Date: 2026-10-18

## Offline method

The compiled AgentHostActionOutputProbe compares A, B, and C using the same synthetic inputs and the production Host semantic validator and reply encoder. It covers the five action types, full ten-field compatibility, action-specific forms, missing text after seven successful tool results, invalid/missing fields, explicit scopes, malformed and oversized JSON, refusal, and untrusted tool results. This is protocol evidence only; it is not a measurement of GLM output quality.

| Candidate | Model-facing shape | Result for full ten-field legacy actions | Result for the observed list/shell missing-text shape | Runtime change |
| --- | --- | --- | --- | --- |
| A: strict ten-field | One exact ten-field schema | Accepts all five valid types | Rejects | None; baseline |
| B: strict per-action | Five exact action-specific schemas, while retaining the legacy ten-field union | Accepts | Rejects the nine-key legacy shape; it accepts its four-key shell form only when that full per-action schema is present | Not selected |
| C: restricted compatibility | Existing ten-field schema plus one missing-text exception for list and shell | Accepts all five valid types | Accepts missing text only for list or shell, then inserts the existing empty string value | Selected |

Candidate B's action-specific required keys in the offline comparator are: text=(type,text), list=(type,readScope,writeScope), shell=(type,argv,readScope,writeScope), plugin=(type,pluginID,candidateDigest,generation,pluginInput), and evolution=(type,pluginID,candidateDigest,generation,evolutionGoal). It remains strict and can be safe, but the extra schemas do not address the observed nine-key shape. It is a larger protocol change than the bounded exception in C.

## Results and decision

All candidates accept valid ten-field actions. At the seven-tool missing-shell-text case the results are A=reject, B=reject, C=accept. C also accepts missing text for list. All three reject missing final-text content, missing readScope or writeScope, unknown fields, wrong types, unsupported types, incompatible Plugin/evolution fields, malformed JSON, oversized content, and a refused continuation. Explicit scope strings are preserved into the existing Launcher reply; candidates do not strip or repair them.

C is implemented because it is the smallest change that addresses the demonstrated missing field while retaining every sensitive field and full semantic validation. Normalization requires the exact ten-field target, exactly one missing key (text), and type list or shell. The inserted value is empty, matching the existing valid value for those action types. The input size is checked before parsing and normalized output is checked against the same size cap before decoding.

## Change size

The production Host parser diff is 34 insertions and 12 deletions (net +22 lines). The benchmark Observer diff is 7 insertions and 6 deletions (net +1 line); it is not runtime application code. The offline comparison probe adds 356 Swift lines, and the Observer test module adds 74 lines while removing 3. No production A or B implementation was added.

Schema count: A uses the existing one union schema; B adds five action-specific schemas alongside legacy compatibility; C keeps the existing one schema and adds one local conditional. Candidate C adds no IPC, dependency, persistent state, process, or authority.
