# Architecture decision: CONDITIONAL GO

## Decision

Khaos should **not yet replace its production AgentHost with DeepSeek Harness**. Continue only with bounded experiments on the isolated `experiment/khaos-dsh-integration` branch. The signed deterministic acceptance proves that the pinned DSH AgentLoop can propose one tool action, pass it through the real signed Khaos AgentHost/Launcher/Kernel/Runner chain, and consume the actual result without adding Kernel authority or ABI. It does not close the remaining XPC-specific isolation and lifecycle tests.

The architectural direction remains: DSH supplies untrusted intelligence; Khaos owns approval, scope, execution, validation, and commit. Cordis plugin load is not Khaos Candidate admission or activation.

## Results

| Requirement | Status | Evidence boundary |
|---|---|---|
| Build pinned DeepSeek Harness | PASS | 9 build checks passed at pinned SHA |
| DSH AgentLoop / Tool Registry | PASS | 215 targeted upstream tests and five adapter cases passed |
| Capability adapter validation | PASS | Headless adapter tests only; mock port is not signed integration evidence |
| Real signed Launcher/Kernel tool roundtrip | PASS | One read-only tool call; real UI, XPC identities, Kernel, Runner, Task Record, and DSH result consumption |
| Signed OS sandbox runtime | PASS | Separate signed App Sandbox probe; actual XPC-host hostile I/O still not run |
| Actual signed XPC cancellation and terminal consistency | NOT_PROVEN | No XPC-run cancellation; B32/B34/B39 unchanged |
| AgentHost XPC child crash/restart | NOT_PROVEN | Only standalone signed runtime child restart was exercised |
| Dynamic plugin loading in signed XPC product | PARTIAL | Bundled DSH tool plugin registered and used; arbitrary module loading not tested |
| Candidate lifecycle integration | NOT_STARTED | No Candidate admission, activation, evaluation, or rollback API exposed |
| Production test-hook isolation | PASS | Ordinary production build contains original Host and no Node/test override |
| Production Kernel/ABI/scope delta | 0 | No trusted or production source changed |
| Canonical Khaos tests | PASS | 399 tests passed on the pinned PR #40 base |
| Security Freeze | PASS | `sensitive changes=0`; independent approval remains external |
| GitHub CI for this experiment | PENDING | Draft PR is the next delivery step |
| Owner Review | PENDING | Owner must review the Draft PR; single-maintainer mode |

## Conditions before production replacement

1. Run direct protected-file, write, network, credential-environment, and child-process probes from the DSH Node child inside the actual signed AgentHost XPC service, then verify the canaries from the parent process.
2. Exercise Node/DSH child termination and cleanup after AgentHost XPC invalidation, followed by a fresh signed XPC task.
3. Exercise signed end-to-end cancellation while DSH awaits the Khaos result. Verify the original Kernel result, workspace, Launcher Task Record, and DSH terminal result agree; cancellation must not hide a completed commit or trigger a retry.
4. Test the supported dynamic Cordis module-loading mechanism in the signed XPC service and show that every loaded module stays in the same untrusted sandbox boundary.
5. Review the approximately 110.5 MB bundle increase and the measured approximately 54.7 MiB standalone Node RSS against the target product's packaging budget.
6. Keep B32, B34, B39, and Technical Gate A at `NOT_PROVEN` until their own signed acceptance requirements are met. This spike is not Gate A evidence.

## Delivery and owner state

PR #39 and PR #40 remain open Drafts and unchanged. This branch is based exactly on PR #40. The experiment adds no production runtime dependency, no trusted process, no Kernel RPC, and no persistent state. The owner explicitly authorized Codex to operate the read-only signed UI approval; the evidence records that the UI operator was Codex rather than claiming a physical owner click.

Independent code-owner review is `NOT_PERFORMED — SINGLE_MAINTAINER_MODE`. Owner Review remains `PENDING` until the project owner reviews the resulting Draft PR. B32/B34/B39 remain `NOT_PROVEN`; Technical Gate A remains `NOT_PROVEN`; production Structured Edit remains `NOT_STARTED`.
