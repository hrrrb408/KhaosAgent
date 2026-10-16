# Khaos M7 Harness Foundations — taskbook completion audit

Taskbook: `Khaos_M7_Harness_Foundations.md`, all batches M7.1–M7.5.
M7 starting source: `33e9193a0b8b066caec60d1d5385cbb9123987f1`.
This supersedes interpreting delivery as M7.2 alone. Small stacked PRs preserve
batch boundaries; the prior reports are historical evidence, not current-state
claims. The owner resumed the previously deferred concurrent stale-approval UI on
2026-10-16. The default full signed lifecycle test now passes; earlier partial
and failed records retain their original verdicts.

## Requirements and current evidence

| Taskbook item | Delivered behavior / audit | Authoritative evidence |
| --- | --- | --- |
| M7.1.1 existing Host/Launcher lifecycle before editing | State/owner/transition table distinguishes handlingRequest, pending result, proposal count and trusted Launcher accounting | `M7.1.md`, first lifecycle table |
| M7.1.2 original invalid action after list | Preserve original failed attempt, no invented rejected fields; current replay attributes wire-contract failure after correction | `../tool-planning/frozen-recheck.json`, `m7.2/frozen-replay.json`, `m7.5/comparison.json` |
| M7.1.3 fixed payload-free rejection categories | Existing actual guard groups have enum diagnostics; no raw model paths/argv/secrets in diagnostics | `AgentHostActionOutput.swift`; canonical compiled action-output probe |
| M7.1.4 one correction / no authority expansion | Initial and corrected outputs share validation; corrected failure terminates without a second operation | Action-output probe, actual remote replay and signed refusal tests |
| M7.1.5 legal transitions / termination | Small Host sequencing value, no Launcher loop migration; unsolicited/duplicate idle results and a second pending proposal rejected | `M7.1.md`; compiled task sequencing; actual signed Host crash/stale result evidence |
| M7.1.6 governed test changes | Exact base declaration and reviewed protected hashes, runtime unchanged | Per-PR declaration/history and required freeze checks |
| M7.2 context budget | Original goal/current controls/recent success/failure pinned; deterministic eviction and required-set oversize rejection; preserved result/truncation bytes | `m7.2/REPORT.md`, baseline counterexample, byte/UTF-8/spoofing/extreme cases |
| M7.2 causal/evidence limits | Old planning failure is not attributed to eviction; native FoundationModels implicit retention is not covered as an 8 KiB path | `m7.2/REPORT.md`, `m7.5/audit.json` |
| M7.3 normal/nonzero/timeout/cancel/Host loss/Kernel unavailable/refusal/Picker/budget/exit | Existing mechanisms audited; actual approved nonzero commit is distinguished from failed/aborted execution | `m7.3/REPORT.md` event matrix; 27 fresh targeted tests; `m7.2/signed-deterministic-v2.json` |
| M7.3 connection-bound cancellation and descendant cleanup | Real process-group / snapshot / commit-gate / Launcher-death / signed XPC attacks; no new process or IPC | `m7.3/targeted-macos.log`, signed XPC logs and diagnostic-validation JSON |
| M7.3 results consumed once | Trusted Launcher sends synchronously without retry; Host consumes pending result before continuation; restarted Host rejects unsolicited old result | Existing client/session source, compiled sequencing probe and signed Host-loss result |
| M7.3 observed remote failure | Preserve one failed cancellation fixture and truncated uncertainty; bounded exception-tail diagnostic only, no timeout/retry/assertion weakening | `m7.3/remote-ci-attempt-1.txt`, `REPORT.md`, exact-head PR #24 checks |
| M7.4 Seatbelt/scope/direct Kernel access/XPC peers | Existing actual OS denials rechecked, no new Kernel feature | `m7.4/REPORT.md` boundary/test map, canonical 341-test log |
| M7.4 per-operation/activation approvals and routing rollback | Actual native A activation, Agent denial + new independent approval, A run, separate B activation/run, separate rollback and generation-3 A run; parent hashes and signatures checked | `m7.4/signed-product-v5.json` / log, 287.457 seconds |
| M7.4 stale Candidate/generation, invalid rollback/crash | Canonical headless real Kernel and lifecycle tests remain enabled; their scope is separate from concurrent UI | Canonical product XPC lifecycle, wrong/expired approval and invalid rollback/crash tests |
| M7.4 concurrent old-A approval during B activation | PASS: A generation-1 review stayed open while B activated at generation 2; submitting A returned stale_approval with an unchanged workspace | `m7.4/signed-product-v5.json` / log, default full path; parent snapshot, active B and signature assertions |
| M7.5 fixed real benchmark | Same original task, baseline, hidden patch, provider profile and budgets; all attempts preserved, one authorized new replay, no post-result prompt tuning | `m7.5/audit.json` (15 checks), comparison, events, inventory; original M7.2 frozen run/grade |
| M7.5 real vs deterministic vs fixture success | Real replay failed coding and hidden test (1); list 0 and Launcher exit 0 do not score repair | `m7.5/REPORT.md`; Coding Reliability Closure NOT_PROVEN |
| Every PR delivery / validation | Focused report, delta, invariants, executable validation, failed outcomes, limitations and next batch; exact-head security-tests/security-freeze required | PRs #22 → #23 → #24 → #25 → #26 and their check rollups |

