# Khaos Seed Threat Model

**Status:** development evidence ledger, not a production security claim.

The architecture constitution in [`Khaos vNext 架构设计文档.md`](Khaos%20vNext%20架构设计文档.md)
defines the required security properties. This file records the Seed prototype's
attacker model, enforcement boundary, executable evidence, and limits. Detailed
macOS experiments and upstream research remain in
[`SEED_BACKEND_RESEARCH.md`](SEED_BACKEND_RESEARCH.md).

## 2026-10-05 persistent single-slot Candidate lifecycle

The signed Launcher and existing `KernelProduction.xpc` now provide Candidate
admission, activation, state inspection, execution request, and rollback for one
fixed `primary` slot. Admission validates and stores read-only content-addressed
Candidates. Activation and rollback bind exact Candidate, Manifest, and scope
digests to the reviewed slot generation and a fixed 30-day validity. The Kernel
loads `plugin.run` source and scopes from the active Candidate under the store
lock; its caller can provide reviewed digests and generation but no source or
scope. Rollback changes future routing only. The store and HMAC key remain
user-owned and are not protected against a same-UID process that can replace
both.

The headless signed-product lifecycle test passed against the real
`KernelProduction.xpc`, including admission, mismatched and stale approval
rejection, persisted slot state, rollback, source non-disclosure, and rejection
of `plugin.run` without a workspace bookmark. The full canonical macOS suite
passed all 276 tests in 496.541 seconds on this host, including the signed
product lifecycle test, Runner/Seatbelt attacks, and XPC peer/container identity
checks. Swift type checks for the Launcher and Kernel service and the XPC probe
compile passed; focused Candidate lifecycle and bridge suites passed 20 and 15
tests. A separate real macOS Seatbelt test now activates and runs Candidate A,
activates and runs B, rolls back, and runs A again through the existing Kernel
Runner and changeset path. Each Candidate's attempts to read or alter the store
and to resolve a live Mach service are denied; an unconfined positive control
resolves that service. This is Python Kernel/Runner evidence, not a successful
signed product XPC `plugin.run` with a selected workspace. That UI-to-Runner
path remained unverified as of this 2026-10-05 record; the 2026-10-06 acceptance
below closes that evidence gap for the tested host and product composition.

## 2026-10-06 signed-product persistent Plugin execution lifecycle

The opt-in `test_seed_app_builds_and_authenticates_its_kernel_service` acceptance
passed with `KHAOS_RUN_PRODUCT_PLUGIN_LIFECYCLE_UI=1` against a disposable,
locally signed `KhaosSeed.app`, its production `KernelProduction.xpc`, the
production Plugin lifecycle, Seatbelt Runner, and existing validated changeset
writeback path. The human-operated package and workspace Pickers and approval
alerts completed `activate A → run A → activate B → run B → rollback → run A`;
the test completed in 455.805 seconds. The canonical
`python3 -m unittest discover -s tests -v` suite also passed all 276 tests in
497.746 seconds on this host.

For each run, the Launcher review displays Candidate, Manifest, and scope
digests, slot generation, capability and paths; its approved operation digest
binds the exact XPC request. The `plugin.run` payload contains the reviewed
digests and generation but no source or scopes. The bridge rejects injected
fields, and the Kernel resolves the active Candidate's source and Manifest
under the store lock before invoking the existing workspace Runner path. The
test parent checks the real disposable workspace after every run: only the two
Manifest write paths change, their contents are bound to the approved input,
and the unapproved canary remains unchanged. Runner evidence records OS denials
for activation state reads/writes, Candidate-store reads/permission changes,
and direct live-workspace reads. The Launcher confirms its Picker scope is
released after each run, and `codesign --verify --deep --strict` passes after
each lifecycle operation and run. For the generation race, the test leaves A's
generation-1 approval open, activates B at generation 2, then confirms that
approving the old request returns `stale_approval` without changing workspace
bytes.

This closes the signed-product positive execution evidence gap recorded above
for this host and test composition. It does not claim distribution signing,
protected installation, resistance to a same-UID process that can replace both
the Plugin store and its HMAC key, or equivalent enforcement on another macOS
version or machine.

## 2026-10-06 signed-product Agent Plugin invocation

The focused opt-in `KHAOS_RUN_PRODUCT_AGENT_PLUGIN_UI=1` acceptance passed in
224.762 seconds on this host. A locally signed product activated Candidate A in
the fixed `primary` slot at generation 1. The Agent Host received only the active
Plugin ID, Candidate digest, and generation, proposed that binding, and the
Launcher re-read `plugin.state` before showing the real invocation approval.
The first approval was denied by the user; the parent verified the workspace
bytes were unchanged. The second proposal was approved by the user and ran through
the existing signed Launcher → `KernelProduction.xpc` → Seatbelt Runner →
changeset writeback route.

The parent verified exactly the two Manifest write paths changed, their contents
matched the active Plugin result, and both the approved input and unapproved
canary remained unchanged. Runner evidence confirmed the scoped read/list behavior,
denial of unscoped reads, denial of Candidate-store and activation-state access,
and denial of direct live-workspace reads. The signed product passed deep code
signature verification. The Host received a result no larger than 16 KiB, labeled
as untrusted model input, and the Agent's following response stated that two
approved files were added.

The signed test bundle used the deterministic `AgentHostSandboxModelProbe` in the
local `llama-cli` slot. This validates AgentHost framing, Launcher authority checks,
the real approval UI, Kernel/Runner execution, result bounds and the following model
turn; it does not measure proposal quality or prove behavior for every production LLM.

The focused AgentHost protocol probe rejects forged Candidate digests and
generations, a proposal for a replaced active Candidate, injected source,
Manifest, read/write scope, capability, or approval fields, lifecycle mutation
responses, and an oversized result. The signed headless product check separately
proposes a Plugin while no Candidate is active and verifies the Launcher denies
it without presenting invocation approval. These are local signed test-product
results on this macOS host; they do not establish distribution signing,
protected installation, or behavior on another macOS version or machine.

## 2026-10-04 signed product boundary and interactive acceptance

The trusted `KernelProduction.xpc` is now signed without App Sandbox so that it
can apply the real Seatbelt profile to its untrusted Runner. A signed App Sandbox
helper returned `sandbox_apply: Operation not permitted` for that operation on
this host. The separate Broker remains trusted and uses its narrow Seatbelt
deny rules around a private per-user temporary storage subtree. The signed
headless product test passed Broker mounting, release, and XPC identity checks.
An initial selected-workspace attack run reached the cancellation stage after
earlier read, writeback, and changeset checks, but its external parent did not
observe the randomized sleep child. On resumption, XPC cancellation returned
`process_not_active`; the driver had discarded the original operation response.
The driver now retains that response and the parent releases a missing-child
pause after 40 seconds. A subsequent selected-workspace run observed the child
and received `process_cancelled`, but its recovery request omitted the required
Snapshot Broker endpoint and was rejected. The test-only driver now passes that
endpoint for the new request. The subsequent interactive signed-product XPC
attack passed in 116.146 seconds. Its external parent checked the selected
workspace's exact file set and bytes, unchanged sibling canary, committed file
mode `0600`, cancellation descendant cleanup, no cancelled writeback, recovery,
and `codesign --verify --deep --strict` on the product bundle. The driver also
required OS denial for direct Runner live-workspace reads and for App access
after Picker scope release, plus Kernel rejection of unsafe changesets. The
canonical headless suite passed 250 tests in 484.088 seconds before the
test-only recovery-endpoint correction; the focused headless product test then
passed in 40.306 seconds. This evidence is local to this Mac and temporary
signed product copy. It does not establish Candidate admission, protected
installation, or final Plugin authority grants.

The signed Kernel service now packages an explicit list of 14 Python modules
needed by the Seed execution chain. The builder rejects a missing module or a
symlinked source path, and does not copy the rest of the repository's `khaos/`
tree into the trusted service. The signed-product test checks the exact module
set. This limits accidental growth of the bundled trusted code; it does not
establish installed-bundle immutability or make the embedded Python runtime
itself small.

The Snapshot Broker Seatbelt policy now denies signals to processes outside
its sandbox. The existing signed-product headless XPC probe confirms
`kill(host_pid, 0)` succeeds in the host control but is denied by the Broker
with `EPERM` or `EACCES`; it also uses the production tool runner to cancel and
reap a same-sandbox child. Its real snapshot create/attach/release path remains
in the same focused test. This limits signal authority for the tested Broker
profile on this macOS host; the Broker still uses `(allow default)` and is not
fully confined.

## 2026-10-04 one-shot command entry

The signed Launcher now accepts one bounded `--command` plus up to eight exact
`--read` / `--write` paths. It encodes the command as data in Runner source,
validates the request before opening the Picker, then shows the selected
workspace, full command, scopes, and a digest of the exact one-run invocation
for user confirmation. It releases its Picker scope before submitting that
invocation to the existing Kernel XPC path. The Runner requests commit only
after a zero command exit; the Kernel's existing complete-changeset scope check
still decides what reaches the real workspace. Type checking, a headless signed
product build/XPC identity check, and focused real Seatbelt allow/reject tests
passed. The new command UI has not completed an interactive selected-workspace
run, so its user-confirmation and product writeback path remain unproven.
The command Seatbelt profile now grants `file-read-metadata` only for exact
write-scope paths absent from the trusted snapshot baseline. This lets ordinary
tools stat their newly created output without granting file-content reads or
metadata reads of unreadable baseline entries. A real Seatbelt test runs
`cat input.txt > result.txt`, commits that single scoped output, and requires
OS denial for command reads of both an unscoped sibling and the output itself.
The existing metadata-write denial and out-of-scope changeset rejection tests
also pass. A focused OS attack on the new metadata rule requires hardlinking an
unreadable baseline file to fail (or its metadata read to fail), and rejects
`stat` through both a newly created symlink and a baseline symlink ancestor to
an outside file. `/bin/cp` still exits nonzero when it tries to copy extended
attributes; the Launcher command mode does not commit a nonzero command.

## 2026-10-04 manual one-shot Plugin loading

The signed Launcher now has an opt-in `--plugin-run` path. Its first system
Picker selects a package folder; the Launcher opens `manifest.json` and
`plugin.py` relative to a directory descriptor with `O_NOFOLLOW`, requires
regular single-link files, bounds their sizes, and retains the captured bytes.
It accepts only a canonical, exact-field Manifest with ABI v6, a bounded ID,
an explicit process request, and up to eight read/write scope paths. The
existing XPC request validator checks every scope before the workspace Picker.
The package scope is released before Runner launch. A second Picker selects the
workspace, and a trusted approval alert displays the exact Plugin and Manifest
digests, requested scopes, process authority, and the digest of the invocation
containing the workspace bookmark. The existing signed XPC, Kernel, Seatbelt,
and trusted changeset commit path then executes the captured source once.
No installed or active Plugin slot is written; completion discards the Runner.
This does not implement Candidate promotion, durable approval, or rollback.

The bundled example Plugin completed one real local Seatbelt Runner → Kernel
writeback in a disposable workspace. The updated product built with a stable
local signing identity, passed deep signature verification, and completed its
headless Kernel/Snapshot Broker bootstrap check. The canonical no-Picker suite
then passed 250 tests in 485.373 seconds after two stale process-cleanup
fixtures were removed from their unapproved changesets and a static Swift
error-classification assertion was updated for its existing prefix cases.
At this point, there was no evidence yet that the two-Picker product UI had
completed a selected-workspace Plugin invocation.

## 2026-10-05 signed two-Picker Plugin writeback

The user selected `examples/seed-writer`, selected a fresh workspace, approved
the one-run confirmation, and received the product alert `Kernel operation
completed` with one added file. The same workspace then contained
`seed-plugin-output.txt` with bytes `Khaos Seed plugin ran\n` and SHA-256
`92d9641b3613c290f07aa781c193a955b4b38386da79f74d5889710059d7effc`. The
signed app passed `codesign --verify --deep --strict`; the one-shot process
exited. This closes the selected-workspace product UI evidence gap for one
manual Plugin invocation and Kernel commit on this Mac. It does not prove
Candidate admission, durable activation, or a Plugin-bound reusable grant.

The run's `stderr` included Bash's `getcwd` warning because the command sandbox
denies ancestor directory enumeration. The command and Kernel commit still
completed. The Kernel now supplies the resolved private snapshot path as the
command's `PWD`, avoiding a broader directory-read grant. A focused real
Seatbelt regression confirmed Bash starts without `stderr`, sees the matching
logical `pwd`, reads only the authorized input, cannot read an unscoped sibling
or its newly written output, and commits the scoped result. This regression
uses the current source; the already-run product bundle was not rebuilt for
this `PWD` adjustment. A current-source signed product was subsequently rebuilt
with the pinned local model. Its deep signature and headless XPC bootstrap
passed, and the packaged Kernel source contains the `PWD` setting. The new
bundle completed one local-model text turn through Agent Host XPC and exited
normally; the focused real Seatbelt regression passed again. The user's later
Picker screenshot shows one committed addition but still contains the warning,
so it records success on the earlier bundle and does not verify the rebuilt
bundle's interactive warning-free path.

## 2026-10-02 exact changeset write scope

The Kernel now applies the trusted `workspace_write_scope` to the complete
changeset, including output created by `process.exec`. Each added, modified, or
deleted filesystem entry must exactly match a scoped path; an omitted entry
rejects the entire commit before the live-mutation gate. The Runner may still
modify its private snapshot, but it cannot cause an out-of-scope change to
reach the selected workspace. The same scope also continues to govern SDK
`fs.write`.

Real macOS Seatbelt integration evidence confirms both outcomes: an explicitly
scoped command output commits, while commands that add, modify, or delete an
out-of-scope entry receive `commit_rejected` and leave live workspace contents
unchanged. The scope remains a trusted-launcher session parameter, not a
Plugin identity-bound grant or user approval. See
[`test_separate_kernel_commits_sandbox_output_and_denies_live_write`](../tests/test_launcher.py)
and [`test_kernel_rejects_out_of_scope_process_output_before_writeback`](../tests/test_launcher.py)
and [`test_kernel_rejects_out_of_scope_modified_and_deleted_process_output`](../tests/test_launcher.py).

The low-level committer now also rejects a sandboxed commit when its trusted
write scope is absent, before scanning output or invoking the live-mutation
gate. The existing snapshot-race test verifies this omission fails closed, and
the real Broker changeset test confirms scoped commit still runs under OS
enforcement; both focused tests passed on 2026-10-04.

The canonical `python3 -m unittest discover -s tests -v` suite passed all 240
tests on 2026-10-02 (481.131 seconds). It includes these real macOS Seatbelt
commit/rejection checks and the signed XPC product/recovery checks; this run
was headless and opened no Picker. This remains development-session scope, not
Plugin-bound or user-approved write authority.

## 2026-10-02 signed XPC readiness-probe APFS identity

The signed Kernel XPC readiness probe must copy its fixture from a Kernel-owned
filesystem into the Broker's separately mounted APFS lease. An earlier layout
created the source on the same leased volume; the snapshot's real separate-device
check correctly rejected that copy. Moving the source to Python's configured
`TMPDIR` then exposed that `URL.temporaryDirectory` did not grant the sandboxed
Kernel XPC the needed write access. The executor now takes Python's `TMPDIR` from
the validated Broker lease root created by the Kernel client.

A selected product XPC run reached the snapshot path but returned
`sandbox_unavailable` before Runner launch. A real host reproduction confirmed
that `hdiutil info -plist` can omit `volume-kind` for an attached APFS volume;
however, accepting that optional omission did not fix the selected product run.
Unified logs also recorded an App Sandbox denial of `system-info vfs.disk-space`.
The production Python path was repeating `hdiutil`/`diskutil` volume inspection
already performed by the authenticated live Snapshot Broker. The brokered path
now relies on that retained Broker lease for image, APFS device, capacity, and
mount validation, while Python still checks the lease path, ownership, marker,
and mount state. The workspace's already-open root descriptor supplies source
filesystem type and case semantics through Darwin `fgetattrlist`; any non-APFS
filesystem or missing case-capability validity bit fails closed. This removes
duplicate sandboxed metadata subprocesses without adding a fallback.

Real host tests mount case-sensitive and case-insensitive APFS volumes and verify
the descriptor-reported semantics; a real HFS+ image is rejected. The focused
APFS and HFS+ regressions pass. The canonical suite passed all 244 tests on
2026-10-02 (473.402 seconds), including the signed-product headless XPC check;
it does not open the Picker. The user later reported selecting a fresh
`/Users/huangruibang/Applications/khaos-seed-app-l2fgx4wq/user-selected-product-xpc-workspace`
and dismissing its result alert, but no matching process output, workspace
digest, or app signature result is available. This is only a user-observed
selection and alert dismissal, not evidence that the current XPC attack passed.

