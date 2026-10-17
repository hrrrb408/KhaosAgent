# M8.1 — Completion audit

## Closure status

| Area | Result | Basis |
| --- | --- | --- |
| Engineering implementation | PASS | Opt-in diagnostics and the exact Action contract are implemented in the untrusted Agent Host; default parsing remains strict and approval behavior is unchanged |
| Action Contract Root Cause | PARTIALLY_PROVEN | M8.0 ended with `invalid_model_output_shape`, but its rejected content and initial-versus-correction attribution were not retained |
| Coding Reliability Closure | NOT_PROVEN | The deterministic product acceptance verifies workflow behavior, not a real model's coding quality or hidden-test completion |
| Local validation | PASS | 341 canonical tests, the focused compiled probe, headless signed-product regression, interactive signed-product acceptance, Security Freeze checks, and `git diff --check` passed |
| PR validation | PASS at `b56a730d0abca179151e2082df8aea8ae9c12b60` | PR #28 `security-freeze` and `security-tests` workflows both passed |
| Independent Code Owner approval | NOT_PROVEN | Single-maintainer mode does not provide independent approval |
| Remote model calls | 0 | No remote provider was used for this work |

## Deliverables

This directory contains all seven requested reports:

- `ROOT_CAUSE_ANALYSIS.md`
- `FAILURE_ATTRIBUTION.md`
- `ACTION_SCHEMA_REVIEW.md`
- `DIAGNOSTICS_SPEC.md`
- `TEST_REPORT.md`
- `SECURITY_AUDIT.md`
- `COMPLETION_AUDIT.md`

The separate M8.1 pull request is [PR #28](https://github.com/hrrrb408/KhaosAgent/pull/28),
created from `feature/m8-1-action-contract-diagnostics`. Its two required hosted
workflows passed on the recorded SHA above. PR #28 remains open and unmerged.
PR #27 also remains open at its recorded head and was not modified.

## Architecture and TCB delta

| Required field | Delta |
| --- | --- |
| Production code delta | `AgentHost.swift`: +159/-27 lines; `AgentHostActionOutput.swift`: +191/-0 lines; net +323 lines, all in untrusted Agent Host code |
| Trusted code delta | 0 runtime TCB files or lines; frozen runtime hashes are unchanged |
| New architecture concepts | 0 |
| New trusted processes | 0 |
| New IPC operations | 0 |
| New persistent state | 0; the one-time harness diagnostic guard is Host-session memory only |
| New dependencies | 0 |
| Removed duplication / abstractions | One canonical ten-key Action list and shared bounded model-content/JSON decode path replace repeated Host checks |

The Security Freeze declaration covers the two offline test files and three
freeze-governance records. The base-aware and current-inventory checks both
passed. No Kernel, Launcher, ABI, approval, capability, or sandbox code changed.

## Limits

M8.1 cannot recover the unrecorded M8.0 model response or determine whether the
initial response or correction response triggered the terminal shape error.
The ten-field schema remains a plausible source of model formatting burden, but
causality is NOT_PROVEN. The new diagnostics classify a future run only when the
owner explicitly enables them in the Agent Host environment. No result here
establishes model quality, improved hidden-test success, or comprehensive
same-UID tamper resistance.
