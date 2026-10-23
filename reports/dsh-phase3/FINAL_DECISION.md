# Khaos × DeepSeek Harness Phase 3: Final Decision

Date: 2026-10-23

## Decision

**CONDITIONAL GO for bounded experimentation; NO production Harness migration.**
The local real-model integration ran through the pinned DSH AgentLoop and the
existing signed Khaos Launcher. The real model produced proposals, one scoped
Runner command executed, and the real non-zero result was returned. All eight
independent hidden evaluations failed, so this model/integration is not a
reliable coding harness. The integration and security boundary are suitable
for further isolated investigation only; the evidence does not support
replacing the production Khaos AgentHost.

Engineering status is **PARTIAL**: the runtime adapter, frozen four-task
benchmark, eight signed real-model trials, bounded plugin-evaluation
prototype, raw records, and reports are present. DSH session-internal telemetry
is incomplete, DSH did not generate the evaluated Candidate, remote-provider
calls were not run, the original freeze manifest's oracle source hashes were
stale (the unchanged task and hidden-test content is hash-verified in a
post-hoc audit), full performance timings are partial, and final GitHub CI
remains pending until the Draft PR's exact head is checked.

## Required acceptance summary

| Field | Result |
|---|---|
| Phase 3 Engineering | `PARTIAL` |
| Real Model Integration | `PASS` — local CPU model; remote provider `NOT_RUN` |
| Real DSH AgentLoop | `PASS` for the signed runtime/proposal path; full session-message telemetry `PARTIAL` |
| Benchmark Freeze Provenance | `PARTIAL`: content hashes match; original oracle source hash list was stale and has a post-hoc audit |
| Real Coding Trials | `8` |
| Task Success Rate | `0/8` (`0%`) |
| First-Pass Success Rate | `0/8` (`0%`) |
| Repair Success Rate | `0/2` Task C trials; neither reached a Runner test/repair cycle |
| Unauthorized Workspace Changes | `0` in the eight valid trials; one unrelated write in excluded A-2 UI incident |
| Unauthorized Approvals | `0` |
| Out-of-Policy Proposals Rejected | `8` |
| Kernel Rejections | `0`; out-of-policy requests were not submitted |
| False Success Count | `0` |
| Kernel Authority Delta | `0` |
| Kernel ABI Delta | `0` |
| Scope Authority Delta | `0` |
| Plugin Candidate Generation | `PASS` — Codex-authored candidate; DSH Evolver generation `NOT_RUN` |
| Isolated Candidate Evaluation | `PASS` for the bounded fixture and named malicious probes |
| Trusted Candidate Activation | `NOT_AUTHORIZED` |
| Node Runtime Measurements | `PARTIAL` |
| Canonical Tests | `PASS`: 411 tests in 853.067 s at source SHA `55ac27c5553ea91c64d5c47ad85907008079dc08` |
| Security Freeze | `PASS`: default and exact PR #43 base have 0 sensitive changes; PR #41 base verifies 5 declared paths |
| GitHub CI | `PENDING` at final PR SHA |
| Owner Review | `PENDING` |
| Independent Code Owner Review | `NOT_PERFORMED` |
| Technical Gate A | `UNCHANGED: NOT_PROVEN` |
| Production Harness Migration | `NOT_AUTHORIZED` |

## Security and architecture delta

The production Seed runtime, `khaos/macos/AgentHost.swift`, Kernel ABI,
workspace scope, and production dependencies were not changed. The signed
experimental builder substituted the DSH test Host only in disposable app
builds. Local-model trials had network-client entitlement disabled for
AgentHost, Node, and the model bridge. A separate remote-provider bridge
prototype was built and probed without sending a provider request; it remains
experimental and is not authorized for production.

```text
Production code delta: 0
Trusted code delta: 0 production; experimental bridge/service code only
New architecture concepts: 0 production; experimental model bridge prototype
New trusted processes: 0 production; 1 test-only network bridge in remote-provider builds
New IPC operations: 0 production; experimental model-completion XPC only
New persistent state: 0
New production dependencies: 0
New experimental dependencies: pinned DSH, Node v22.19.0, local CPU llama.cpp/model
Removed duplication / abstractions: 0
```

No production approval, migration, trusted Candidate activation, or independent
review has been fabricated. UI records consistently identify the operator as
`codex_agent` and `owner_personally_clicked=false`.

## Source and artifacts

- Development branch: `experiment/khaos-dsh-phase3-real-agent`.
- PR #43 exact base: `fd6747abd9ba785f784126dd848112cffa782163`.
- Phase 3 signed benchmark source: primarily
  `55ac27c5553ea91c64d5c47ad85907008079dc08`; A-1 used
  `26d6747fb7f371e98a89f1cc8a438a9a6146aace` with the same DSH runtime path.
- DSH: `687f282e8625c6b8d11ff58211a90524be2e4317`.
- Node archive: SHA-256
  `1c3a9e78da501bbc1f0c99fbbb69bb7c722bc7a9bf30128b21ea502f3905892a`.
- Benchmark freeze: `reports/dsh-phase3/benchmark-freeze.json`.
- Raw trials, operator reviews, bridge probes, and candidate evaluation:
  `reports/dsh-phase3/raw/`.
- Canonical test output and status:
  `reports/dsh-phase3/raw/canonical-tests-worktree.log` and
  `canonical-tests-55ac27c.status.json`.
- Security Freeze output and statuses:
  `reports/dsh-phase3/raw/security-freeze-*.log`.
- GitHub CI for the new Draft PR remains `PENDING` until the exact pushed head
  finishes its checks.

## Validation completed

- `python3 -m unittest discover -s experiments/dsh_phase3 -v`: 18/18 passed.
- `python3 tools/run_dsh_model_bridge_tests.py --dsh-source
  /private/tmp/khaos-dsh-687f282 --node
  /private/tmp/khaos-phase3-node22/bin/node`: 10/10 passed.
- `python3 -m unittest discover -s tests -v`: 411/411 passed in 853.067 s.
- `python3 tools/check_security_freeze.py`: passed, 0 sensitive changes.
- `python3 tools/check_security_freeze.py --base
  fd6747abd9ba785f784126dd848112cffa782163`: passed, 0 sensitive changes.
- `python3 tools/check_security_freeze.py --base
  b08ab11e01663d2b26304cb541efb5361dea0417`: passed, 5 declared sensitive
  paths.
- `git diff --cached --check`: run on the staged report/evidence set before commit.

## Next work

1. Fix the observed model-to-tool formatting failure only in a separately
   authorized experiment, retaining this frozen result set unchanged.
2. Persist payload-free DSH session counters in a way the acceptance parent can
   bind to the same Launcher task and result IDs.
3. Repeat the frozen tasks only after that integration change, under the same
   bounds and with exact model identity recorded.
4. Measure cold launch, first completion, tool round trip, and process cleanup
   with parent-visible instrumentation.
5. Keep the remote bridge and Candidate ABI unchanged until independent review
   and owner approval.
