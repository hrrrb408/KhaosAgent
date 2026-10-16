# M7.3 — execution state and cancellation audit

Base: `4e0c39a88c27efb31cfe35bce6497d2de9a7dff9` (M7.2, PR #23).
This batch audits the existing mechanisms before proposing a replacement. No
reproducible runtime gap was found in the initial local reviewed cases, so production code,
trusted runtime code, protocol, timeouts, retries and permissions remain unchanged. A later remote fixture failure and test-only diagnostic follow-up are retained below.

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
remain applicable to the identical runtime; the later diagnostic-only test change
does not change their assertions. They
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

The initial report added no normative contract or protected source. The diagnostic
follow-up below has its own fresh security declaration and reviewed test hash. PR CI checks must still pass at its
final head. Independent Code Owner approval remains NOT_PROVEN in the accepted
single-maintainer mode. M7.4 boundary regression and M7.5 fixed benchmark closure
are the next sequential batches; the full taskbook is not yet declared complete.

Fresh validation completed: 27 targeted tests passed in 61.382 seconds; the signed
XPC test passed in 118.8 seconds. Both exited 0. The signed fixture
asserted request/connection-bound cancellation, disconnect without writeback,
service recovery, OS peer denial and workspace byte checks.

## Remote failure and bounded diagnostic follow-up

PR #24 CI run 38885620597 ran 341 tests in 716.667 seconds and failed one:
`test_xpc_sandbox_scope_peer_identity_and_service_container_identity`. The
shared-service cancellation fixture returned execution output rather than the
expected `process_cancelled`. Its 600-character prefix retained setup markers
and the start of a Python traceback but discarded the exception tail.
`remote-ci-attempt-1.txt` preserves this failure. The earlier local signed test
pass is not substituted for remote closure. No command rerun, timeout increase
or assertion relaxation was applied in response. The underlying exception and
causal stage remain NOT_PROVEN from that truncated record.

The test-only Host.swift diagnostic now retains up to 280 leading and 280 trailing
characters with a fixed truncation marker when output exceeds 600 characters;
short output and explicit error codes are unchanged. This fits the existing cap
and preserves the actual exception tail. It never enters production/model input;
the fixture child has its existing minimal environment and synthetic workspace.
Every cancellation/no-write/request/connection assertion is unchanged. This is
a diagnostic change, not a claimed repair of a runtime cancellation bug. The
fresh security declaration binds c97bb05 and exactly the diagnostic plus its
three governance files. Runtime TCB delta stays 0.

The focused signed XPC diagnostic build passed in 118.426 seconds (exit 0).
This confirms the revised fixture compiles and the local attack assertions pass;
it does not identify the cause of the earlier remote exception. Exact-head CI
is required again, with the failed run preserved.
