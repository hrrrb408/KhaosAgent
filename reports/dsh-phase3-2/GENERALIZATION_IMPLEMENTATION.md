# Phase 3.2 Generalization Implementation

## Scope and implementation

Phase 3.2 keeps the Phase 3.1 semantic tools and the existing Cordis Tool Registry, AgentLoop, Launcher proposal path, and Kernel execution path. The changes in this phase generalize the experimental coding policy, add a frozen eight-task holdout, and strengthen signed telemetry and independent evaluation. They do not add a second tool registry or an alternate workspace writer.

The semantic tools remain `read_file`, `replace_text`, and `run_tests`. They accept task intent and lower it deterministically to the existing bounded Khaos proposal interface. The model cannot supply `argv`, shell text, working directory, environment, or read/write scopes. The Launcher and Kernel independently validate requests, approval, execution, and commit. `replace_text` continues to use the fixed Candidate B preview protocol and does not claim production M8.5.2B integration.

Phase 3.2 implementation is confined to experimental DSH sources, benchmark/evaluator code, and the signed acceptance runner. The independent evaluator copies a trial workspace to a disposable directory and runs public and hidden tests in a read-only, network-denied Seatbelt profile with bounded output, time, and RSS. Its result does not substitute for a signed operation record.

## Signed deterministic Stage A

Two earlier attempts reached one approved `read_file` request each but failed in the AgentHost result bridge. The third attempt, `stage-a-3.json`, completed a real signed Task A workflow:

- DSH AgentLoop fixture calls: `read_file`, `read_file`, `replace_text`, `run_tests`.
- Launcher/Kernel operations: 4; each request, approval, invocation digest, terminal result, and Session result was correlated.
- Runner return codes: `[0, 0, 0, 0]`.
- Candidate B edit: one modified path, `fee.py`.
- Independent hidden verification: 3 tests passed in the read-only Seatbelt evaluator.
- Canary and all out-of-scope paths: unchanged; unexpected changes: 0.
- Unauthorized proposals, approvals, and observed Kernel authority violations: 0.
- Model invocation: NO; this proves the signed deterministic tool chain only.
- Operator: `codex_agent`; owner personally clicked: NO.

The signed app was 199,142,955 bytes, deep signature verification passed, and the Kernel executable digest matched before and after the run. Runtime inputs were DSH `687f282e8625c6b8d11ff58211a90524be2e4317` and Node `v22.19.0`. The source used for this signed run was `12ae44732ef591d5e5a0f6f56b820ecbdc730ea1`; the later fix only changed handling of incomplete evaluator correlations.

The private raw JSON SHA-256 is `44c6643be8845209e62bab87ca20427f42d41e068b336d8f83c308b70ee857f5`. Its compressed Launcher stderr SHA-256 is `9277502657994a92b622e44c95eaf09a3bfa0dadc173c1a1c5bd3472a5a6d019`. Raw evidence remains owner-only outside Git; this report includes bounded metadata and hashes.

## Engineering boundaries

| Delta | Result |
|---|---:|
| Production runtime code | 0 |
| Trusted code / TCB | 0 |
| Kernel authority | 0 |
| Kernel ABI | 0 |
| Workspace scope authority | 0 |
| Production dependencies | 0 |
| New trusted IPC or persistent state | 0 |

The Phase 3.2 work therefore improves experimental benchmark coverage and evaluation evidence without changing the production security boundary. It does not establish real-model coding reliability; the real-model gate is recorded separately in `SIGNED_EXPERIMENTS.md`.
