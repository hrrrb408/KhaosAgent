# M7.3 — execution state and cancellation audit

Base: `4e0c39a88c27efb31cfe35bce6497d2de9a7dff9` (M7.2, PR #23).
This batch audits the existing mechanisms before proposing a replacement. No
reproducible runtime gap was found in the reviewed cases, so production code,
trusted code, protocol, timeouts, retries and permissions remain unchanged.

## State / owner / executable evidence

| Event | Existing enforcement and terminal behavior | Evidence |
| --- | --- | --- |
| Normal command exit 0 | Launcher receives one result, reports its actual returncode; another proposal needs a new review | M7.2 signed deterministic six-call workflow and parent retest |
| Nonzero command exit | A normally returned command can commit its exact scoped changeset; the nonzero code remains failure evidence | M7.2 signed workflow and approved exit-1 write during Host loss |
| Timeout | Seatbelt process group is terminated, descendants reaped; no normal result means no commit request | Fresh `test_sandboxed_command_timeout_kills_forked_descendants`; Broker tool timeout probe |
| Caller cancellation before execution / snapshot / commit | Existing cancellation channel is checked at each gate; private output discarded and no live mutation | Fresh preflight, partial snapshot copy, before-commit and commit-gate cancellation tests |
| Launcher / XPC caller loss | Pipe closure or connection invalidation requests cancellation on the admitted operation; command descendants cannot remain detached | Fresh launcher-death test and signed shared-service XPC disconnect test |
| AgentHost loss during an already approved operation | Host owns no execution permission; Kernel finishes the already reviewed operation, Launcher stops on lost Host result recipient | M7.2 actual signed Host-kill acceptance: scoped exit-1 write committed, command and Host exited; restarted Host rejects stale result |
| Kernel unavailable / missing sandbox | Failure is returned with `can_continue=false`; no Host fallback or automatic retry | Fresh missing-backend test; canonical signed product missing-Broker rejection; source review of `runAgentTool` catch paths |
| Workspace Picker cancellation | No approval, Runner or next operation | M7.2 actual signed Picker cancellation, 0 approvals / 0 executions |
| Tool refusal | No Kernel invocation; `can_continue=false`; only text can follow | M7.2 signed mid-task refusal: one prior read, denied write, no next approval, workspace unchanged |
| Budget exhaustion | Trusted Launcher independently counts calls/time/bytes; no ninth approval | M7.2 signed eight-call test and existing protocol/action transition probe |
| Unsolicited / duplicate result | Host serializes requests, consumes a pending result before model work; duplicate while idle is rejected; only one proposal can be pending | Fresh compiled production `AgentHostTaskProgress` / action-output probe, plus restarted signed Host stale-result rejection |
| Cross-request / cross-connection cancellation | Exact active request ID and owning XPC connection must match; another connection cannot cancel it | Fresh signed shared-service XPC scope/connection cancellation attacks |

`validation.json` records fresh commands, actual exits, durations and log hashes.
The existing canonical 341-test log and signed acceptance JSON under `../m7.2/`
remain applicable because all runtime and test inputs are byte-identical; they
are reused evidence, not falsely presented as another UI run at this report SHA.
The signed XPC fixture uses the production shared Workspace service and real OS
boundaries in a temporary signed probe bundle; it does not replace the distinct
actual signed AgentHost/Launcher acceptance evidence.

## Why no new cancellation machinery

`AgentHostClient.request` is synchronous per request and never retries. Timeout
invalidates its connection; `stop` and `deinit` also invalidate it. Host
`handlingRequest` uses its lock to reject concurrent work and clears on completion.
A pending tool result is consumed before continuation, so a rejected/generated
reply cannot replay that result. This proves the supported trusted Launcher's
single-send path and pending-result gate; the protocol is not claimed to provide
a general deduplicating RPC ledger for an arbitrary malicious Launcher. Such a
Launcher is not the supported untrusted runtime adversary.

`KernelWorkspaceService` binds its single operation slot to both request ID and
connection, installs disconnect handlers, and clears them only after executor
cleanup. `KernelWorkspaceClient` invalidates its operation connection on every
return. Python Worker preserves cancellation through preflight, snapshot and IPC,
kills Runner on exceptions, and only serves commit after a normal process result.
The Broker ToolRunner owns/reaps its process group. The relevant source paths are
`AgentHost.swift`, `AgentHostActionOutput.swift`, `AgentHostClient.swift`,
`TrustedWorkspaceLauncherMain.swift`, `KernelWorkspaceClient.swift`,
`KernelWorkspaceService.swift`, `KernelWorkspacePythonExecutor.swift`,
`kernel/worker.py`, `kernel/macos_seatbelt.py`, and `KernelSnapshotBrokerToolRunner.swift`.
These existing primitives serve the actual requirement; no new IPC, thread,
trusted process, task manager, retry or receipt database is justified.

Invalidating the model connection is not a claim that every in-flight provider
inference instantly stops; a bounded model computation may finish without a live
Launcher. It cannot approve or launch another operation. Likewise cancellation
does not reverse an already validated commit or external side effect. These
limits follow architecture §11.1 and remain unchanged.

## Change budget and remaining work

Production code delta: 0.
Trusted code delta: 0.
New architecture concepts: 0.
New trusted processes: 0.
New IPC operations: 0.
New persistent runtime state: 0 (audit artifacts only).
New dependencies: 0.
Removed duplication / abstractions: 0; reused existing cancellation, result gates,
process-group cleanup and prior exact-source UI evidence instead of a new layer.

This report adds no normative security contract and therefore no freeze-protected
source change or new security declaration. PR CI checks must still pass at its
final head. Independent Code Owner approval remains NOT_PROVEN in the accepted
single-maintainer mode. M7.4 boundary regression and M7.5 fixed benchmark closure
are the next sequential batches; the full taskbook is not yet declared complete.

Fresh validation completed: 27 targeted tests passed in 61.382 seconds; the signed
XPC test passed in 118.8 seconds. Both exited 0. The signed fixture
asserted request/connection-bound cancellation, disconnect without writeback,
service recovery, OS peer denial and workspace byte checks.
