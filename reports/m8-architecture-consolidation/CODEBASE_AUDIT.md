# M8.7 Codebase Audit

Date: 2026-10-19 (Asia/Shanghai). Implementation target: `hrrrb408/KhaosAgent`.
This is a source/dependency audit and narrow cleanup, not a new architecture contract.

## Exact development baseline

Live `gh pr list --state all` and `git fetch origin` confirmed:

| Ref | State | Exact HEAD |
|---|---|---|
| origin/main | fetched | `27ef0b4787f807fc76ffd7ba9cdb467ffc9a2f27` |
| PR #33 | OPEN | `1d1457f43f788d30f6fa4f48890b900ef9406c07` |
| PR #34 | OPEN | `6724d5ac5e52e1c157f3701f30009ed81b55fb90` |
| PR #35 | OPEN | `9dac79839da1d2d7c1c29027136f85eb85c28bce` |
| PR #36 | OPEN | `9c111de6053bde6e83483724e45ce5bc337f10ec` |
| PR #37 | OPEN | `02b8277c8c8b96d8679a1d064e23595d87dab657` |
| PR #38 | OPEN | `12c75d75c1464aabd631b092e07903631f692ff6` |
| PR #39 | OPEN | `dee62b20dc1acbd64b009d47c29dc3f42ba9fdde` |

PR #39 exact-head checks were terminal SUCCESS when queried: `security-tests` run
`39182342218`, `security-freeze` run `39182342248`. These are inherited baseline CI,
not evidence for this cleanup branch.

The cleanup branch `refactor/m8-7-khaos-codebase-consolidation` starts at the exact
PR #39 HEAD and its PR targets #39's branch, not main. The original checkout on
`experiment/m8-glm53-coding-baseline` has unrelated untracked logs, frozen inputs,
workspaces and local evidence; all are untouched. Work uses a separate managed worktree.
No prior PR is merged or rewritten.

The inherited `reports/m8-trusted-final-acceptance/COMPLETION_AUDIT.md` still says
B32/B34/B39 `NOT_PROVEN`, Owner Review `PENDING`, Technical Gate A `NOT_PROVEN`,
production M8.5.2B `NOT_STARTED`. This change does not close those gates.

## Method and evidence limits

Inspected tracked source definitions, imports, entrypoints, compile/copy lists,
actual dispatch call sites, test/probe references, manifest roles, Git history and
workflow commands. An identifier-frequency scan was a lead generator only; deletion
also required caller, dynamic lookup, packaging and history checks. All major runtime
modules are classified below; this is not a formal proof that every line is live.
No unreviewed third-party dead-code tool or new dependency was installed.

`tools/build_macos_seed.py` has explicit Swift compile tuples and 14 Python source
paths; it embeds `launcher.py` but excludes development-only `macos_disk_image.py`.
The three untrusted Swift intelligence files are explicitly excluded by the freeze
checker; shared `AgentHostProtocol.swift` is trusted because Launcher consumes it.
Python package initializers execute during trusted imports, so they remain frozen.

## Runtime inventory and deletion impact

Paths below are relative to the repository. Test names identify regression families,
not a promise of line coverage. Each row states the current responsibility and what
would break on removal.

