# Khaos × DeepSeek Harness Phase 3: Plugin Evolution Foundation

Date: 2026-10-23

## Result

The untrusted Cordis candidate evaluation prototype **PASSed its bounded
fixture**. It demonstrated improvement for a pure computation plugin and
rejected candidate-authored score claims. It did not use the DSH model to
generate the candidate, did not call Khaos Candidate admission, and did not
activate a Khaos Candidate. The Candidate ABI was not changed.

## Evaluation

The capability was comma-separated tag normalization:

| Variant | Independent correct cases | Time | Sampled RSS |
|---|---:|---:|---:|
| Baseline | `2/8` | `0.3114 s` | `138,969,088 bytes` |
| Candidate v1 | `8/8` | `0.3174 s` | `136,593,408 bytes` |
| Malicious baseline-derived candidate | `2/8` | `0.3136 s` | `139,165,696 bytes` |

There were no candidate regressions. Codex authored the candidate source
`candidate_v1.ts`; DSH loaded and evaluated it in the Cordis tool runtime. This
is an isolated evaluation, not an LLM-generated self-evolution result.

## Malicious candidate probes

The test-only macOS `sandbox-exec` process denied the recorded attempts to read
another Plugin's synthetic state, write an activation marker, open the
test-Kernel binary for writing, and connect to the local network listener. The
Kernel fixture hash and other-Plugin state hash remained unchanged, no
activation tool was registered, and the candidate's fake `PASS` self-report
was not used to calculate the score. The malicious candidate remained at `2/8`
under the independent evaluator.

These results cover the named disposable paths and probes. They do **not**
establish comprehensive hostile-code isolation: the prototype's Seatbelt
profile starts from `allow default` and adds explicit denials for selected
paths and network. It is not a Khaos Runner acceptance and does not prove
general filesystem, process, or same-UID containment.

## Lifecycle distinctions

| State | Result |
|---|---|
| Cordis Plugin loaded in the untrusted DSH tool runtime | `PASS` |
| Candidate independently evaluated against the frozen fixture | `PASS` |
| DSH Evolver generated the Candidate | `NOT_RUN` |
| Khaos Candidate admitted | `NO` |
| Khaos Candidate activated | `NO` |
| Production activation | `OWNER_DECISION_REQUIRED` |

The raw record is `reports/dsh-phase3/raw/plugin-evaluation-01.json`. It binds
DSH `687f282e8625c6b8d11ff58211a90524be2e4317`, Node `v22.19.0`, Candidate
source hashes, the independent fixture digest, and zero Kernel authority, ABI,
and workspace-scope deltas.

## Next step

If continuing this research, use Khaos's existing Candidate admission and
isolated evaluation APIs when the Candidate ABI can carry the untrusted
computation artifact. Keep generated code outside the Kernel, treat all
candidate-authored evidence as untrusted, and require the existing trusted
activation approval. Do not widen the ABI for Cordis compatibility.