M7.1's original NOT_RUN interactive paragraph remains an honest historical
statement for that earlier SHA. The integrated M7.2 signed six-operation run,
refusal/cancellation/budget/Host-loss checks and actual frozen replay exercise
the unchanged M7.1 behavior in the current stack; they are not relabeled as UI
runs at the old SHA. The M7.4 partial UI result is likewise never called full
stale-generation UI acceptance; the later separate v5 full run supplies that evidence.

## Eight responsibility ownerships retained

| Responsibility | Intelligence / authority ownership |
| --- | --- |
| Agent loop / task lifecycle | Host proposes; trusted Launcher retains its loop, counts and terminal control |
| Tool dispatch | Host suggests bounded list/shell/Plugin actions; Launcher approval and Kernel execution remain independent |
| Context assembly | Untrusted Host custom adapters use one bounded representation/helper; no scope/grant comes from history metadata |
| Cancellation / execution state | Existing XPC connection/request binding, cancellation pipe, process groups and snapshot/commit gates |
| Sandbox | Existing Kernel Seatbelt enforcement; no Host fallback |
| Capabilities / scope | Existing Kernel-bound descriptors, approved scopes and complete changeset validation |
| Permission approval | Existing actual per-operation Launcher review; data-send, development and activation decisions remain separate |
| Plugin admission / activation / rollback | Existing fixed slot, exact Candidate/Manifest/scope/generation and isolated Runner; not a generic Plugin market |

No Harness foundation was migrated into a Plugin, and no legacy runtime,
TaskManager, scheduler, receipt ledger, generic context engine or authority
framework was added. Existing mechanisms were reused unless a demonstrated local
gap justified the M7.1/M7.2 untrusted Host changes or a test-oracle/diagnostic fix.

## Overall change budget and evidence limits

Production code delta versus starting source: +337 / -220 lines, net +117,
only `AgentHost.swift` and `AgentHostActionOutput.swift` (untrusted intelligence).
Trusted runtime code delta: 0; all 34 runtime TCB manifest hashes match the
starting baseline and on-disk files. New architecture concepts: 0. New trusted
processes: 0. New IPC operations: 0. New persistent runtime state: 0. New runtime
dependencies: 0. Removed duplication: shared initial/corrected action checks and
shared local/remote history representation; no second execution/authority path.
Protected test and documentation changes use fresh declarations and reviewed
hashes; reports/logs are evidence artifacts, not runtime state.

Fixed trusted budgets stay 8 calls / 180 seconds cumulative / 30 per call /
4 KiB result / 32 KiB aggregate. No secret read scope, new remote recipient,
root service, administrator bypass, permission relaxation or hidden-test edit
was introduced. The sole new real replay used its explicit task/data/endpoint
authorization, not broad UI permission as data-send approval. No further remote
transmission or benchmark attempt is authorized by this recording batch.

Remaining boundaries: native Apple implicit history is not proven by the custom
8 KiB helper; the one remote XPC fixture failure's underlying exception is unknown
from its truncated original record, even if later checks pass; external
unconfined same-UID tampering and independent Code Owner enforcement remain
outside / NOT_PROVEN as already documented. Rollback changes future routing,
not past side effects. Separate model latency/cost and hosted model-weight
revision are unavailable. No universal reliability or security claim is made
from a finite regression suite. The previously deferred concurrent stale-approval UI now has its own full
passing signed-product run. Taskbook development, regression and recording
delivery does not establish Coding Reliability Closure.

## Final integration fixture follow-up

Ordered integration exposed an existing process-group test's duplicated
post-reap cleanup: PR #26 run `38937639884` failed at the second raw `killpg`
in `finally`, after the real kill/wait/pipe checks. The minimal test-only fix
reuses the existing reviewed cleanup helper, keeps every enforcement assertion,
and adds known-reaped-leader branch coverage. The before/after real-OS fault
injection, four focused passes and original failed CI are preserved in
`m7.5/integration-cleanup/REPORT.md`. Only that test's reviewed manifest hash
and governance binding change; all production/runtime TCB source remains intact.
Exact-head CI and final-main canonical/Freeze results are recorded in the PR
integration record; passing a rerun does not erase this failed attempt.