A new corrected product XPC attack run opened a Picker for
`/Users/huangruibang/Applications/khaos-seed-app-8zlitftj/user-selected-product-xpc-workspace`.
The parent received only `production-xpc-driver-pid` and
`production-xpc-picker-requested`; no selection arrived within 600 seconds, and
the focused test exited after 629.559 seconds. At the last workspace check it
still contained only the two original fixtures. The test cleaned its temporary
bundle and workspace. This is a missing user selection, not a Kernel failure or
an enforcement result; Runner execution, XPC attacks, commit, cancellation, and
post-run signature verification did not run. A correlated interactive run is
still required before claiming selected-workspace XPC evidence.

## 2026-10-02 `process.exec` read-scope rename bypass

A real macOS Seatbelt attack showed that path-only read grants were not enough
while the command could write the entire private snapshot. With scope limited
to `allowed-file.txt`, the command successfully renamed an unreadable
`private-canary.txt` over that path and read the canary. The pre-fix test exited
with the attack's sentinel code `48`; this was a real read-authority bypass,
not a mock result.

The command profile now denies `file-write-unlink` for unreadable baseline
entries and whole unreadable subtrees, and protects directory ancestors of
read-scope roots from being moved. These denials are emitted after the broad
private-snapshot write grant. File data writes and creation remain available
inside the private snapshot; any resulting changeset still
passes through Kernel validation. If the scope is empty or none of its roots
can be tied to a safe baseline entry, movement is denied throughout the
snapshot. If generated scope rules exceed the existing bounded Seatbelt profile
budget, process execution fails closed.

The real macOS regression covers `os.replace`, APFS `RENAME_SWAP`, moving a
scope-parent directory and then attempting the laundering rename, and source
path aliases for case and Unicode normalization where the host volume resolves
them. It also confirms that the empty-scope command cannot rename a canary.
Those cases pass in
[`test_fixed_command_reads_only_scoped_files_and_denies_link_escape`](../tests/test_launcher.py)
and [`test_fixed_command_cannot_bypass_runner_read_scope`](../tests/test_launcher.py);
the profile rule-order test also passes. The canonical unittest suite passes
all 237 tests in 472.947 seconds on this host, without opening the interactive
Picker. These results are limited to the current macOS host and tested Seatbelt
operations.

