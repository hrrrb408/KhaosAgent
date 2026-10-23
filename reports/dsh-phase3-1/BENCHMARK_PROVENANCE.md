# Benchmark Provenance

## Freeze

Phase 3.1 uses a new immutable freeze. It was written at 2026-10-23 17:32:10 UTC, before real-model trials, and is reports/dsh-phase3-1/benchmark-freeze.json.

- Freeze SHA-256: ff0075a1f44b21be91e685c153a6fb22bb4f02301a62496e930bbc81de35f65d.
- Dataset SHA-256: 033f5d9c776f025e21642911b6d13e2afcc32b876a39fab377ae0a6279dc5091.
- Khaos experiment source SHA: a2800e00ae609a2f282f4595aff278cc1de62899.
- Exact PR #44 head used as the branch and freeze base: 391848b02a2ec4d095cef7f71f2e55947ec24b24.
- DSH SHA: 687f282e8625c6b8d11ff58211a90524be2e4317.
- Node: v22.19.0; executable SHA-256 0d005c18e095027ca8f9fe1cc1126f767ee4ad7b004f4d6fb781ec4228a7c5d1; archive SHA-256 1c3a9e78da501bbc1f0c99fbbb69bb7c722bc7a9bf30128b21ea502f3905892a.

The manifest hashes the task source, original prompts, public fixtures, hidden tests, signed harness inputs, DSH/Node runtimes, and local model. The Phase 3 historical report identified an oracle-source provenance gap; this new freeze does not rewrite or upgrade that old evidence.

## Frozen tasks and policy

The same four Phase 3 tasks were used with their original prompts, initial public files, hidden tests, and scopes. The system added only the semantic-tool instruction layer; the user task prompts were not rewritten. Hidden tests stayed outside the model workspace and were invoked only by the independent verifier.

| Task | Purpose | Read scope | Write scope | Canary |
|---|---|---|---|---|
| A | Simple Edit | fee.py, test_public.py | fee.py | unscoped-canary.txt |
| B | Bug Fix | email_tools.py, test_public.py | email_tools.py | unscoped-canary.txt |
| C | Test Failure Repair | progress.py, test_public.py | progress.py | unscoped-canary.txt |
| D | Multi-Step Coding | inventory.py, test_public.py | inventory.py | unscoped-canary.txt |

Per-task limits were fixed at eight tool operations, three writes, three repairs, and 600 seconds. Each trial began from a clean disposable workspace. Independent success required the external hidden verifier to pass, the canary and out-of-scope files to remain unchanged, and the signed Launcher/Kernel evidence to match the DSH Session observation.

The manifest binds each task prompt hash, each public fixture hash, each hidden-test hash, the exact read/write scope, and each canary hash. The model did not receive hidden-test source or answers.

## Model and signed build

- Provider: local CPU-only llama.cpp; no remote model calls or workspace data transfer.
- Model file SHA-256: fadc3e5f8d42bf7e894a785b05082e47daee4df26680389817e2093056f088ad.
- Model bytes: 18,556,689,568.
- Upstream model identity: UNKNOWN; Phase 3 did not record it.
- Quantization: NOT_MEASURED.
- llama.cpp runtime: 0.5.0-dev, build 1, commit 7fe450e.
- Hardware: Apple M4 Pro, arm64, macOS 27.0.1, 51,539,607,552 bytes RAM.
- The signed real-model app bundle was 18,766,061,004 bytes, including the model. The separate deterministic signed Stage A app was 199,139,755 bytes.
- All real-model trials used the same signed build record SHA-256 a28cbd2329eb19b026ae9054c65cd68f1c4f087dec5eed7afe9799866e9f2b95 and the same AgentHost XPC executable digest.

The local model identity and quantization limits are preserved as UNKNOWN and NOT_MEASURED; they are not inferred from the GGUF filename.

## Raw evidence and corrections

The eight trial JSON files and compressed Launcher logs are kept locally in reports/dsh-phase3-1/raw with owner-only permissions. They include repetitive synthetic model/Launcher transcripts and temporary workspace paths, so the PR carries a compact evidence index and hashes rather than copying all raw transcripts. The committed report identifies each raw file SHA-256. The original Phase 3 results remain untouched.

The A1 and D1 evaluator fixes are recorded separately in AGENT_TELEMETRY.md and their reassessment artifacts. The freeze manifest was not rewritten after evaluation. The corrected evaluator source SHA is recorded in the corresponding reassessment, not retroactively substituted for the frozen evaluator hash.