| Source / group | Classification | Actual consumer / current problem; removal impact |
|---|---|---|
| `khaos/__init__.py`, `kernel/__init__.py` | Core Security packaging | Trusted Python import roots; removing breaks package resolution / manifest inventory. |
| `ipc.py` | Core Security | Versioned bounded framing, peer handshake, request/source validation; launcher, Worker, Broker and SDK consume it. `test_ipc.py` covers malformed/oversize frames. |
| `launcher.py` | Trusted Boundary | `run_workspace_command` spawns authenticated Worker, holds root descriptor and cancellation; used by production bridge and real OS tests. Not a superseded Host execution fallback. |
| `kernel/worker.py` | Core Security | `main` admits one request, proves backend, isolates Runner, handles lifecycle/cleanup and diagnostics. Removing loses process enforcement. `test_worker.py`, `test_launcher.py`. |
| `kernel/broker.py` | Core Security | `serve_runner_execution`, scoped filesystem/process/state handlers and commit child admission. This is Kernel internals, not a second product manager. `test_broker.py`. |
| `kernel/workspace_snapshot.py` | Core Security | Hard-link-free baseline, descriptor/mount identity and separate read/write scopes. Read scopes authorize subtrees; write scopes authorize exact entries. `test_workspace_snapshot.py`. |
| `kernel/workspace_changes.py` | Core Security | Full diff validation, staging, conflict/race checks, trusted live mutations and uncertain-outcome reporting. Not interchangeable with snapshot copying. `test_workspace_changes.py`. |
| `kernel/macos_seatbelt.py` | Core Security | Real OS policy/probe/process execution, denial, timeouts and descendant cleanup. `test_macos_seatbelt.py`, `test_launcher.py`. |
| `kernel/macos_disk_image.py` | Experimental / development enforcement | Direct APFS fixture backend, dynamically imported when no production broker mount is supplied. Tests still require it; excluded from signed app, retained. |
| `kernel/peer_identity.py` | Core Security | Local socket peer PID validation before pipe ping; trusted launcher/Worker plus Runner consume it. `test_peer_identity.py`. |
| `kernel/plugin_lifecycle.py` | Plugin Runtime / Core Security | Locked content-addressed admission, exact digests, activation/generation/expiry/rollback; opaque Plugin state. `test_plugin_lifecycle.py`, memory tests. No Plugin business schema belongs here. |
| `kernel/workspace_xpc_bridge.py` | Trusted Boundary | `main` decodes authenticated native bridge frames, resolves bookmarks and dispatches to the same launcher/lifecycle primitives. Revalidates across native/Python boundary. `test_workspace_xpc_bridge.py`. |
| `runner.py`, `runner_sdk.py` | Plugin Runtime (untrusted) | Dedicated Runner loads bounded source via `compile/exec` only inside Seatbelt; SDK sends narrow IPC requests. State/output and process cancellation have distinct protocols. `test_runner_sdk.py`, real Runner tests. |
| `macos/TrustedWorkspaceLauncherMain.swift` | Trusted Boundary + fixed Harness coordination | Actual CLI/UI entry, data consent, Picker, budget, per-operation approval, frozen invocation and result reporting. Removing or moving whole loop loses trusted control. Memory replay coordination is a future extraction candidate. |
| `TrustedWorkspacePicker.swift` | Trusted Boundary | Captures user-selected bookmark/scope; used by Launcher. Not just UI decoration. |
| `TrustedEditApproval.swift` | Trusted Boundary | Canonical Runner wrapper, Candidate B parser, exact scope/source/request binding, complete review UI. Current producer is feasibility/acceptance only. Keep all B32/B34/B39 semantics stable. |
| `AgentTaskProgress.swift` | Trusted Boundary | Cancel-capable main-thread progress/reply arbitration, used by Launcher. Not the Host's model-sequencing counter. |
| `AgentHostClient.swift` | Trusted Boundary | Launcher-facing bounded XPC, validated replies, connection cancellation. Async turn requests coexist with synchronous Candidate/evaluation calls; both have consumers. |
| `AgentHostProtocol.swift` | Trusted Boundary + misplaced fixed business helpers | Canonical Launcher/Host wire validation, proposal binding and budgets; also fixed Memory dataset/grading/canonical-state helpers. Do not move the entire module to untrusted code; separate pure scoring later with unchanged trusted approval verification. |
| `AgentHost.swift` | Agent Harness + Capability | Actual AgentHost XPC main; Apple/local-llama/BigModel adapters, bounded history, turn sequencing, one correction, Candidate generation. Hardcoded capabilities, not installed Plugins. Diagnostic duplication reduced in this change. |
| `AgentHostActionOutput.swift` | Agent Harness | Model JSON inspection, format normalization, diagnostic categories, advisory sequencing. Uses canonical trusted protocol for final wire validation; cannot authorize. |
| `AgentHostCandidateSource.swift` | Capability | Bounded replacement of exactly one `run` function; used by all Candidate model providers, covered by Candidate-source probe. |
| `KernelWorkspaceXPC.swift` | Trusted Boundary | Wire structs, serialization, strict envelope/scope/source checks and authenticated stream transfer. `readInvocation → decodeInvocationRequest → decodeWorkspaceRequest` is live. Only the unused `decodeRunRequest` wrapper is removed. |
| `KernelWorkspaceClient.swift` | Trusted Boundary | Authenticated endpoints, immutable invocation handle, request/task/session/connection binding, cancel/original-result reconciliation. Sync request path serves bootstrap/plugin/smoke; async handle serves Agent tasks. Neither is dead. |
| `KernelWorkspaceService.swift`, `ServiceMain.swift`, `Bootstrap.swift` | Core Security | Service entry/listeners, same-connection operation cancellation and fixed executor composition. Native process is part of Kernel; not a new architecture concept. |
| `KernelWorkspacePythonExecutor.swift`, `Root.swift` | Core Security | Embedded Python launch/FD hygiene, bookmark/root identity, bridge reply validation and broker lease acquisition/release. Different boundary from Python snapshot checks. |
| `KernelSnapshotBrokerService.swift`, `ServiceMain.swift` | Core Security | Signed production APFS lease creation/hold/release and owner/process cleanup. Direct image test backend cannot replace this sandboxed service. |
| `KernelSnapshotBrokerSandbox.swift`, `StoragePolicy.swift` | Core Security | Apply Broker confinement before listener readiness; fixed storage policy. `test_snapshot_broker_process.py` and signed bundle attacks. |
| `KernelSnapshotBrokerClient.swift`, `BootstrapClient.swift`, `XPC.swift`, `BootstrapXPC.swift` | Trusted Boundary | Authenticated narrow broker transport and endpoint bootstrap; distinct native protocols/consumers, no forwarding-only deletion proven. |
| `KernelSnapshotBrokerToolRunner.swift`, `KernelCStringArray.swift`, `XPCPeerIdentity.swift` | Core Security primitives | Bounded APFS tools, correct C argv ownership and audit-token PID identity; reused native utilities. Removing breaks compilation/enforcement. |
| `examples/memory/plugin.py`, `memory-candidate-b/plugin.py` | Capability Plugins / Evidence | `remember/recall/forget`, opaque `khaos-memory-v1`; A/B are intentionally different fixed Candidates and state-continuity fixtures. Do not deduplicate their frozen source identity. |
| `examples/seed-writer`, `interface-probe` | Capability / Evidence | Minimal workspace writer and hostile metadata/unscoped-write canary; consumed by tests and product acceptance. |

