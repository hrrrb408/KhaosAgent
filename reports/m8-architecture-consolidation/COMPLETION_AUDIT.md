# M8.7 Completion Audit

Date: 2026-10-19, Asia/Shanghai. Base: PR #39
`dee62b20dc1acbd64b009d47c29dc3f42ba9fdde`. This audit concerns M8.7 only.

## Engineering result

Actual cleanup is deliberately small: remove one dead native convenience function,
consolidate one nontrusted diagnostic path, and remove four unused Python imports. Full module/dependency inventory,
rejected deletions and TCB extraction candidates are in [CODEBASE_AUDIT.md](CODEBASE_AUDIT.md).
Five reports are the sole new report set; prior evidence/fixtures remain untouched.

| Required result | Status / result |
|---|---|
| M8.7 Engineering | Audit / cleanup / research COMPLETE; overall PASS requires the exact-head delivery receipt below |
| Codebase Audit | COMPLETE for major source/dependency/packaging surfaces; no claim of formal whole-program liveness proof |
| Dead Code Removal | 0 files; 1 function (11 LOC) and 4 imports (4 LOC) |
| Duplicate Logic Reduction | Four duplicate diagnostic emit/throw arms become one; existing error-stage map reused; net -17 LOC |
| Legacy Code Elimination | One obsolete `decodeRunRequest` projection; no whole legacy subsystem claimed |
| Production Code Delta | +17 / -48, net -31 shipped LOC; development-only backend -1 LOC separately |
| Trusted Runtime Code Delta | +0 / -13, net -13 LOC; 33 of 36 runtime TCB files byte-identical |
| Kernel Authority Delta | 0 |
| Kernel ABI Delta | 0 |
| Workspace Scope Authority Delta | 0 |
| Canonical Tests | 398 PASS (824.271s), then 399 PASS (837.785s), both transition evidence; authoritative fixed-tree result is in the delivery receipt below |
| Security Freeze | PASS current checker, exact-base check, independently extracted base checker |
| GitHub CI | Final-head `security-tests` and `security-freeze` must be terminal PASS in the live delivery receipt; no older CI success is substituted |
| DeepSeek Harness Source Research | COMPLETE static source review at fixed D SHA; no upstream execution claim |
| Plugin Architecture Matrix | COMPLETE: ownership/status, pinned references, security/cost and ordered tasks |
| Upstream Reuse Strategy | COMPLETE: KEEP / REUSE DESIGN selected; REUSE SOURCE / REPLACE evaluated and deferred |
| New Runtime Dependencies | 0 |
| New Architecture Concepts | 0 implemented; target vocabulary is roadmap only |
| New Trusted Processes | 0 |
| New IPC Operations | 0 |
| New Persistent State | 0 |
| Owner Review | PENDING |
| Independent Code Owner Approval | NOT_PROVEN; single-maintainer mode |
| Technical Gate A | UNCHANGED: NOT_PROVEN |
| Production Structured Edit | NOT_STARTED |
| Linux Port | NOT_STARTED |

## Security invariant accounting

M8.7 does not claim any broader security guarantee. The full canonical suite exercises
existing prohibited paths through real macOS enforcement; test family names below are
coverage pointers, not proof of all possible attacks. The only trusted runtime changes
are removal of an uncalled Swift helper and two unused Python import lines; all remaining
parser/enforcement bytes are identical.

| Invariant | Change / executable regression family |
|---|---|
| Plugins cannot bypass Kernel side effects | No change; `test_launcher`, `test_macos_seatbelt`, `test_broker` retain direct OS/write/network denial attacks |
| Plugins cannot modify Security Kernel | No change; real Runner and signed bundle write-denial checks retained |
| Plugins cannot grant capability | No change; real XPC caller-authority/scope attacks, strict schemas retained |
| Candidates cannot self-activate | No change; admission/generation/digest attacks in `test_plugin_lifecycle` and real replacement-path attacks retained |
| Harness failure is not Kernel failure | No change; Runner/Host termination and bounded protocol failure tests retained |
| Missing/broken enforcement fails closed | No change; backend probe and unsupported-platform/no-host-fallback checks retained |
| Data reads / event subscriptions scoped by default | No read change; real file/list scope and sibling/alias attacks retained; no general Event Bus implemented or claimed |
| Remote input explicit, no secret default | No data flow change; synthetic decoder checks payload-free error diagnostics; signed UI remote-data consent not rerun |
| Activation approval exact binding | No change; Candidate/Manifest/scope/generation/expiry/rollback regressions retained |
| Process/IPC/OS enforcement, not objects/prompts | No change to Launcher → Kernel → Runner, native peer requirements, Seatbelt or bounded pipe framing |
| Read authority as important as effects | No change; read denial/symlink/hardlink/mount/scope tests retained |

## Evidence boundaries and remaining work

- No GLM, other remote model or local model quality experiment was run. The decoder
  probe is synthetic, compiles actual Swift mapping and redirects only its temporary
  diagnostic sink; it does not prove real-provider quality or deployment.
- No interactive signed cancellation acceptance was rerun. B32/B34/B39 stay
  `NOT_PROVEN`; no inherited report is modified. Owner development authorization is
  not Owner Review. Prior signed B38 evidence is not reattributed to the cleanup build.
- No production structured-edit Host producer, generic Plugin framework, Cordis
  dependency, Scheduler, Planner, Event Bus, database, port or privileged service added.
- The original checkout and all unrelated untracked evidence are preserved. Work is
  isolated in the managed `m8-7-consolidation` worktree.
- Future Plugin/source adoption is conditional on the dedicated scope and tests in
  [PLUGIN_ARCHITECTURE_MATRIX.md](PLUGIN_ARCHITECTURE_MATRIX.md), plus all inherited gates.


## Final delivery receipt (outside the commit being verified)

Production, tests and security inputs are fixed at code commit
`9218141` (after `69e3721` and `972cba6`). Subsequent M8.7 commits are reports only.
The exact final PR head cannot be embedded into itself. The final immutable-head
receipt is therefore published in the **Draft PR description and final handoff**, not
as a self-referential report edit that would create another unverified head:

[Find the delivery Draft PR and its current checks](https://github.com/hrrrb408/KhaosAgent/pulls?q=is%3Apr%20head%3Arefactor%2Fm8-7-khaos-codebase-consolidation).

Before a PASS handoff, that receipt must contain all of:

- final local/origin/PR HEAD equality and the unchanged PR #39 base;
- final fixed-code-tree canonical suite count, duration and exit status, with product,
  tests and governance inputs equal to code commit `9218141`;
- current and exact-base Security Freeze plus the extracted base checker results;
- terminal `security-tests` and `security-freeze` run URLs for that **exact final head**;
- Draft/open/non-merged state, no auto-merge, and a clean managed worktree;
- Owner Review PENDING, B32/B34/B39 and Technical Gate A unchanged/NOT_PROVEN.

The two transition suites are retained in `/tmp/khaos-m87-baseline-tests.log` and
`/tmp/khaos-m87-final-tests.log`; the final fixed-tree run is
`/tmp/khaos-m87-canonical-tests.log`. Local temporary logs are not durable Git evidence;
GitHub's exact-head run links are the remote regression record. No upstream suite,
real model, interactive acceptance, separate lint/formatter or distribution build
is claimed. No separate lint/formatter command was found in repository build metadata.

The first synthetic decoder probe expected stderr output from an OSLog sink; its
four diagnostic-observation subcases failed while error codes were correct. The
probe now redirects only the temporary copied sink to observe the unchanged formatter.
This is test instrumentation, not a production logging change or provider retry.
