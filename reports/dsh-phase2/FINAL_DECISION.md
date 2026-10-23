# Khaos × DSH Phase 2: Decision

Date: 2026-10-23

## Decision

CONDITIONAL GO for continued isolated experimentation only. Do not replace the
production AgentHost or begin production Harness Migration from this result.

All nine signed acceptance modes passed on exact Khaos implementation source
SHA 5abf5d34426304b77a0773c1b30eb8814f5aa44c: hostile-plugin XPC attack,
Cordis lifecycle, deterministic Read → Edit → Test, fake-result handling,
B32 cancellation, pre-commit cancellation, post-commit cancellation, Node
child-crash recovery, and AgentHost XPC crash recovery. They use the pinned
DSH SHA 687f282e8625c6b8d11ff58211a90524be2e4317 and signed Node v22.19.0
runtime. Evidence is checked into reports/dsh-phase2/.

The results demonstrate that these bounded DSH requests still pass through
the existing Launcher and Kernel path, that the hostile plugin's tested OS
operations were denied, and that the tested cancellation and crash scenarios
retain their recorded Kernel outcomes. They do not establish real-model
reliability, every possible macOS sandbox attack, or production suitability.

Independent Code Owner approval remains NOT PROVEN in SINGLE_MAINTAINER_MODE.
The signed UI was operated by codex_agent under the user's explicit
authorization, not by the project owner. Owner review must therefore remain
open. Technical Gate A also remains independent; this experiment does not
close it.

## Repository validation

The canonical command, python3 -m unittest discover -s tests -v, passed all
411 tests in 824.946 seconds. This run used the c258575 report commit plus the
then-current two-entry Security Freeze inventory and declaration in the
working tree. The implementation and all signed UI evidence remain bound to
source SHA 5abf5d34426304b77a0773c1b30eb8814f5aa44c; later edits are reports
and governance metadata only.

Security Freeze passed in both modes after the inventory update:

- Default inventory check: verified, 0 sensitive changes.
- Exact PR #41 HEAD b08ab11e01663d2b26304cb541efb5361dea0417: verified,
  5 declared sensitive paths. The five are the two new test-only
  build-governance inputs plus security/tcb-manifest.json,
  security/freeze-baseline.json, and security/security-change.json. This is
  governance inventory, not a runtime TCB or authority expansion.

After the governance inventory update, both local Freeze commands passed at
the resulting exact head. The first GitHub Security Freeze run for c06d925
(run 39914050934) captured the old PR base,
707395146bbaf6be9ac6f58ae1f538e443b064a8, while PR #43 was being retargeted.
It failed because that event base did not match the declaration bound to
PR #41's b08ab11 base. The PR now targets the exact b08ab11 commit; that earlier
run is retained as a stale-base attempt and is not counted as current-base
evidence. The final exact-head Seed CI and Security Freeze run links are
recorded in PR #43's description. A green check does not replace the
independent review recorded below.

## Production and architecture deltas

Production code delta: 0
Trusted code delta: 0
Kernel Authority Delta: 0
Kernel ABI Delta: 0
Workspace Scope Authority Delta: 0
Trusted Runtime Delta: 0
New architecture concepts: 0
New trusted processes: 0
New IPC operations: 0
New persistent state: 0
Production Dependency Delta: 0
Experimental Dependency Delta: pinned DSH and Node.js v22.19.0 in the
disposable signed acceptance app only
Removed duplication / abstractions: 0

The harness changes and the Candidate B output-decoding regression fix are
confined to experimental tooling, tests, and reports. The production security
boundary is unchanged.

## Pull request

The existing PR #43 remains a draft and is the sole delivery PR. PRs #39–#42
were not modified, no PR was merged, and no main branch merge was performed.
The latest exact-head GitHub checks are linked from the draft PR description.
PR status does not change the independent-review result above.