## Repository support inventory

| Tree | Classification | Decision |
|---|---|---|
| `tests/` Python suites, Swift and Python probes | Evidence / governance | Keep real Seatbelt, XPC, scope, cancellation, peer, Candidate and Memory attacks. New decoder test adds five synthetic cases, without calling BigModel. |
| `tools/build_macos_seed.py` | Trusted build governance | Explicit private source snapshot, immutable compile lists, embedded Python/model/signatures and exclusive output publication. No alternative builder is introduced. |
| `tools/check_security_freeze.py`, `security/` | Security governance | Preserve inventory, exact-base declaration and manifest digest chain; not runtime authority or independent Owner approval. |
| `docs/`, `SECURITY.md`, `AGENTS.md` | Normative contracts / evidence | Relevant architecture §§9–14, 17–19, 33, 43, 45 plus current ABI/freeze govern review. No normative decision changed. |
| `reports/` | Evidence + Experimental | 427 tracked files at base, including active secure-edit fixtures and prior failed attempts. Python/Swift prototypes have evidence consumers and do not ship. No deletion/rewriting of raw Gate A, logs, test fixtures, frozen datasets or hashes. |
| `.github/` | Build governance | `seed-ci.yml` runs canonical suite on macos-26; `security-freeze.yml` checks proposed manifest and runs base checker against proposed tree. Both unchanged. No configured separate lint/formatter command found in tracked root build metadata. |