Upstream review found the same class of path-rule laundering addressed by
late `file-write-unlink` denials in
[Anthropic's sandbox-runtime](https://github.com/anthropics/sandbox-runtime/blob/main/src/sandbox/macos-sandbox-utils.ts).
That project is Apache-2.0 but describes itself as a beta research preview and
requires Node.js 22.12 or later. Khaos adopted the narrow OS-policy principle,
not the general runtime or a dependency; the local implementation is tested
against Khaos's own Runner and Seatbelt boundary.

## 2026-10-02 Runner-selected `process.exec` ABI

Runner IPC v6 makes command selection explicit in the Runner request:
`process.exec` accepts exactly `{"argv":[string,...]}`. The Kernel validates
argument count and encoded size, then applies the retained timeout, private
snapshot cwd, sanitized environment, read scope, resource limits, and macOS
Seatbelt policy. The outer Workspace XPC operation ABI v8 no longer carries
command argv; it binds only the Runner source, timeout, workspace scopes, and
selected workspace transport.

This resolves the fixed-command Seed path's inability to let an untrusted
Runner request build, test, or formatter commands. It does not add workspace,
cwd, environment, scope, timeout, or approval fields to that request. The
trusted workspace session currently enables `process.exec` implicitly, so this
remains a development capability rather than a Plugin identity-bound grant.
Every command result is untrusted private-snapshot output and still goes through
the Kernel changeset validator before writeback. Executable evidence for this
ABI change: the canonical macOS suite passed all 235 tests in 436.097 seconds.
It includes a real Seatbelt Runner that sends an otherwise valid `process.exec`
with an appended `workspace` field; the Kernel rejects it and neither the
workspace nor the outside directory gains the attempted marker. It also builds
and tests the signed product XPC service headlessly. The suite does not open a
Picker and does not prove a selected-workspace product run, Plugin admission,
or identity-bound capability grants.

Separately, the user confirmed selecting the disposable workspace in the latest
Picker interaction and dismissing its result alert. No process output, workspace
digest, or app identity from that interaction is retained, so it remains a UI
observation and does not add automated writeback evidence.

## 2026-10-02 Snapshot Broker `/Users` boundary

The Broker's existing process Seatbelt policy protected the current account's
home path, common temporary locations, mounted volumes, and network access, but
could still reach other user-space paths such as `/Users/Shared`. The policy
now protects the full `/Users` tree and its `/System/Volumes/Data/Users`
firmlink alias, while retaining access only to the fixed private snapshot
storage subtree and the directory ancestors needed to traverse to it. Non-
`/Users` home layouts retain the previous home-only rule.

The signed product XPC probe places host-readable, writable, chmod-able, and
executable canaries under `/Users/Shared`. Host controls first perform each
operation successfully; the real Broker XPC process must then receive
`EPERM` or `EACCES` for file reads, metadata lookup, file creation, mode
changes, and process execution. Existing tests still cover the Data-volume
alias, temporary paths, Kernel executable write-open, loopback denial,
malformed-policy startup refusal, and the valid APFS snapshot lease path. The
focused signed-product test passed in 29.192 seconds; the canonical
`python3 -m unittest discover -s tests -v` suite then passed all 237 tests in
471.837 seconds on this macOS host, without opening the Picker. The source and
real OS regression are in
[`KernelSnapshotBrokerSandbox.swift`](../khaos/macos/KernelSnapshotBrokerSandbox.swift)
and [`test_macos_xpc_sandbox.py`](../tests/test_macos_xpc_sandbox.py).

This narrows the file and execution authority exposed under `/Users`; the
Broker profile still starts with `(allow default)`. Paths outside the tested
deny rules may retain authority. This does not prove deny-by-default
containment, another macOS version, or Candidate admission.

### 2026-10-03 Homebrew write and process-execution roots

The Broker denies `process-exec` and `file-write*` below the standard
`/opt/homebrew` and `/usr/local` prefixes. On this Apple Silicon host, the
signed-product probe copies `/usr/bin/true` into Homebrew's user-writable
temporary directory and separately tests creating a fresh file there. Host
controls can execute the copied binary and create the file; the same-identity
test Broker, running the production Seatbelt helper, receives `EPERM` or
`EACCES` from `posix_spawn` and file creation. The write canary remains absent.
The production Broker still creates, attaches, and releases its APFS snapshot.
This checks a writable `/opt/homebrew` path on this host; it does not establish
behavior on Intel Macs, `/usr/local`, or deny access to every system resource.

The focused signed-product test passed in 30.237 seconds, and the canonical
`python3 -m unittest discover -s tests -v` suite passed all 244 tests in
470.812 seconds without opening the Picker. The policy still starts with
`(allow default)`, so other system authority remains. See
[`KernelSnapshotBrokerSandbox.swift`](../khaos/macos/KernelSnapshotBrokerSandbox.swift)
and [`test_macos_xpc_sandbox.py`](../tests/test_macos_xpc_sandbox.py).

### 2026-10-04 Package-manager Data-volume aliases

The write and process-execution rules now cover `/System/Volumes/Data` firmlink
spellings for both package-manager roots. On this Apple Silicon host, the
signed-product probe confirms `/System/Volumes/Data/opt/homebrew` resolves to
the same writable directory, and host controls successfully execute and create
canaries through that spelling. The same-identity test Broker, using the
production policy helper, receives `EPERM` or `EACCES` for both alias
operations while production APFS snapshot operations still
succeed. The focused headless test passed in 28.856 seconds. Only the
`/opt/homebrew` alias is exercised here; this does not establish `/usr/local`,
other macOS versions, or complete Broker containment.

### 2026-10-04 Temporary-root Data-volume alias

The signed-product Broker probe covers `/System/Volumes/Data/private/tmp`. A
host positive control confirms it is the same writable directory as `/tmp`; the
Broker receives `EPERM` or `EACCES` when creating a canary through that spelling.
The policy also denies equivalent Data-volume roots for `/var/folders` and
`/var/tmp`, while retaining the fixed lease's matching storage alias. The
focused headless product test passed in 28.858 seconds. Only the `private/tmp`
alias was directly exercised; the Broker still starts from `(allow default)`
and retains untested system authority.

### 2026-10-04 Snapshot Broker execution from temporary roots

The same production policy now denies `process-exec` under the standard
temporary roots and their Data-volume aliases. A signed-product probe places a
copy of `/usr/bin/true` under `/System/Volumes/Data/private/tmp`; the host
executes it successfully, while the Broker's `posix_spawn` receives `EPERM` or
`EACCES`. Production APFS create/attach/release/detach still succeeds in that
run. The focused headless product test passed in 29.283 seconds. Direct
execution evidence covers `private/tmp`; this does not close the Broker's
remaining `(allow default)` authority.

## 2026-10-03 Product XPC request without a Snapshot Broker

The production Python executor requires the per-request Snapshot Broker
endpoint before it resolves a workspace bookmark or launches its Python bridge.
A signed-product test driver now submits a valid, digest-matched Runner source
that attempts to create a canary in `/Users/Shared`, but deliberately omits the
Broker endpoint. An unconfined host control creates the same canary first; the
real `KernelProduction.xpc` returns exactly
`snapshot_broker_not_configured`, and the Runner canary stays absent. This
exercises the fixed signed product service and catches execution fallback on
this request path. It does not establish behavior for every backend failure or
replace the interactive product writeback acceptance or the lower-level real-OS
Runner and cancellation attacks.

The focused signed-product test passed in 27.918 seconds. The canonical
`python3 -m unittest discover -s tests -v` suite passed all 244 tests in
471.613 seconds without opening the Picker. See
[`KernelWorkspacePythonExecutor.swift`](../khaos/macos/KernelWorkspacePythonExecutor.swift),
[`WorkspaceGrant.swift`](../tests/macos_xpc_probe/WorkspaceGrant.swift), and
[`test_macos_xpc_sandbox.py`](../tests/test_macos_xpc_sandbox.py).

## 2026-09-30 bounded `fs.write` development ABI

At the time of this 2026-09-30 record, Runner IPC v5 added
`fs.write(path, bytes)` with a separate exact-path
`workspace_write_scope`; empty scope denies Runner SDK `fs.write` requests. It
did not constrain the separately authorized `process.exec` command, which could
change the selected workspace's private snapshot. SDK `fs.write` uses
descriptor-relative no-follow traversal, a 32 KiB limit, single-link regular-file
checks, staged atomic installation, and a content digest reply. The product
Launcher source now binds one generated
writeback marker path and asks its Runner to verify that an unscoped sibling
write is denied. This is a fixed smoke path, not general product editing or a
user-approved Plugin capability flow. A later Picker run reached the current
Launcher success alert according to the user's observation; its temporary app
and workspace and the test parent's final result were not retained, so that run
does not prove its post-alert signature assertion. See the run-specific records
below.

At that point, the selected workspace root was the `process.exec` output
boundary. Its shell/project command could change the private snapshot without a per-path allowlist;
all resulting changes remain untrusted and must pass the full Kernel changeset
validator before writeback. A real Seatbelt test runs with the default empty
`workspace_write_scope`: the Runner's `fs.write` request is denied, then the
trusted-launcher-bound command creates a file in the private copy. Direct writes
to the live workspace and an outside canary are denied, and the Kernel commits
the validated file only inside the selected workspace. This is a
trusted-launcher development authority, not a per-Plugin or approved process-write
grant; [`test_separate_kernel_commits_sandbox_output_and_denies_live_write`](../tests/test_launcher.py).

[`test_workspace_snapshot.py`](../tests/test_workspace_snapshot.py) exercises
safe replacement/creation plus traversal, symlink, hardlink, and oversize
rejection. [`test_broker.py`](../tests/test_broker.py) permits an exact scoped
write and rejects its sibling. The real macOS Seatbelt test
[`test_launcher.py::test_kernel_writes_only_explicit_files_and_runner_cannot_write_workspace`](../tests/test_launcher.py)
confirms the permitted snapshot change reaches the validated commit, an
unscoped write is denied, and direct Runner writes to the selected workspace
and an outside canary fail with `EPERM` or `EACCES`. The focused signed XPC
package test passes with Workspace XPC v6 but does not execute the selected-
workspace Runner. This proves the lower-level development path on this host,
not product-Launcher writeback, user-approved capability grants, or Plugin
admission.
The canonical `python3 -m unittest discover -s tests -v` suite then passed all
207 tests in 390.154 seconds on this macOS host. The opt-in interactive product
writeback test was not part of that suite.

The user reported that the selected-workspace Picker displayed `PASS` before
the test parent's final result was available in that turn. The later
`2026-09-30 normal product Launcher selected-workspace writeback` record below
ties this interaction to the successful process exit and the parent's
workspace-content, fixture, and signature checks. Treat those parent assertions
as the verification; the popup alone is only a UI observation.

## Scope and assumptions

The current Seed path is a macOS-only development prototype. A trusted Launcher
calls the authenticated `KernelProduction.xpc` service, which delegates to its
Python Bridge and one-shot Worker. The Worker starts an OS-confined Runner and a
fixed command process in a private, bounded APFS snapshot. An authenticated
Snapshot Broker mounts and releases that APFS lease under its own restricted
policy. Runner requests cross bounded IPC. The trusted Kernel validates the
snapshot changeset before writing to the selected workspace.

## Current TCB inventory and architecture terms

The product-level model is `Launcher → Kernel → Runner`. Bootstrap, Service,
Client, Executor, Bridge, Worker, Broker, and commit child name implementation
units inside those nodes; they are not additional product layers. Some are real
process boundaries and remain trusted because they carry enforcement authority.

| Trusted process or source group | Why it must be trusted |
| --- | --- |
| Launcher: `TrustedWorkspaceLauncherMain.swift`, `TrustedWorkspacePicker.swift`, `KernelWorkspaceClient.swift`, `KernelSnapshotBrokerBootstrapClient.swift`, `KernelSnapshotBrokerBootstrapXPC.swift`, `KernelWorkspaceXPC.swift`, `XPCPeerIdentity.swift`, `AgentHostClient.swift`, `AgentHostProtocol.swift` | Obtains the user's selected folder/bookmark, presents and constrains each request, retains the requested scopes, and authenticates service endpoints. Model/Plugin proposals remain untrusted and must pass Launcher review and Kernel validation. |
| `KernelProduction.xpc`: `KernelWorkspaceXPC.swift`, `KernelWorkspaceService.swift`, `KernelWorkspaceBootstrap.swift`, `KernelWorkspaceRoot.swift`, `KernelWorkspacePythonExecutor.swift`, `KernelWorkspaceServiceMain.swift`, `KernelWorkspaceClient.swift`, `KernelSnapshotBrokerXPC.swift`, `KernelSnapshotBrokerClient.swift`, `KernelSnapshotStoragePolicy.swift`, `KernelCStringArray.swift`, `XPCPeerIdentity.swift` | Authenticates Launcher and Snapshot Broker, validates bounded requests, binds the selected workspace to a descriptor, retains cancellation and lease state, and launches the trusted Python execution path. |
| Kernel Python execution path: `khaos/ipc.py`, `khaos/launcher.py`, `khaos/kernel/broker.py`, `khaos/kernel/macos_seatbelt.py`, `khaos/kernel/plugin_lifecycle.py`, `khaos/kernel/peer_identity.py`, `khaos/kernel/worker.py`, `khaos/kernel/workspace_changes.py`, `khaos/kernel/workspace_snapshot.py`, `khaos/kernel/workspace_xpc_bridge.py` | Provides bounded IPC and peer checks, OS sandboxing, exact read/write scope, private snapshots, process-tree cleanup, complete changeset validation, and the only live-workspace writeback path. `plugin_lifecycle.py` also validates immutable Candidates and binds active-slot changes and runs to persisted digests and generations. |
| `KernelSnapshotBroker.xpc`: `KernelSnapshotBrokerXPC.swift`, `KernelSnapshotBrokerBootstrapXPC.swift`, `KernelSnapshotStoragePolicy.swift`, `KernelSnapshotBrokerSandbox.swift`, `XPCPeerIdentity.swift`, `KernelCStringArray.swift`, `KernelSnapshotBrokerToolRunner.swift`, `KernelSnapshotBrokerService.swift`, `KernelSnapshotBrokerServiceMain.swift` | Restricts and authenticates the APFS mount helper, validates lease identity and capacity, and bounds/cancels tool process groups. This separate trusted process exists for its narrower platform policy; it is an internal Kernel implementation. |

The builder's explicit source allowlist and the signed-product test define and
check the packaged Kernel Python set. `khaos/runner.py` and
`khaos/runner_sdk.py` are bundled for the isolated Runner, but execute in that
untrusted Seatbelt process and do not enforce authority. `AgentHost.swift` and
the model runtime are separately App-Sandboxed and untrusted. Plugins, generated
source, workspace contents, tests, probes, and build scripts are also outside the
runtime TCB. The source-tree-only `khaos/kernel/macos_disk_image.py` direct APFS
backend remains available to development tests, but the signed Kernel bundle
omits it and uses only the authenticated Broker lease path.
The two Python `__init__.py` package markers in that bundle contain no
enforcement code.

`docs/Khaos vNext 架构设计文档.md` and `docs/KERNEL_ABI.md` define normative
architecture and wire contracts. This file is an evidence ledger: its scope,
current limitations, and test mappings describe what is established, while dated
run entries record historical evidence rather than changing the contract.
`docs/SEED_BACKEND_RESEARCH.md` is a historical research log, and `README.md` is
the user-facing setup and current-status summary.

Treat Plugin source, command output, workspace contents, and IPC payloads as
untrusted. Treat the launcher, Kernel worker, commit child, and macOS enforcement
as trusted for this prototype. The bounded Workspace XPC ABI, one-operation
admission/cancellation service, peer-authenticating bootstrap, and outbound client
connector are shared product sources. The client connector is
[`KernelWorkspaceClient.swift`](../khaos/macos/KernelWorkspaceClient.swift).
Bookmark-to-root descriptor handling is shared in
[`KernelWorkspaceRoot.swift`](../khaos/macos/KernelWorkspaceRoot.swift). The executor
implementation is shared in
[`KernelWorkspacePythonExecutor.swift`](../khaos/macos/KernelWorkspacePythonExecutor.swift)
and [`workspace_xpc_bridge.py`](../khaos/kernel/workspace_xpc_bridge.py). The fixed
service entrypoint in
[`KernelWorkspaceServiceMain.swift`](../khaos/macos/KernelWorkspaceServiceMain.swift)
binds the peer-authenticating bootstrap to that executor. A headless bundle-build test
compiles and signs it; a separate unbundled run confirms that missing peer
requirements make it exit before serving. A headless build-mode probe also starts the
fixed entrypoint from a signed test bundle, retrieves its anonymous endpoint, and receives
`process_not_active` for a random idle-cancellation request. This proves the bootstrap and
endpoint response paths under the test signing requirements; it does not run the workspace
executor or prove a selected bookmark grant. The selected-workspace execution evidence
below still comes from an ad-hoc signed XPC test bundle. A separate local `KhaosSeed.app`
build test starts its named service and anonymous endpoint, then confirms macOS rejects a
same-identifier client with the wrong signer. That test does not submit a workspace
operation. A second headless call sends a plain bookmark (`options: []`) for a random
directory under the sandboxed app's own Application Support without opening the picker;
the fixed `KernelProduction.xpc` executor returns `workspace_rejected`, and the test
confirms the input is unchanged with no output or bypass file. The probe also creates a
`withSecurityScope` bookmark for that same app-container directory without opening the
picker; the fixed executor still returns `workspace_rejected` and the same no-writeback
checks pass. These are negative checks for that fixed entrypoint and fixture, not evidence
of an external user-selected workspace grant or of every XPC service. The
sandboxed `UntrustedHost.xpc` sibling, embedded in the same test app, also cannot retrieve
the Kernel bootstrap endpoint: the OS invalidates its XPC connection, while its own
container remains writable and an external workspace canary remains unchanged. These are
test-identity checks, not production signing or installation evidence. The
default signed-product test also runs a test-only driver in the temporary bundle:
it sends the real `KernelProduction.xpc` a validly framed `workspace.run` with a
mismatched Runner source digest and no bookmark. The service returns
`invalid_request` before bookmark handling, and the disposable fixture and sibling
canary remain unchanged. This verifies content-integrity rejection on that
product service path, not Candidate approval or source authorization. The same
default test also sends an over-depth JSON envelope; the service rejects it before
bookmark handling and remains responsive to a subsequent request. The parser also
requires byte-for-byte round-tripping through Foundation's sorted-key serializer; a
duplicate-field request to the real product service is rejected before bookmark
handling. Shipped Swift clients use the same encoding. The
directory-selection and bookmark helper itself is shared in
[`TrustedWorkspacePicker.swift`](../khaos/macos/TrustedWorkspacePicker.swift); it does not
persist user grants. The local app is built by
[`build_macos_seed.py`](../tools/build_macos_seed.py), with its launcher in
[`TrustedWorkspaceLauncherMain.swift`](../khaos/macos/TrustedWorkspaceLauncherMain.swift).
A locally signed `KhaosSeed.app` selected an external temporary workspace and displayed
its fixed no-change `PASS` alert. The first bundle later inspected still carried
`com.apple.security.files.bookmarks.app-scope`; a newer fresh bundle built with the
reduced entitlement set also displayed `PASS`, as confirmed by the user. Its selected
workspace fixture retained the expected SHA-256 after the run. Post-run deep signature
verification found new `__pycache__` files inside the signed `Python.framework`, so the
run exposed runtime mutation of the packaged framework. Fixed isolated Python launches
now pass `-B` at each interpreter boundary; the executor also sets
`PYTHONDONTWRITEBYTECODE=1` for non-isolated descendants. The focused package test passed in 7.743 seconds and checks nested Python imports leave
the signed bundle verifiable; Launcher (24), Seatbelt (37), and Broker (27) tests also
passed serially. The canonical `python3 -m unittest discover -s tests -v` suite passed all 185 tests in 361.049 seconds after the fix. The user later confirmed the reduced-entitlement product app displayed PASS. Its selected fixture SHA-256 was c00d07fbc2916475914e8ccf2fbbb10c255a41ebc775898bb4ca2294df614659 before and after the run; post-run codesign --verify --deep --strict passed and no __pycache__ remained in the signed Python framework. This confirms only the fixed zero-change route. These runs alone do not establish
non-empty changeset writeback, Picker write-scope revocation, or Candidate execution.
The first separate 2026-09-29 product run, recorded below, established the fixed
one-file writeback path only. The later product acceptance below also verifies
direct Picker-write denial; neither run establishes Candidate execution.
The app is not installed or notarized. `test_app_sandbox_cannot_create_or_mount_kernel_apfs_images`
reproduces nonzero results for `hdiutil create`, the production backend's exact
`hdiutil attach` command, `diskutil image attach`, and a follow-up `diskutil mount`
inside a signed App-Sandboxed helper. `diskutil image attach` can leave an unmounted
APFS device in the system image inventory despite returning nonzero; the test's host
process removes it and verifies no volume remains mounted. Its unconfined controls
successfully mount the same image with both attach commands. This is evidence about
these exact calls on this host, not every DiskImages route. The current packaged
`KernelProduction.xpc` has no App Sandbox entitlement. A signed helper on this
Mac received `sandbox_apply: Operation not permitted` when it tried to apply
the nested Seatbelt policy needed for an untrusted Runner. A separate
`KernelSnapshotBroker.xpc` creates, attaches, and detaches the bounded APFS
image because the complete mount operations tested here do not succeed inside
App Sandbox. The Broker has no App Sandbox entitlement and remains
in the trusted computing base. Before either listener resumes, it now applies a fixed
Seatbelt policy that denies network access, file reads/xattrs/writes under `/Users`,
temporary paths outside its exact snapshot-storage subtree, `/Volumes`, and
execution of programs from `/Users`. Its policy permits path-ancestor directory traversal
needed to reach the storage subtree. The named bootstrap still requires the signed
Launcher, the anonymous operations endpoint requires the signed Kernel, and each
operation requires the canonical private per-user temporary storage URL. A real signed-product
headless test reaches the packaged Broker through that endpoint, creates and mounts
an image, releases it, and verifies it is no longer mounted. A test-only replacement
Broker applies the exact same Seatbelt helper and receives real OS denials for
`/Users/Shared` read/metadata/write, the APFS Data-volume alias, parent-directory chmod,
standard temporary aliases, shared-folder process execution, Kernel write-open, and
loopback; host controls prove each attempted operation is otherwise available. These results cover
the listed operations on this host, not every OS resource or release. The policy uses
`allow default`, so system authority outside the denied locations remains; the Broker
also lacks an App Sandbox entitlement and uses deprecated `sandbox_init(3)`. It is
therefore still a TCB component with residual process authority, not a complete
minimum-privilege sandbox. Interactive Picker evidence remains separate and must
verify each selected-workspace run.

Evidence applies only to the tested macOS host and current implementation. A
test pass does not establish behavior on other macOS releases or against a
privileged or same-user process that can modify the development checkout.

## Enforced paths and evidence

| Threat | Enforcement in the prototype | Executable evidence |
| --- | --- | --- |
| Runner tries to grant itself `fs.read`, `fs.list`, or `fs.write` scope by adding scope fields to raw IPC payloads | The Broker retains read/write scopes from the trusted launch context and validates exact per-operation payload fields; filesystem operations have no grant or scope-update field | Broker tests send forged `workspace_read_scope` fields with `fs.read` and `fs.list`, and `workspace_write_scope` with `fs.write`; each receives `invalid_request`. A real macOS Seatbelt Runner test performs all three raw-wire attacks with empty scopes and requires `runner_failed`, unchanged secret bytes, and no fixed-command marker. This proves the tested Broker/Runner path on this host, not Candidate admission or user approval; [`test_broker.py`](../tests/test_broker.py), [`test_launcher.py`](../tests/test_launcher.py) |
| Runner reads or enumerates a workspace path outside its exact Kernel-granted read scope | The Kernel validates `fs.read` and `fs.list` paths against `workspace_read_scope`; ancestor listings return only entries covered by the granted paths | The 2026-09-30 selected-workspace product XPC test allowed `fs.read("production-input.txt")`, denied sibling reads with `path_not_readable`, filtered the root listing to only `production-input.txt`, and denied direct sibling listing with `path_not_listable`. The same real signed `KernelProduction.xpc` run completed writeback, post-scope direct-write denial, unsafe changeset checks, connection-bound cancellation, exact workspace verification, and deep signature verification in 250.479 seconds. A 2026-10-04 rerun against the current signed bundle passed in 238.506 seconds, rechecking scoped read/list, writeback, post-scope OS denial, unsafe changeset rejection, connection-bound cancellation and descendant cleanup, recovery, exact workspace state, and deep signature. Its test driver now waits for the parent’s cancellation signal without stopping the asynchronous XPC sender. These runs use test-only Runner source, so they prove the Kernel's requested-scope enforcement on this host, not Candidate or Manifest admission; [`WorkspaceGrant.swift`](../tests/macos_xpc_probe/WorkspaceGrant.swift), [`test_macos_xpc_sandbox.py`](../tests/test_macos_xpc_sandbox.py) |
| XPC caller changes Runner source without changing its bound digest | The Swift Kernel parser verifies SHA-256 of the decoded UTF-8 source before bookmark handling; the Python bridge repeats the check before starting the Worker. This binds content only and does not authorize a Candidate | The default signed-product test sends the real `KernelProduction.xpc` a valid `workspace.run` frame with a mismatched digest and no bookmark. It requires `invalid_request`, unchanged fixture bytes, and unchanged sibling canary; [`KernelWorkspaceXPC.swift`](../khaos/macos/KernelWorkspaceXPC.swift), [`workspace_xpc_bridge.py`](../khaos/kernel/workspace_xpc_bridge.py), [`test_macos_xpc_sandbox.py`](../tests/test_macos_xpc_sandbox.py) |
| XPC caller supplies malformed read or write scope paths | The native parser rejects absolute paths, empty paths/components, `.`/`..`, NUL, over-depth paths, duplicate paths, and over-budget scopes before reading a bookmark; the downstream Python Worker independently validates scopes before snapshot creation | The default signed-product test sends valid-digest requests with no bookmark to the real `KernelProduction.xpc`; traversal, absolute, empty, NUL, empty-component, dot-component, over-depth, duplicate, over-count, and over-budget scopes must each return `invalid_request` before bookmark handling. The service must remain responsive afterward; [`KernelWorkspaceXPC.swift`](../khaos/macos/KernelWorkspaceXPC.swift), [`WorkspaceGrant.swift`](../tests/macos_xpc_probe/WorkspaceGrant.swift), [`test_macos_xpc_sandbox.py`](../tests/test_macos_xpc_sandbox.py) |
| Duplicate or noncanonical JSON fields make XPC admission ambiguous | Before schema validation, the Swift parser requires exact byte equality with Foundation's sorted-key serialization of the parsed object, rejecting duplicate fields and alternate encodings | The default signed-product test sends exact and escaped-name duplicates of `workspace_read_scope` to the real `KernelProduction.xpc`, with no bookmark; both must return `invalid_request` before bookmark handling, then an idle cancellation confirms the service remains responsive; [`KernelWorkspaceXPC.swift`](../khaos/macos/KernelWorkspaceXPC.swift), [`test_macos_xpc_sandbox.py`](../tests/test_macos_xpc_sandbox.py) |
| Over-depth XPC JSON reaches the Kernel parser | The Swift service checks a bounded eight-level structural depth before Foundation parsing; the current schema needs at most three levels | The default signed-product test sends an over-depth request without a bookmark, requires `invalid_request`, then verifies the service responds to an idle cancellation; [`KernelWorkspaceXPC.swift`](../khaos/macos/KernelWorkspaceXPC.swift), [`test_macos_xpc_sandbox.py`](../tests/test_macos_xpc_sandbox.py) |
| Snapshot Broker reads protected user files, writes to user-writable tool roots, runs programs from those roots, or reaches loopback | The Broker applies Seatbelt before opening either XPC listener; it denies network, file data/xattrs/writes across `/Users` outside fixed storage, standard temporary roots including metadata/existence checks outside fixed storage and its ancestors, `/Volumes`, writes below `/opt/homebrew`, `/usr/local`, and their Data-volume firmlink spellings, and process execution from `/Users` and all four package-manager spellings. It permits only directory-data/metadata access needed to traverse storage ancestors. Its storage URL remains canonical and the Kernel peer remains signature-bound | The signed-product test confirms real APFS create/attach/release through the production Broker. A same-identity test-only Broker attempts `open`, `lstat` of `/Users/Shared` and `/var/tmp`, `access(F_OK)` on `/var/tmp`, file creation, parent-directory `chmod`, `/tmp` and `/var/tmp` writes, `/Users/Shared` and user-writable Homebrew-root `posix_spawn` and file creation, Kernel write-open, and loopback connect. Host controls succeed and the Broker operations receive OS denials. On this Apple Silicon host, the Homebrew probe also succeeds via `/System/Volumes/Data/opt/homebrew` before requiring real Broker denials for alias execution and creation; `/usr/local`, other architectures, and other writable roots remain unverified. Another temporary signed product uses malformed SBPL; the OS rejects it and the service exits before serving bootstrap. The policy uses `allow default`; authority outside the tested deny rules remains, and `sandbox_init(3)` is deprecated, so this is partial host-specific containment rather than complete sandboxing; [`KernelSnapshotBrokerSandbox.swift`](../khaos/macos/KernelSnapshotBrokerSandbox.swift), [`test_macos_xpc_sandbox.py`](../tests/test_macos_xpc_sandbox.py) |
| Launcher reads an acceptance workspace before the user selects it | The acceptance-only `--acceptance-workspace` path controls Picker navigation, while Kernel receives only the actual selected URL's bookmark. Before presenting the panel, the Launcher requires `open(O_RDONLY | O_NOFOLLOW)` on the known fixture to fail with `EPERM` or `EACCES`; it also compares the selected URL with the requested workspace | The first 2026-09-29 signed run recorded `preselection-read=denied` but timed out before selection. The later interactive acceptance test passed (1 test, 103.483 seconds) and asserted the same denial before showing the Picker, then verified the selected-scope checks and writeback described below. This proves the acceptance path on that build and host, not a durable production grant policy; [`TrustedWorkspaceLauncherMain.swift`](../khaos/macos/TrustedWorkspaceLauncherMain.swift), [`test_macos_xpc_sandbox.py`](../tests/test_macos_xpc_sandbox.py) |
| Launcher retains read access after handing the selected bookmark to Kernel | In acceptance mode, the Launcher first proves a real `open(O_RDONLY | O_NOFOLLOW)` succeeds while the open-panel grant is live; after calling `stopAccessingSecurityScopedResource()`, the same open must fail with `EPERM` or `EACCES` before Kernel contact, or the Launcher fails closed. This covers read access, while a separate post-commit open covers writes | The 2026-09-29 interactive signed acceptance-bundle test passed after the user selected its fresh fixture (1 test, 103.483 seconds). It required ordered `selected-read=available` then `selected-read=denied`, Kernel writeback, and direct-write denial, and verified the fixture and signed bundle before temporary cleanup. This evidence applies to this build and host; it does not establish production app identity or grant policy; [`TrustedWorkspaceLauncherMain.swift`](../khaos/macos/TrustedWorkspaceLauncherMain.swift), [`test_macos_xpc_sandbox.py`](../tests/test_macos_xpc_sandbox.py), [Apple App Sandbox file-access documentation](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox) |
| Runner reads or mutates the live workspace outside its allowed data flow | Runner runs in a distinct Seatbelt process; its cwd is private scratch, snapshot reads go through Kernel IPC scope checks, and command writes are confined to a separate snapshot. The end-to-end adversarial path attempts direct `listdir`, `stat`, `unlink`, `rename`, `renameatx_np(RENAME_SWAP)`, and `fclonefileat` from both Plugin source and its fixed command; unconfined host controls confirm directory enumeration, file metadata, same-volume cloning, and swapping work, while sandboxed operations must receive `EPERM` or `EACCES`. The packaged product Runner independently proves direct live-workspace `listdir` and `stat` denial. While `workspace.commit` is pending, a Runner thread continues swap attempts against live entries. The validated Kernel commit still updates the intended file and leaves the swap peer unchanged | [`test_runner_cannot_bypass_kernel_authority`](../tests/test_launcher.py), [`test_macos_seatbelt.py`](../tests/test_macos_seatbelt.py), [`test_broker.py`](../tests/test_broker.py), [`test_macos_xpc_sandbox.py`](../tests/test_macos_xpc_sandbox.py) |
| Runner attempts direct Mach/XPC service lookup | The Runner's Seatbelt profile denies unlisted operations, including `mach-lookup`; Plugin source must continue through the authenticated Runner pipe and Kernel Broker | A real Runner test first resolves the live `com.apple.cfprefsd.agent` service outside Seatbelt, then requires `bootstrap_look_up` from Plugin source to fail while Kernel-mediated `fs.read`, `process.exec`, and `workspace.commit` still succeed. This proves the tested Mach lookup denial on this host; it does not replace the product XPC caller-signature checks | [`test_runner_cannot_bypass_kernel_authority`](../tests/test_launcher.py), [`macos_seatbelt.py`](../khaos/kernel/macos_seatbelt.py) |
| Untrusted Runner opens packaged Kernel code for writing | The real Seatbelt Runner profile denies writes to the Kernel installation while the trusted command and committer retain only their bounded snapshot authority | The signed-product test runs the packaged Python Worker/Runner against the actual `KernelProduction.xpc` `workspace_changes.py`; `open(O_WRONLY)` must fail with `EPERM` or `EACCES`, after which a normal one-file Kernel commit succeeds. The Kernel file digest and deep bundle signature remain unchanged. This uses the packaged runtime through a trusted test launcher; it does not exercise XPC caller authorization or installation protection against unconfined same-UID processes; [`test_macos_xpc_sandbox.py`](../tests/test_macos_xpc_sandbox.py) |
| Workspace traversal, symlink, hardlink, special-file, or snapshot race | Descriptor-relative no-follow traversal; single-link regular-file policy; bounded snapshot; changeset validation before writeback | [`test_workspace_snapshot.py`](../tests/test_workspace_snapshot.py), [`test_workspace_changes.py`](../tests/test_workspace_changes.py), [`test_launcher.py`](../tests/test_launcher.py) |
| Unicode normalization or case-fold alias attempts to broaden read scope | Broker compares requested components with retained raw-spelling scopes, then descriptor-relative reads and listings require each existing component to match an actual directory-entry spelling before opening it. An aliased spelling in the scope itself therefore cannot resolve to another entry | [`test_broker.py::test_workspace_read_scope_rejects_unicode_normalization_alias`](../tests/test_broker.py) exercises a real case-insensitive APFS volume and verifies alias-spelled read/list scopes are rejected by the Kernel path layer; the existing real Seatbelt Runner coverage remains a separate end-to-end check |
| Runner appends authority fields to `process.exec` or forges a changeset target | `argv` alone is accepted for `process.exec`; appended workspace, cwd, environment, timeout, scope, or capability fields are rejected. `workspace.commit` accepts no payload fields | [`test_broker.py`](../tests/test_broker.py), [`test_launcher.py`](../tests/test_launcher.py), including real Seatbelt IPC attacks |
| Command escapes the workspace or contacts the network | macOS Seatbelt denies outside writes, direct live-workspace writes, sandboxed `hdiutil attach`, `diskutil image attach`, and direct `mount_apfs`, loopback, IPv6 loopback, proxy, DNS, and tested child-process paths. Unconfined positive controls mount the disk image successfully. The full Kernel/Runner chain verifies both image tools cannot mount, then verifies a separate safe output passes validated commit | [`test_macos_seatbelt.py::test_real_sandbox_blocks_disk_image_mount_over_live_workspace`](../tests/test_macos_seatbelt.py), [`test_workspace_changes.py`](../tests/test_workspace_changes.py), [`test_launcher.py::test_kernel_chain_blocks_disk_image_mount_and_commits_safe_output`](../tests/test_launcher.py) |
| Command double-forks and tries to keep writing the snapshot after its leader exits | The command Seatbelt profile denies `setsid` and `setpgid`; the Kernel terminates the command process group when the leader exits and before changeset validation. A real double-fork probe confirms the detached-session attempt is denied and its late write never enters the changeset | [`test_macos_seatbelt.py::test_double_fork_cannot_daemonize_past_command_exit`](../tests/test_macos_seatbelt.py), [`test_macos_seatbelt.py::test_command_exit_kills_snapshot_writer_before_commit`](../tests/test_macos_seatbelt.py) |
| Untrusted changeset path injects additional Seatbelt permissions | A backslash-quote path component crafted to add an outside literal write matcher remains a path string; a sandboxed process can write its planned output but the outside canary write is denied | [`test_macos_seatbelt.py`](../tests/test_macos_seatbelt.py) |
| Host environment, inherited descriptors, or process metadata expose secrets | Explicit child environments; a real Seatbelt execution verifies a host pipe FD is closed in both Runner and its command; Runner and fixed-command denial of tested `KERN_PROCARGS2` access | [`test_launcher.py::test_host_environment_sentinel_is_not_inherited_by_runner_or_command`](../tests/test_launcher.py), [`test_launcher.py::test_host_secret_pipe_descriptor_is_not_inherited_by_runner_or_command`](../tests/test_launcher.py), [`test_launcher.py::test_sandboxed_command_cannot_read_unconfined_process_metadata`](../tests/test_launcher.py), [`test_macos_seatbelt.py::test_sandboxed_command_does_not_inherit_an_open_pipe`](../tests/test_macos_seatbelt.py) |
| Runner or command inherits the trusted live-workspace root descriptor | The Kernel Worker receives the selected root FD, but it must not reach the sandboxed Runner or command. A high-numbered copy is `EBADF` in both children; Runner `fstat` / `openat` read and create attempts and command `openat("../...")` traversal therefore fail before live mutation | [`test_launcher.py::test_workspace_root_descriptor_is_not_inherited_by_runner_or_command`](../tests/test_launcher.py), using the real macOS Seatbelt backend |
| Unsafe Runner output partially changes the workspace | Trusted changeset rejects symlinks, hardlinks, FIFOs, and an actual AF_UNIX socket before writeback. A real Seatbelt Runner's socket `bind` attempt receives `EPERM` on this host; its safe companion file is not committed. The authenticated XPC executor probe confirms no candidate path is written. The hardlink probe verifies either OS denial at link creation or Kernel rejection at commit. A real Seatbelt commit-child race replaces a newly cloned destination with a same-owner, same-mode, same-link-count, same-size file; the Kernel detects the content digest mismatch and preserves the competitor | [`test_workspace_changes.py::test_rejects_unix_socket_output_before_partial_writeback`](../tests/test_workspace_changes.py), [`test_launcher.py::test_kernel_chain_rejects_unix_socket_output_before_partial_writeback`](../tests/test_launcher.py), [`test_broker.py::test_commit_child_preserves_post_clone_target_replacement`](../tests/test_broker.py), [`test_macos_xpc_sandbox.py`](../tests/test_macos_xpc_sandbox.py) |
| Runner supplies ACL metadata for a new file or directory | Kernel drops ACLs from Runner snapshot output, but macOS applies `file_inherit` / `directory_inherit` ACEs from the selected workspace's destination parent. Those inherited ACEs are existing OS policy; mode `0600` / `0700` does not override their grants. The Kernel preserves the parent policy rather than silently removing it | [`test_workspace_changes.py::test_new_file_discards_runner_acl_and_xattrs`](../tests/test_workspace_changes.py), [`test_workspace_changes.py::test_new_directory_discards_runner_mode_acl_and_xattrs`](../tests/test_workspace_changes.py), [`test_workspace_changes.py::test_new_entries_inherit_parent_acl_not_runner_acl`](../tests/test_workspace_changes.py) |
| Concurrent writer replaces the committer's new-file temporary path | The commit child compares the displaced path's device/inode with the identity pinned from its open descriptor; a mismatch is restored and reported as `commit_outcome_uncertain`, preserving the competing file | [`test_broker.py::test_commit_child_preserves_new_file_temporary_path_replacement`](../tests/test_broker.py), using the real macOS Seatbelt commit child |
| A post-clone failure races with a replacement of the new destination | The commit child does not issue a pathname-based rollback unlink after the clone. It reports `commit_outcome_uncertain`; the current path may contain the candidate or a concurrent replacement | [`test_broker.py::test_commit_child_preserves_replacement_after_post_install_failure`](../tests/test_broker.py), using the real macOS Seatbelt commit child |
| Directory creation is followed by a parent-binding or sync failure | The committer leaves the created or competing directory in its original (possibly detached) parent and returns `commit_outcome_uncertain`; it does not `stat` then `rmdir` a mutable pathname | [`test_workspace_changes.py`](../tests/test_workspace_changes.py), including parent detachment and a racing replacement at the sync-failure boundary; [`test_broker.py::test_commit_child_preserves_new_directory_after_parent_failure`](../tests/test_broker.py), using the real macOS Seatbelt commit child |
| Concurrent writer replaces the displaced baseline backup before the sentinel identity check | The committer restores the replacement and reports `commit_outcome_uncertain`; this test does not cover the later check-to-unlink window | [`test_broker.py::test_commit_child_preserves_displaced_backup_replacement_before_unlink`](../tests/test_broker.py), using the real macOS Seatbelt commit child |
| Unconfined same-UID writer replaces a backup after identity validation but before `unlink` | Not prevented: a regular replacement inside the authorized workspace can be removed while commit reports success. A symlink replacement is removed as a directory entry; its outside target is not followed | [`test_broker.py::test_commit_child_unlink_does_not_follow_raced_symlink`](../tests/test_broker.py) replaces the checked path with a symlink to an outside canary immediately before the real Seatbelt commit child's unlink; the symlink disappears and canary bytes stay unchanged. This does not establish global same-UID write exclusion; [`SEED_BACKEND_RESEARCH.md`](SEED_BACKEND_RESEARCH.md#2026-09-29-final-unlink-identity-race), [Apple `unlink(2)`](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/unlink.2.html) |
| New-file clone races with parent-directory detachment | The real Seatbelt commit child attempts descriptor clone only after an independent process moves the opened parent outside the workspace; the OS denies the clone and the candidate destination remains absent | [`test_broker.py::test_commit_child_cannot_clone_through_a_detached_parent_fd`](../tests/test_broker.py) |
| Commit child unlinks through a parent descriptor after that directory leaves the workspace | After the committer has validated the parent binding and backup identity, an independent process moves the containing directory outside the workspace. Seatbelt denies the stale-descriptor unlink with `EPERM` or `EACCES`; the Broker reports `commit_outcome_uncertain`, preserving the detached baseline backup and outside canary. The candidate may already have been installed before detachment. This does not close the separate same-UID replacement race at the final pathname unlink | [`test_broker.py::test_commit_child_cannot_unlink_after_parent_detaches`](../tests/test_broker.py), using the real macOS Seatbelt commit child |
| Cancellation, caller exit, or Worker exit leaves a writer or commits untrusted output | Cancellation is request-bound; process groups and abandoned Worker-owned APFS volumes are cleaned up. Interrupted image operations carry a private pending marker; cleanup detaches only the exact image identity reported by hdiutil and preserves the backing directory if OS state remains ambiguous. Commit is refused when Runner exits before requesting it | [`test_launcher.py`](../tests/test_launcher.py), [`test_broker.py`](../tests/test_broker.py), [`test_workspace_snapshot.py`](../tests/test_workspace_snapshot.py), including real unmounted-image detach and pending-marker preservation probes |
| Sandbox backend is absent or fails its capability probe | Unsupported platform and failed probe abort execution. On macOS, a host marker command is a positive control; with the backend path set to a missing executable, the Seatbelt API and Kernel Worker both fail before the fallback marker can run. This simulates backend absence and complements, but does not replace, real Seatbelt escape tests | [`test_macos_seatbelt.py`](../tests/test_macos_seatbelt.py), [`test_launcher.py`](../tests/test_launcher.py) |
| Sandboxed Host attempts to modify or replace the embedded Kernel executor | A container write control succeeds while App Sandbox denies write-open, create, chmod, hardlink, atomic file swap, replacement rename, symlink replacement, and unlink for the signed KernelExecution helper, fixed KernelProduction executable, Python bridge, changeset implementation, and Python interpreter. It also denies same-volume atomic directory swaps of the containing XPC bundles. Target digests remain unchanged and each bundle passes deep code-signature verification. This is a temporary ad-hoc test bundle, not production installation integrity or same-UID unconfined-process protection | [`test_macos_xpc_sandbox.py`](../tests/test_macos_xpc_sandbox.py) |
| XPC peer spoofing, request injection, delegated stream from another process, caller disconnect, caller crash, or stalled transfer | The shared service accepts a bounded `workspace.run` request and bookmark, binds the inner request ID to the authenticated outer call, checks the AF_UNIX stream's `LOCAL_PEERPID` against the authenticated outer caller before parsing, keeps one active operation, and binds cancellation to its submitting connection. The server authenticates callers; the signed test Launcher also applies the matching service code requirement to both the named bootstrap connection and returned endpoint connection before requesting or invoking Kernel. Real XPC attacks exercise inbound and outbound peer denial, oversized and mismatched-ID request frames, oversized/stalled bookmark streams, disconnect, and crash. A sandboxed sibling XPC service creates a valid request-prefix socketpair with no bookmark; the authenticated app relays its reader descriptor to Kernel, which returns `invalid_request` before parsing. The probe checks that the descriptor's OS peer PID is the sibling process and differs from the authenticated XPC caller. A separate real-socketpair parser test also confirms rejection before parsing. A sandboxed `UntrustedHost.xpc` sibling in the same test app attempts the named Kernel bootstrap; its connection is invalidated, and the shared outbound connection setup pinned to the Kernel identity is rejected by macOS when aimed at that sibling. A headless positive probe launches the fixed `KernelWorkspaceServiceMain.swift` from a signed test bundle, retrieves the anonymous endpoint, and receives `process_not_active` for an idle cancellation; it proves bootstrap and endpoint response under test identities, not workspace execution. Headless requests send both a plain bookmark and an app-container bookmark created with `.withSecurityScope`, neither selected by the user; both receive `workspace_rejected` and leave no output or bypass file. This does not prove an external user-selected grant. A test-only driver in a temporary signed product-app copy passed the selected-workspace `KernelProduction.xpc` safe-commit, unsafe-changeset, and active-cancellation attack probe on 2026-09-29; details and limits are recorded below. An unbundled run confirms missing peer requirements fail closed before listener startup. The local Seed app package also starts the service through both XPC layers and rejects an incorrect same-identifier signer; a freshly built product app with the reduced entitlement set completed its fixed no-change smoke after external workspace selection. The user-selected one-marker product acceptance passed on 2026-09-29 and is
recorded below. The later product acceptance also verifies direct Launcher write-open
denial after releasing Picker scope. Candidate admission and arbitrary Plugin execution through the production Launcher remain unverified. Distribution
signing, notarization, and installation identity are absent | [`KernelWorkspaceClient.swift`](../khaos/macos/KernelWorkspaceClient.swift), [`KernelWorkspaceService.swift`](../khaos/macos/KernelWorkspaceService.swift), [`KernelWorkspaceXPC.swift`](../khaos/macos/KernelWorkspaceXPC.swift), [`KernelWorkspaceBootstrap.swift`](../khaos/macos/KernelWorkspaceBootstrap.swift), [`KernelWorkspaceServiceMain.swift`](../khaos/macos/KernelWorkspaceServiceMain.swift), [`build_macos_seed.py`](../tools/build_macos_seed.py), [`test_macos_xpc_sandbox.py`](../tests/test_macos_xpc_sandbox.py) |
| A workspace bookmark root contains symlinked Kernel probe children | Shared `KernelWorkspaceRoot` opens its fixed child directories relative to the held root descriptor with `openat` and `O_NOFOLLOW`; real XPC requests fail before the probe marker or workspace output appears, and an outside canary stays unchanged | [`KernelWorkspaceRoot.swift`](../khaos/macos/KernelWorkspaceRoot.swift), [`test_macos_xpc_sandbox.py`](../tests/test_macos_xpc_sandbox.py); the signed service composition remains test-only |
| A sibling Host service reuses the picker's workspace grant | An earlier selected-path probe confirmed Kernel writeback and OS denial for the path-only sibling. A fresh selected run of the shared Picker source passed its read-only reopen and direct `open(O_WRONLY)` denial checks, then completed the shared `KernelExecution` one-file commit; a sibling XPC path-only write was also denied. The run later failed in the separate `KernelProduction` attack group, so this is partial evidence, not an overall test pass. A subsequent retry received no selection within 300 seconds | [`test_macos_xpc_sandbox.py`](../tests/test_macos_xpc_sandbox.py), interactive test-only path |
| A sandboxed Host consumes a security-scoped bookmark created without user selection | The shared `KernelWorkspaceRoot.withScopedBookmark()` rejects a bookmark created by a non-sandboxed test parent without a picker grant; a separately signed App Sandbox process with no user-selected-file entitlement then gets `EPERM`/`EACCES` opening the workspace canary, consistent with [Apple's App Sandbox file-access contract](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox) | [`KernelWorkspaceRoot.swift`](../khaos/macos/KernelWorkspaceRoot.swift), [`test_macos_xpc_sandbox.py`](../tests/test_macos_xpc_sandbox.py), real macOS App Sandbox denial |
| Trusted Picker retains workspace write authority after granting Kernel access | The `WorkspaceGrant` probe now passes the original `NSOpenPanel` root bookmark to both Kernel services; its fixture and unsafe-path canary sit relative to that selected root. The focused headless build-mode check passed in 109.470 seconds, but the test-only
WorkspaceGrant assertions have not run with this version. A fresh product bundle with the reduced entitlement set displayed `PASS` after external selection and its fixture hash remained unchanged; this proves only its fixed zero-change route. After execution, deep signature verification found Python bytecode caches added inside the signed framework. Fixed isolated Python launches now pass `-B`, and the executor sets `PYTHONDONTWRITEBYTECODE=1` for non-isolated descendants; a package test checks nested imports preserve the signature, and the post-fix app process exited without an observable result; the unchanged fixture and signature do not distinguish success from cancellation. The user-selected product smoke and the one-marker acceptance prove fixed
file writeback; the latter also verifies that the Launcher receives `EPERM` or
`EACCES` for a direct `open(O_WRONLY | O_NOFOLLOW)` after releasing Picker scope.
The separate test-only product-bundle attack below covers unsafe output rejection
and active XPC cancellation. Neither proves arbitrary Plugin admission through the
production Launcher. Apple documents the `options: []` bookmark transfer form | [`TrustedWorkspacePicker.swift`](../khaos/macos/TrustedWorkspacePicker.swift), [`WorkspaceGrant.swift`](../tests/macos_xpc_probe/WorkspaceGrant.swift), [`test_macos_xpc_sandbox.py`](../tests/test_macos_xpc_sandbox.py), [Apple App Sandbox file access](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox) |

The product Launcher now attempts a real `O_WRONLY | O_NOFOLLOW` open of the
Kernel-committed marker after stopping the Picker's security scope. It treats only
`EPERM` or `EACCES` as the required denial and will not show `PASS` otherwise.
The focused signed-package and peer-authentication test passed after this change
(1 test, 7.772 seconds). The opt-in selected-workspace product acceptance then
passed (1 test, 30.270 seconds); its test asserted the path-free
`direct-write=denied` diagnostic and independently verified the committed marker,
unchanged fixture, mode `0600`, single link, deep signature, and unchanged signed
Python framework. This proves the direct denial for this product build and tested
macOS host, not unsafe changesets, active cancellation, or arbitrary Plugin
admission. The canonical suite then passed all 186 tests in 384.191 seconds.

Run the repository's canonical suite with:

```bash
python3 -m unittest discover -s tests -v
```

The test-only XPC picker flow requires an interactive macOS session. On 2026-09-27,
a fresh post-extraction picker run passed in 201.018 seconds on this host. It confirmed
the selected-root bookmark, Kernel writeback, sibling XPC denial, and rejection of
symlink, hardlink, and FIFO changesets without partial writeback. This evidence is limited
to the ad-hoc test bundle and does not establish a shipped or persistent production grant
flow. The earlier timeout and cleanup remain recorded in
[`SEED_BACKEND_RESEARCH.md`](SEED_BACKEND_RESEARCH.md).

The picker was reopened at the user's request on 2026-09-28. The focused interactive XPC
test passed in 99.112 seconds with a newly selected temporary workspace. It rechecked
bookmark use by Kernel, denial of path-only writes from a sibling XPC service, cross-process
stream-relay rejection, safe changeset writeback, and rejection of symlink, hardlink, and
FIFO changesets. This remains test-only evidence from the current host's ad-hoc bundle.

On 2026-09-28 the shared fixed executor was added in
[`KernelWorkspacePythonExecutor.swift`](../khaos/macos/KernelWorkspacePythonExecutor.swift)
and its bounded Python bridge in
[`workspace_xpc_bridge.py`](../khaos/kernel/workspace_xpc_bridge.py). The focused
interactive XPC test passed in 145.998 seconds with a newly selected temporary
workspace. It exercised scoped read, denied direct live-workspace write, validated
Kernel writeback, unsafe changeset rejection, and outside-canary preservation through
the shared executor. The executor composition and signed service remain test-only;
this does not prove Candidate digest admission, approval, or durable grant lifecycle.
After closing the spawned bridge's stdin descriptor exactly once, a final interactive
rerun passed in 334.921 seconds with the same adversarial checks. The canonical suite
passed all 181 tests in 332.225 seconds on 2026-09-28.

A focused real XPC operation also passed on 2026-09-27 with the Runner exercising
`fs.read` and `fs.list`: only the scoped file was readable, the unscoped file was hidden
from ancestor listing and both direct SDK requests were rejected. The canonical 181-test
suite passed in 326.951 seconds with this coverage. Production executor composition remains
unimplemented.

The authenticated Runner path now also rejects a `../sibling-secret.txt` read with
`path_not_readable` before command execution or commit. The focused XPC run passed in
69.088 seconds, and a fresh interactive picker rerun passed in 137.345 seconds with a
user-selected bookmark, sibling-service write denial, and Kernel changeset validation.
The picker app, executor adapter, and signed XPC bundle remain test-only.
The canonical suite passed all 181 tests in 329.005 seconds with this traversal denial.

After the directory-selection helper moved into shared Khaos source, the interactive
XPC test passed on 2026-09-27 in 100.706 seconds. The signed test app exercised that
helper, and the test confirmed the selected bookmark reached Kernel, sibling XPC writes
were denied, valid output was committed, unsafe changesets were rejected, and the exact
workspace path delta matched expectation. Production grant persistence, launcher and
Kernel packaging, and installation integrity remain unimplemented.
The canonical suite on this code state passed all 181 tests in 338.241 seconds.

On 2026-09-27, a fresh interactive run passed in 139.630 seconds after a user
selected the temporary workspace. Before using that bookmark, the app relayed a
valid request-prefix descriptor created by the sandboxed sibling XPC service;
Kernel rejected it as `invalid_request` before parsing, then completed the normal
scoped write and rejected unsafe changesets. The headless build-mode test passed
in 71.439 seconds and asserts the same cross-process relay denial without opening
the picker. Both results apply to the ad-hoc test bundle, not a production Launcher
or Kernel service.

The shared Workspace XPC ABI now carries the bounded Runner IPC v4 `workspace.run`
envelope and a single scoped bookmark in one deadline-bound stream. The service rejects
oversized request lengths and inner/outer request-ID mismatch before reading the bookmark
or launching its executor. The test-only client passes its actual command argv, Runner
source, timeout, and read scope through the authenticated XPC boundary to the existing
`run_workspace_command()` validator. Build-mode XPC passed in 68.598 seconds on
2026-09-27, including the real request-frame, bookmark-stream, Runner-scope, and changeset
attacks. The later focused run also rejected an empty `argv` payload before executor
launch and passed in 68.982 seconds. The canonical suite then passed all 181 tests in
320.241 seconds with the ABI v4 changes. The requested interactive retry reached the picker
helper, but received no selection or cancellation within 300 seconds; it then terminated
the helper and cleaned the temporary fixture. The helper was explicitly brought to the
front, but this run did not establish a user-selected grant or positive Kernel writeback.
Production executor composition is still unimplemented.

The later ABI v4 peer-PID binding passed its focused build-mode XPC test in 71.164
seconds. A user-requested interactive picker reopen reached the foreground helper,
but no selection or cancellation arrived within 300 seconds; the helper and fresh
fixture were cleaned up, so no user-grant or positive writeback evidence was added.

On 2026-09-27 the canonical command `python3 -m unittest discover -s tests -v`
passed all 181 tests in 331.930 seconds on this macOS host. This rechecked the
current Runner, Kernel IPC, Seatbelt, snapshot, changeset validation, commit-race,
and test-only XPC paths together. It does not establish the unshipped Trusted
Launcher, immutable Kernel installation, user-grant persistence, or production
Host composition listed below.

On 2026-09-28 the interactive test probe was extended to exercise cancellation
through the shared `KernelProduction.xpc` executor: a different XPC connection
must be denied, the submitting connection must receive cancellation, the command
descendant must exit, snapshot output must not be committed, and a following
no-change operation must succeed. The focused headless XPC test compiled the probe
and passed in 74.228 seconds; the canonical 181-test suite passed in 328.892
seconds. Two fresh interactive retries passed their APFS/XPC preflight but received
no folder selection. The second left the native picker visible and foregrounded,
then timed out after an extended 1,800-second wait (1,874.365 seconds total) and
cleaned its helper and fixture. Those assertions have not run, so the shared
executor's real cancellation path remains unverified. An earlier attempt stopped
before opening the picker because the APFS probe reported ambiguous image identity;
a later attempt passed that preflight without code changes, and the cause of the
first failure remains undetermined.

On 2026-09-28, the canonical suite passed all 182 tests in 319.729 seconds. Afterward,
the focused App Sandbox bookmark attack was rerun in 1.754 seconds with the probe calling
the shared `KernelWorkspaceRoot.withScopedBookmark()` implementation. It confirms only
that this sandboxed helper cannot consume the tested externally created bookmark without
a user-selected grant; it does not establish the pending interactive XPC cancellation
assertions or production grant flow.

On 2026-09-28, a requested picker reopen again received no selection or cancellation
within 300 seconds. The focused test stopped the helper and removed its temporary fixture;
it added no user-selected-grant or writeback evidence. The subsequent build-mode XPC test
passed in 77.793 seconds after extending the real App Sandbox write-denial probe to the
fixed `KernelProduction` executable, its Python bridge and changeset implementation, and
its bundled interpreter. The sandboxed Host's app-container positive control succeeded;
each protected-file open was denied, file digests stayed unchanged, and deep code-signature
checks passed. This proves denial for those files in the ad-hoc test bundle on this host,
not an immutable production installation. At this point, the canonical suite had not yet
been rerun after this test-only change.

The canonical command was then rerun on this tree and passed all 182 tests in 322.741
seconds on the same macOS host. It re-exercised the real Runner, Seatbelt, snapshot,
changeset-race, XPC, and App Sandbox paths, including the expanded Kernel bundle write
denial probe. This headless suite did not open the interactive Picker and therefore does
not establish a fresh external-workspace grant, Picker scope relinquishment, or the
fixed executor's active-cancellation writeback path.

On 2026-09-28, another user-requested picker reopen confirmed `WorkspaceGrant` was the
foreground process but received no selection or cancellation within 300 seconds. The
focused run ended with `subprocess.TimeoutExpired` after 409.692 seconds and cleaned its
temporary helper and fixture. This adds no user-selected-grant or writeback evidence and
does not replace earlier successful test-only picker evidence.

After the outbound XPC peer-authentication change, the canonical command passed all 184
tests in 375.548 seconds on this host. This default run did not open the Picker; the
real wrong-peer rejection is covered by the focused headless build-mode XPC test above.

## Not established

The prototype does not yet establish the following required properties:

- a shipped Trusted Launcher that alone owns the user picker and workspace grants;
- a distribution-signed, installed Trusted Launcher and Kernel service. The current
  locally signed app checks that a direct write-open is denied after Picker scope
  release, but it has no distribution identity or installation protection;
- selected-workspace product evidence for running a persistently activated
  Candidate through `--plugin-run`. The 2026-10-05 user-selected run exercised
  the earlier one-shot package path; it does not verify the current install,
  active-slot lookup, run binding, workspace Picker, and Runner in one product
  session;
- a shipped composition connecting that Launcher and authenticated Kernel service
  to the existing Python Worker. [`KernelWorkspaceServiceMain.swift`](../khaos/macos/KernelWorkspaceServiceMain.swift)
  now fixes that service composition in shared source and has run in a temporary copy
  of the locally signed product app with a test-only driver; it is not an installed,
  distribution-signed service or production Plugin Launcher. [`launcher.py`](../khaos/launcher.py)
  still explicitly assumes a trusted Python caller and must not be exposed directly to
  an untrusted Host;
- production Kernel service identity, protected installation, update, revocation,
  or restart policy. The current local Seed lifecycle has a fixed primary slot,
  digest/scope/generation-bound activation and rollback, and a 30-day expiry,
  but user-owned Application Support state is not protected from a same-UID
  process that can alter both its data and integrity key;
- a Trusted Promoter, multiple slots, general Plugin capability handles,
  Plugin-based Memory/Context/Tools, or a production Plugin platform;
- exclusive write control against other same-user workspace writers;
- a per-command aggregate memory quota or cleanup after simultaneous launcher and
  operating-system failure;
- secret classification, redaction, or approval for sending workspace data to a
  remote model;
- the complete cross-version macOS attack matrix.

In particular, the test XPC service has no App Sandbox entitlement so it can
exercise APFS image setup on this host. It must remain trusted test code and must
not load or execute Host or Plugin code. The prototype's `sandbox-exec` backend
is an experimental macOS enforcement path, not a production platform commitment.

An absent item in the evidence table is not a passing security property. Keep
unsupported or untested behavior explicit until a real enforcement test proves
it.

On 2026-09-28 the current Picker code received one new user-selected temporary
workspace, but its helper exited with `NSPOSIXErrorDomain` code 1 before returning
the evidence report; XPC/Worker processes were observed, but no commit result was
collected. A diagnostic retry added stage labels around the two bookmark operations,
then timed out because no folder was selected. The build-mode probe compiled and
passed; current Picker write denial and external-workspace writeback remain
unverified. The Kernel transfer bookmark was then corrected to use the original
panel URL with `options: []` rather than the normalized URL. The updated build-mode
probe passed in 119.557 seconds; a fresh interactive retry received no selection
within 300 seconds and timed out after 408.694 seconds. This does not invalidate or
extend earlier successful test-bundle runs.

The canonical suite passed all 184 tests in 402.372 seconds on 2026-09-28.
That default run did not open the interactive Picker, so the external
user-selected workspace grant and current Picker write-scope release remain
unverified.

On 2026-09-28, a fresh interactive run of the focused XPC test selected its disposable
workspace and advanced through the Picker read-only-scope check: reopening the input for
write returned `EPERM`/`EACCES`, and the shared `KernelExecution` service committed its
expected output. The run then failed in the separate `KernelProduction` attack group
because macOS returned `EPERM` while issuing the probe's explicit child security-scope
bookmark. This was not an overall test pass. The probe now uses an implicit-scope bookmark
for its one-run XPC transfer, matching the product picker; its build-mode test passed in
109.250 seconds. A subsequent interactive retry received no selection within 300 seconds
and timed out after 408.723 seconds, so the new bookmark form and `KernelProduction`
writeback/cancellation attacks still lack fresh interactive evidence. Separately, a
locally signed product app's fixed no-change smoke passed after external workspace
selection; later `codesign` inspection showed that bundle still had the app-scope
bookmark entitlement, so it does not establish the reduced-entitlement path or replace
the non-empty changeset attack test.

After that run, `TrustedWorkspacePicker` stopped generating an unused explicit
read-only bookmark, and `build_macos_seed.py` removed the product app's
`bookmarks.app-scope` entitlement. The test probe now checks write-open before and after
revoking the panel scope, then sends the original `options: []` bookmark to Kernel. The
updated product-app packaging test passed in 7.195 seconds, and the focused headless XPC
build-mode test passed in 109.402 seconds. Neither opens the Picker. The new package test
now also verifies the builder's signed entitlement set, but the current direct-revocation probe and full
`KernelProduction` unsafe changeset/cancellation sequence still need a fresh selected
run before their runtime behavior is claimed.

## Current-tree rerun after the product Picker smoke

The focused interactive XPC test reached the `WorkspaceGrant` Picker but received no
selection within 300 seconds. It timed out after 419.214 seconds and cleaned up its
helper and fixture; no new Picker write-denial or `KernelProduction` attack evidence was
collected. The canonical headless suite then passed all 185 tests in 384.048 seconds.
That run includes current Seatbelt/APFS and headless XPC tests, but does not replace the
outstanding selected-workspace checks.

## 2026-09-28 product Picker smoke and current headless suite

The test-only `WorkspaceGrant` path was simplified to transfer the original Picker root
bookmark into `KernelProduction`; its fixture and unsafe-path canary now sit relative to
that selected root. The focused headless XPC build-mode test passed in 109.470 seconds,
and the canonical suite passed all 185 tests in 383.060 seconds. Neither opens the
`WorkspaceGrant` Picker.

After those checks, the user selected an external temporary workspace in a fresh local
product bundle built with the reduced entitlement set and confirmed the fixed smoke
displayed `PASS`. The workspace fixture hash remained
`e15de7f2e6c2cfe2e8b4f4aafe7f79ada1b50b1b50a90695d207a22e12b13d1e`. The smoke runs
fixed `/usr/bin/true` through Kernel XPC and the Runner and requires the exact zero-change
commit result. Post-run deep signature verification found added Python `__pycache__`
files inside the signed framework. Fixed isolated Python launches now pass `-B`; the
executor also passes `PYTHONDONTWRITEBYTECODE=1` for non-isolated descendants. The
package test checks nested imports and post-run signature validity. The fix is not yet
covered by a fresh interactive Picker run. The product smoke does not exercise the
`WorkspaceGrant` Picker write-denial probe, non-empty changeset commit,
symlink/hardlink/FIFO rejection, or cancellation.
The updated helper's interactive attempt subsequently opened its Picker but received no
selection within 300 seconds; it timed out after 408.852 seconds and cleaned up its
fixture. The product `PASS` and this helper timeout are separate outcomes, so the
selected-workspace attack assertions remain unverified.

## 2026-09-28 WorkspaceGrant retry after product PASS

The selected-workspace attack test was reopened with a fresh fixture at
/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-xpc-sandbox-xfgwfbv2/user-selected-workspace.
The WorkspaceGrant process was confirmed frontmost, but the Picker received no
selection before its 300-second limit. The focused test ended with
subprocess.TimeoutExpired after 379.907 seconds and removed its temporary fixture.
No Picker-scope write-denial, Kernel commit, unsafe-changeset, or cancellation assertion
ran in this attempt. This is missing user selection, not a security assertion failure;
the separate product app PASS remains limited to the zero-change route described above.

## 2026-09-28 product writeback source update

The current Launcher source now creates one unique marker through the fixed Runner
command and requires the Kernel to report exactly one addition, with no modification
or deletion. The command receives an empty workspace read scope, and its nonzero exit
prevents the commit request. The Picker discloses the file creation before selection.
The focused product package test, real Seatbelt writeback/denial test, headless XPC
build-mode test, and 185-test canonical suite passed on this source state. These
checks do not exercise a selected external workspace in the newly built product app.

The user then reported that the product Picker displayed PASS for the selected path
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-picker-b_oua14q/Workspace`.
Inspection found only the pre-existing `seed-picker-fixture.txt` (SHA-256
`67ba479e325ce715164ee46d8bad6b8a482fc301e656dfbd6d457f08cfbfe26`) and no marker.
Because a successful current-source alert names a committed marker, the observed PASS
cannot be tied to this source without confirming the binary used. Current product
non-empty writeback remains unproven; this is an evidence mismatch, not a failed
security assertion.

A fresh local bundle from the current source was then built and passed the focused
product package/XPC test and `codesign --verify --deep --strict`. Its read-only
`--bootstrap-check` returned `kernel-xpc-peer-authentication=verified` with exit 0,
although it also emitted `sandbox_extension_issue_file_to_process` on stderr. No
workspace request or Picker was used in that check, so this evidence does not resolve
the writeback mismatch above. The warning's cause remains unknown.

## 2026-09-28 fresh real-Seatbelt writeback attacks

Five focused macOS integration tests were rerun on this tree. The safe-output test
proved that a snapshot file can be committed while direct writes to the live
workspace, an outside canary, traversal target, and workspace-parent move are denied.
The disk-image test first established an APFS mount positive control, then showed the
sandboxed command cannot attach that image over a workspace directory; its ordinary
validated output still committed. Separate tests created symlink, hardlink, and FIFO
output candidates alongside otherwise acceptable files; Kernel commit rejected each
whole changeset, leaving the real workspace without partial output and preserving
the canary/baseline.

All five tests passed against the real macOS Seatbelt backend: safe output 3.616s,
APFS mount 5.141s, symlink 3.640s, hardlink 3.683s, FIFO 3.630s. This is fresh
evidence for the shared Python Kernel/Runner path with temporary fixtures. It does
not exercise the newly built product app's user-selected Picker/XPC operation.

The output-metadata attack also passed (3.698s): the Runner could create ordinary
workspace output but OS enforcement denied chmod and `setxattr`; committed file and
directory mode bits stayed at the Kernel's 0600/0700 defaults, with no injected xattr.
Those mode bits do not override inheritable ACLs already configured on the selected
workspace's parent directory.

Two additional real-Seatbelt commit-race tests passed: concurrent replacement of a
target (1.664s) and detaching an already-open parent directory before swap (1.659s).
The first returned `commit_outcome_uncertain` and preserved the attacker-replaced
target bytes and inode; it did not install the staged candidate over the replacement.
The second returned `commit_outcome_uncertain` after Seatbelt denied writes through
the stale directory descriptor; the moved target retained its prior bytes. These
prove the specific synchronized race windows, not global arbitration against every
same-UID writer.

Two process-death tests also passed against the real macOS execution chain. Killing
the launcher (3.828s) terminated the sandbox command and its descendant and discarded
uncommitted snapshot output. Killing the Kernel worker itself (14.125s) returned
`kernel_ipc_failed`, terminated the command group, removed the snapshot and detached
image, and left the real workspace unchanged. These are current-host failure-containment
checks; they do not prove Kernel availability after arbitrary host-level failure.

Network-denial tests also passed under the real Seatbelt profile: IPv4 loopback TCP,
UDP/DNS and HTTP proxy access, including a child process (1.883s); IPv6 loopback
(1.715s); and both stream/datagram access to macOS `mDNSResponder` (1.823s). These
prove denial for the tested local endpoints on this host; they do not claim broad
network-policy portability beyond the supported macOS backend.

The focused headless signed-XPC integration probe also passed on this tree
(1 test, 81.372s) with `KHAOS_RUN_WORKSPACE_GRANT_UI=build`. It exercises the real
macOS peer-signature and service-container identity boundaries plus bounded/relayed
XPC request checks in a temporary signed probe bundle. Build mode does not open the
user Picker and therefore adds no selected-workspace writeback evidence.

## Current execution-chain revalidation (2026-09-28)

The current checkout passed all four tests in `test_macos_xpc_sandbox.py` (94.825s),
including the signed App Sandbox `hdiutil create`/`attach` denial probe and the
headless product/XPC checks. Four focused `test_launcher.py` attacks also passed
(24.913s): a safe snapshot output was committed while direct live-workspace writing
was denied, and symlink, hardlink, and FIFO changesets were rejected without
partial writeback. These results revalidate the shared macOS Kernel/Runner path and
the tested XPC boundaries on this host. They do not prove a non-empty commit through
the newly built product app after an external user-selected Picker grant; that
product-level run remains unverified.

The product-package test now has an opt-in interactive branch controlled by
`KHAOS_RUN_PRODUCT_WRITEBACK_UI=1`. It launches the freshly built, locally signed
`KhaosSeed.app`, prints the disposable folder to select, and waits for the app to
exit after the user dismisses its result alert. A passing run requires exactly one
uniquely named committed file with the expected bytes and 0600 mode, the original
fixture unchanged, no extra workspace entries or links, a valid deep code signature,
and no Python bytecode cache in the signed framework. This branch has not yet been
run with a user-selected workspace; default headless tests do not exercise it.

After that note, the user reported seeing a `PASS` popup during a manual Picker
attempt. The live product process (PID 39952) was still blocked in
`TrustedWorkspacePicker.selectWorkspace()` / `NSOpenPanel.runModal` when sampled,
before the Kernel XPC request. The reported workspace
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-picker-b_oua14q/Workspace`
still contained only its fixture, whose SHA-256 remained
`67ba479e325ce715164ee46d8bad6b8a482fc301e656dfbd6d457f08cfbfe26d`; no
`workspace-kernel-smoke` success record was present for the live process. At
that observation point, the reported popup could not be attributed to this
process and workspace; see the later recheck below.

## 2026-09-28 product output recheck and 2026-09-29 acceptance retry

After the earlier sample, PID 39952 exited. The same selected workspace then
contained the unchanged fixture plus two UUID-named marker files. A later
recheck found two more markers, for four total. Each marker was a 33-byte
regular file with mode `0600` and link count 1; all had SHA-256
`424af2cf1970670c0feb3cb8b563daafe1d9d97d5cd50882db21af67938711e4`. The
fixture still had SHA-256
`67ba479e325ce715164ee46d8bad6b8a482fc301e656dfbd6d457f08cfbfe26d`. The
locally signed app at `/private/tmp/KhaosSeed-writeback-20260928-review.app`
passed `codesign --verify --deep --strict`; its launcher had App Sandbox and
user-selected read/write entitlements, without the app-scope bookmark
entitlement. Its executable contains the fixed write script and the success
alert text. In the current source, that alert is shown only after the Kernel
reply reports exactly one addition and no modifications or deletions. This is
strong product-path evidence for the reported PASS and non-empty writeback.
The user later confirmed that the PASS popup came from the product run against
this selected workspace. The unchanged fixture and four exact marker files tie
the popup to non-empty writeback. Since this workspace accumulated markers
across repeated runs, it is not the fresh-workspace one-marker acceptance test
below. The evidence remains limited to the fixed product smoke, not the
interactive, attack-oriented WorkspaceGrant test.

The opt-in acceptance test was then run with its own temporary self-signed
bundle. Its first selected-workspace attempt exited 1 after 140.526 seconds
without a process result line. A later selected attempt exited 1 after 77.798
seconds and printed `workspace-kernel-smoke=failed code=invalid_workspace_result`;
its temporary workspace was cleaned before the result fields could be inspected.
The Launcher now reports path-free result categories, and the test includes a
bounded metadata-only workspace summary on nonzero exit. The updated headless
product/XPC checks passed in 7.669, 7.619, and 8.452 seconds. A subsequent
opt-in retry opened its Picker but received no selection before the 300-second
limit; the test ended after 307.471 seconds, terminated the app, and cleaned the
temporary workspace. The later product-workspace recheck found only the original
fixture and four expected marker files, with the fixture unchanged and every
marker still single-link and mode `0600`. A subsequent deep signature check of
the same product app passed, and its signed Python framework contained no
`__pycache__` directories. The prior self-signed acceptance attempts either reported
`invalid_workspace_result` or timed out without a selection. The latest run below
passed after the test opened the Picker at its own fresh workspace; the exact
one-marker acceptance is now established for this fixed product smoke.


## 2026-09-29 canonical suite before the product direct-write probe

The canonical `python3 -m unittest discover -s tests -v` run passed all 186 tests
in 388.531 seconds on this macOS host. It exercised the real Seatbelt, APFS snapshot,
changeset race and unsafe-output, XPC identity, bounded IPC, and fail-closed paths.
The default suite did not open an interactive Picker and does not establish the current
product Picker's direct-write denial or the opt-in fresh-workspace acceptance test.


## 2026-09-29 product writeback acceptance and current-tree revalidation

The opt-in product test passed in 153.683 seconds after the app opened its Picker at
the test's fresh workspace and the user confirmed the selection. Its path-free diagnostic
reported `workspace-kernel-smoke=passed`; after the alert was dismissed, the test found
exactly the fixture and one marker, verified the expected marker content, mode `0600`,
single link, unchanged fixture digest, deep bundle signature, and no Python bytecode cache
inside the signed framework. The warning `sandbox_extension_issue_file_to_process ...
(Operation not permitted)` also appeared during launch; the test passed, but the warning's
source and cause remain unclassified. The product still runs fixed Runner source, and this
acceptance does not test direct Picker-write denial or arbitrary Plugin admission.

After this Swift and test-harness change, the canonical `python3 -m unittest discover
-s tests -v` suite passed all 186 tests in 365.245 seconds on this macOS host. The suite
did not open a Picker; the selected-workspace evidence is the separate opt-in run above.
After the direct-write probe change, the focused package test and opt-in interactive
product acceptance above passed; the canonical suite also passed all 186 tests in
384.191 seconds on this macOS host.

## 2026-09-29 product-bundle XPC attack probe

The product package test now has a headless mode that compiles a test-only driver,
places it in a temporary copy of the product app, and checks that its signature still
matches the product XPC caller requirement. The packaged `KernelProduction.xpc` is
unchanged. The latest headless preflight passed in 10.766 seconds and received the
real service's authenticated idle-cancellation response. This does not run a
workspace operation.

The interactive mode reuses the existing production-executor attack requests. Its
first selected run received the expected one-file Kernel result, but the sandboxed
test driver could not read the committed file after it had released Picker scope;
the independent filesystem assertions were moved to the unconfined test parent. A
later selected run returned `EPERM`; source inspection pointed to process discovery
inside App Sandbox. The driver now leaves process observation to the external parent,
which waits for the exact randomized `/bin/sleep` child before signaling cancellation.
After one historical 600-second no-selection attempt, the current interactive probe
passed in 135.293 seconds on 2026-09-29. The test parent verified one safe commit,
direct-write denial, rejection of symlink/hardlink/special-file changesets without
partial writeback, connection-bound cancellation, descendant termination, no
cancelled writeback, service recovery, unchanged canary, and deep bundle signature.
The probe uses a test-only driver in a temporary copy of the product app and leaves
`KernelProduction.xpc` unchanged; it does not prove production Candidate admission
or arbitrary Plugin execution through the product Launcher.

## 2026-09-29 workspace commit race replay

`python3 -m unittest discover -s tests -p test_workspace_changes.py -v` passed all
40 tests in 70.161 seconds on this macOS host. The run covered concurrent
cross-process file replacement and in-place edits, destination races during file and
directory deletion, workspace-root and parent-directory detachment during swaps,
symlink replacement, hardlink and special-file rejection, and a real nested APFS
mount introduced after snapshot creation. The tests preserve racing replacement
data or reject the commit when identity changes; they do not claim an exclusive lock
against arbitrary same-UID writers or transactional multi-file writeback. Several
precise race windows are synchronized by test hooks around the real filesystem
operations; the separate cross-process probes use an independent writer process.

After these test and documentation changes, the canonical
`python3 -m unittest discover -s tests -v` suite passed all 186 tests in 366.288
seconds on this macOS host. It does not open the Picker or exercise the new
interactive product-bundle attack path.

## 2026-09-29 source digest-bound XPC v5

Native Workspace XPC now carries `runner_source_sha256`, the lowercase SHA-256 of
the Runner source's UTF-8 bytes. The Swift Kernel parser and the separate Python
bridge both verify the binding. A headless attack against the real signed
`KernelProduction.xpc` was rejected as `invalid_request` before bookmark handling.
A selected-workspace product-bundle XPC attack then passed with a matching digest
and exercised writeback, direct-write denial, unsafe changeset rejection, cancellation,
and recovery. The test used a test-only driver in a temporary product copy; the normal
Launcher still submits only its built-in source. This field proves content integrity,
not user approval, Manifest admission, or a capability grant.

The subsequent normal Launcher writeback test opened its Picker but received no
selection within 300 seconds; it timed out after 308.598 seconds and cleaned its
fixture. The earlier user-reported PASS and marker workspace predate ABI v5, so they
do not establish a selected-workspace run through the current Launcher. The user later
reported that the repaired Picker displayed `PASS`; this UI observation could not be
correlated with the timed-out test's fresh fixture or bundle identity, so the automated
v5 selected-workspace result remains unverified.

The canonical `python3 -m unittest discover -s tests -v` suite passed all 188 tests
in 365.615 seconds after the ABI v5 change. It does not open the Picker and does not
resolve the normal Launcher's selected-workspace success gap.
After the subsequent Launch Services visibility check, the user again reported seeing
a `PASS` popup. The current run still had no selected-workspace or success diagnostic
and its fresh fixture contained no marker before cleanup; this observation does not
close the v5 selected-workspace evidence gap.

The later 2026-09-29 acceptance-bundle run did complete: after the user selected the
fresh workspace and saw `PASS`, the opt-in test exited 0 in 103.483 seconds. Its
assertions bind that selection to ordered real-OS checks: fixture open denied before
selection, allowed while the Picker scope is active, denied after scope release, then
Kernel writeback and direct-write denial. It also verified unchanged fixture bytes,
exactly one Kernel-created marker with mode `0600` and one link, and strict deep bundle
signature validity before temporary test cleanup. This closes the acceptance-path
selected-read/writeback evidence gap for this build and host. It does not establish
production grant policy, production app identity, Candidate admission, user approval,
or the full production Harness boundary.

## 2026-09-29 XPC JSON nesting bound

Before Foundation parses a Workspace XPC body, the Swift parser now rejects structural
nesting deeper than eight levels. The current envelope needs at most three; braces and
brackets inside JSON strings are ignored by the pre-scan. A real signed-product request
without a bookmark is rejected as `invalid_request`, and the same service subsequently
answers an idle cancellation. The focused product test passed with UI flags unset in
10.429 seconds; the canonical 193-test suite passed in 394.905 seconds. This bounds
one parser input path; it does not prove Candidate admission or user authorization.

## 2026-09-29 added-file post-clone replacement race

`_install_staged_file` used to record the destination inode immediately after the APFS
clone, before checking candidate bytes. A real Broker/Seatbelt attack test replaced the
new destination from an independent process with a same-size regular file during that
window; failed validation then deleted the competing file. The committer now records
cleanup identity only after the named inode passes content and path-binding checks, so a
different-content replacement is preserved and the operation fails as
`commit_outcome_uncertain`. The focused real-Seatbelt Broker attack and five APFS
new-file race/metadata tests pass. Same-UID global workspace write exclusion remains
unimplemented; these checks cover the synchronized race window only.
The canonical suite subsequently passed all 189 tests in 366.991 seconds on this
macOS host; it does not open the interactive Picker.

## 2026-09-29 prepared replacement cleanup race

A real Broker/Seatbelt test exposed the matching failure path for modified files:
an independent same-UID process replaced the prepared temporary pathname just
before validation, and preflight cleanup blindly unlinked the competing inode.
Cleanup now atomically exchanges that path with a separately scoped sentinel and
removes it only when the displaced file still has the inode recorded at creation.
A mismatch is restored and reported as `commit_outcome_uncertain`; the competing
file remains at the temporary path. The exact-path sentinel is included in the
commit child's Seatbelt write scope. The new attack test, workspace-change tests,
Seatbelt tests, and related Broker attacks passed together (81 tests, 113.807
seconds). The canonical `python3 -m unittest discover -s tests -v` suite then passed
all 190 tests in 368.974 seconds; it does not open the interactive Picker. This closes only
the synchronized preflight cleanup race; it does not grant exclusive write
authority against arbitrary same-UID processes.

## 2026-09-29 prepared-file cleanup identity-check race

Cleanup previously checked a prepared temporary entry with `stat` and then removed it
by pathname, leaving a replacement window. A real Broker/Seatbelt test now synchronizes
an independent same-UID writer after that identity check and before the cleanup
sentinel exchange. The committer exchanges the entry with its exact scoped sentinel,
checks the displaced device/inode against the descriptor identity, restores a mismatch,
and reports `commit_outcome_uncertain`. The test confirms that the original workspace
file is unchanged and the competing temporary inode and contents survive. Cleanup also
revalidates the parent-directory binding. This proves only the synchronized pre-exchange
window on the tested macOS host; it does not establish global same-UID write exclusion
or a multi-file transaction. If the parent binding changes or atomic swap is unavailable,
the prepared entry is retained and the result is `commit_outcome_uncertain`; callers must
inspect the workspace before retrying. `test_commit_child_preserves_prepared_cleanup_replacement_race`
exercises the cross-process replacement under the real Seatbelt commit child;
`test_atomic_swap_failure_fails_closed` and the parent-detachment workspace-change tests
exercise the retained-entry fail-closed outcome. The canonical suite passed all 192 tests
in 384.108 seconds on this host; it does not exercise the interactive Picker.

## 2026-09-29 Runner Mach service lookup denial

`test_seatbelt_allows_only_peer_socket_and_still_denies_loopback` resolves the active
`com.apple.coreservices.launchservicesd` Mach service from the unsandboxed test process,
then attempts the same `bootstrap_look_up` from a Runner-shaped Python process under the
real Seatbelt profile. The host lookup succeeds; the sandboxed lookup returns
`BOOTSTRAP_NOT_PRIVILEGED` (1100). The Runner still completes its peer-PID check through
the one allowed Unix socket, while loopback and an unrelated Unix socket remain denied.
`python3 -m unittest discover -s tests -p test_peer_identity.py -v` passed all five tests
in 0.310 seconds on this macOS host. This demonstrates generic Mach service lookup denial
for the Runner profile; signed-XPC peer-identity rejection remains a separate check.

## 2026-09-29 Kernel installation bundle exclusion

The Worker previously compared the selected workspace only with its Python package
root. In the signed app, that root is `KernelProduction.xpc/Contents/Resources`, so
a workspace under the sibling `Contents/MacOS` directory could pass the overlap
check and let the trusted committer write into the Kernel bundle. The Worker now
protects the package root and every enclosing `.xpc` and `.app` bundle. A real
subprocess integration test places a copied Kernel package in both standalone XPC
and nested app layouts. It requests a fixed command that would commit a marker into
the sibling `Contents/MacOS` workspace; both requests return `workspace_rejected`
and leave the marker absent. This proves the current path check rejects those
workspace roots before Runner execution. It does not make the development or
product installation immutable against unconfined same-user processes.

## 2026-09-29 new-file temporary-path replacement during writeback

A real Seatbelt commit-child attack replaced the new-file temporary pathname with
an independent same-UID writer's file after the committer opened it and before it
cloned the validated output. The old success cleanup unlinked that pathname without
checking its identity; the first attack run passed the commit and deleted the
competing inode.

The committer now pins the temporary file's device/inode from its open descriptor
and removes it through a separately scoped same-directory sentinel exchange. A
mismatch is restored, the competing file is retained, and the result is
`commit_outcome_uncertain`. The descriptor-backed clone may already have installed
the candidate at the destination; post-clone failure does not attempt pathname
rollback. The test uses an external writer and the real macOS Seatbelt commit child;
it verifies the preserved inode and bytes, candidate contents, and response code.
This covers the synchronized replacement window exercised by the test; the commit
lock still does not exclude arbitrary same-UID writers globally.

## 2026-09-29 new-file clone through a detached parent descriptor

A real Seatbelt Broker test synchronizes an independent same-UID process to rename
the destination parent after the commit child opens it and immediately before the
descriptor-backed APFS clone. The test captures the clone's OS error through the
attacker process and accepts only `EPERM` or `EACCES`; the candidate destination is
absent both in the moved directory and at the replacement workspace path. This
proves the tested Seatbelt path denies that stale-descriptor create attempt. It does
not exclude arbitrary same-UID workspace races or guarantee cleanup after an
attacker moves a directory outside the authorized root.

## 2026-09-29 displaced-baseline backup replacement during cleanup

A real Seatbelt Broker attack replaced the old-file backup after its baseline
identity and content had been checked but before the committer's pathname `unlink`.
The old path-based cleanup deleted the independent writer's inode and returned
success. Cleanup now uses the shared atomic sentinel exchange and validates the
displaced baseline again; the race test returns `commit_outcome_uncertain`, retains
the competing inode and bytes, and leaves the validated candidate at the target.
This closes the synchronized replacement window exercised by the test, not global
write exclusion against arbitrary same-UID writers.

## 2026-09-30 selected product-bundle XPC execution

The interactive product-bundle XPC attack test passed in 180.343 seconds after a
user-selected disposable workspace. A test-only driver occupied the Launcher slot
inside a temporary signed app copy; the signed `KernelProduction.xpc`, caller
requirement, Python executor, Worker, Runner, Seatbelt policy, snapshot, and trusted
changeset commit path were the current product sources. The test asserted a safe
writeback, direct app-write denial after Picker-scope release, symlink and
special-file changeset rejection, hardlink rejection or OS denial, connection-bound
cancellation, descendant cleanup, no cancelled writeback, and successful recovery.
The external test parent checked exact workspace contents, the unchanged sibling
canary, the signed Python framework, and the deep bundle signature.

This is selected-workspace execution evidence for the product Kernel service on
this host. Replacing the Launcher with a test driver means it does not establish
Candidate/Manifest admission, user approval, arbitrary Plugin execution through
the normal Launcher, or installation integrity against unconfined same-UID
processes. The normal Launcher still submits its fixed Runner source.

## 2026-09-30 product XPC concurrent live-workspace swap denial

A follow-up real product XPC run completed with exit code 0 in 509.509 seconds
after a user-selected disposable workspace. Its test-only Runner attempted
`renameatx_np(RENAME_SWAP)` against two live workspace files while another Runner
thread submitted the trusted Kernel commit. The Runner failed on a successful swap,
any error other than `EPERM` or `EACCES`, a failed commit, or zero attempts. Passing
the test therefore exercises OS denial of the concurrent live-path replacement
under the product service's sandbox, alongside the prior checks documented above.
The external parent also verified exact workspace contents, link counts and output
mode, the sibling-canary digest, the deep app signature, and no signed Python
framework cache writes. As above, a test-only Launcher replacement limits this
evidence to the current product Kernel service and host; it does not establish
normal Candidate/Manifest admission or protection against unconfined same-UID
processes.

## 2026-09-30 normal product Launcher selected-workspace writeback

The opt-in selected-workspace acceptance test passed in 95.427 seconds with exit
code 0 using the normal locally signed Seed app Launcher. It proved read denial
before selection and after releasing Picker scope, one validated Kernel marker
writeback, and direct Launcher write denial after that scope release. The external
test parent checked the unchanged fixture digest/link count, exact workspace entry
set, marker content/mode/link count, deep signature, and absence of signed Python
framework cache writes. This verifies the fixed product smoke on this host; it does
not establish arbitrary Plugin execution, Candidate/Manifest admission, user
activation approval, distribution signing, or installation protection.

## 2026-09-30 product XPC exact read-scope check

The interactive product XPC attack test passed in 293.018 seconds after a fresh
user-selected workspace. Its test-only Runner successfully read the one file in
`workspace_read_scope`, then attempted to read an existing sibling file and
required the real Kernel to return `path_not_readable`. The test then completed
the normal one-file Kernel commit, direct app-write denial after Picker-scope
release, unsafe symlink/special-file/hardlink checks, connection-bound active
cancellation, descendant termination, no cancelled writeback, and a healthy
recovery request. The test parent verified exact workspace contents, the sibling
canary, and the deep product signature.

This run uses the signed product `KernelProduction.xpc` with a test-only
Launcher replacement. The harness now launches that bundle through Launch
Services, matching the normal product acceptance path; the external parent uses
`SIGSTOP`/`SIGCONT` only to synchronize cancellation with observation of the
randomized descendant. The XPC cancellation itself remains on the submitting
authenticated connection. This proves the tested exact read scope for the
current Kernel service on this host; it does not prove arbitrary Plugin
admission, Candidate/Manifest approval, or behavior on other macOS releases.

## 2026-09-30 product XPC directory-list scope

A follow-up interactive run passed in 250.479 seconds. In the same authenticated
Product XPC request as the content-read checks, the Runner listed the workspace
root while its read scope contained only `production-input.txt`. The Kernel
returned that one entry and hid the existing `production-hardlink-source.txt`
name. A direct `fs.list` of that sibling was denied with `path_not_listable`.
The test would fail before `process.exec` and commit if the listing leaked an
entry or the direct query returned another result.

The same run passed the existing OS-enforced writeback, direct-write denial,
unsafe changeset, hardlink, cancellation, descendant cleanup, recovery, and
bundle-signature assertions. This closes the directory-name disclosure gap for
the tested scope path; it still uses test-only Runner source and does not prove
production Plugin admission or Manifest/user approval.

After adding this check, the canonical `python3 -m unittest discover -s tests
-v` suite passed all 207 tests in 393.411 seconds. The default suite does not
open the Picker; the scope evidence above is from the separate interactive run.

## 2026-09-30 fixed product Launcher read/list acceptance attempt

The current fixed product Runner requests a one-file read scope only when the
trusted Launcher is started in `--acceptance-workspace` mode. Before process
execution and commit, its source requires the expected fixture bytes, a filtered
root listing containing only that fixture, and Kernel denials for reading and
listing an existing sibling. An ordinary no-argument launch sends an empty read
scope and checks that fixture reads and root listing are denied.

The signed product package/service test passed headlessly (1 test, 14.968
seconds). Its interactive acceptance timed out after 300 seconds before
`workspace-selected`; diagnostics contained only `preselection-read=denied` and
`picker-requested`. The fresh workspace had its two input fixtures and no marker.
No Runner file operation, Kernel commit, or post-selection signature check ran.
The separate Product XPC attack above demonstrates the Kernel behavior using
test-only source, but does not prove this normal-Launcher integration.
The canonical headless suite passed 207 tests in 403.161 seconds after this
source update; it does not open the Picker or execute this product path.

After reopening the Picker, the user selected the reported
`khaos-seed-app-3mfj1nf_` workspace and saw `PASS`. The current Launcher source
shows success only after scoped fixture read/list, sibling read/list denial,
post-scope OS denial, Kernel writeback, and direct-write denial. This is positive
user-observed execution evidence for those Launcher success gates. The temporary
app/workspace and app process were removed before local inspection, so no exact
bundle digest or test-parent signature result remains. This is separate from the
`m3629ih1` run, which timed out before selection.

## 2026-09-30 Runner cannot inject filesystem scopes

Raw Runner IPC attacks tried to attach `workspace_read_scope` to `fs.read` and
`fs.list`, and `workspace_write_scope` to `fs.write`. Broker-level tests require
`invalid_request` for every extra field. The same attacks from isolated macOS
Seatbelt Runner processes require `runner_failed` before the fixed command can
create its marker; the workspace secret remains unchanged. Both Broker and real
Seatbelt attacks passed, and the canonical headless suite passed all 209 tests in
406.525 seconds. This proves the tested Runner-to-Broker boundary on this host; it
does not independently attest a specific signed Launcher build, Candidate
admission, or user-approved capability grants.

## 2026-09-30 product Launcher scoped `fs.write` attempt

The signed product Launcher now gives its fixed Runner one generated marker
path in `workspace_write_scope`. The Runner source writes that file through
Kernel `fs.write`, attempts to write the existing unscoped sibling fixture and
requires `path_not_writable`, then runs the fixed command and requests the
validated Kernel commit. The command no longer creates the marker itself.

The focused signed-app build, bootstrap, and peer-authentication test passed
(1 test, 24.556 seconds), and the existing real macOS Seatbelt test for scoped
`fs.write` plus direct-workspace denial passed (1 test, 3.535 seconds). The
opt-in product acceptance opened a fresh Picker for
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-4iah6xev/user-selected-writeback-workspace`,
but received no selection within its 300-second window. At timeout the workspace
still contained only the two input fixtures and diagnostics stopped at
`picker-requested`; Runner execution, `fs.write`, Kernel commit, and signature
verification did not run. The signed product path for a non-empty write scope
therefore remains unverified. This timeout is separate from the earlier user-
observed `PASS` for the previous fixed one-file shell-write smoke and does not
invalidate the lower-level Seatbelt evidence. After this source update, the
canonical `python3 -m unittest discover -s tests -v` suite passed all 212 tests
in 428.374 seconds. The default suite does not open the Picker, so it adds no
selected-workspace evidence for this new product `fs.write` path. After a small
cleanup removed unused shell arguments, the focused signed-app build and
peer-authentication test passed again (1 test, 14.253 seconds). A second opt-in
acceptance then opened a fresh Picker for
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-mc3x9hi0/user-selected-writeback-workspace`;
it also timed out after 300 seconds with only the two fixtures, no marker, and
diagnostics ending at `picker-requested`. It did not execute the new write path.

## 2026-09-30 Native Workspace XPC scope validation

The native request parser now validates each read/write scope before it reads the
bookmark: relative path shape, component count, duplicate paths, path count, and
the 4 KiB per-list byte budget. This mirrors the independent Python scope parser;
exact UTF-8 byte keys avoid changing its path comparison semantics.

The signed-product service test sent valid-digest requests with no bookmark for
traversal, absolute, empty, NUL, empty-component, dot-component, over-depth,
duplicate, over-count, and over-budget scopes. Each had to return
`invalid_request` before bookmark handling, after which the service had to answer
an idle cancellation. The expanded focused test passed (1 test, 14.303 seconds).
This proves early rejection in the tested signed XPC service on this host; it
does not test workspace access or grant any scope. The
first canonical suite run had one unrelated `test_commit_child_preserves_prepared_file_replacement_race`
error; that test passed alone on rerun, and a following canonical suite passed
all 212 tests in 428.802 seconds. After expanding the native scope attacks to
cover NUL, empty paths, path-count overflow, and byte-budget overflow, the
canonical suite passed all 212 tests in 426.185 seconds.

## 2026-09-30 normal Product Launcher Picker verification retry

The opt-in signed-product acceptance printed a fresh workspace path ending in
`khaos-seed-app-ebiza556/user-selected-writeback-workspace`. No selection reached
the process in 300 seconds; it exited after 312.038 seconds with diagnostics only
`preselection-read=denied` and `picker-requested`. The workspace had its two input
fixtures and no marker, so no Runner scope check, Kernel writeback, or post-run
signature verification ran. The user-reported `PASS` was for a different older
temporary path (`khaos-seed-app-3mfj1nf_`), and is retained as separate user
observation. This is an interaction timeout, not a failed sandbox/commit assertion;
the user-observed PASS recorded above is a separate run and cannot be assigned to
this workspace or its bundle.

## 2026-09-30 Picker navigation prompt and current-source retry

The UI acceptance test now prints Command-Shift-G navigation instructions with
the exact disposable workspace path; its timeout regression asserts both pieces
of guidance and passes (1 test, 0.002 seconds). A new signed Product Launcher
run used `khaos-seed-app-rx5bn0nu/user-selected-writeback-workspace`. The
frontmost application was `KhaosSeed`, but no selection reached the test within
300 seconds. At timeout (312.321 seconds), diagnostics still ended at
`preselection-read=denied` and `picker-requested`; the workspace contained only
the original 41-byte and 27-byte fixtures and no marker. No scoped Runner
read/list/write, Kernel commit, post-scope denial, or signature assertion ran.
The app, temporary bundle, and workspace were cleaned by the test. This is a
missing interactive selection, not an enforcement failure. The user-reported
PASS for the separate `3mfj1nf_` run remains recorded independently and does not
close this run.

## 2026-10-01 canonical suite

The current worktree passed `python3 -m unittest discover -s tests -v`: all 212
tests passed in 437.331 seconds, including real macOS Seatbelt attacks, signed
Product XPC peer/request checks, and the Picker timeout-prompt regression. The
suite is headless with respect to workspace selection and does not independently
verify the user-reported Product Launcher PASS or its post-alert signature check.

## 2026-10-01 focused real-macOS boundary revalidation

Eight targeted tests passed on the current host:
[`test_runner_cannot_bypass_kernel_authority`](../tests/test_launcher.py),
[`test_commit_child_cannot_unlink_after_parent_detaches`](../tests/test_broker.py),
[`test_commit_child_preserves_displaced_backup_replacement_before_unlink`](../tests/test_broker.py),
[`test_kernel_chain_rejects_unix_socket_output_before_partial_writeback`](../tests/test_launcher.py),
[`test_kernel_rejects_new_symlink_from_sandbox_output`](../tests/test_launcher.py),
[`test_kernel_rejects_hardlinked_files_from_sandbox_output`](../tests/test_launcher.py),
[`test_kernel_chain_blocks_disk_image_mount_and_commits_safe_output`](../tests/test_launcher.py),
and [`test_kernel_rejects_fifo_from_sandbox_output_without_partial_writeback`](../tests/test_launcher.py).
These exercise the Runner's real Seatbelt denial of live-workspace mutation,
Kernel commit behavior, and rejection of unsafe snapshot output. They do not
close the separately documented check-to-unlink race against an unconfined
same-UID writer, and they do not establish Candidate admission or activation
approval.

Follow-up runs on the same host passed the three chain-critical attacks again:
`test_runner_cannot_bypass_kernel_authority` (3.563 seconds),
`test_kernel_chain_rejects_unix_socket_output_before_partial_writeback`
(3.558 seconds), and
`test_commit_child_cannot_unlink_after_parent_detaches` (1.630 seconds).
The first requires live-workspace unlink, rename, clone, and swap attempts from
the Runner and command to receive OS denial while validated Kernel output is
committed. The second rejects an actual socket changeset before any sibling
file is written. The third confirms Seatbelt denies a commit child's stale-dirfd
unlink after an independent process detaches the parent. The check-to-unlink
race against an unconfined same-UID writer remains a separate unresolved case.

## 2026-10-01 macOS workspace ACL inheritance

Apple documents that macOS copies inheritable ACEs from a parent directory onto
new files and directories. A native APFS probe and the Kernel commit test confirm
that behavior here: a selected workspace root's ACL remains unchanged, and new
committed entries inherit its `file_inherit` / `directory_inherit` ACEs. The test
also attaches different ACLs to the untrusted snapshot directory and file; those
Runner ACEs are discarded. The focused ACL set passed all four tests in 6.599
seconds, including the existing tests that prove Runner ACLs are dropped when
the destination has no inheritable ACEs. The canonical suite then passed all 213
tests in 423.624 seconds.

This is intentional OS policy preservation. `0600` and `0700` describe mode bits;
they do not override grants in an inherited ACL. Khaos does not silently rewrite
the ACL the user selected for the workspace. See Apple's
[ACL permission inheritance documentation](https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/FileSystemProgrammingGuide/FileSystemDetails/FileSystemDetails.html).

## 2026-10-01 live-workspace root descriptor isolation

The trusted launcher passes the selected workspace root FD to the Kernel Worker
so snapshot creation and commit can stay bound to the opened directory inode. A
real Seatbelt test pins that FD at number 200, then requires both Plugin source
in the Runner and the fixed command to observe `EBADF`. The Runner attempts a
live-workspace `openat` read and create; the command attempts `openat("../...")`
outside the workspace. Both fail before mutation, and the real fixture and
outside canary remain unchanged. The focused test passed in 3.743 seconds. This
proves the descriptor handoff on this host and current process launch path; it
does not prove isolation from an unconfined same-UID process.

## 2026-10-01 Runner authority after Kernel commit

The Kernel Worker sends the commit result before closing the Runner pipes and
waiting for the Runner process to exit. The existing real-Seatbelt end-to-end
write-scope test now keeps the Runner active after that response: a direct write
to the just-committed live file must receive `EPERM` or `EACCES`, and a late SDK
`fs.write` must fail because the Kernel IPC pipe has closed. The final workspace
content remains the validated bytes. The focused test passed again after the
Worker lifecycle fix in 3.728 seconds. A second real-Seatbelt attack has the
Runner spin forever after a successful commit; the Worker kills it after its
bounded wait but still returns the trusted commit result, and the committed file
is present (1 test, 8.698 seconds). After the Worker fix, the full real-Seatbelt
`test_launcher.py` module passed all 31 tests in 125.383 seconds; `test_worker.py`
passed all seven tests in 0.007 seconds. These close the observed post-commit
Runner window for the tested Worker path; they do not establish product-bundle
coverage or exclude an unconfined same-UID process. A subsequent canonical run
passed all 215 tests in 438.268 seconds, including this lifecycle attack; the
default suite remains headless and does not open the Picker.

## 2026-10-01 ordered Product Launcher evidence

The Launcher acceptance path now records an explicit `kernel-commit` result only
after the authenticated XPC response has passed the exact one-added-file, no-modify,
no-delete check. It then records the OS denial for a direct write after Picker
scope release. The interactive test requires the ordered diagnostics from
preselection denial through the final PASS, and independently checks the selected
workspace contents and deep app signature after the alert is dismissed. This adds
traceability to the existing fixed smoke; it does not change the Kernel authority
or authorize arbitrary Plugin code.

Immediately after adding the Launcher diagnostics, the canonical suite passed all
216 tests in 441.830 seconds. Its signed-product test is headless. A separate opt-in run of the exact
current Product Launcher opened a fresh Picker for
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-phav2sls/user-selected-writeback-workspace`.
No folder selection reached the test within 300 seconds; it exited after 312.295
seconds with only `preselection-read=denied` and `picker-requested`. The workspace
contained its two original fixtures, no Kernel marker, and no changeset output.
The app and temporary workspace were cleaned. This run therefore did not exercise
the new ordered diagnostics, Runner scopes, Kernel commit, post-scope write denial,
or parent-side content/signature checks. It is a missing interactive selection,
not an enforcement assertion failure. The user's earlier `PASS` remains a separate
observation and is not evidence for this fresh build.

The ordered-diagnostic gate itself now has a headless regression: one focused
test accepts the complete sequence and rejects both a missing event and reversed
events. That test passed; the timeout regression and signed-product headless XPC
test also passed (1 test each, the product test in 25.116 seconds). None opens the
Picker or adds selected-workspace execution evidence.

The user subsequently confirmed selecting
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-3mfj1nf_/user-selected-writeback-workspace`
and seeing `PASS`. This is separate from the timed-out `phav2sls` run above. The
reported temporary bundle/workspace has since been removed, and no test-parent
exit status or bundle/source digest is available. Record it as user-observed
Launcher evidence only; it does not prove the post-alert content or deep-signature
assertions for the `phav2sls` build.

After that report, the canonical suite passed all 217 tests in 452.195 seconds.
It is headless and does not cover the selected-workspace Launcher path. A fresh
opt-in run built a new signed product app and opened its Picker for
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-od7g0_lr/user-selected-writeback-workspace`.
No selection reached the test within 300 seconds; it exited after 311.939
seconds with only `preselection-read=denied` and `picker-requested`. The
workspace retained its two original fixtures and had no Kernel marker. This run
did not exercise scoped Runner read/list/write, Kernel commit, post-scope OS
denial, or parent-side content/signature checks. It is a missing interactive
selection, not an enforcement assertion failure. The earlier `3mfj1nf_` PASS
remains separate user-observed evidence and is not attributed to this fresh
build.

## 2026-10-01 Product XPC rejects caller-asserted authority

The headless signed-product probe now sends two otherwise valid `workspace.run`
requests to the real `KernelProduction.xpc`: one adds `approval: true`, and one
adds caller-supplied `capabilities` strings. Both carry a matching Runner source
digest but no workspace bookmark. The service must return `invalid_request`
before bookmark handling, then answer a fresh idle-cancellation request. The
focused signed-product test passed (1 test, 14.375 seconds). This proves the
current exact-schema parser rejects these unauthenticated authority claims; it
does not implement or prove Candidate admission, user approval, or a capability
grant model. The first canonical run found a stale hardcoded response in the
timeout-regression fixture; after syncing that fixture and passing the focused
regression, the canonical suite passed all 217 tests in 455.010 seconds.

## 2026-10-01 packaged Runner denied direct live-workspace write

The signed-product package test now runs the packaged Python runtime and Kernel
Worker against a disposable workspace. An unsandboxed host positive control can
open the live fixture with `O_WRONLY`; the packaged Runner then attempts the
same open by absolute path and must receive `EPERM` or `EACCES`. It also must be
unable to write the packaged Kernel changeset module. The fixed command writes
only to the private snapshot, after which the Kernel commits one new file; the
fixture and Kernel digest remain unchanged, and the app bundle passes deep
signature verification. The focused signed-package test passed (1 test,
16.507 seconds). The canonical suite then passed all 217 tests in 440.864
seconds, including this packaged Runner attack. This invokes the packaged
launcher/Worker directly from its embedded Python rather than through the
`KernelProduction.xpc` endpoint; the separate product XPC tests cover that
transport boundary.

## 2026-10-01 packaged Runner denied direct reads and writes outside its Kernel boundary

The signed-product package test now gives the Runner a test-owned `HOME`
canary beside (not inside) the selected workspace. The host confirms it can
read that canary and can open the live fixture for writing. The packaged Runner
must receive `EPERM` or `EACCES` when it tries to read the live fixture, write
the live fixture, read the canary, or write the packaged Kernel changeset
module. The fixed command still writes only to the private snapshot and the
Kernel commits exactly one new file. The parent then verifies that the live
fixture and canary are unchanged, the Kernel module digest is unchanged, and
the signed app passes `codesign --verify --deep --strict`. The focused signed
package test passed (1 test, 14.011 seconds); the canonical suite passed all
217 tests (450.812 seconds).

This is a test-owned canary, not a read attempt against the user's actual home
or secrets. It invokes the packaged launcher and Worker from embedded Python,
not through `KernelProduction.xpc`; it does not prove Candidate admission,
Manifest approval, or arbitrary Plugin execution.

## 2026-10-01 Product XPC Picker timeout and phase diagnostics

A fresh opt-in signed-product XPC run reached the Picker for its disposable
workspace, but no selection arrived within the test's 600-second deadline. The
test exited after 614.180 seconds with only `production-xpc-driver-pid` in its
captured output. The workspace still contained only its two original fixtures;
the test cleaned the temporary product and workspace. No selected-workspace
Runner, read/list, direct-write denial, unsafe changeset, cancellation,
writeback, or parent-side signature assertion ran. This is a missing user
selection, not a security assertion failure.

The timeout initially reported that the cancellation descendant was missing,
even though execution had not left the Picker. The test-only driver now emits
path-free `production-xpc-picker-requested` and
`production-xpc-selection=complete` phase markers. The parent distinguishes a
Picker wait from a post-selection cancellation wait and prints explicit
Command-Shift-G navigation steps. The timeout regression passed (1 test,
0.004 seconds), the signed-product headless test compiled the updated Swift
probe and passed (1 test, 14.134 seconds), and the canonical suite passed all
217 tests (439.790 seconds). The canonical run is headless and does not add
selected-workspace XPC evidence.

## 2026-10-01 Product XPC direct-read denial probes

The signed-product XPC probe now adds three selected-workspace assertions: the
app can read the selected fixture while its Picker scope is active; after releasing
that scope, direct OS opens for both read and write must fail with `EPERM` or
`EACCES`; and the untrusted Runner must receive the same OS denial when it tries
to read the live workspace directly. The Runner proceeds only after that direct
read is denied, then exercises the existing Kernel-scoped read/list, snapshot
execution, changeset validation, commit, and cancellation checks. The interactive
parent also verifies the resulting workspace and signed bundle after the app's
completion alert is dismissed.

The updated Swift probe compiled and passed the signed-product headless test, and
the canonical suite passed all 217 tests (440.185 seconds). A fresh opt-in
`KHAOS_RUN_PRODUCT_XPC_ATTACK_UI=1` run reached the Picker but received no folder
selection within 600 seconds; after 614.303 seconds its only driver output was
`production-xpc-driver-pid` and `production-xpc-picker-requested`. The temporary
app and workspace were cleaned up. Therefore none of the new scope-release or
Runner live-read assertions, nor the selected-workspace XPC commit and signature
checks, ran in this attempt. The separate user-reported PASS was for the ordinary
Product Launcher writeback workspace, not this XPC attack run. No selected-workspace
XPC evidence is added by that report.

## 2026-10-02 user-observed Product Launcher writeback result

The user reported selecting the fresh
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-b1jcjm5v/user-selected-writeback-workspace`
and dismissed the result alert after the prompt asked them to close it. The
reply did not state the displayed result. In the current Launcher source, a
`PASS` alert follows scoped Runner read/list allow/deny checks, Runner `fs.write`
allow/deny checks, one Kernel writeback, and OS denial of direct writes after
the Picker's scope is released. The temporary workspace and matching processes
are no longer present, and no test-parent exit status or bundle digest was
retained. This is a user-reported selection and alert dismissal only; neither
the displayed result nor the post-alert workspace-content and deep-signature
assertions are independently verified for this run.
This does not close the separate Broker-confinement gap or prove Plugin
admission, approval, or a Plugin-bound capability grant.

## 2026-10-03 Product XPC sandbox readiness diagnostic boundary

The Kernel now maps readiness-probe failures to a finite set of path-free
internal stage codes. The authenticated XPC reply carries only those fixed
codes; exception text, OS error text, and local paths remain private. The
production Launcher normalizes every stage code back to `sandbox_unavailable`
and still fails closed. Tests cover the mapping and allowlist, and the signed
headless product test compiles and exercises the updated service without a
Picker. The canonical `python3 -m unittest discover -s tests -v` suite passed
all 247 tests in 459.405 seconds; this remains headless with respect to
workspace selection.

Two earlier selected-workspace product-XPC runs returned generic
`sandbox_unavailable` before the cancellation handshake, so they did not run
Runner, scope-release denial, writeback, or signature assertions. A later
diagnostic build timed out before a workspace selection. The user subsequently
reported selecting `/Users/huangruibang/Applications/khaos-seed-app-l2fgx4wq/user-selected-product-xpc-workspace`
and dismissing the result alert, but the temporary directory, process, and
correlated test output are gone. This UI observation does not establish an
XPC stage code or selected-workspace result. Product XPC execution after
selection remains unproven; do not treat the diagnostic codes or headless
service checks as that evidence.

## 2026-10-03 App Sandbox ancestor denial during snapshot setup

A correlated selected-workspace Product XPC run reached the trusted Python
bridge and returned `sandbox_unavailable_probe_snapshot`. Unified OS logs
showed App Sandbox denying a directory read on `/Users`. A signed, sandboxed
helper then measured the exact condition:
opening `/Users` as a directory returned `EPERM`, while direct opens of its
own temporary source directory and mounted APFS directory succeeded. Both
directories also returned `ATTR_VOL_MOUNTPOINT` and `ATTR_DIR_MOUNTSTATUS`
through their opened descriptors. The helper's real-OS test passed.

The snapshot opener now falls back on macOS only when an ancestor open is
denied: it opens the exact requested directory and requires the kernel's
`F_GETPATH` for that descriptor to equal the already resolved expected path.
Failure remains closed. Existing descriptor, device, mount identity, and
source-root stability checks still apply to the returned descriptor. A unit
regression forces ancestor denial and verifies both the accepted exact path
and rejection of a mismatched descriptor path. A new correlated interactive
run still returned `sandbox_unavailable_probe_snapshot`, while OS logs showed
that the sandbox probe child had already run. Review found that the probe
wrapper also mapped errors thrown from its body, including commit errors, to
the snapshot-creation stage. That mapping is now limited to context entry;
the body-error regression verifies the original error remains distinct. The
observed `/Users` denial is real, but these runs do not establish it as the
cause of the Product XPC failure. Runner and writeback assertions still lack
a passing correlated run.

## 2026-10-04 Interactive XPC test reduction

The duplicate compound Product XPC Picker driver has been removed. It required a
second manual run, a 600-second wait, and external cancellation-child coordination
after the product writeback acceptance already exercised a selected workspace
through the signed Kernel XPC path. The headless signed-product digest, schema,
scope, authority-field, peer-identity, and missing-Broker checks remain. The single
interactive product writeback acceptance still checks scoped read/list and write
operations, Kernel commit, and OS read/write denial after Picker-scope release.
Lower-level real-OS Runner, changeset, and cancellation tests remain in the suite;
they are not evidence for those same attacks through a selected-workspace Product
XPC request. This change removes an interactive test path and adds no security
evidence.