## Proven cleanup and rejected deletions

1. `KernelWorkspaceXPC.decodeRunRequest`: repository-wide symbol search finds only
   its definition before deletion. Git commit `9a17a03` changed the live stream reader
   to the generalized invocation decoder when Plugin lifecycle was added. The leftover
   projection wrapper has no caller. Swift-only `static func`, not `@objc`; explicit
   build source tuples have no external exported consumer. No `NSSelectorFromString`,
   `NSClassFromString` or selector-based call targets it. Remove 11 lines, no replacement
   API. The canonical tests exercise the unchanged actual parser/service path.
2. `BigModelSession.decode`: four catch arms repeated the same optional-attempt
   diagnostic and throw, while `BigModelError.diagnosticStage` already mapped those
   exact errors. Retain four typed error mappings and optional shape, send once using
   existing stage property, throw once. Net -17 production lines. No retry, model,
   output normalization, provider, logging sink or prompt changes.
3. Keep Swift/Python envelope/path/digest validation: distinct trusted receivers
   must independently reject malformed/hostile inputs. SDK checks are convenience,
   not the enforcement authority. Combining across that boundary would weaken defense.
4. Keep fixed Candidate/fixture copies, different state read vs state mutation reply
   validators, snapshot copy vs commit identity checks, and local tolerant model JSON
   extraction vs strict remote JSON decoding. Superficial similarity is insufficient.

A supplementary AST import/name-load audit found four unused imports and repository-wide
consumer/dynamic-attribute/test-patch checks confirmed removal: `MAX_PLUGIN_INPUT_BYTES`
in Runner SDK, `_open_absolute_directory` in launcher, `hashlib` in Broker and `uuid`
in the development APFS backend. These are unused bindings, not authority validators.
No legacy Scheduler/TaskManager runtime, old generic Plugin manager or obsolete runtime
entrypoint was proven removable. Removed files: **0**.
Legacy elimination: **one obsolete internal compatibility wrapper**; no claim of a
whole legacy subsystem removal. There is no deletion quota.

## TCB opportunities deferred

- Launcher embeds fixed Memory Proposal/replay/dataset presentation and serial replay
  orchestration (`evolveMemory`, `loadMemoryEvaluationDataset`, `evaluateMemoryCandidates`).
  `AgentHostProtocol.evaluateMemoryInput` also interprets business samples. Their pure
  grading/history logic should be untrusted future capability code; digest binding,
  state isolation, scopes and user activation decisions remain trusted. Extracting now
  changes the approval/evaluation surface and is deliberately outside this cleanup.
- Candidate B UI and generic approval detail text have similar view construction, but
  scroll gating, copy/export, visible control-character rendering and exact invocation
  binding differ. Do not merge during outstanding signed cancellation acceptance.
- `AgentHost.swift` contains three model providers and fixed Agent Loop. Future interfaces
  belong in the untrusted process. Do not add Cordis or a new privileged Host manager.
- Broad result/error folding appears in multiple trusted transports; retain local
  allowlists until a separate cross-boundary adversarial change proves equivalence.

Legacy reference checked at `Khaos-Agent` local HEAD
`03cf742d6b5fb16dc746ceb6443fc4d23a6f1eff`: `python/khaos/coding/edit_transaction.py`
uses generations, scoped storage and mutation locks. Reuse the precondition/scope lesson,
not its multi-file transaction/manager stack or same-process trust model. No legacy
code was copied and its unrelated untracked files were untouched.

Regression and exact-SHA delivery status live in [COMPLETION_AUDIT.md](COMPLETION_AUDIT.md).
