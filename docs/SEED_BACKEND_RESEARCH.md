# Khaos Seed backend research

## Current scope

The first executable security work consists of a macOS-only Seatbelt capability
probe, a private workspace snapshot copier, bounded command execution, and a changeset
validator and committer. The outer probe child can read a copied workspace and write file
data, create entries, and delete entries inside it, while unscoped outside reads/writes,
symlink escape writes, permission changes, direct child-process spawning, hardlink creation
to an explicitly readable outside canary, and loopback networking fail. The profile grants
read access to only one temporary canary to exercise the hardlink attack. It passes
anonymous request and response pipes to the sandboxed child and completes a bounded startup
ping. The child can request `process.exec` with bounded `argv`; the Broker validates the
arguments and retains the Kernel-selected timeout, cwd, workspace read scope, and OS policy.
The command receives a fixed minimal environment and no inherited descriptors. The child
receives bounded, untrusted output and can then request `workspace.commit`. Neither request
supplies a workspace path, cwd, or environment. In the capability probe, the validated changeset
is applied only to a
disposable test workspace, and both trees are removed when the probe exits. A separate
development path now applies the same validator to an explicitly selected workspace after
starting a one-shot Kernel worker and Seatbelt Runner. This is not a durable production
Broker, Agent-facing Candidate Plugin runtime, or completed Seed.

## 2026-10-02 Read-scope movement policy reuse check

Review of [Anthropic's macOS sandbox profile generator](https://github.com/anthropics/sandbox-runtime/blob/main/src/sandbox/macos-sandbox-utils.ts)
confirmed a relevant OS-policy pattern: a broad writable root can reopen rename/unlink of
paths whose file data remains read-denied, so the profile must apply a later
`file-write-unlink` denial. The project is Apache-2.0, but its README describes a beta
research preview and its package requires Node.js 22.12 or later. Khaos needs one narrow
Python Seatbelt profile and already owns the OS boundary, so this project is a research
reference rather than a runtime dependency. Khaos's local rule generator stays bounded and
is checked by real macOS `os.replace`, `RENAME_SWAP`, ancestor-move, and alias attacks.

The one-shot IPC Runner starts in its private scratch directory, but its Seatbelt profile
denies persistent file writes there and everywhere else except the `/dev/null` sink. It
cannot directly read or write the separate workspace snapshot; only the Broker-launched
`process.exec` child receives the snapshot as a writable root. The Runner can request
bounded `fs.read` and `fs.list` results over its authenticated pipe, but it never receives
the snapshot path or a filesystem descriptor. The SDK returns at most 32 KiB from a
single-link regular file, or at most 128 sorted directory entries whose encoded names total
at most 4 KiB. Symlinks may appear in listings as `symlink`, but their targets are not
returned and symlink path components are not followed. One Runner execution may make at
most 128 read/list requests before `process.exec`. A real Seatbelt test confirms the Runner
cannot directly read or write the snapshot, write to scratch or an adjacent outside canary,
or write a Kernel-like module path that the profile explicitly allows it to read. The
launcher integration test exercises the allowed IPC connection and separate command write
scope. A real Runner attack additionally attempts to overwrite an existing live-workspace file,
create a workspace file, and overwrite an external canary directly; Seatbelt denies all three
and the original contents remain unchanged. The development launcher may also supply up to
128 workspace-relative read roots; the Worker retains that scope and the Broker enforces it on
each `fs.read` and `fs.list`. An empty scope denies both operations and leaves the private
snapshot unreadable to `process.exec`. Directory roots are enforced in the command's OS profile
only when the trusted snapshot baseline identifies them as directories; exact regular-file roots
receive literal read rules. Symlink paths, unsafe ancestors, and missing roots receive no command
read rule. A real Seatbelt launcher test confirms scoped file and directory reads succeed while
unscoped sibling reads and in-scope symlink escapes fail under the OS policy.
The Runner profile grants literal read access to the package directory and exact modules needed
to start the SDK, but not to the checkout root. A real launcher attack confirms the Runner
cannot list the repository root or read `AGENTS.md` directly; package imports and Kernel-mediated
workspace reads still work.

ABI v4 retains the bounded `plugin.start` frame added in v3. It carries at most 10 KiB of
UTF-8 source; `khaos/runner.py` requires `run()` and executes it in the isolated Runner. The
trusted launcher defaults to a small source that requests the fixed command and commit, but
callers may provide untrusted source for development tests. Python's `compile`/`exec` only
loads code; Python explicitly warns that executing untrusted input is unsafe
([Python `exec` documentation](https://docs.python.org/3.13/library/functions.html#exec)).
Seatbelt, peer authentication, bounded IPC, and Kernel validation remain the enforcement
boundary. No third-party plugin framework is used because the required runtime is one entry
point plus the existing IPC SDK, and a framework cannot replace OS enforcement. A targeted
search of the legacy Khaos Python tree found no small Runner matching this boundary; its
plugin lifecycle architecture was not copied.

The legacy [`effective_policy.py`](https://github.com/hrrrb408/Khaos-Agent/blob/03cf742d6b5fb16dc746ceb6443fc4d23a6f1eff/python/khaos/security/effective_policy.py#L607-L635)
compiled `allowed_paths` into in-process root capabilities and documented an empty list as
deny-all. That is a useful fail-closed policy lesson, not an enforcement primitive for this
design; the new Kernel applies its own scope check before descriptor-relative snapshot reads.
No legacy code was copied.

A real launcher integration test now runs caller-supplied source in the isolated Runner. The
source reads an explicitly scoped workspace file through Kernel IPC; an in-workspace file
outside that read scope is denied and hidden by the filtered listing. The source also rejects
traversal, fails to read live/outside files, write a readable Kernel module, or send `SIGKILL`
to its Kernel Worker parent, then asks the Kernel to execute the launcher's fixed command and
commit. The signal attempt must fail with `EPERM`/`EACCES` under the real Runner Seatbelt
profile. This proves only that Plugin Runner code cannot signal this unsandboxed Worker via
that tested path; it does not isolate an untrusted Host from the Worker. This is development
execution only: the source is not a content-addressed Candidate and no Manifest or user
approval is checked. Its Seatbelt profile does not grant same-sandbox signaling; the
separate project-command profile retains that rule.

The macOS Kernel Worker now calls `ptrace(PT_DENY_ATTACH)` before reading its first IPC
request and fails closed if the OS call is unavailable or unsuccessful. Apple XNU's
[ptrace implementation](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/mach_process.c)
sets the target's no-attach flag and sends `SIGSEGV` to a tracer attempting `PT_ATTACHEXC`.
A real launcher attack executes a Runner under Seatbelt against its actual one-shot Kernel
Worker. The fixed command first writes a pending marker to the private snapshot; then Runner
calls `PT_ATTACHEXC`. On the current macOS 27.0 / Darwin 27.0.0 host, the Runner exits from
`SIGSEGV`, the Worker remains alive long enough to report `runner_failed`, and the pending
marker is not committed to the workspace. This protects the tested debugger-attachment path
only; it does not establish Kernel installation integrity, block privileged OS mechanisms, or
replace Seatbelt's resource restrictions.

A separate real launcher test requests control, read, and inspect task ports for the Worker
with `task_for_pid`, `task_read_for_pid`, and `task_inspect_for_pid`. The Runner continues to the
fixed command and commits its marker only when none of these calls returns a task port; the test
completed that path on the current host. Apple XNU's
[task_for_pid implementation](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/vm/vm_unix.c#L3444-L3836)
checks POSIX access and then invokes `mac_proc_check_get_task` before granting the control port;
the [read and inspect syscall definitions](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/syscalls.master#L538-L539)
are separate entry points. This is current-host evidence for this Runner profile and Worker
pairing, not a general claim that `PT_DENY_ATTACH` blocks Mach task ports or that every
task-port flavor is denied.
The symlink writeback attack now uses caller-supplied `plugin.start` source as well: that
source requests the fixed command, then asks `workspace.commit` to apply a newly created
symlink to an outside canary. The trusted Kernel returns `commit_rejected`; the real workspace
gets no link and the outside canary remains unchanged. The same output also contains an
otherwise acceptable regular file, and the Kernel does not partially apply it after finding
the invalid symlink. This ties whole-output validation to the untrusted Plugin entrypoint
across the full Seatbelt and IPC path.

The launcher path now also exercises real `/bin/bash` commands. One command writes an
ordinary file to the private APFS snapshot, attempts direct and `../`-traversal writes to an
outside file and tries to move a live-workspace directory, then completes; Seatbelt denies
the outside writes and move while the trusted Kernel commits the ordinary snapshot output.
A second Bash command creates a
safe file and a symlink to an outside canary; the Kernel rejects the entire untrusted
changeset, leaves the real workspace unchanged, and preserves the canary. This covers the
actual shell execution path as well as the Python-based adversarial probes.
Another end-to-end Bash attack creates two hard-linked snapshot files and verifies their
link count before requesting commit. The Runner command can create the links, but Kernel
changeset validation rejects the whole output and leaves the real workspace unchanged.
An end-to-end Bash attack also creates a FIFO beside an otherwise acceptable file, verifies
the FIFO with `test -p`, and requests `workspace.commit` through the untrusted Runner. The
Kernel rejects the changeset as unsupported and writes neither path to the real workspace.

The real capability-probe child also attempts `open(O_WRONLY)` on the actual
`khaos/kernel/macos_seatbelt.py` source file. Seatbelt denies the open. This proves the
probe profile cannot directly open that Kernel module for writing; it does not
make the installation immutable against the user or other same-UID processes outside the
sandbox. Profile construction also fails closed if an additional writable root overlaps a
runtime read root or any explicitly readable path, so a future scratch-path change cannot
make the Kernel or Runner code tree writable by the Runner.

The runtime read policy now includes the current Python executable, standard library, dynamic
module directory, and the required Framework library paths instead of granting the whole
`sys.prefix` and `sys.base_prefix`. `site-packages` and `dist-packages` are explicit read
denials, including the Homebrew `site-packages` symlink inside the standard-library directory.
A real Seatbelt attack confirms that Runner source cannot read the Python installation's
`pyconfig.h` header or list that symlink target; a companion execution test confirms normal
standard-library imports still work. This evidence is specific to the runtime layout on the
current macOS host.

On macOS, that execution path copies into a capacity-bounded APFS volume mounted separately
from the source workspace. The `process.exec` command and its scratch directory can write
only inside that volume; the IPC Runner has no writable filesystem root except `/dev/null`.
Profiles deny
direct `mount` and `unmount` syscalls. Trusted snapshot and commit code retain distinct
source and snapshot mount identities and validate each tree on its own mount before any
source writeback.

The command supervisor also treats a successful leader exit as a process-tree boundary.
It sends `SIGKILL` to the command process group before returning output to the Broker; a
real Seatbelt test makes a forked child close stdout/stderr, wait for a snapshot marker, and
then try to write after the leader has returned. The test releases that marker only after
the trusted command call returns and confirms the late file is absent from the committed
changeset. This exercises why output remains untrusted until the command group is stopped.
Apple documents `killpg(2)` as signaling the target process group
([Apple `killpg(2)`](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/killpg.2.html));
the Seatbelt profile separately denies `setsid` and `setpgid` to keep command descendants in
that group. A separate real macOS attack now performs a double fork, attempts `setsid`, and
holds the grandchild behind a snapshot write gate while the command leader exits. The test
requires Seatbelt to deny `setsid`; after the supervisor kills the process group, it opens the
gate and verifies that no late file appears before committing the snapshot. This exercises the
combined daemonization and leader-exit path on the current host/profile; it does not establish
global control over unrelated processes outside Khaos.

Separate real Seatbelt command tests now also deny TCP connections to IPv4 and IPv6
loopback listeners, a child process's IPv4 connection, an explicit HTTP proxy connection,
a direct UDP DNS query to a local test listener, and stream/datagram connections to the
macOS `/var/run/mDNSResponder` resolver socket. Each attempted connection fails with
`EPERM` or `EACCES`, and the UDP listener receives no packet. A separate real Seatbelt test
calls `getaddrinfo()` for a unique name and confirms the request fails; it then queries the
unified log for that exact child PID and requires an OS denial of the
`com.apple.system.opendirectoryd.libinfo` resolver lookup, the resolver socket, or outbound
network access. This exercises the current libc/system-resolver path rather than inferring
denial from a negative DNS result. It does not cover every resolver configuration or macOS
release. A separate real Seatbelt test also confirms that a host-only environment sentinel
and a deliberately inheritable anonymous-pipe descriptor do not reach the command process.
A further live attack launches `/usr/bin/sandbox-exec` from inside the command profile with
`(version 1)(allow default)` and asks its child to create an outside canary. The same profile
successfully launches `/usr/bin/true` outside Seatbelt as a syntax/control check; inside the
restricted command, nested `sandbox-exec` fails with `sandbox_apply: Operation not permitted`
and the canary remains absent. The local macOS `sandbox(7)` manual states that new processes
inherit their parent's sandbox. This test exercises that inheritance on the current host and
this Khaos profile; it does not cover privileged service delegation or every macOS release.
A companion attack calls `/usr/lib/libsandbox.dylib:sandbox_init` directly with the same
permissive profile. An unsandboxed control child applies that profile and creates its canary;
the call from a confined command returns `Operation not permitted`, and its outside canary is
absent. The same API attack under the read-only IPC Runner profile also returns
`Operation not permitted` without creating its canary; the unsandboxed control confirms the
permissive profile applies. These tests exercise the direct API on the current host and the
two Khaos profiles, not every macOS release or privileged service delegation.

`commit_snapshot()` stages snapshot file bytes privately, compares the live workspace
to the captured baseline, rejects unsafe or changed output, and applies relative-path
operations without following links. It is a local prototype for the future trusted
commit boundary. The outer Seatbelt probe allows only file data, create, and unlink
operations inside its private snapshot and denies mode changes and child creation. The
nested `process.exec` profile allows the requested command to fork and exec, but confines
writes to the snapshot and a private temporary directory, denies network access, and
blocks session/process-group changes. The command's changes remain inside the snapshot;
the separate `workspace.commit` pipe request routes them through changeset validation into
a disposable fixture. It does not expose a workspace capability to an Agent or modify the
user's workspace. The snapshot object is an in-process data structure, not an authorization
token; the Kernel worker retains its metadata and gives the Runner only the scoped
snapshot path. The development launcher runs the capability probe before it starts that
worker; the probe still writes only to its disposable fixture.

The end-to-end launcher test also gives the sandboxed command the live workspace's nested
directory path and asks it to rename that directory outside the workspace. Seatbelt denies
the rename, and the original directory remains available for the trusted commit. This proves
the Khaos command Runner cannot trigger a parent-directory detach race through its live
workspace write authority; it does not serialize unrelated same-UID writers outside the
sandbox, which remains a documented limitation of the prototype.

`commit_snapshot()` now takes a non-blocking `flock(LOCK_EX)` on the opened source-volume
mountpoint root before scanning the live baseline and applying changes. This makes overlapping
Khaos Kernel committers that use this path fail closed, including committers targeting nested
workspace roots under the same mountpoint; a real subprocess test holds the mountpoint lock
while a nested workspace commit is attempted, verifies rejection without a write, then releases it
and verifies the same changeset can commit. Apple's `flock(2)` contract defines this as an
advisory lock for cooperating processes
([Apple `flock(2)` documentation](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/flock.2.html)).
An unrelated same-UID process can ignore it, so this does not establish exclusive Kernel
authority over the live workspace or close the external-writer gap.

`serve_workspace_commit()` now forks a one-shot trusted commit child and refuses to
fork from a multi-threaded Worker. The child closes inherited descriptors except for
its bounded result pipe. After output staging and live-baseline revalidation, it
fixes the validated changeset and generates its temporary names before applying a
deny-by-default Seatbelt profile. Live writes are limited to exact changeset paths,
temporary entries, and their immediate parent directories; new files and regular
file temporaries receive exact `file-write*` rules, while existing entries and
directory paths receive only exact `file-write-create` / `file-write-unlink` rules.
Recursive workspace writes are not granted. The private staging root remains fully
writable for staging and cleanup. Network is denied and the child cannot fork. The
Worker remains outside that profile so it can supervise the Runner and clean up the
APFS snapshot after the commit child exits. The child returns only a fixed-size
status and change counts.
Write scopes exceeding 8,192 exact paths or 1 MiB of generated allowlist rules are
rejected before the first live mutation so an unusually large changeset cannot
produce an unbounded Seatbelt profile.

A real end-to-end Seatbelt Broker test commits nested additions, a file replacement,
and a deletion under this exact write set, then attempts an extra write to an
unchanged sibling. The changeset succeeds and Seatbelt denies the extra write. A
separate real Seatbelt profile attack confirms that an allowed file and a new file
can be written while both truncating an unchanged sibling and creating an unplanned
sibling are denied by the OS. The Broker-path test also confirms that direct data
writes and mode changes to an existing file being replaced are denied, and the
profile test confirms directory mode changes are denied while child creation and
removal remain available.

A real Broker-path adversarial test coordinates an independent same-UID writer at the
atomic-swap boundary. After the commit child has opened the nested workspace parent
and prepared the replacement, the writer moves that parent outside the workspace. The
commit child then attempts `RENAME_SWAP` through its retained directory descriptor;
Seatbelt denies the operation, the Broker rejects the changeset, and the file carried
outside retains its baseline contents. This closes that tested stale-descriptor write
window in the Khaos commit path. It does not prevent a non-cooperating writer from
changing entries that remain inside the workspace, establish exclusive Kernel write
authority, or turn a sequence of file operations into a multi-file transaction.

The commit profile omits recursive read access to the live workspace. It grants exact
`file-read*` rules to changed source entries and pre-generated temporary entries, plus
`file-read-data` on the directory paths required for descriptor-relative traversal.
Seatbelt's directory data permission also permits enumerating names in those directly
used directories; unlisted sibling file contents and metadata remain denied. A real
Broker-path attack now attempts to read an unchanged sibling and to follow an in-scope
symlink to an outside canary after the profile is applied. Seatbelt denies both reads;
the nested file, empty-directory, and symlink deletions still commit, and the canary stays
unchanged. These reads occur only in the trusted commit child and are not returned over
Runner IPC.

## Bounded workspace reads

The v4 Runner ABI exposes only `fs.read` and `fs.list` before its single `process.exec`.
Both operations are scoped to the retained private snapshot; they do not accept absolute
paths, `.`/`..`, symlink traversal, caller-selected workspace roots, or file descriptors.
The Kernel additionally enforces the launcher's bounded `workspace_read_scope`: empty means
deny-all, directory roots are recursive, and ancestor listings contain only scoped entries.
The same scope is applied to the fixed command's Seatbelt file-read rules, preventing command
stdout from bypassing Runner `fs.read`/`fs.list` limits.
The real Seatbelt command test also attempts to hardlink an unscoped canary into an allowed
directory. It accepts OS denial of link creation and requires the alias read to be denied if
link creation succeeds.
`fs.read` uses descriptor-relative component opens with `O_NOFOLLOW`, verifies the final
entry is a single-link regular file, and reads at most 32 KiB. `fs.list` opens a directory
through the same no-follow component walk, returns at most 128 entries and 4 KiB of encoded
names, sorts them by UTF-8 bytes, and reveals no symlink target. The broker caps these
operations at 128 requests per Runner session. An adversarial Runner integration test reads
a workspace source file only through the Kernel, lists a directory, and confirms traversal,
file-symlink, and directory-symlink reads are rejected while a later command and validated
commit still work. Unit tests also cover oversized files/lists and hard-link rejection.

The trusted snapshot copier and commit scanner also enforce the snapshot-retained tree limits:
100,000 non-root entries, 1 GiB of copied entry bytes, and depth 64 by default. A copy test
sets a one-entry limit and rejects a two-file workspace. Broker-path macOS APFS subtests add
candidate output beyond the retained entry and byte budgets independently and verify
`commit_rejected` before the baseline file or workspace changes. These scanner limits bound
candidate tree processing; they are not a per-command or aggregate process memory quota.

This reuses Python's descriptor-relative `os.open(..., dir_fd=...)` and `O_NOFOLLOW` rather
than adding a filesystem library. Python documents `dir_fd` support and platform availability
for these flags in its [`os` module reference](https://docs.python.org/3.13/library/os.html);
Apple's `open(2)` manual states that `O_NOFOLLOW` fails when the final component is a
symbolic link ([Apple `open(2)`](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/open.2.html)).
The legacy Khaos `SafeWorkspaceFS` was consulted for its dirfd-anchored, no-follow and
single-link invariants; vNext keeps its own implementation and process model.

The data returned by these operations is still untrusted workspace data. This does not
classify files as secret or authorize sending their contents to a remote model. No Agent
Host, model adapter, per-plugin identity, or user capability grant consumes this ABI yet.

## IPC probe

`khaos/ipc.py` implements bounded length-prefixed JSON frames and a nonce-bound `ping`.
`khaos/kernel/broker.py` serves bounded `fs.read`/`fs.list` requests before one
`process.exec`, followed by `workspace.commit`; it is still a one-shot diagnostic session,
not a production capability dispatcher.
The live Seatbelt probe uses anonymous pipes created by `subprocess.Popen(stdin=PIPE,
stdout=PIPE)` as one-way request and response channels. `close_fds=True` closes other
descriptors in the child. The frame parser accepts only correctly directed anonymous
pipe descriptors, caps input at 64 KiB, uses one absolute deadline, and rejects duplicate
JSON keys, non-finite numbers, non-object frames, and oversized lengths. `process.exec`
accepts exactly an `argv` list and rejects extra fields; the Kernel validates the command and
retains timeout, cwd, environment, workspace, and read/write scopes from trusted parent state.
`workspace.commit` accepts an empty payload. Execution and writeback scopes come from trusted
parent state, not the message.

A real Seatbelt Runner failure test requests an authorized command that changes
the private snapshot, then exits without sending `workspace.commit`. The Broker's
commit handler observes pipe EOF and rejects the writeback; after snapshot cleanup,
the selected live workspace retains its original file and has no new output. This
proves the one-shot Broker path discards command output after this Runner failure;
it does not establish Plugin lifecycle recovery or production activation behavior.

The framed IPC deliberately uses pipes instead of an AF_UNIX socket. On this macOS host,
an experiment with a deliberately undersized `recvmsg` control buffer showed that a
truncated `SCM_RIGHTS` message could leave received descriptors open even though Python
did not expose all of them in the ancillary-data result. Anonymous pipes cannot carry
that descriptor-passing side channel.

The Kernel-to-Runner launch now adds a one-time AF_UNIX `SOCK_STREAM` identity handshake.
It carries no application data: the Kernel accepts only the `LOCAL_PEERPID` matching its
live `Popen.pid`, while the Runner checks that its socket peer matches `os.getppid()`. Both
ends close this socket before framed IPC begins, which remains on the existing pipes. Apple's
XNU header defines `SOL_LOCAL` and `LOCAL_PEERPID` in
[`sys/un.h`](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/un.h).
The older Khaos RPC protocol also queried this native option; vNext reuses only the OS
identity primitive, not the legacy RPC architecture.

Seatbelt's `(deny network*)` also blocks AF_UNIX `connect`. The Runner profile therefore
allows `network-outbound` only to the exact socket path inside its private scratch root.
The adversarial test confirms this handshake works under the real profile while another
AF_UNIX listener under the same scratch directory and IPv4 loopback remain unreachable.
The exact-path rule follows a narrow pattern also used by
[Chromium's macOS Seatbelt policy](https://github.com/chromium/chromium/blob/main/sandbox/policy/mac/common.sb);
the Khaos live test, not that policy, is the enforcement evidence. To run the Runner-side
check, its profile grants reads to `kernel/__init__.py` and `kernel/peer_identity.py` only;
the same live test confirms `kernel/worker.py` remains unreadable from the Runner.

The outer diagnostic Seatbelt profile leaves both `process-fork` and `process-exec`
denied by default. It grants `process-exec` only to the exact Python executable and, when
present, its exact Framework runtime executable so the probe can start. The live probe
requires the OS to reject `subprocess.run()` and an in-place `execve("/usr/bin/true", ...)`
attempt with `EPERM`/`EACCES`. This proves the outer probe cannot start child processes or
replace itself with an unrelated executable. The separate broker-launched `process.exec`
command uses a distinct profile and remains diagnostic; it is not an approved production
capability.

Process-group termination needs another boundary before a future sandbox can enable
forking: an experiment with `process-fork` allowed showed that `setsid()` succeeds by
default, allowing a descendant to leave the launcher's process group. The profile now
denies the `SYS_setsid` and `SYS_setpgid` syscalls through `syscall-unix`. Real adversarial
tests verify those calls fail in forked children, that killing a group closes an inherited
pipe, and that the bounded `process.exec` supervisor kills forked descendants on timeout.
The `process.exec` handler accepts one in-flight `process.cancel` control frame on the same
private pipe, bound to the exact active `process.exec` request ID. The Runner SDK can send
this frame while its `process_exec()` call waits for a reply. A mismatched or inactive target
receives `process_not_active`. For a matching target, the Broker acknowledges cancellation
only after the command process group is killed and its direct launcher is reaped, then
returns `process_cancelled` for the original execution. A real Seatbelt Runner SDK test
exercises this exchange while a forked child is poised to write a survivor marker. A delayed
cancel that arrives after the command handler returns is rejected as inactive before the
following `workspace.commit` request. Cancellation remains scoped to this one-shot process
operation; there is no Host-to-Runner cancellation source or general operation lifecycle.

The public one-shot `run_workspace_command()` API also accepts a caller cancellation
predicate. Its trusted launcher sends one `workspace.cancel` frame bound to the active
`workspace.run` request ID over the existing private pipe. The Kernel worker checks it
before the Seatbelt capability probe and passes it through the probe and snapshot builder.
The snapshot builder polls between entries and before each 1 MiB file-copy read. The same
callback now reaches the APFS case-sensitivity query, sparse-bundle creation and attachment,
and volume-identity queries. Cancellable `hdiutil` and `diskutil` commands run in their own
process groups; cancellation sends `SIGTERM`, waits for the tool group to exit, then escalates to
`SIGKILL` if required and reaps it. A live macOS probe showed that the DiskImages helper may
continue an interrupted `hdiutil attach` after its CLI exits: inventory can first contain the
image with an empty `system-entities` list, then later report the device and mounted volume.
Cleanup now waits up to five seconds for the image inventory and expected mountpoint to settle,
detaches any device that appears, and checks both inventory and mountpoint before removing the
backing directory. If the state remains ambiguous, it fails closed and retains the directory.
The real macOS attach-cancellation test passed five consecutive reruns after this change and
verifies that neither the private directory nor an attached image remains. A separate process
test verifies a cancelled OS tool process is reaped. Cancellation during file copy still raises
before exposing the snapshot, so the APFS context detaches and removes its private volume. A
deterministic test cancels after one real file-copy chunk and verifies the
workspace input is unchanged and no snapshot directory remains. A real launcher integration
test triggers caller cancellation after observing a partially copied 768 MiB input inside the
private APFS volume; it verifies `process_cancelled`, byte-for-byte unchanged live input, and no
new snapshot directory left behind. The worker also checks it through the existing process
supervisor while `process.exec` is active. During commit, the
isolated child stages Runner output and validates the live baseline under its Seatbelt
profile, then sends READY before any live-workspace write. The parent polls cancellation
while the child prepares and checks again at READY; only ACCEPT lets the child begin the
commit. The last cancellation state observed before sending ACCEPT is the operation's
cancellation cutoff; a signal arriving after that observation may be treated as too late,
even before the child starts writing. A cancel accepted before the cutoff aborts the child,
discards the snapshot, and returns `process_cancelled`; after the cutoff, the changeset may
complete without rollback of partial writes. A real macOS
Seatbelt integration test triggers cancellation at READY and verifies that the Broker
rejects the commit while the live file remains unchanged. This is still a one-shot
development API, not an Agent Host API, a general operation dispatcher, or a production
lifecycle.

A real macOS failure test also kills the Broker parent after the commit child has
applied Seatbelt and emitted READY but before the parent sends ACCEPT. The decision
pipe reaches EOF, so the child aborts, removes staging, and leaves the live file
unchanged. This proves fail-closed behavior for Worker death before authorization;
death after ACCEPT does not revoke the already-authorized commit or promise rollback.

A separate real macOS failure test sends `SIGKILL` to the process calling
`run_workspace_command()` while `process.exec` is active. The Kernel detects EOF on its
control pipe, terminates the uniquely marked sandbox descendant, and exits without
committing the file already written to the private snapshot. This covers abrupt caller
death in the current one-shot path.

A second real macOS failure test sends `SIGKILL` to the Kernel worker after the sandbox
command starts. The command launcher inherits a duplicate of the existing bounded
launcher-worker pipe. Python's child `preexec_fn` sends a `process_started` frame bound to
the `workspace.run` request ID after `start_new_session` and before executing
`sandbox-exec`, then closes that descriptor so sandboxed code cannot access it. The parent
checks the reported ID against the OS process group. If the Worker dies before `Popen`
returns, the launcher can still kill the group; an exec failure after the notification is
also handled by killing the reported group before returning the Kernel error. On Worker EOF,
the launcher then kills remaining Runner and helper processes in the Worker process group,
and detaches/removes the APFS work image whose temporary-directory prefix contains that
Worker PID. The test confirms that the marked command and its forked descendant disappear,
the uncommitted snapshot file never reaches the live workspace, and the Worker mount and
temporary directory are gone.

Launcher error and timeout cleanup now kills the entire Kernel worker session
after sending `SIGINT`, even when the Worker exits promptly. `SIGINT` targets
only the Worker PID; its forked trusted committer and same-group helpers can
otherwise outlive it. A real process-group test makes the Worker exit from its
`SIGINT` handler while a same-group helper waits to write a marker. Cleanup
kills the helper before that write. This closes the prompt-Worker-exit gap in
the one-shot launcher cleanup path; it does not cover launcher death before
cleanup begins or OS-level cleanup failure.

This uses Python's standard-library `subprocess.Popen`, not a new process-management
dependency. Python documents that `preexec_fn` runs in the child before exec and can deadlock
when the application has other threads; the one-shot Worker currently has one thread, and
this path fails closed if that changes. CPython performs `setsid()` before `preexec_fn` in
the supported interpreter path ([`subprocess` documentation](https://docs.python.org/3.13/library/subprocess.html),
[CPython 3.13.4 process creation](https://github.com/python/cpython/blob/v3.13.4/Modules/_posixsubprocess.c)).
This covers Worker death while the launcher remains alive; it does not cover launcher or OS
death or cleanup-tool failure.

The diagnostic `process.exec` launcher caps argv at 128 arguments and 32 KiB of UTF-8,
wall time at 30 seconds, combined stdout/stderr at 8 KiB, individual files at 512 MiB,
open descriptors at 128 per process, and process count at 1024 per real UID. It also sets
`RLIMIT_CORE` to zero and `RLIMIT_CPU` to `ceil(timeout)+1` CPU seconds per process, in
addition to the wall-clock supervisor. Apple documents `RLIMIT_FSIZE` as a per-file size
cap and `RLIMIT_NPROC` as the simultaneous process count for a user ID in
[`getrlimit(2)`](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/getrlimit.2.html).
XNU defines `RLIMIT_AS` as an address-space limit and `RLIMIT_RSS` as its compatibility
alias in [resource.h](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/resource.h).
These RLIMIT settings do not form a complete per-command resource quota. `RLIMIT_NPROC` is
UID-wide and can be affected by unrelated processes. On the current macOS 27 / Python 3.13
host, a launcher Python process reports 488,746,736 KiB of virtual address space;
`setrlimit` rejects 1 GiB and 64 GiB `RLIMIT_AS` limits, while 1 TiB is accepted. An attempted
1 GiB `RLIMIT_DATA` cap was also rejected. A direct `/bin/bash -c 'ulimit -v 1048576'`
attempt on the same host also fails with `Invalid argument`, so moving this limit setup into a
shell wrapper does not make it usable. This does not provide a useful memory cap for this
launch path, so no per-command memory quota is claimed. These command resource limits are
per process, not aggregate across the process tree.
XNU exposes per-task jetsam limits through `memorystatus_control`, but its command path checks
that the caller is root or has the private `com.apple.private.memorystatus` entitlement before
setting memory limits ([XNU authorization check](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_memorystatus.c#L8516-L8545),
[private entitlement and command definitions](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/kern_memorystatus.h)).
The API addresses a PID's task limit; it does not provide an aggregate command-process-tree
quota. Khaos does not add a root helper or depend on Apple's private entitlement for this
prototype, so it continues to claim no command memory quota.
An additional audit on 2026-09-27 checked the local macOS 26.5 SDK's public `spawn.h`,
`sys/spawn.h`, and `sys/resource.h`: they expose no `posix_spawnattr_t` memory/Jetsam limit
setter. Apple's current XNU `posix_spawn.c` initializes internal active and inactive memory-limit
fields to `-1`, while XNU's subsystem documentation says `launchd` supplies those per-process
values from `JetsamProperties` at spawn and applies them as managed processes change state
([spawn implementation](https://github.com/apple-oss-distributions/xnu/blob/main/libsyscall/wrappers/spawn/posix_spawn.c),
[memorystatus lifecycle](https://github.com/apple-oss-distributions/xnu/blob/main/doc/vm/memorystatus.md)).
The XNU header describes fatal custom limits as per-task and non-fatal high-water marks as
pressure-driven early-kill candidates ([limit semantics](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/kern_memorystatus.h)).
This confirms that the launchd-managed/private per-process path is not a supported aggregate
command-tree quota for this prototype; no private spawn API or memory watchdog is added.
The real command test now verifies that extending a file one byte beyond `RLIMIT_FSIZE`
fails with `EFBIG`, opening pipes stops with `EMFILE` at `RLIMIT_NOFILE`, and the command
cannot raise either hard limit. These checks cap per-file size and per-process descriptor
count; they do not cap aggregate memory use across a process tree.

A real Seatbelt command test also verifies that the command inherits the configured
`RLIMIT_NPROC` value, successfully forks while the profile permits it, then lowers that
limit to two and receives `EAGAIN` from the next fork. This exercises the OS process-count
limit rather than only inspecting the Python facade. It does not prove a command-tree
quota: Darwin counts processes by real UID, so unrelated processes affect the same limit,
and the test does not exhaust the configured 1024-process threshold. Apple documents
`RLIMIT_NPROC` as a per-UID simultaneous process limit in [`getrlimit(2)`](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/getrlimit.2.html).

The runner now executes from a private APFS sparse bundle with a fixed maximum capacity.
`workspace_snapshot()` creates the bundle through `/usr/bin/hdiutil`, using a fixed sector
count and either APFS or case-sensitive APFS to match the source volume. It mounts the image
in a private temporary directory; the image backing file stays outside the source workspace
and mounted work volume, while command scratch stays inside the bounded volume. The default
image capacity is twice the copied workspace byte budget plus 256 MiB of filesystem
headroom; the API accepts a smaller limit down to 128 MB. After attachment, the trusted
helper matches the resolved image path in `hdiutil info -plist`, verifies the image is a
writable sparse bundle with the exact expected `blockcount * blocksize` capacity, and
cross-checks the whole-device identity against attach output. `diskutil info -plist` then
confirms the requested mountpoint, APFS personality, volume device, and a volume size no
larger than the image. On exit, the image is detached and the helper confirms it no longer
appears in the attachment inventory before deleting the backing directory. If detach or
inventory verification fails, it retains that directory and fails closed.

A 128 MB real Seatbelt test first mounts a separate disposable APFS volume without Seatbelt
and confirms the same user's direct `unmount(2)` call succeeds. Against the Kernel-created
snapshot, the real sandboxed command gets `EPERM` or `EACCES` from `unmount(2)`, writes
across multiple files until APFS returns `ENOSPC`, removes the fill files, then commits one
remaining file through the trusted changeset validator. This differential proves the tested
direct unmount denial is enforced by Seatbelt rather than the caller's ordinary user privileges
on this host.
A separate real snapshot test preserves distinct `CaseName` and `casename` entries on a
case-sensitive source volume.

Apple's Disk Utility guide documents read-write sparse bundles and APFS case-sensitive
volumes ([Disk Utility disk images](https://support.apple.com/en-ge/guide/disk-utility/dskutl11888/mac)).
Apple now marks `hdiutil create`, `attach`, and `detach` as deprecated and recommends the
`diskutil image` interface. Earlier bounded probes on the current macOS 27 development host
timed out for `diskutil image create blank`, `diskutil image attach`, and `diskutil
partitionDisk`. A current targeted probe now successfully attaches the exact APFS sparse
bundle copied into the workspace snapshot with `diskutil image attach --plist --nobrowse
--mountPoint`, then detaches it; the earlier attach timeout is not evidence for this invocation.
The production snapshot helper still uses `hdiutil` because its complete create/attach/detach
sequence and inventory checks are implemented and tested. The same real Seatbelt test proves
both `hdiutil attach` and this `diskutil image attach` form work in a trusted host control but
return nonzero under the command profile; the live workspace target stays unmounted and the
image remains absent from `hdiutil info`. This differential evidence covers these two attach
paths on the current host, not every Disk Arbitration or system-service route. Other
`diskutil image` operations still need fresh bounded probes. Both tools are invoked by absolute
path with fixed arguments in the sandbox probe and bounded timeouts. Runner input cannot select
the image path, capacity, mountpoint, filesystem personality, or device identifier.

Apple's XNU [`fs_snapshot_create(2)` manual](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/man/man2/fs_snapshot_create.2)
does not provide a drop-in replacement for this private work volume. It describes snapshots
of a mounted filesystem as read-only, mounts those snapshots read-only, and requires
superuser privileges plus an additional entitlement for all snapshot operations. A snapshot
also belongs to the source filesystem and may retain storage as that filesystem changes; it
does not impose the fixed capacity required for untrusted command output. Its destructive
revert applies to the whole filesystem, not one workspace. This source-backed contract makes
the API unsuitable for a same-user, bounded, writable workspace scratch volume; no privileged
helper or private entitlement was added to work around those constraints.

An end-to-end launcher test now repeats the `hdiutil attach` escape attempt through
`run_workspace_command()`: an unsandboxed control mounts the same sparsebundle over a
workspace directory, then detaches it; the sandboxed command writes one ordinary snapshot
file and attempts the same mount. The mount fails, the workspace target stays unmounted,
and the trusted Kernel validates and commits only the ordinary file. This exercises the
launcher, Kernel, Runner, command sandbox, and changeset commit together on the current
host. It does not cover other Disk Arbitration or system-service delegation paths.

This establishes an aggregate disk cap for the sandboxed command's snapshot and scratch
writes, not a memory quota or a whole-machine physical-disk reservation. The snapshot
copy and trusted commit staging are separately bounded by `max_bytes`. `RLIMIT_NPROC`
remains a per-real-UID setting, not a per-command process-tree quota.

The command process receives only the explicitly constructed environment. A real Seatbelt
test places a sentinel in the Kernel parent's environment and verifies it is absent from
the command. An end-to-end launcher test places a unique sentinel in the launcher's
environment and verifies it is absent from both the Seatbelt Runner and its fixed command.
Another test marks an anonymous pipe descriptor inheritable and verifies the command cannot
read its sentinel bytes. These tests exercise the environment allowlists and the
`close_fds=True` process boundary.

These are two tested operation handlers, not the final IPC boundary or a general request
dispatcher; `process.cancel` is accepted only as a control frame while `process.exec` is
active. The capability probe binds its channel to the exact probe child by retaining its
`Popen` pipe ends; the outer sandbox denies child creation and the protocol cannot transfer
descriptors. The development launcher additionally starts a one-shot Kernel worker as a
separate process, which starts a separate Seatbelt Runner; framed requests still use private
inherited pipes. Both launcher-to-Kernel and Kernel-to-Runner peer PIDs are checked by a
one-time native handshake before framed IPC begins. The handshake carries no application
data. The worker runs with the caller's user identity and its source installation remains
mutable by that user, so process separation here does not make the Kernel immutable or
exclusive.

## One-shot local workspace path

`khaos/launcher.py` starts `khaos/kernel/worker.py` in an isolated Python subprocess and
exchanges one bounded `workspace.run` request over stdin/stdout pipes. The workspace path
is fixed as a trusted-launcher startup argument; it is not accepted in Runner messages.
The Worker rejects a workspace that overlaps its imported Kernel package or an enclosing
macOS `.xpc` / `.app` bundle before probing Seatbelt. This protects signed service and app
files in sibling bundle directories, not only the Python `Resources` directory. It then
probes Seatbelt, snapshots the selected workspace, and starts `khaos/runner.py` under
Seatbelt. The Runner SDK exposes `process_exec(argv)` and `workspace_commit()`; its
`process_exec(argv)` call can send a request-correlated `process.cancel` while waiting.
The Kernel owns the snapshot object and scope, executes the requested command in another Seatbelt
process with no inherited descriptors and a minimal environment, validates its output, and
commits the resulting changeset to the selected workspace.

Real macOS integration tests cover this vertical path: a command's direct write to a live
outside canary is denied by Seatbelt, ordinary output inside the snapshot is committed,
and a new symlink in Runner output is rejected without changing its target. A Runner
profile attack against disposable live-workspace and user-home secrets and canaries confirms
direct file read and write attempts are denied. Unsupported platforms fail before the Kernel process
starts. The path has no Host or model, Candidate Plugin loading/admission, user capability
grant or activation approval, immutable Kernel installation, or exclusive authority over
live workspace writes. The development launcher can send cancellation through the Kernel
worker, but no Agent Host exists to provide a Host-to-Runner cancellation source or use a
production-facing operation lifecycle. A real subprocess regression places a fixed command's
would-be output workspace inside a standalone `KernelProduction.xpc` sibling to
`Contents/Resources`, and inside an outer `KhaosSeed.app` sibling to `XPCServices`; both are
rejected as `workspace_rejected` before the command marker can be committed.

Apple documents `pipe(2)` as a unidirectional interprocess channel and `killpg(2)` as
signaling every process in a process group. Python's `Popen` supplies the private
stdin/stdout pipes, descriptor closure, and new-session launch used by this diagnostic. See
[Apple's pipe manual](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/pipe.2.html),
[Apple's killpg manual](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/killpg.2.html),
and the [Python subprocess documentation](https://docs.python.org/3.13/library/subprocess.html#subprocess.Popen).
These standard-library and OS primitives keep this bootstrap independent of a third-party
RPC framework.

The committer intentionally accepts a narrow changeset: new or changed symbolic links
are rejected; regular files with multiple hard links, special files, cross-device
entries, permission changes to existing files, and stale workspace baselines are
rejected. New files receive mode `0600`, new directories receive mode `0700`, and
existing file permissions are preserved. For a modified existing file, the committer
preserves uid/gid, ACL, and extended attributes from the opened trusted baseline inode;
it never copies those fields from Runner output. The baseline xattr names are enumerated
and value lengths queried through descriptor APIs, with a 64 MiB aggregate value-and-name
budget per commit and a 1 MiB cap for one xattr name list. Metadata that exceeds those bounds and
file flags that cannot be carried across replacement are rejected before workspace
mutation. Before applying changeset entries, the committer prepares each modified existing
file beside its destination and copies the trusted baseline ACL/xattrs onto that temporary
replacement. A failure-injection test makes the second metadata copy fail and confirms the
workspace files remain unchanged and prepared entries are removed. Later OS failures can
still leave a partial changeset because this is not a multi-file transaction. The broker
returns `commit_rejected` when it can establish that writeback did not begin, and
`commit_outcome_uncertain` when a failure may have left live entries partially applied. A
real Seatbelt broker test injects failure before the second APFS swap: the first file contains
the new bytes, the second retains its baseline bytes, and the response is
`commit_outcome_uncertain`. Callers must inspect the workspace before retrying. A separate
real Seatbelt test kills the commit child immediately after its first successful APFS swap.
The Broker still returns `commit_outcome_uncertain`; the workspace retains one updated and
one baseline file, two `.khaos-*.tmp` entries, and the private `khaos-changes-*` staging
directory. There is no crash-recovery or automatic cleanup protocol yet. A separate
failure-injection test rejects a new-directory commit when its parent `fsync` fails and
confirms the just-created directory inode is removed. A second race-injection test replaces
that entry before cleanup and confirms the replacement survives while the commit reports
incomplete cleanup. This local rollback does not make the whole changeset transactional.
Apple's XNU [`fs_snapshot_revert(2)` documentation](https://github.com/apple/darwin-xnu/blob/main/bsd/man/man2/fs_snapshot_create.2)
describes a destructive revert of the entire filesystem and requires superuser privileges
plus an entitlement. It is not a workspace-scoped transaction primitive for this committer.
Timestamps are intentionally refreshed by replacement. This uses Apple's
descriptor-based `fcopyfile(3)` with ACL and xattr flags only, leaving
Runner-provided file data on the destination; xattr enumeration and size checks use
`flistxattr(2)` and `fgetxattr(2)`. See Apple's [`copyfile(3)` source manual](https://github.com/apple-oss-distributions/copyfile/blob/main/copyfile.3)
and [XNU xattr API](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/xattr.h).
For both added files and replacements, the committer also rechecks the scanned size and
SHA-256 while copying staged bytes into the same-directory temporary file. A failure-injection
test changes an added file in staging after the scan and confirms the Kernel rejects it before
the live destination is installed. This detects staged-content drift; it does not establish
exclusive control over temporary paths against arbitrary same-UID processes.
New files are created with mode `0600`; their data is copied without carrying Runner-provided
ACLs or extended attributes. A real macOS filesystem test attaches both kinds of metadata to
a new snapshot file and confirms they are absent from the committed file. A separate real
filesystem test gives a new snapshot directory mode `0777`, an ACL, and an xattr; the committed
directory is fixed at `0700`, drops the ACL/xattr, and keeps nested new files at `0600`.
An end-to-end Seatbelt test runs a sandboxed command that creates a directory and file in
snapshot output. `chmod` and the native `setxattr` syscall are denied with `EPERM`/`EACCES`;
the Kernel still commits the valid content change and installs the directory at `0700`, the
file at `0600`, and no Runner xattr. The direct filesystem metadata attack remains separate
evidence that commit drops injected ACLs and xattrs even when they reach its input.
New-file creation is exclusive. The final install uses `fclonefileat` with the still-open verified temporary-file
descriptor, so replacing its directory entry cannot redirect the clone to another inode. A
cross-process APFS attack replaces that temporary name with a hard link to an outside canary;
the committed file still contains the scanned Runner bytes, remains single-link, and the canary
is unchanged. Because `fclonefileat` copies source extended attributes, the committer captures
the temporary descriptor's stat fields (excluding link count and ctime, which can change when
the raced temporary name is unlinked) and fingerprints of each xattr's name, length, and value
before cloning, then checks the source and cloned destination afterward. A real cross-process
APFS test seeds an xattr, changes its value to a different value of the same length during the
clone, then restores the source value before the post-clone source check. The destination
fingerprint still differs, so the Kernel rejects and removes it. This detects that metadata race
within the clone window; it does not serialize arbitrary writers that can independently modify
the live workspace. The [macOS `clonefile(2)` manual](https://keith.github.io/xcode-man-pages/clonefile.2.html)
documents that cloning copies source extended attributes and inherits the target directory's
ACL by default. The primitive requires same-volume clone support and fails closed when
unavailable. On macOS, replacing an existing file or
removing an entry uses `renameatx_np(RENAME_SWAP)` with a same-directory sentinel, then checks
the displaced inode and contents (or
symlink target / directory identity) against the snapshot baseline. If a change raced
the pre-swap check, the swap is reversed and the commit is rejected. A filesystem
without swap-rename support fails closed when an operation needs a swap. The operation
also reopens the named workspace root and parent path around mutations. Real APFS race
tests detach the root or parent during file replacement and deletion, after new-file cloning,
and after directory creation; the commit rejects these cases and restores or removes the
entry where the operation still has a recovery object. These checks cover the tested
windows but cannot serialize a non-cooperating writer between checks. The operation is
not a multi-file transaction; the future Kernel/Host/Runner boundary must make the Kernel
the only live-workspace writer before this primitive can support a complete security guarantee.
The trusted Launcher now opens the selected root before starting the Worker and passes the
directory descriptor through `Popen(pass_fds=...)`. Snapshot creation duplicates that handle
and verifies the canonical path still names the same device/inode before copying. A real
end-to-end race test replaces the selected path after the Launcher opens it but before the
Worker starts; the Worker rejects the request before command execution, leaving both the
original and replacement directories unchanged. This binds the selected root across this
process boundary; it does not exclude later non-cooperating same-UID writes.
Real APFS cross-process race tests coordinate a separate same-UID writer that ignores the
advisory mountpoint lock. Immediately before `RENAME_SWAP`, one case replaces the target
inode and another overwrites the existing inode with same-length content. In both cases the
committer observes the displaced entry no longer matches the baseline, restores the competing
file, and rejects the commit. These verify two real cross-process windows; they do not
serialize every non-cooperating writer or close the external-writer gap.

A real Seatbelt Broker-path test now coordinates the same replacement through the actual
one-shot commit child. After the child's live-baseline and pre-swap checks, an independent
same-UID writer replaces the destination with a different inode immediately before
`RENAME_SWAP`. The sandboxed committer detects the unexpected displaced entry, swaps it back,
removes its candidate temporary file, and returns `commit_outcome_uncertain`. The competing
file's inode and bytes remain at the destination, and neither the workspace nor private
staging contains leftover Khaos temporary entries. This proves the tested race window under
the real Seatbelt write scope; it does not prevent the independent writer's in-scope change
or establish exclusive live-workspace authority.

The APFS sparse-bundle backing file is created in the system temporary directory, outside
the selected workspace tree and mounted work volume. It can still share the source workspace's
APFS mount: on the current macOS 27 host, the temporary path is spelled under `/private`, but
`fstat` and `ATTR_VOL_MOUNTPOINT` identify it as the same `/System/Volumes/Data` mount as the
workspace. Workspace ancestry checks normalize paths through their reported mount roots and
verify firmlink aliases with `samefile`, including the Kernel-install exclusion check. The
snapshot's mounted APFS volume is separate and has a fixed virtual capacity; this does not
reserve physical disk space on the host volume. The copier and committer read
`ATTR_VOL_MOUNTPOINT` through `fgetattrlist` on each opened root, directory, and regular file.
Source entries must match the captured source mount; snapshot entries must match the separate
bounded APFS mount.
The committer validates each tree on its own mount, then applies staged changes only through
the descriptor tree rooted at the original workspace. This rejects nested mounts even when
their `st_dev` matches the containing volume. A missing API, malformed result, or changed
mount point fails closed. The descriptor-based volume query uses Apple's `fgetattrlist(2)`
and `ATTR_VOL_MOUNTPOINT`, which Apple documents as the volume's mount path and equivalent
to `f_mntonname` in `statfs`:
[Apple getattrlist(2)](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/getattrlist.2.html).

The tests exercise the native query on real descriptors and simulate a different
mount-point result while keeping the device number unchanged. A disposable APFS sparse
image was also mounted below a temporary workspace on macOS; the snapshot rejected the
live nested volume because its `st_dev` differed. That experiment exercises the real
cross-device rejection, but not the same-device mount-point check. An automated real-APFS
commit attack adds a nested volume to the live workspace after the snapshot; the committer
rejects before applying the candidate output. Both real nested-mount cases have a different
`st_dev` from the containing volume. A new end-to-end test places the workspace and an outside
canary on one disposable APFS volume, snapshots the workspace, then has the unconfined same-UID
Host try to mount that already-mounted volume over a nested workspace directory. On macOS 27.0,
`mount_apfs` returns 75 (`Operation already in progress`) and the directory remains on its
original mount. The test commits the safe candidate only after that OS refusal; if a later OS
allows the duplicate mount, the test reads the canary through it and requires Kernel commit to
reject the mounted changeset. Because the current OS refuses to create the duplicate mount, the
Kernel's real same-device/different-mount-root rejection remains unproven. The untrusted command
path is separately tested against real `hdiutil` and `diskutil image attach` attempts, and its
Seatbelt profile denies `mount` and
`unmount` syscalls. Apple's [`mount(2)` documentation](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/mount.2.html)
describes when caller privileges can independently produce `EPERM`. The unconfined same-user
positive control and sandboxed snapshot attempt isolate the direct `unmount(2)` denial on this
host. A separate direct APFS probe uses the current host's `mount_apfs(8)` tool: the same UID
successfully mounts an attached APFS image read-only over a disposable workspace directory;
the sandboxed Runner cannot launch that helper (`EPERM` or `EACCES`) and leaves the directory
unmounted. The raw `libc.mount()` probe returns `EFAULT` without Seatbelt for intentionally null
APFS mount data, then `EPERM` or `EACCES` under the real Runner profile, showing the `SYS_mount`
rule rejects the syscall before argument validation. The raw probe does not supply a valid
filesystem-specific mount structure. The Disk Arbitration-backed attach paths also have
successful unconfined controls and are denied under Seatbelt. These results cover the tested
same-user mount paths on this host; privileged host-level mount interference remains outside this
evidence. Matching the
containing mount keeps filename normalization aligned between the copied tree and the eventual
commit target.

## OS and implementation research

- The local macOS `sandbox-exec(1)` manual marks the command deprecated. Apple’s
  [App Sandbox documentation](https://developer.apple.com/documentation/security/app-sandbox)
  describes an app entitlement model; the current Khaos work needs to constrain a
  child process launched by a local developer tool.
- Apple documents that a helper launched directly with `Process`, `fork`, or `exec`
  inherits the launching app's sandbox; a differently entitled helper should use an
  XPC service. XPC services run in their own sandbox and are the platform mechanism for
  privilege isolation. A listener can enforce a peer code-signing requirement, giving
  the OS an identity predicate to check on a connection. Its strength depends on the
  requirement and signing authority; an ad-hoc-signed identifier is not publisher
  authentication. This is a candidate route for separating a future untrusted Host from
  the Kernel, not a complete authorization policy: the Host must never receive writable
  workspace scope, and the Kernel service must independently validate bounded requests,
  user-selected workspace scope, and approval. The current Python CLI has no signed app
  targets or XPC service, so this remains research rather than an implemented boundary.
  The code-signing requirement checks the peer against its configured predicate, but it
  does not authorize workspace, operation, or capability requests. Those remain Kernel
  decisions. XPC process separation also cannot make unrelated same-UID applications obey the Kernel's
  advisory lock. The inference from Apple's process-scoped sandbox model is that any
  write-exclusion claim must be scoped to Khaos processes whose Host and Runner are actually
  sandboxed; a global claim against arbitrary same-UID software needs a different OS-level
  authority model. Apple's file-access documentation also supports passing a security-scoped
  bookmark to another process. A signed, ad-hoc XPC/App Sandbox probe now exercises a bookmark
  for a disposable snapshot on the current macOS host. The XPC Runner reports that
  `startAccessingSecurityScopedResource()` succeeds and can write inside the bookmarked
  snapshot; direct sibling and outside-canary reads/writes, symlink and traversal escapes,
  the hard-link attempt, and the Runner's loopback connection fail with `EPERM` or `EACCES`.
  A shell child launched by the Runner inherits the same snapshot scope and cannot read the
  sibling or outside canary or connect to a loopback listener. The outside path is a
  disposable canary, not Khaos's live workspace, which is not
  wired to this probe. These results establish only this signed probe on the tested host.

  A follow-on execution check first tried to launch the current Homebrew CPython 3.13
  executable from outside the XPC service bundle. `Process.run()` failed with Cocoa
  error 4 (`python3.13` was not visible to the service), both through the Homebrew
  symlink and its resolved Cellar path. `/usr/bin/python3` is an `xcrun` shim and exits
  with `cannot be used within an App Sandbox`. The real Command Line Tools CPython 3.9
  executable did start as a child; its small probe script wrote to the bookmarked
  snapshot while sibling/outside reads and loopback networking were denied. Khaos uses
  `dataclass(slots=True)`, which requires Python 3.10 or newer.

  The probe now copies the host's relocatable CPython 3.13 `Python.framework` into each
  test XPC service bundle and includes the current `khaos` package as a service resource.
  It removes Homebrew's external `site-packages` link and generated bytecode, rewrites
  the interpreter and framework helper's library paths to the bundled framework, then
  signs the copied code and service. The service starts that bundled interpreter with
  `PYTHONHOME` inside its own bundle. A real Python 3.13 child imports
  `khaos.kernel.workspace_changes` (including its slotted dataclasses), writes into the
  bookmarked snapshot, and receives OS denials for sibling and outside-canary reads and
  loopback networking. The macOS XPC test passes on this host. This proves a bundled
  current-version Python child can run under the tested App Sandbox service and inherit
  its filesystem and network restrictions. It is test-harness packaging from this host's
  Homebrew build, not a reproducible release package. Production XPC Kernel/Runner IPC,
  trusted installation and signing, runtime updates, and Plugin-specific storage remain
  unimplemented; no production execution path uses these services.

  A separate no-bookmark XPC invocation now starts the repository's actual
  `khaos.runner` under the bundled interpreter before the service receives any
  security-scoped workspace bookmark. A test-only Python Kernel peer uses the existing
  OS PID listener/accept helpers, ABI v4 nonce ping and bounded anonymous-pipe frames to
  start an untrusted `plugin.start`. The Plugin's direct reads and writes against the
  Host app's snapshot and sibling, an outside canary, and loopback networking receive
  OS denials. The Plugin then obtains one synthetic `fs.read` value over the existing
  Runner SDK/pipe protocol; a second request for an out-of-scope path receives
  `path_not_readable`. This exercises real Runner code, peer-PID binding, and one
  Kernel-mediated read request inside the test XPC process tree. The test Kernel is a
  small probe shim in the same XPC service sandbox, and its allowlisted data is a fixed
  in-memory fixture: this does not prove access to a real snapshot, `process.exec`,
  `workspace.commit`, or separation of the production Kernel from the Runner. The
  service's own App Sandbox container is also shared by every process under that service
  identity; do not store cross-Plugin private state there. Production XPC Kernel/Runner integration and production workspace writeback remain
  unimplemented; the disposable end-to-end execution probe is recorded below.

  A separate native `Kernel.xpc` service now exercises a real cross-process workspace bookmark
  independently of that Python Runner probe. Before resolving any bookmark, the service tries
  to open the same disposable Host app-container `input.txt` using only its path string; macOS
  denies that open. The outer Host obtains a Kernel endpoint through the named bootstrap, then
  forwards the endpoint to an embedded `HostClient.xpc` over a real XPC connection. The
  client creates and sends the app-container bookmark to Kernel.
  The Kernel endpoint's anonymous listener requires both that service's code-signing identifier
  and the current executable cdhash for every architecture. The Kernel resolves the bookmark, starts
  scoped access, and opens only fixed `input.txt` relative to a no-follow directory descriptor.
  It accepts only a single-link regular file up to 4 KiB and checks descriptor identity and
  modification time before and after reading. The service reads the fixture bytes, while the
  existing actual `khaos.runner` still receives no bookmark and its direct read of that same
  path remains denied. A separately signed `Spoof` XPC service deliberately uses the same
  signing identifier as `HostClient.xpc` but different code; the OS rejects its Kernel endpoint
  connection. Setup confirms identifier-only matching succeeds while identifier-plus-cdhash
  matching fails. This is OS evidence for a disposable Host app-container
  fixture only: it is not an external user workspace, production Kernel IPC, a Runner `fs.read`
  implementation, `process.exec`, or `workspace.commit`. The Python Runner's SDK read remains
  the earlier fixed in-memory Kernel-shim fixture. The bookmark has been reported stale on this
  host even though the disposable read succeeds. The native probe now recreates a stale bookmark
  while its original scoped access remains active, requires the new bookmark to resolve as fresh,
  and compares the old and new root directory device/inode before using the refreshed URL. The
  real XPC test exercises this path. This is a one-call probe policy only; it does not persist
  renewed grants or implement production revocation and user re-authorization. Apple documents passing a
  bookmark created with `options: []` to another process or XPC service in its
  [App Sandbox file-access guide](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox).

  The anonymous Kernel/Runner endpoints use Apple's
  `NSXPCListener.setConnectionCodeSigningRequirement`; the named client XPC services also
  bind each incoming connection to the parent app's designated code-signing requirement with
  `NSXPCConnection.setCodeSigningRequirement` before resuming it. In the earlier
  helper-based picker topology, both HostClient and WorkspaceGrantClient failed closed when
  their signed service bundle lacked that requirement. A real same-bundle-identifier,
  different-signer attack reached each named service but could not invoke its peer probe;
  identifier-only matching succeeded while the designated requirement failed. The
  WorkspaceGrantClient part of this evidence is historical; that forwarding service has been
  removed. The current direct WorkspaceGrant.app→KernelExecution path has a separate OS
  identity-rejection test described below. The legitimate Host call and the earlier
  user-selected workspace flow completed. The
  parent apps use a temporary self-signed test identity so their designated requirements stay
  stable when the containing app is re-signed. Pinning the parent executable's cdhash from an
  embedded helper would be self-referential because the helper's signed caller requirement is
  itself sealed into the containing app bundle. This is local peer-authentication evidence, not
  release identity or same-signer binary pinning. Apple's [TN3127](https://developer.apple.com/documentation/technotes/tn3127-inside-code-signing-requirements)
  explains requirement semantics
  ([endpoint API](https://developer.apple.com/documentation/foundation/nsxpclistenerendpoint),
  [anonymous-listener API](https://developer.apple.com/documentation/foundation/nsxpclistener/setconnectioncodesigningrequirement%28_%3A%29),
  [incoming-connection API](https://developer.apple.com/documentation/foundation/nsxpcconnection/setcodesigningrequirement%28_%3A%29)).

  A companion KernelExecution.xpc service now runs the existing trusted Launcher path from
  an XPC service without the App Sandbox entitlement. Its exported anonymous endpoint exposes
  only the fixed workspace.run method and requires the embedded `HostClient.xpc` identifier
  and current executable cdhashes for every architecture. The
  ordinary Kernel.xpc service remains App-Sandboxed for the bookmark-scope probe above; the
  Host app and Runner/Plugin XPC services also remain App-Sandboxed. Apple documents separate
  XPC services as a way to assign different capabilities to a helper
  ([sandbox diagnosis](https://developer.apple.com/documentation/security/discovering-and-diagnosing-app-sandbox-violations)).
  This is a test-harness authority split, not a production IPC or user-grant design.

  A signed App-Sandboxed Host positive control writes inside its own application container,
  then attempts `open(O_WRONLY)` on the embedded KernelExecution executable. The OS returns
  `EPERM` or `EACCES`; the helper's SHA-256 digest remains unchanged and `codesign --verify`
  still succeeds. This proves the current temporary test Host cannot open its bundled helper
  for writing. It does not establish production installation integrity or protection against an
  unsandboxed same-UID process that can replace the test bundle.

  The differential APFS probe found that hdiutil create exits 1 with “device not configured”
  inside the App-Sandboxed Kernel service, and diskutil image attach returns nonzero there.
  A later signed App Sandbox regression found that a nonzero `diskutil image attach` can
  still leave an unmounted image device registered; the earlier service probe did not
  establish whether its failed attach left such a device behind.
  diskutil image create blank succeeds in the service container when using the documented
  UDSB format and default APFS filesystem, but its subsequent image attach still fails.
  With no App Sandbox entitlement, KernelExecution.xpc completes the existing hdiutil
  sparse-bundle create/attach/detach path. This is why only the trusted execution service
  receives the APFS authority in this harness.

  The XPC execution probe resolves a disposable Host app-container bookmark, opens its root with
  `O_NOFOLLOW`, and keeps that descriptor through the operation. For a stale bookmark it creates
  a replacement while the old scope is active, resolves and opens it, then compares the old and
  new descriptor device/inode before using the replacement URL. The test moves each bookmarked
  directory away and back before service resolution to exercise that branch. The root descriptor
  is mapped to fd 198 in bundled CPython using `posix_spawn` file actions; the execution probe
  passes the same descriptor into `run_workspace_command()`, whose Launcher rechecks the named
  path against it and forwards it to the Kernel Worker. The trusted
  KernelExecution service is not constrained by App Sandbox: its descriptor child can read a
  parent traversal, sibling symlink, and hardlink to the sibling canary. The contaminated
  descriptor fixture therefore remains separate from the clean execution fixture. This is
  evidence that the Kernel process must validate and snapshot workspace data itself; its
  inherited descriptor is not an inode-level read boundary.

  In the descriptor handoff probe, Foundation `Process.run()` did not preserve the selected
  non-standard directory descriptor in the child; the child observed `EBADF`. Mapping the
  descriptor to standard input was not a viable workaround because it prevented Python from
  initializing normally. The native probe instead uses the POSIX `posix_spawn` file action
  `adddup2` to map the already-open directory to fd 198, then verifies it with `fstat` and
  descriptor-relative opens. Apple's [`posix_spawn_file_actions_adddup2` manual](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man3/posix_spawn_file_actions_adddup2.3.html)
  documents that file action; this result is specific to the XPC test harness and does not
  establish the production workspace authorization path.

  The clean fixture then calls the real `run_workspace_command()` path with the still-open
  bookmark-root descriptor. Its APFS snapshot mounts,
  the Seatbelt capability probe succeeds, Runner returns zero, a direct live-workspace write
  attempt fails under Seatbelt, and trusted changeset commit installs exactly one output file.
  A spoof-signed XPC service with the same signing identifier as `HostClient.xpc` but a
  different cdhash is denied by the KernelExecution endpoint's peer requirement.
  The test exercises a disposable app-container path, not an external user workspace or a
  user-approved external-workspace grant. The bookmark refresh plus descriptor handoff is
  exercised against the Host app-container fixture only. Production grant persistence,
  revocation and user re-authorization remain unimplemented.

  The macOS test now also prepares an external workspace outside the Host app container and
  verifies that the sandboxed Host cannot read it by path. Apple documents that a directory
  chosen with `NSOpenPanel` extends the presenting app's sandbox recursively, and that an
  implicit-scope bookmark passed to an XPC service extends the receiving process's sandbox
  ([file access](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox),
  [NSOpenPanel](https://developer.apple.com/documentation/appkit/nsopenpanel)). Therefore,
  the chooser must belong to a separate trusted-launcher identity; presenting it in the
  untrusted Host would grant the Host the same directory scope. XPC services are background
  processes and aren't the supported place for this UI
  ([Apple service guidance](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/DesigningDaemons.html)).
  An opt-in native probe uses a separately signed, sandboxed `WorkspaceGrant.app` with
  user-selected read/write access. An earlier version forwarded the endpoint and bookmarks
  through an embedded `WorkspaceGrantClient.xpc`; that forwarding process has been removed.
  The current UI app obtains a `KernelExecution.xpc` endpoint through its named bootstrap
  service, creates the bookmarks after selection, and connects directly to the anonymous
  endpoint. KernelExecution pins the parent app's designated code-signing requirement before
  accepting that connection. The ordinary Host receives only the selected path as a
  negative-test input; it receives no bookmark or descriptor. A separate same-service-identifier,
  different-signing-identity client attempts `workspace.run` with empty bookmarks and is
  invalidated by the OS before the service accepts the call. The focused build-mode test covers
  this denial but does not open the picker. The interactive `NSOpenPanel`→KernelExecution→snapshot→Runner→commit
  successes recorded below predate removal of `WorkspaceGrantClient.xpc`; they are historical
  evidence for the earlier forwarding topology and do not yet prove the current direct positive
  path. This probe remains ad-hoc signed and test-only, and does not establish production grant
  policy or app identity.
  A further audit found that the earlier picker helper wrote `workspace-grant-report.txt`
  directly into the selected directory after the Kernel request. Those successful runs therefore
  do not prove Kernel-only writeback or that the Kernel output was the only new path. The helper
  now reports over stdout. The interactive test checks the selected directory's path delta for
  exactly `kernel-workspace/output.txt` and the trusted
  `kernel-descriptor-scope/descriptor-probe-started.txt` marker. The descriptor marker is written
  by the Kernel's test probe, not by the picker app.
  The picker starts in the fixture's parent and resolves symlinks before checking the selected
  path against the expected root. Build/sign without opening the chooser
  using `KHAOS_RUN_WORKSPACE_GRANT_UI=build python3 -m unittest discover -s tests -p
  'test_macos_xpc_sandbox.py' -v`; use value `1` only for the interactive selection run. The
  earlier interactive attempts each waited for the 240-second UI timeout without a selection
  and produced no grant or writeback evidence. At that point the test allowed 600 seconds for
  the opt-in selection; the later direct-helper retries below use a 300-second bound. Launch Services returns `kLSIncompatibleSystemVersionErr` when
  asked to open this ad-hoc app bundle from the temporary test directory; a minimal no-sandbox
  app at the same location reproduces it, so the probe invokes its executable directly. This
  is a test-host packaging limitation, not evidence about a normally installed signed app.
  The probe is test-only and does not implement production grant persistence, revocation,
  approval binding, or publisher-authentic signing.

  After the completed interactive run, the client callback paths were changed to complete once
  on either an XPC reply or an XPC error. The current `build`-mode full XPC test passes in
  20.134 seconds. A repeat interactive run with this callback change was stopped while the
  picker awaited a new selection; the external-workspace success evidence above predates that
  callback-only change.

  A further interactive attempt on 2026-09-27 rebuilt a fresh temporary workspace and opened
  the grant helper, but no folder selection arrived within the 600-second window. The test
  ended with `subprocess.TimeoutExpired`; its temporary root and helper process were removed,
  and this attempt produced no grant or writeback evidence. The later opt-in rerun after the user
  requested reopening the picker passed in 44.971 seconds; a fresh rerun for the next user request
  to reopen it passed in 50.376 seconds on 2026-09-27. The selected directory matched
  the fresh disposable workspace; assertions verified successful Kernel execution, the expected
  committed output, no direct-write bypass, and rejection of an unsafe changeset while preserving
  the previous output and outside canary. This is again evidence for the ad-hoc test identity and
  temporary fixture only.

  A later user-requested reopening created a fresh temporary fixture and displayed the native
  `Authorize Temporary Khaos Workspace` picker as a visible foreground window. No directory
  selection reached the probe before its 600-second timeout; the test raised
  `subprocess.TimeoutExpired` after 646.895 seconds. The temporary root and helper process were
  removed, and this attempt produced no grant or writeback evidence.

  The next user-requested reopening on 2026-09-27 again displayed the picker with the fresh
  `user-selected-workspace` folder visible. No selection arrived before the 600-second timeout;
  the test raised `subprocess.TimeoutExpired` after 646.215 seconds. The temporary root and
  helper process were removed, and this attempt produced no grant or writeback evidence.

  Another user-requested reopening on 2026-09-27 displayed the direct-path picker in the
  foreground with a fresh `user-selected-workspace` visible. No selection arrived before the
  600-second timeout; the test raised `subprocess.TimeoutExpired` after 645.734 seconds. The
  test process and temporary root were gone after cleanup. This attempt produced no grant or
  direct-path writeback evidence.

  After removing the probe's direct report-file write and deleting the app-container fixture,
  the build-mode test passed on 2026-09-27 in 46.068 seconds, including the same-identifier,
  different-signing-identity XPC denial. The next user-requested interactive run launched a fresh
  picker probe but received no selection before the 600-second timeout; it raised
  `subprocess.TimeoutExpired` after 645.871 seconds. The temporary root and helper process were
  absent after test cleanup. This run produced no external-workspace grant or writeback evidence;
  the stdout-report and single-new-path assertions are implemented but remain unexercised by a
  successful user selection.

  The next user-requested reopening on 2026-09-27 again displayed the direct-path picker in
  the foreground. No folder selection arrived during the 600-second limit; the test raised
  `subprocess.TimeoutExpired` after 645.855 seconds. The temporary root, helper, and unittest
  process were absent after cleanup. No external-workspace grant or writeback evidence was
  produced.

  The first XPC workspace ABI v1 passed bookmarks as typed `Data` and checked their 64 KiB
  combined limit only after `NSXPC` decoded the arguments. ABI v2 moves request IDs to two
  fixed-width `UInt64` values and sends bookmark bytes through an `NSFileHandle` stream socket.
  The Kernel reads a four-byte length first, rejects a payload above 65,544 bytes before body
  allocation, requires exact inner lengths and EOF, caps combined bookmark bytes at 64 KiB, and
  applies one five-second absolute read deadline. Oversized input is rejected before the
  descriptor-probe marker appears. A real XPC slow-stream attack sends half the outer length,
  waits four seconds, then sends the remaining length and one body byte while keeping the socket
  open. The service returns `invalid_bookmark` within the single deadline, does not start the
  descriptor probe, and accepts a valid request on the same XPC connection afterward. The real
  XPC build-mode test verifies the slow-stream deadline, oversized rejection, fixed-width request
  IDs, valid Kernel execution and commit, cancellation, caller disconnect, and
  same-identifier/different-signing-identity denial; it passed in 52.415 seconds on 2026-09-27.
  This remains a test-only service and does not establish production admission,
  grant persistence, publisher identity, or user-data authority. The opt-in external-workspace
  picker is not exercised by this build-mode test.

  The next interactive attempt found that the temporary signed app's executable was built
  with Swift 6.3.3's default deployment target `arm64-apple-macosx28.0`, while this host runs
  macOS 27.0. Launch Services rejected that app with `-10825`; Apple defines this as
  `kLSIncompatibleSystemVersionErr` ([result code](https://developer.apple.com/documentation/coreservices/3074489-anonymous/klsincompatiblesystemversionerr)).
  Building `WorkspaceGrant` for the current host's architecture and macOS version removed
  that launch error. `/usr/bin/open -W -n -a` started the signed app and `NSWorkspace` reported
  it as the foreground application, but no folder selection arrived within 600 seconds. The
  test timed out after 654.749 seconds; its Python process and `open` waiter exited, but the
  Launch Services app remained orphaned after temporary-root cleanup. The exact probe PID was
  terminated. The opt-in test then invoked the bundled executable as a managed child with a
  300-second bound. It again received no selection and timed out after 352.736 seconds. This
  time `subprocess.run` terminated the helper; process inspection found no surviving
  `WorkspaceGrant` or Kernel service, and the temporary root was gone. `NSWorkspace` reported
  the app as frontmost during the wait, but UI automation returned `timeoutReached` when asked
  to attach, so the modal panel's visible contents remain unverified. Neither attempt
  establishes an external-workspace grant or Kernel writeback. Apple's
  [`LSMinimumSystemVersion` key](https://developer.apple.com/documentation/BundleResources/Information-Property-List/LSMinimumSystemVersion)
  describes the bundle-level minimum; matching the Mach-O deployment target to the running
  host allowed this app launch.

  The user-requested interactive rerun on 2026-09-27 rebuilt a fresh fixture and left the
  `WorkspaceGrant` helper waiting in `NSOpenPanel.runModal()`. No selection reached the helper
  within 600 seconds; the test raised `subprocess.TimeoutExpired` after 647.630 seconds and
  cleaned up the temporary root and helper. UI automation could not attach to the temporary app
  through Launch Services (`kLSIncompatibleSystemVersionErr`), so this attempt does not establish
  whether the panel was visibly foregrounded. It produced no external-workspace grant or
  writeback evidence.

  A second clean interactive rerun on 2026-09-27 left the helper waiting without switching other
  applications. It still received no folder selection within 600 seconds and raised
  `subprocess.TimeoutExpired` after 647.153 seconds. Test cleanup removed the temporary root and
  helper; this run also produced no external-workspace grant or writeback evidence.

  On 2026-09-27, the user's request reopened a fresh picker. A system screenshot confirmed the
  `WorkspaceGrant` panel was foregrounded and displayed the new `user-selected-workspace` folder;
  the UI automation attachment still returned `timeoutReached`. No selection reached the helper
  during its 300-second bound. The focused XPC test ended with `subprocess.TimeoutExpired` after
  363.448 seconds, and post-run process and filesystem inspection found no surviving helper or
  temporary fixture. This confirms the current direct-path picker is visible, but establishes no
  external-workspace grant or Kernel writeback.

  A subsequent user-requested retry on 2026-09-27 rebuilt the disposable fixture and ran the
  interactive XPC test. `WorkspaceGrant` remained the frontmost application while waiting for a
  directory choice; no selection or cancellation reached it within the 300-second bound. The
  test raised `subprocess.TimeoutExpired` after 351.457 seconds. Process and filesystem checks
  found no surviving helper or temporary fixture. This run produced no external-workspace grant
  or Kernel writeback evidence.

  The latest user-requested reopen on 2026-09-27 again left the `WorkspaceGrant` helper waiting
  in `NSOpenPanel.runModal()`; no selection or cancellation arrived within the 300-second
  bound. The focused test raised `subprocess.TimeoutExpired` after 352.557 seconds and removed
  its temporary root and helper. UI attachment timed out, so this run does not establish that the
  picker was visible. It produced no external-workspace grant or Kernel writeback evidence.

  On 2026-09-27, the user selected the fresh `user-selected-workspace` in the direct-path
  picker. The test reached the Kernel output and rejected an unsafe changeset, then initially
  failed its final path-delta assertion because it expected only `kernel-workspace/output.txt`.
  The second new path, `kernel-descriptor-scope/descriptor-probe-started.txt`, is deliberately
  created by the trusted Kernel test probe. The assertion and ABI/research notes now include both
  expected Kernel-created paths. The corrected interactive test passed in 72.161 seconds; it
  verified the selected root, Kernel commit, absent bypass/report files, and exact two-path delta.
  This proves the current test-only direct picker-to-XPC positive path on this host, not a shipped
  grant flow, persistent authorization, or production installation integrity.

  A follow-up interactive attack on 2026-09-27 tested scope transfer while the picker app still
  held its selected-folder grant. The picker app successfully opened `kernel-workspace/input.txt`
  for writing. A separate sandboxed `UntrustedHost.xpc` received only the absolute path, proved
  its app-container write control, and received `EPERM`/`EACCES` opening that same workspace file
  with `O_WRONLY`; it received no bookmark. KernelExecution then received the two scoped
  bookmarks and the direct workspace commit completed. The focused interactive XPC test passed
  in 104.323 seconds with the exact output-plus-descriptor-marker path delta. This establishes
  noninheritance for these distinct sandboxed processes in the temporary test bundle only.

  The OS peer-requirement setup was then moved into the small shared Khaos source
  helper `khaos/macos/XPCPeerIdentity.swift`; test protocols and XPC services remain
  test-only. After this extraction, build mode passed in 53.701 seconds. The user
  selected the fresh workspace in the interactive picker, and the sibling-service
  denial plus Kernel writeback attack passed in 321.592 seconds on 2026-09-27. This
  verifies that the temporary probe compiles and exercises the shared helper. It
  does not establish a production Launcher, XPC service, installation, or grant policy.

  The bounded Workspace XPC ABI implementation was subsequently moved from the
  probe directory to `khaos/macos/KernelWorkspaceXPC.swift`, and the test service
  protocol was renamed to `KernelWorkspaceEndpoint`. The post-move build-mode XPC
  test passed in 66.194 seconds on 2026-09-27, compiling that shared source and
  exercising real peer-identity denial. The 321.592-second interactive
  picker/sibling-scope success predates this ABI source move; the picker positive
  path has not been rerun against the relocated ABI. The endpoint bundle and
  service implementation remain test-only. The canonical repository suite then
  passed all 181 tests in 317.693 seconds on the same host.

  A subsequent IPC audit found the sender only compared the framed bookmark size
  with `UInt32.max`, allowing it to copy caller-provided data far beyond the
  receiver's 64 KiB protocol limit. The shared ABI now validates both nonempty
  bookmark lengths against one total 64 KiB limit before building the frame; the
  receiver uses the same length rule. The test includes a local endpoint counter
  proving the oversized client call fails with `EMSGSIZE` before XPC invocation,
  plus a separate raw XPC request that sends only an oversized frame header and
  is rejected before the Kernel descriptor marker. Build-mode XPC passed in
  54.080 seconds, the post-move interactive picker/sibling-scope attack passed
  in 69.477 seconds, and the final canonical suite passed all 181 tests in
  317.673 seconds on 2026-09-27. The production service bundle is still absent.

  A user-requested clean picker rerun then created a fresh temporary fixture. The
  native panel returned the matching `user-selected-workspace`, and the focused
  XPC test passed in 72.619 seconds. Passing assertions covered the sibling
  sandbox's denied workspace write, Kernel safe commit and unsafe changeset
  rejection, and the exact output-plus-descriptor-marker path delta. This remains
  test-only evidence; no production Launcher or service bundle is shipped.

  The one-operation XPC admission/cancellation logic was then extracted from
  `tests/macos_xpc_probe/Kernel.swift` into the shared Khaos source
  `khaos/macos/KernelWorkspaceService.swift`. Test-only scoped-read probes and the
  Python executor adapter remain in the probe. After extraction, the build-mode XPC
  test passed in 53.586 seconds, the interactive picker/sibling-scope attack passed
  in 130.694 seconds, and the full suite passed all 181 tests in 305.833 seconds.
  Peer-authenticating bootstrap, production executor composition, and signed service
  packaging remain absent.

  The peer-authenticating bootstrap was subsequently extracted to
  `khaos/macos/KernelWorkspaceBootstrap.swift`. The signed service bundle must provide
  separate nonempty `KhaosBootstrapRequirement` and
  `KhaosWorkspaceCallerRequirement` values:
  the named bootstrap connection is checked before `resume()`, while the anonymous
  workspace listener checks the caller before accepting `workspace.run`. The XPC
  attack client now uses the bootstrap protocol itself; an ad-hoc-signed process with
  the expected identifier but a different signing identity is rejected by the OS
  when it requests the endpoint. The positive Host and picker paths retrieve and use
  the endpoint. Build-mode XPC passed in 54.456 seconds and the fresh interactive
  picker/sibling-scope run passed in 65.468 seconds on 2026-09-27; the canonical
  suite then passed all 181 tests in 325.061 seconds. This proves the shared bootstrap
  source and both identity roles in the current test bundle only;
  production service composition, signing, installation, and grant policy remain
  unimplemented. Apple documents the distinct APIs in its
  [incoming-connection](https://developer.apple.com/documentation/foundation/nsxpcconnection/setcodesigningrequirement%28_%3A%29)
  and [anonymous-listener](https://developer.apple.com/documentation/foundation/nsxpclistener/setconnectioncodesigningrequirement%28_%3A%29)
  references and [TN3127](https://developer.apple.com/documentation/technotes/tn3127-inside-code-signing-requirements).

  Final self-review moved `KernelWorkspaceBootstrapEndpoint` into the shared
  `KernelWorkspaceXPC.swift` ABI and changed the operation-caller key to
  `KhaosWorkspaceCallerRequirement`; the Host, picker, and negative client all compile
  against that one protocol definition. The fresh interactive picker/XPC attack passed
  in 96.327 seconds. The requirement lookup was then consolidated into the existing
  `XPCPeerIdentity.codeSigningRequirement` helper, which rejects absent, non-string,
  empty, and whitespace-only values. After that final source change, build-mode XPC
  passed in 53.223 seconds and the canonical suite passed all 181 tests in 313.424
  seconds on 2026-09-27. The picker positive predates this lookup-only refactor; the
  final build and full suite exercise the refactored shared parser. Production packaging
  and identity limitations still apply.

  An initial XPC disconnect run invalidated the caller, after which the next valid request did
  not reach the descriptor probe. That run's assertion did not preserve the response error code,
  so it did not distinguish an occupied operation slot from another early rejection. The
  Kernel now captures
  `NSXPCConnection.current()` for each admitted run, binds cancellation to that exact connection
  and request ID, and signals the existing worker cancellation pipe on connection interruption
  or invalidation. This keeps cleanup and the writeback cutoff in the existing Kernel path. The
  adversarial test invalidates the caller during a 20-second command, verifies the disconnected
  operation leaves no output, then runs a valid request through the same Kernel service. A
  second connection with the same test signing identity and correct request ID receives
  `process_not_active`; the submitting connection can cancel it. The focused real XPC test passed
  in 29.395 seconds on 2026-09-27. A follow-up now starts a long `workspace.run` from the
  authenticated `HostClient.xpc`, waits for its descriptor-probe marker, and has that helper send
  itself `SIGKILL`. The outer Host observes XPC interruption; a fresh helper then completes a new
  request through the same Kernel. The crashed workspace has no committed output or bypass file.
  This real process-death test passed in 45.299 seconds on 2026-09-27. It covers caller failure
  after request admission, not Kernel-worker or operating-system failure. Apple documents
  [`NSXPCConnection.current()`](https://developer.apple.com/documentation/foundation/nsxpcconnection/current()),
  [`interruptionHandler`](https://developer.apple.com/documentation/foundation/nsxpcconnection/interruptionhandler),
  and [`invalidationHandler`](https://developer.apple.com/documentation/foundation/nsxpcconnection/invalidationhandler);
  the test-only service uses the current connection to bind the request and the two callbacks to
  signal cancellation without sending messages from an invalidation handler.

  A later build-mode run returned `operation_busy` for the full existing 10-second retry window
  after a disconnected operation. The Kernel intentionally keeps the single-operation slot until
  the Worker returns and its private snapshot and APFS volume cleanup finishes. The two XPC
  recovery probes now share a 75-second bounded retry window, allowing one 60-second APFS tool
  timeout plus teardown while still failing if the slot remains occupied. The focused build-mode
  test passed in 45.494 seconds after this test-deadline correction. This changes test waiting,
  not Kernel admission or cancellation semantics.

  The native `workspace.run` probe now rejects empty or oversized bookmarks, and rejects a
  combined bookmark payload above 64 KiB, before resolving either scope or starting a Python
  child. A real authenticated XPC request supplied an oversized execution bookmark with a
  valid descriptor bookmark; the service returned `invalid_bookmark`, the descriptor probe's
  marker was absent, and the following valid request ran and completed. The focused build-mode
  XPC test passed in 36.529 seconds on 2026-09-27. This bounds admission work after NSXPC has
  decoded the `Data` arguments; it is not a transport-level memory bound, a production ABI, or
  evidence for a deployed Kernel service.

  The shared native workspace protocol is now ABI v3: its framed stream carries one opaque
  workspace bookmark, not separate caller-supplied execution and descriptor roots. The test
  adapter resolves that one bookmark, holds its root descriptor, and opens the fixed descriptor
  probe and clean execution directories with descriptor-relative `openat`, `O_DIRECTORY`, and
  `O_NOFOLLOW`. Real XPC requests replace each child directory in turn with a symlink to a
  sibling outside the bookmark; both fail with `kernel_failed` before either probe starts, with
  no output and an unchanged outside canary. Build-mode XPC passed in 52.547 seconds, and the
  full suite passed all 181 tests in 305.044 seconds on 2026-09-27. One fresh interactive picker
  rerun using ABI v3 timed out after 300 seconds without a folder selection and cleaned up its
  fixture and helper. A subsequent fresh run activated the picker immediately; after the user
  selected the workspace, the focused XPC test passed in 293.641 seconds. It verified the
  picker's selected-scope write, OS denial of workspace writes by a path-only sibling sandboxed
  XPC, Kernel output commit, unsafe changeset rejection, unchanged outside canary, and that only
  the Kernel output plus descriptor-probe marker were added. This is positive ABI v3 evidence for
  the current ad-hoc test bundle and host, not a production Trusted Launcher, persistent grant
  policy, install protection, or defense against unsandboxed same-UID writers. The production
  Trusted Launcher and executor composition remain absent.

  The bookmark-to-root boundary was moved from `tests/macos_xpc_probe/Kernel.swift` into the
  shared `khaos/macos/KernelWorkspaceRoot.swift`. It now owns scoped-resource lifetime, reuses
  the ABI bookmark-size validator for original and refreshed bookmarks, opens the root without
  following symlinks, checks device/inode identity across stale-bookmark refresh, and opens fixed
  child directories relative to the held root descriptor. The test adapter uses that same code.
  The real XPC build-mode test passed in 53.484 seconds and the canonical 181-test suite passed
  in 303.552 seconds on 2026-09-27. The executor and service bundle remain test-only.
  A post-extraction interactive picker rerun left `WorkspaceGrant` in the foreground but
  received no selection during its 300-second deadline; its helper and fixture were cleaned
  up. External-workspace grant/writeback has therefore not yet been re-proved through the
  extracted resolver.

  The first Seatbelt run from the bundled framework interpreter exposed a separate runtime
  allowlist gap: dyld could not load the framework's exact Python shared library from the
  restricted child. The runtime path collector now adds that one framework library next to
  the bundled interpreter while continuing to exclude its prefix. A focused unit test proves
  the library is allowed without opening the full Python prefix, and the real XPC execution
  probe now passes the Seatbelt capability check.

  The Launcher-opened workspace-root descriptor now remains live through snapshot capture,
  Runner execution, and trusted commit. The snapshot borrows that descriptor for its lifetime,
  and the forked committer preserves and duplicates it instead of resolving a new source root
  for its baseline scan and mutations. Absolute-path opens remain as checks that the selected
  root is still bound to its original name, and the mountpoint is reopened for the advisory
  commit lock. This closes descriptor continuity inside the tested operation; it does not
  create an external user-grant policy or prove authorization for a user-selected workspace.
  The end-to-end test uses a clean app-container fixture and does not pass the
  hardlink-contaminated descriptor tree through the snapshot copier. Existing snapshot tests
  reject `st_nlink != 1`. Persistent stale-grant handling and a production user-grant path
  remain unimplemented.

  Follow-up on 2026-09-27: a fresh interactive picker run after the root-helper extraction
  passed in 201.018 seconds. It resolved the user-selected bookmark through the shared helper,
  committed the expected Kernel output, and confirmed the path-only sibling XPC still could not
  write the selected workspace. The same XPC operation positively created symlink, hardlink,
  and FIFO changesets and proved that each was rejected before writeback, with prior output and
  the outside canary preserved and no candidate path present. A separate build-mode XPC run
  passed in 67.871 seconds, and the canonical 181-test suite passed in 324.414 seconds.
  The XPC executor and picker remain test-only; production grant persistence, Kernel
  packaging, and installation protection remain absent.

  A focused XPC run on 2026-09-27 passed in 68.555 seconds after adding scoped SDK reads to
  the same operation: the untrusted Runner read only `input.txt`, `fs.list` omitted an
  unscoped workspace file, and `fs.read` / `fs.list` requests for that file returned their
  scope errors before the fixed command and trusted commit completed. This joins the existing
  local Worker/Broker scope evidence to the XPC→Runner execution path; the native executor
  composition remains test-only. The canonical suite passed all 181 tests in 326.951 seconds
  after this addition.

  The Runner probe now also requests `fs.read("../sibling-secret.txt")` through the same
  authenticated XPC operation and receives `path_not_readable` before command execution or
  commit. The focused build-mode test passed in 69.088 seconds. A user-requested interactive
  rerun then passed in 137.345 seconds after the system picker returned a bookmark matching
  the fresh fixture; it verified the path-only sibling XPC could not write the selected
  workspace and the Kernel committed the validated output while rejecting unsafe changesets.
  These results exercise the ad-hoc test bundle only; production grant persistence, launcher,
  and executor composition remain unimplemented. The canonical suite then passed all 181
  tests in 329.005 seconds with the traversal denial included.

  The current probe gives its anonymous Runner listener the `HostClient.xpc` code requirement:
  its signing identifier plus the current executable cdhash for every architecture. The
  outer Host passes the endpoint to `HostClient.xpc` over XPC. A separate ad-hoc-signed `Spoof`
  service uses the same signing identifier but different code; the OS rejects its Runner
  request, and the disposable target snapshot has no Runner output file. Both signatures are
  ad hoc, and local code can be re-signed with a copied identifier; the cdhash pins this test
  build's code but does not authenticate a publisher or establish a production admission
  policy. The runtime still does not use these XPC services.

  The same probe sends two plugin labels through one XPC service identity. Plugin A writes
  its input into the Runner service's own application-support container; Plugin B then reads
  that value. This is a reproduced cross-plugin data leak: reusing an XPC Runner identity
  and its writable container does not isolate plugin state. The probe also packages the same
  Runner binary as two XPC services with different bundle identifiers. Plugin A writes to
  its own container, then Plugin B tries to open that exact path; the OS returns `EPERM` or
  `EACCES`, and Plugin B's own container has no such state. This confirms that distinct XPC
  service identities isolate the tested default app containers on this host. A future
  implementation could use a distinct service/container per plugin or mediate plugin storage
  through Kernel-scoped IPC without exposing shared Runner persistence. These tests do not
  cover App Group containers or a Plugin attempting to connect to another service, so bundle
  identity separation alone is not a complete production admission policy. The test
  intentionally asserts both the shared-identity leak and the different-identity denial;
  passing is OS mechanism evidence, not proof that Khaos currently enforces per-plugin
  isolation.

  The current Python CLI still has no signed app target or XPC service and does not use this
  probe as its execution path. This is OS research evidence, not an implemented Khaos
  boundary. It also does not exercise app-group data access or establish that a Runner cannot
  access the actual live workspace, because neither is connected to the fixture.
  Sources: Apple's [Process documentation](https://developer.apple.com/documentation/foundation/process),
  [App Sandbox violation guidance](https://developer.apple.com/documentation/security/discovering-and-diagnosing-app-sandbox-violations),
  [Code Signing Services](https://developer.apple.com/documentation/security/code-signing-services?changes=l_2),
  [sandbox file access documentation](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox),
  [XPC service overview](https://developer.apple.com/documentation/xpc),
  [`xpc_listener_set_peer_requirement`](https://developer.apple.com/documentation/xpc/xpc_listener_set_peer_requirement?language=objc),
  and Apple's [Creating XPC services guide](https://developer.apple.com/documentation/xpc/creating-xpc-services).
- Apple DTS has stated that the Seatbelt profile language is not documented for
  third-party use and warned against treating it as a stable product interface
  ([Apple Developer Forums](https://developer.apple.com/forums/thread/661939)).
  This backend therefore remains tied to the tested macOS host and must keep failing
  closed when the current-host enforcement probe cannot demonstrate its behavior.
- The local macOS `sandbox(7)` manual says new processes inherit the parent's sandbox.
  The nested `sandbox-exec -p "(allow default)"` test exercises this property against the
  exact command profile instead of treating the manual statement as enforcement evidence.
- Apple's
  [containerization issue 737](https://github.com/apple/containerization/issues/737)
  records the open question about a supported replacement for applying Seatbelt to
  arbitrary command-line processes. No replacement is relied on here.
- Backend reassessment on 2026-09-25: Apple's maintained
  [Containerization package](https://github.com/apple/containerization) and [`container` CLI](https://github.com/apple/container)
  run Linux containers inside lightweight Virtualization.framework VMs, one VM per
  container. The CLI currently requires Apple silicon and macOS 26, installs a system
  service under `/usr/local`, and does not isolate native macOS command processes. It is
  therefore not a drop-in backend for the current native-macOS Seed path; it remains an
  option only if Khaos explicitly chooses a Linux guest environment. The package is Apache
  2.0 licensed, but its broader VM, image, networking, and service surface would need a
  separate TCB and operations review before reuse. Sources: the project's
  [README](https://github.com/apple/container/blob/main/README.md),
  [technical overview](https://github.com/apple/container/blob/main/docs/technical-overview.md),
  and [license](https://github.com/apple/containerization/blob/main/LICENSE). Its current
  Linux container implementation writes CPU quota and memory limit into OCI cgroup resources
  and creates cgroup and PID namespaces; the CLI exposes `--cpus` and `--memory`. This is a
  concrete candidate for aggregate process-tree resource limits inside a Linux guest, but it
  changes the command environment and does not constrain native macOS processes. Neither the
  CLI nor the library has been integrated or adversarially validated by Khaos; the Apple
  `container` executable was not available on this host's `PATH`. Sources: the package's
  [`LinuxContainer` resource setup](https://github.com/apple/containerization/blob/main/Sources/Containerization/LinuxContainer.swift),
  [`container run` options](https://github.com/apple/containerization/blob/main/Sources/cctl/RunCommand.swift),
  and [ulimit documentation](https://github.com/apple/container/blob/main/docs/ulimits.md).
- Darwin memory-limit experiments on 2026-09-26 used CPython 3.13.4 and a tiny dynamically
  linked C executable compiled by Xcode clang on macOS 27.0 arm64. Both attempted to set
  `RLIMIT_AS` to 8, 16, 32, 64, 128, and 256 GiB. The Python calls failed with
  `ValueError: current limit exceeds maximum limit`; the C calls failed with `EINVAL`.
  Setting 512 GiB succeeded in both processes, and 1 TiB also succeeded in Python. Apple's
  XNU implementation validates `RLIMIT_AS` through
  `vm_map_set_size_limit(current_map(), ...)` and rejects lowering it below the current map
  size, so both launched executables already map more virtual address space than the lower
  limits before they can apply them. This does not test kernel-applied spawn attributes or
  every executable/runtime, but rules out useful `RLIMIT_AS` values set after launch by the
  current Python bootstrap or a small native launcher on this host. Even a working
  per-process limit would not impose an aggregate limit on a forked command tree. Sources:
  Apple's [`setrlimit(2)` manual](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/setrlimit.2.html)
  and the XNU [`RLIMIT_AS` enforcement path](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_resource.c).
- Chromium's maintained [macOS common Seatbelt policy](https://chromium.googlesource.com/chromium/src/+/cfbe56f17a3d7a3397a09d091252db6e3470223d/sandbox/policy/mac/common.sb)
  uses `syscall-unix` rules filtered by `SYS_*` syscall names. Khaos uses this policy
  mechanism for session and process-group changes, and relies on its own live adversarial
  test rather than Chromium policy as security evidence.
- Microsoft’s
  [MXC repository](https://github.com/microsoft/mxc) has a current cross-platform
  sandbox implementation and MIT-licensed SDK. Its repository describes itself as an
  early preview, calls out overly permissive policies, and says its profiles must not
  yet be treated as security boundaries. The multi-platform runtime and TypeScript SDK
  are also broader than this bootstrap. It is a useful research source, not a dependency
  or authority source for this implementation.
- The legacy Khaos repository has a Seatbelt backend and real macOS tests. Its
  execution service, profile composition, and policy model are coupled to the legacy
  runtime, so this project reuses only the deny-by-default and executable-probe lessons.
- Apple's [DNS networking guidance](https://developer.apple.com/documentation/technotes/tn3151-choosing-the-right-networking-api)
  recommends the system resolver APIs such as `getaddrinfo()`. Apple's [sandbox violation
  guide](https://developer.apple.com/documentation/security/discovering-and-diagnosing-app-sandbox-violations)
  shows a resolver-related denial at `/private/var/run/mDNSResponder` and notes that system
  libraries can be stopped by sandbox constraints. Khaos now tests both direct access to
  that local endpoint and a `getaddrinfo()` call under its own Seatbelt profile. The latter
  checks a PID-correlated unified-log denial from the current resolver path; it does not
  establish behavior for every resolver configuration or macOS release.

## 2026-09-28 interactive Picker retry

The canonical suite passed all 182 tests in 322.529 seconds. A user-requested fresh
interactive rerun then created a new temporary `user-selected-workspace` and launched the
signed `WorkspaceGrant.app`. The focused test confirmed the helper was frontmost and waited
for the native directory selection, but no selection or cancellation arrived within its
300-second bound. It ended with `subprocess.TimeoutExpired` after 376.117 seconds. The test
terminated the helper and removed the temporary root; process inspection found no surviving
helper or test process. The CUA app inventory saw the temporary app, but attachment timed out,
so this run produced no new external-workspace grant or Kernel writeback evidence. It does not
replace the earlier successful interactive run recorded above.

## 2026-09-28 Picker write-scope release

Apple documents that the OS starts scope for a URL returned by `NSOpenPanel`, and that a
security-scoped bookmark with `withSecurityScope` plus
`securityScopeAllowOnlyReadAccess` can retain read-only access in a receiving process
([App Sandbox file access](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox),
[bookmark creation options](https://developer.apple.com/documentation/corefoundation/bookmark-data-creation-options)).
`TrustedWorkspacePicker` now returns the existing Kernel bookmark, a read-only bookmark,
and the original `NSOpenPanel` URL so the exact implicit scope can be balanced. The interactive
probe stops that original URL before operations,
resolves the read-only bookmark, requires `O_RDONLY` to succeed and `O_WRONLY` to fail, then
continues the Kernel writeback checks. The test process also checks committed bytes after the
Picker helper exits.

The canonical suite passed all 182 tests in 322.896 seconds before the final change that
retains the original panel URL. After that change, the headless XPC build-mode test compiled
the revised picker and passed in 75.966 seconds; it does not execute this selection-dependent
permission transition. A fresh interactive rerun brought the Picker to the foreground but
received no selection or cancellation within 300 seconds; it ended with
`subprocess.TimeoutExpired` after 376.136 seconds and cleaned the helper and temporary root.
Therefore the new Picker write denial and corresponding Kernel write success are not yet
verified on a user-selected external workspace.

After the user requested another reopen, a fresh run again brought the signed
`WorkspaceGrant.app` to the foreground. No directory selection or cancellation arrived
within 300 seconds; the focused test timed out after 387.031 seconds and removed its
temporary root. `System Events` confirmed the helper was foregrounded. The CUA app
inventory saw it, but attaching to its window timed out. This run adds no selected-grant
or Kernel writeback evidence.

The headless unselected-bookmark fixture now creates its workspace inside the sandboxed
app's own Application Support and sends a plain `options: []` bookmark. The fixed
`KernelProduction.xpc` executor returned `workspace_rejected`, and the probe verified no
input change, output, or bypass file. The focused build-mode XPC test passed in 86.472
seconds. This is evidence for this fixed entrypoint and fixture only; it does not prove
selected external-workspace access, behavior of other XPC services, or active executor
cancellation.

The canonical command `python3 -m unittest discover -s tests -v` passed all 182 tests in
322.971 seconds on this host. The suite does not open the interactive Picker or prove a
fresh external-workspace grant.

This difference is specific to the service composition: the older `KernelExecution.xpc`
probe uses a separate test adapter and a different parent app container, so its app-container
fixture result does not establish the fixed Python executor's behavior. Apple documents app
data containers as identity-bound, notes that processes outside the app group may need user
authorization to access them, and lists XPC services among processes that may intentionally
share an app group ([Protecting local app data using
containers](https://developer.apple.com/documentation/xcode/protecting-local-app-data-using-containers)).
Khaos does not broaden Kernel access to Host-private app data to make a test fixture work;
only an explicitly selected workspace bookmark should authorize workspace access.

The interactive write-scope reprobe selected the expected temporary workspace once,
then failed when the helper attempted to restart its explicit read-only bookmark scope.
Apple's [App Sandbox file-access documentation](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox)
requires resolving an explicit scoped bookmark with `withSecurityScope`; the helper
previously passed `[]`. That resolver was corrected. A subsequent selected run still
returned `EPERM` before adding `com.apple.security.files.bookmarks.app-scope` to the
temporary sandboxed Picker app. The entitlement is now test-only, and the no-picker
build-mode XPC test passed in 110.747 seconds; it does not exercise bookmark resolution
after user selection. The canonical suite passed all 184 tests in 387.453 seconds.

The next interactive run confirmed `WorkspaceGrant` was foregrounded, but received no
selection within 300 seconds; it timed out after 409.603 seconds and cleaned its helper
and fixture. Thus the latest read-only scope restart, Picker write denial, and selected
Kernel writeback remain unverified. Do not infer success from the earlier picker test or
from build-mode coverage.

A later selected retry still returned `EPERM` after both the `.withSecurityScope` resolver
option and test-app bookmark entitlement were present. The shared Picker now creates the
read-only bookmark from the original URL returned by `NSOpenPanel`, preserving that URL's
active selection scope; it continues to return a canonical URL for root identity checks.
Apple documents that AppKit panels start security-scoped access on the URL they return
([file-access documentation](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox)).
The headless build-mode XPC test compiled and passed this source change in 109.623 seconds.
The canonical suite then passed all 184 tests in 387.692 seconds on this tree.
The following interactive run foregrounded `WorkspaceGrant` but received no selection
within 300 seconds; it timed out after 408.758 seconds and cleaned the helper and fixture.
This source change therefore has no selected-path permission or Kernel writeback evidence.

## Adversarial finding

On the current macOS host, a direct Seatbelt rule granting
`file-read*` and `file-write*` to a workspace `subpath` permits access through a
pre-existing hard link in that workspace. A local test read an outside canary through
such a link and overwrote it through the same link. A `deny network*` rule rejected
IPv4/IPv6 loopback connections, an explicit HTTP proxy connection, a direct UDP DNS query,
and direct access to the macOS resolver socket with `EPERM`/`EACCES`; a forked child also
could not connect to loopback. The controlled UDP listener received no query packet.

Therefore path-scoped Seatbelt access alone is insufficient for a writable live
workspace. The snapshot copier opens each directory component without following
symlinks, copies regular files into new inodes, rejects files with multiple hard links,
rejects special files and cross-device entries, applies size/depth/count limits, and
fails if an entry changes during copying. The writable snapshot probe grants only
data/create/unlink operations under the disposable snapshot, denies mode changes and
child creation, process-group changes, and replacement with an unrelated executable,
and tests that the OS rejects a new hard link to a specifically readable outside canary.
Direct outside reads, writes through an existing symlink, outside writes, and network
connections also fail under the live Seatbelt profile.

The commit-profile test also feeds an untrusted path component containing a backslash-quote
sequence and SBPL syntax into a real `file-write*` literal. Its remaining path components spell
the absolute path of an outside canary, forming a second write matcher if the path string is not
escaped correctly. Under the generated profile, a planned workspace write succeeds, the outside
write returns `EPERM` or `EACCES`, and the canary remains unchanged. This exercises that injection
shape on the current host; it does not establish parser behavior for every unusual pathname or
macOS release.

On the current host's case-insensitive APFS volume, an NFC filename and its NFD spelling resolve
to the same entry, as does a case-swapped spelling. The real Seatbelt Runner test obtains the
spelling returned by directory enumeration, confirms each alternate spelling identifies that
same source file, then exercises them over authenticated Runner IPC: the enumerated spelling
reads the file, while each alias receives `path_not_readable`; listing through an alias receives
`path_not_listable`. This evidence is limited to the current case-insensitive APFS test volume
and does not characterize every filesystem's name semantics.

Apple XNU defines `KERN_PROCARGS2` as sysctl MIB value `49` under `CTL_KERN` ([Apple XNU
`sysctl.h`](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/sysctl.h)).
A local host-side positive control confirmed that querying it returns a target process's
argument and environment area, and read a fixed command's random argv canary through this
interface. The Runner profile now explicitly denies `process-info*` and re-allows only
`(target self)`; relying on `(deny default)` with a self allow was insufficient for this
known-PID query. A Seatbelt Runner probe given the exact target PID now receives `EPERM` or
`EACCES` from `KERN_PROCARGS2`, while the unconfined positive control still reads the canary. The
profile also grants only the exact runtime metadata sysctls needed by Python instead of
generic `sysctl-read`. This proves the tested process-info route on the current macOS host;
it does not cover other OS interfaces, macOS releases, or other secret channels such as
logs, environment inheritance, and file descriptors.

The end-to-end Kernel execution chain now also tests the untrusted fixed command. An unconfined
positive-control process exposes unique argv and environment canaries through
`KERN_PROCARGS2`; the Seatbelt command receives only that process's PID and must get
`EPERM` or `EACCES` on the sysctl size query before it can read the returned buffer. The
command completes through Runner IPC and trusted commit with no workspace changes. This
confirms the command profile's process-info denial for the tested host and syscall; it does
not prove denial through every macOS process-inspection or logging interface.

This does not yet prove the complete trust boundary: there is no Agent Host or Candidate
Plugin lifecycle, production peer identity validation, protected Kernel installation,
exclusive Kernel write authority, user-approved `process.exec` capability, per-command
memory quota, Agent-controlled cancellation, or complete Seed attack matrix.

## Changeset implementation reference

The implementation uses Python's descriptor-relative `os.open`, `os.stat`, `os.unlink`, and
`os.rmdir` operations and refuses to run if those APIs are unavailable. New files use Apple's
`fclonefileat` to atomically create a distinct inode from an already-open source descriptor;
the source and destination are on the same APFS volume, and an existing destination fails
with `EEXIST`. The current macOS system manual documents descriptor-source semantics, atomic
creation, and failure on filesystems without clone support
([`clonefile(2)`](https://keith.github.io/xcode-man-pages/clonefile.2.html)).
Existing-file replacement and removal call macOS `renameatx_np` through `ctypes` with
directory descriptors, using the system's `RENAME_SWAP` primitive; they fail closed on
other platforms or filesystems without support when a swap is required. Apple exposes
whether a volume supports swap renaming through
[`volumeSupportsSwapRenaming`](https://developer.apple.com/documentation/foundation/urlresourcevalues/volumesupportsswaprenaming),
and the [macOS system call reference](https://keith.github.io/xcode-man-pages/rename.2.html)
documents `renameatx_np` and `RENAME_SWAP`.

The focused [`atomicswap` library](https://github.com/nickovs/atomicswap) provides a
MIT-licensed `renameatx_np` wrapper with directory-descriptor arguments and no
non-standard macOS dependencies. Its latest PyPI release is from February 2023
([package history](https://pypi.org/project/atomicswap/)); adding a runtime package to
this repository's currently dependency-free prototype was not justified for its short
platform binding. The Khaos code therefore calls the documented OS primitive through
the standard library's `ctypes`; no utility implementation is vendored.

A macOS APFS race test replaces a newly scanned snapshot file with a symlink to an outside
canary at the `before_live_mutations` boundary. The committer installs the bytes already
copied into private staging as a single-link regular file, and the canary remains unchanged.
This proves the tested writeback uses the captured staged bytes after that pathname changes;
it does not establish that arbitrary same-UID processes cannot access the private snapshot.
An independent same-UID process also creates a destination entry immediately before
`fclonefileat`: both a regular file and a symlink to an outside canary are covered. The atomic
clone fails without replacing either racing entry, the temporary staged file is removed, and
the canary remains unchanged. This evidence covers those exact destination-appearance races;
it does not establish global arbitration against other same-UID workspace writers.

## Fixed Kernel executor bundle write denial probe

The signed test app's App-Sandboxed Host attacks the `KernelExecution` helper, fixed
`KernelProduction` executable, bundled Python bridge, changeset implementation, and Python
interpreter with write-open, create, chmod, hardlink, `renameatx_np(RENAME_SWAP)`, replacement
rename, symlink replacement, and unlink. It also tries a same-volume atomic swap of each
containing XPC bundle with a directory in its own app container. The container write control
succeeds; each protected operation fails with `EPERM` or `EACCES`. The test confirms the
source and target are on the same filesystem before rename attacks, checks every target
digest, and verifies each XPC bundle's deep code signature afterward. The focused build-mode
XPC test passed on 2026-09-28 in 89.037 seconds. This is real App Sandbox evidence for these
paths in a temporary ad-hoc signed bundle on this host; it does not establish a protected
production installation, updater behavior, or resistance to an unconfined same-UID process.
The subsequent canonical suite passed all 182 tests in 322.741 seconds, including this
write-denial probe and the existing real Seatbelt and changeset-race attacks. It did not
open the user Picker or establish an external-workspace grant.

On 2026-09-28, a user-requested interactive retry rebuilt the temporary fixture and launched
the signed `WorkspaceGrant.app`. The focused test confirmed the helper was frontmost, but no
selection or cancellation reached `NSOpenPanel` within its 300-second bound; the run ended
with `subprocess.TimeoutExpired` after 377.411 seconds. CUA attachment timed out, and
post-run checks found neither the helper nor its temporary fixture. This retry produced no
external-workspace grant or Kernel writeback evidence. It does not replace the earlier
successful interactive test-only path.

## Interrupted APFS image creation cleanup

`hdiutil create` may leave a DiskImages device registered after its command process times
out or is cancelled. Image cleanup now compares the canonical image path against
`hdiutil info -plist`, detaches only the whole device belonging to that exact image, and
waits for the inventory record and requested mountpoint to disappear. A private marker stays
with the temporary root for the full image-operation lifetime. Worker cleanup checks marked
roots before its ordinary stale-directory cleanup; if no stable OS identity is available,
it preserves the backing directory instead of deleting a path a helper may still be using.
Cancellation remains reported as cancellation even when cleanup must preserve that root.

The real macOS probe creates an APFS sparsebundle, attaches it with `-nomount`, and verifies
that cleanup removes that exact device from `hdiutil` inventory without a mounted volume.
A separate probe verifies that an abandoned pending marker is preserved when inventory has
no matching OS identity. The Launcher attach-cancellation and XPC cancellation attacks passed
on 2026-09-28. The final canonical suite passed all 184 tests in 383.827 seconds. One earlier
full run hit the existing 60-second `hdiutil create` bound on the concurrent replacement
test. Its exact path was absent from `hdiutil` inventory and `diskutil list` after cleanup;
the focused test and all 27 Broker tests passed, and the later full run passed. Historical
unmatched inventory entries were left untouched. If identity remains unresolved, a marked
private temporary root can remain; this change does not add a global janitor for such roots.

## Programmatic app-container bookmark rejection

The headless XPC probe now checks both a plain bookmark and a bookmark created with
`.withSecurityScope` for a directory inside the App-Sandboxed launcher's own Application
Support, without opening the system picker. The fixed `KernelProduction.xpc` executor
returns `workspace_rejected` for both; the input stays unchanged and no output or bypass
file appears. The focused build-mode XPC suite passed in 109.555 seconds on 2026-09-28.
This proves that requesting the bookmark option in this flow does not replace a user
selection. It does not prove an external-workspace grant or the active cancellation path,
which still needs a valid picker-created bookmark. Apple documents that an app-scoped
bookmark cannot grant another sandboxed app access unless it has the creator's code-signing
identity ([`bookmarkData(options:includingResourceValuesForKeys:relativeTo:)`](https://developer.apple.com/documentation/foundation/nsurl/bookmarkdata%28options%3Aincludingresourcevaluesforkeys%3Arelativeto%3A))); the observed Kernel result is recorded directly and is not attributed to that rule.


## 2026-09-28 picker retry without selection

The user-requested interactive rerun rebuilt the temporary workspace and signed helper.
`System Events` confirmed `WorkspaceGrant` was frontmost, but the picker received no folder
selection or cancellation within its 300-second bound. The focused run ended after
409.692 seconds with `subprocess.TimeoutExpired`; the test terminated the helper and
removed its temporary fixture. This adds no user-selected-grant or Kernel-writeback
evidence and does not replace the earlier successful test-only picker runs.


## 2026-09-28 outbound Kernel XPC identity check

The shared `XPCPeerIdentity.requirePeerIdentity()` now configures macOS code-signing
validation for either side of an XPC connection. The test Launcher applies the signed
bundle's designated requirement before resuming both the named Kernel bootstrap
connection and each connection made from its returned endpoint. The two embedded Kernel
services are signed with the temporary test identity; their requirements are kept in the
Launcher `Info.plist`, which is sealed by the final app signature. Missing requirements
fail before a connection resumes.

The headless attack connects to the real, reachable sandboxed `UntrustedHost.xpc` using
the `KernelProduction` service requirement, then asks for a harmless write probe. macOS
reports `NSXPCConnectionCodeSigningRequirementFailure` and no method reply arrives; the
outside canary remains unchanged. A correctly pinned `KernelProduction.xpc` still answers
the idle-cancel bootstrap probe. The focused build-mode XPC test passed in 110.251 seconds
on 2026-09-28. Apple documents this client-side API and demonstrates setting the service
requirement before `resume()` in [`NSXPCConnection.setCodeSigningRequirement`](https://developer.apple.com/documentation/foundation/nsxpcconnection/setcodesigningrequirement%28_%3A%29).
This exercises real OS identity enforcement on temporary test identities; it does not
establish a shipped Launcher, release signing identity, or protected service installation.


The canonical command `python3 -m unittest discover -s tests -v` then passed all 184 tests
in 375.548 seconds on 2026-09-28. This default run did not open the interactive Picker;
the outbound peer-mismatch attack was exercised by the focused `KHAOS_RUN_WORKSPACE_GRANT_UI=build`
run above.

## 2026-09-28 current Picker write-scope retry

The current `TrustedWorkspacePicker.swift` code was exercised with a fresh
user-selected temporary workspace. The helper passed selection and reached the
XPC/Worker path, but exited with `NSPOSIXErrorDomain` code 1 before returning its
evidence report. That run predates stage labels around Kernel-bookmark creation
and read-only-bookmark resolution, so it does not identify the failing operation
or prove a writeback result. The focused test failed after 328.352 seconds. A
second diagnostic run opened the picker but received no selection within 300
seconds; it timed out after 409.067 seconds and cleaned its helper and fixture.
Build-mode validation of the diagnostic change passed one focused test in
110.146 seconds. Picker write denial and current-code external-workspace commit
remain unverified.

The Kernel transfer bookmark was then changed to use the original panel URL with
`options: []`, keeping the system-granted implicit scope in the XPC bookmark;
the canonicalized URL is still used for root identity checks. Apple documents
this bookmark form for passing file access to an XPC service. The updated
build-mode test passed in 119.557 seconds. A new interactive run received no
selection within 300 seconds, timed out after 408.694 seconds, and cleaned its
fixture. The bookmark-source fix therefore has no new selected-workspace or
writeback evidence.

## 2026-09-28 user-requested Picker retry

The focused `KHAOS_RUN_WORKSPACE_GRANT_UI=1` XPC run reopened the signed test
`WorkspaceGrant.app`. `System Events` confirmed that `WorkspaceGrant` was the
foreground process, but no directory selection or cancellation arrived within
the test's 300-second wait. The run ended with `subprocess.TimeoutExpired` after
409.627 seconds; test cleanup removed the helper and temporary fixture. This
attempt adds no external-workspace authorization, Picker write-denial, or
Kernel-writeback evidence. The canonical full-suite process was separately
interrupted before completion and is not a passing suite result.

The canonical command was then rerun and passed all 184 tests in 402.372
seconds on 2026-09-28. This default headless run did not open the Picker and
does not add external-workspace grant or Picker write-scope evidence.

## 2026-09-28 shared outbound XPC client

`KernelWorkspaceClient.swift` now owns the authenticated setup for named bootstrap
connections and returned anonymous endpoints. Both paths apply the requirement read
from the caller bundle before `resume()`; the endpoint target retains that same
requirement for the second connection. The adversarial wrong-identity probe uses the
same setup helper while keeping a protocol-compatible test service, so it can assert
the exact `NSXPCConnectionCodeSigningRequirementFailure` from macOS. This uses native
NSXPC and the existing `XPCPeerIdentity`; no library or new platform layer was added.

The focused headless test passed in 109.901 seconds. The 184-test canonical suite
result above predates this extraction and was not repeated. No Picker was opened, so
this change adds no new selected-workspace grant, Picker write-scope, or Kernel
writeback evidence. The signed service and calling app remain temporary test bundles;
there is still no production Trusted Launcher or installed Kernel service.

## 2026-09-28 local Seed app composition

`tools/build_macos_seed.py` now assembles `KhaosSeed.app` and its fixed
`KernelProduction.xpc` from shared sources. The app has App Sandbox and the
user-selected read/write file entitlement; it no longer requests app-scope bookmarks
because it transfers one-run `options: []` bookmarks. The embedded service is signed under the same
stable code identity, with its caller and service requirements sealed into the respective
bundle Info.plists. The service embeds the current Python.framework and `khaos` package;
the copied external `site-packages` link is removed so host Python packages are not part
of the runtime. The local build uses the current architecture and requires an available
non-ad-hoc signing identity. It does not enable the service App Sandbox, Hardened Runtime,
notarization, installation, or updater policy.

`TrustedWorkspaceLauncherMain.swift` provides the app entrypoint. Its default path opens
the existing trusted picker, releases the panel's implicit write scope, and sends one
fixed `/usr/bin/true` request with an empty workspace read scope. `--bootstrap-check`
opens no picker and verifies both the named service and anonymous endpoint connections.
The isolated package test passed in 7.395 seconds: it built and deeply verified the local
bundle, ran that bootstrap check, and confirmed the OS rejected an ad-hoc client with the
same bundle identifier but a different signing identity. The test does not submit a
workspace bookmark or run the executor. The new app's selected-workspace execution and
writeback remain unverified; no Picker was opened. The 184-test canonical suite result
above predates these app sources and the request helper refactor and was not repeated.

## 2026-09-28 production Picker composition attempt

The locally signed `KhaosSeed.app` was launched with its system Picker. Unified logs show
the AppKit open/save panel service, bookmark creation in the app, authenticated named and
anonymous XPC connections to `KernelProduction`, and Kernel-side bookmark resolution.
The bundled Python bridge and APFS image tools then started. The app later exited after
AppKit mouse actions. That sequence is consistent with the old generic failure alert being
dismissed, but the logs do not prove that. Success was printed only to GUI stdout; neither
the app result nor a `workspace.commit` receipt was captured. This is evidence that a
Picker-created bookmark reached the production Kernel and snapshot setup began, not proof
that the Runner completed or any changeset was committed. The prepared temporary fixture
remained unchanged in the observed filesystem listing.

The Launcher now emits only fixed, allow-listed outcome codes through the unified log
subsystem `org.khaos.Seed` / `workspace-smoke` and shows a success or failure alert. It
does not log workspace paths, command output, or file contents. The focused product-app
test passed after this change in 6.877 seconds; it rebuilds and signs the app, checks
bootstrap, and verifies OS rejection of a wrong-signer client, but does not open the
Picker or execute the workspace request. The production Runner completion and trusted
commit therefore remain unverified, and the canonical suite was not rerun.

The focused headless XPC integration test then passed on this current tree:
`env -u KHAOS_RUN_WORKSPACE_GRANT_UI python3 -m unittest discover -s tests -p
test_macos_xpc_sandbox.py -k
test_xpc_sandbox_scope_peer_identity_and_service_container_identity -v` (one test,
104.553 seconds). It exercises bounded/authenticated XPC, real APFS snapshot setup,
Seatbelt Runner restrictions, one trusted output commit, and rejection of symlink,
hardlink, and special-file output while preserving prior output and an outside canary.
The test also rejects programmatically minted app-container bookmarks without writeback.
Its positive workspace is a disposable test fixture; it does not prove the fresh
Picker-created external grant or the product Launcher's default workspace request.

## 2026-09-28 signed Seed App interactive Picker smoke (older bundle)

A locally signed `KhaosSeed.app` was launched against a temporary workspace. The user selected
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-picker-b_oua14q/Workspace`
in the system Picker and confirmed that the app displayed its pass alert. That alert
is reachable only after the fixed `/usr/bin/true` request returns through the
authenticated Kernel XPC path and the Launcher accepts an exact no-change result:
exit code zero, empty stdout/stderr, and zero added, modified, and deleted entries.
The Runner source calls both `process_exec` and `workspace_commit`; the Kernel
executor validates the returned result before replying.

The temporary workspace still contains only its original
`seed-picker-fixture.txt`, whose SHA-256 matches the bytes written before launch.
Subsequent `codesign` inspection of this exact bundle showed that it still had the
`com.apple.security.files.bookmarks.app-scope` entitlement. The run is positive evidence
for this signed bundle's user-selected bookmark, Runner completion, and no-change commit
path; it does not verify the current builder after that entitlement was removed. It also
does not demonstrate a non-empty changeset writeback, execution of attacker-controlled
Candidate source, Picker write-scope denial, app installation integrity, or an
App-Sandboxed Kernel service. A current-builder package test now reads the signed
entitlements and verifies the app sandbox, user-selected read/write grant, absent
app-scope bookmark entitlement, and unsandboxed Kernel service; it passed in 7.154
seconds. A selected Picker run with that exact entitlement set remains unverified.

## 2026-09-28 selected Picker scope and XPC attack retry

The focused real-OS XPC test was run with
`KHAOS_RUN_WORKSPACE_GRANT_UI=1`. In the selected run, the shared Picker helper
released the panel's implicit read/write scope, successfully reopened its explicit
read-only bookmark, and reached a direct `open(O_WRONLY)` denial on the fixture input.
The same helper then completed the `KernelExecution` one-file writeback checks and
confirmed the path-only sibling XPC could not write. It subsequently failed while
starting the separate `KernelProduction` attack group: macOS reported
`sandbox_extension_issue_file_to_process` / `EPERM` for the probe app. The focused test
therefore failed overall; it did not reach the production unsafe-changeset or active
cancellation assertions.

The failing probe had created an explicit `.withSecurityScope` bookmark for a nested
workspace used only for this one XPC request. The test now creates that transfer
bookmark with `options: []`, matching the product Picker's one-run transfer. Apple's
[App Sandbox file-access documentation](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox)
describes passing an implicit-scope bookmark to another process and reserves explicit
security-scoped bookmarks for access that must persist across launches. A later
interactive retry did not receive a selection within 300 seconds; the focused test
timed out after 408.723 seconds and cleaned up its helper and fixture. The corrected
transfer form is therefore not yet interactively verified.

The no-picker build-mode test passed on this tree with
`KHAOS_RUN_WORKSPACE_GRANT_UI=build python3 -m unittest discover -s tests -p
test_macos_xpc_sandbox.py -k
test_xpc_sandbox_scope_peer_identity_and_service_container_identity -v` (one test,
109.250 seconds). It compiles the changed probe and exercises headless XPC denials;
it does not validate a selected bookmark or the production executor writeback path.
The separate signed product-app Picker run recorded above remains a successful
zero-change smoke, not evidence for this non-empty changeset attack sequence.

## 2026-09-28 Picker authority reduction

`TrustedWorkspacePicker` no longer creates a second explicit read-only bookmark;
that value was consumed only by the test probe, not the product Launcher. The probe
now opens its fixture input for write as a positive control while the `NSOpenPanel`
scope is active, closes that descriptor, stops the scope, and requires a new write
open to fail with `EPERM` or `EACCES`. It then sends the original one-run
`options: []` bookmark to Kernel. The product app builder also removed
`com.apple.security.files.bookmarks.app-scope`, which its current flow no longer uses.
Apple documents `stopAccessingSecurityScopedResource()` as revoking panel access and
`options: []` bookmarks as suitable for one-run transfer to another process in its
[App Sandbox file-access documentation](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox).

The earlier product app packaging/authentication test passed after the builder change
(one test, 7.195 seconds), but it did not inspect signed entitlements. The updated
product package test now asserts the signed app has App Sandbox plus user-selected
read/write access, no app-scope-bookmark entitlement, and that the Kernel service is not
App-Sandboxed; it passed in 7.154 seconds. The focused XPC build-mode test passed with
the simplified probe (one test, 109.402 seconds); it compiles the test app and runs
headless XPC attacks, but does not select a workspace. The selected smoke above came
from a bundle whose signature still contained app-scope bookmarks, so it does not verify
the current reduced-entitlement product path. The current direct-revocation probe and
full `KernelProduction` unsafe-changeset/cancellation sequence remain unverified.
Earlier selected evidence for direct Picker write denial came from the prior probe
variant that reopened an explicit read-only bookmark; it does not validate the
simplified probe.

## 2026-09-28 latest current-tree validation

The focused interactive XPC test was started with
`KHAOS_RUN_WORKSPACE_GRANT_UI=1` after the direct-revocation probe was simplified.
`WorkspaceGrant` reached the foreground Picker for
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-xpc-sandbox-p3kaw1rr/user-selected-workspace`,
but received no selection within its 300-second wait and exited with
`subprocess.TimeoutExpired` after 419.214 seconds. Test cleanup removed the helper and
fixture. This run produced no new Picker write-denial, selected-bookmark transfer,
`KernelProduction` changeset, or cancellation evidence; it is a missing selection, not a
security assertion failure.

Afterward, the repository's canonical `python3 -m unittest discover -s tests -v` suite
passed all 185 tests in 384.048 seconds on the current tree. It includes real macOS
Seatbelt/APFS attacks and the headless XPC checks, but does not open the interactive
Picker and does not close the selected-workspace evidence gap above.

## 2026-09-28 current probe and product Picker follow-up

The test-only `WorkspaceGrant` probe now transfers the original Picker root bookmark to
`KernelProduction`; it no longer creates an explicit bookmark for a nested
`kernel-workspace` directory. Production fixtures and the sibling canary are rooted at
the selected workspace, while the Runner's read scope remains `production-input.txt`.
This aligns the probe with the product's one-run Picker grant and avoids an extra
test-only bookmark-creation step. Apple documents `options: []` bookmarks for one-run
transfer to another process in its [App Sandbox file-access documentation](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox).

The focused build-mode test passed in 109.470 seconds, and the canonical
`python3 -m unittest discover -s tests -v` suite passed all 185 tests in 383.060 seconds.
Both are headless for the selected `WorkspaceGrant` path. The user then selected an
external workspace in a fresh locally signed `KhaosSeed.app` built with the reduced
entitlement set and confirmed its fixed smoke displayed `PASS`. The workspace fixture
hash remained
`e15de7f2e6c2cfe2e8b4f4aafe7f79ada1b50b1b50a90695d207a22e12b13d1e`. This validates only
the fixed `/usr/bin/true` route through Kernel XPC, Runner, and the exact zero-change
commit result. Post-run deep signature verification found new Python `__pycache__`
files inside the signed framework. Fixed isolated Python launches now pass `-B`; the
executor also passes `PYTHONDONTWRITEBYTECODE=1` for non-isolated descendants. The
focused product package test passed in 7.743 seconds, checking nested imports and deep
signature verification afterward. Launcher (24), Seatbelt (37), and Broker (27) suites
passed serially. The canonical `python3 -m unittest discover -s tests -v` suite then
passed all 185 tests in 361.049 seconds. The user later confirmed the reduced-entitlement product app displayed PASS. Its
selected fixture SHA-256 was
c00d07fbc2916475914e8ccf2fbbb10c255a41ebc775898bb4ca2294df614659 before and after
the run; post-run codesign --verify --deep --strict passed, with no __pycache__ left
inside the signed Python framework. This proves only the fixed zero-change route. A subsequent run of the updated `WorkspaceGrant` helper opened
its Picker but received no selection within 300 seconds; it timed out after 408.852
seconds and cleaned up its fixture. Therefore the new root-bookmark transfer, Picker
write-scope revocation, non-empty Production writeback, unsafe changeset rejection, and
cancellation remain unverified interactively.

## 2026-09-28 latest WorkspaceGrant Picker retry

After the user confirmed the reduced-entitlement product app's zero-change PASS, the
focused XPC attack test was reopened with a fresh workspace at
/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-xpc-sandbox-xfgwfbv2/user-selected-workspace.
The helper was confirmed frontmost; no directory selection arrived within 300 seconds.
The focused test ended with subprocess.TimeoutExpired after 379.907 seconds and cleaned
the fixture. Consequently, this run did not execute the current Picker write-denial,
non-empty Kernel commit, unsafe changeset, or cancellation assertions. It is an
unselected interaction timeout, not a failed security assertion.

## 2026-09-28 fixed product writeback smoke source

The product Launcher no longer runs `/usr/bin/true`. Its fixed command writes a
UUID-named marker inside the private snapshot, with no workspace read scope. The
Launcher invokes `workspace.commit` only after a successful command exit and accepts
only the exact result shape: return code zero, empty stdout/stderr, one addition, no
modifications, and no deletions. `set -C` prevents a UUID collision from overwriting
an existing file. The Picker tells the user to select a disposable workspace and
warns that one uniquely named file will be created.

Focused package/signature validation, the real Seatbelt commit/direct-write-denial
test, the headless XPC build-mode test, and the canonical 185-test suite passed on
this source state. They do not establish a selected-workspace product run. The user
reported PASS for the selected temporary workspace
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-picker-b_oua14q/Workspace`,
but inspection found only its existing fixture and no marker. Treat that PASS as
unattributed to the current binary until a fresh build produces the named file and
the post-run bundle signature is checked. The current product non-empty writeback
remains unverified.

The current source was rebuilt as
`/tmp/KhaosSeed-writeback-20260928-review.app`. The focused product package/XPC test
passed (1 test, 7.742 seconds); `codesign --verify --deep --strict` passed both
before and after its read-only `--bootstrap-check`, which returned
`kernel-xpc-peer-authentication=verified` with exit 0. The bootstrap emitted
`sandbox_extension_issue_file_to_process failed ... Operation not permitted` on
stderr. No Picker was opened and no workspace request was made. No `__pycache__`
directory appeared in the signed bundle. The warning is not attributed yet; the
interactive current-source writeback remains pending.

## 2026-09-28 fresh focused Seatbelt evidence

The current tree passed five fresh tests against the real macOS Seatbelt backend:

- `test_separate_kernel_commits_sandbox_output_and_denies_live_write` (3.616s):
  private snapshot output committed, while direct live-workspace writes, traversal,
  writing an outside canary, and moving the workspace parent failed under Seatbelt.
- `test_kernel_chain_blocks_disk_image_mount_and_commits_safe_output` (5.141s):
  an unconfined positive control attached an APFS image; the sandboxed command's
  attach attempt failed and its separate regular-file output was still Kernel-committed.
- `test_kernel_rejects_new_symlink_from_sandbox_output` (3.640s),
  `test_kernel_rejects_hardlinked_files_from_sandbox_output` (3.683s), and
  `test_kernel_rejects_fifo_from_sandbox_output_without_partial_writeback` (3.630s):
  each malicious changeset was rejected as a whole, with no safe sibling file partially
  written to the real workspace and existing baseline/canary content preserved.

These results strengthen the shared Kernel→snapshot→Seatbelt Runner→validated commit
evidence. They are not product Picker/XPC results and do not resolve the current app's
pending user-selected workspace check.

The output-metadata attack passed (3.698s): the Runner created ordinary output while
the OS denied chmod and `setxattr`; the committed file and directory retained the
Kernel's 0600/0700 modes and no injected extended attribute.

Two fresh Broker commit-race tests also passed under real Seatbelt: a synchronized
concurrent replacement of a destination (1.664s) and moving a parent directory after
the committer opens it (1.659s). The former preserves the replacement's bytes/inode
and reports `commit_outcome_uncertain`; the latter receives OS denial when the
committer tries its stale dirfd and preserves the moved target's bytes. The evidence
covers those controlled race windows only and does not claim global same-UID write
coordination.

Failure-containment probes passed as well: `test_launcher_death_kills_command_descendant_and_discards_snapshot`
(3.828s) and `test_kernel_worker_death_cleans_command_group_and_snapshot` (14.125s).
The first killed the launcher while a sandbox command and child were active; both
processes exited and uncommitted output never reached the real workspace. The second
killed the actual Kernel worker; the caller received `kernel_ipc_failed`, command
descendants and the worker process group were reaped, the APFS snapshot/image were
removed, and the workspace retained its original file. This is current-host process
failure evidence, not a claim of Kernel availability after arbitrary OS or host failure.

Three real-Seatbelt network probes passed: IPv4 loopback TCP plus UDP/DNS and a
localhost HTTP proxy, including a child process (1.883s); IPv6 loopback (1.715s);
and macOS `mDNSResponder` Unix-socket access over stream and datagram sockets (1.823s).
The tests bind local positive-control listeners/resolver and require OS `EPERM` or
`EACCES` denial inside the sandbox. This is current-host backend evidence, not a
portability claim for unsupported operating systems.

The focused headless XPC probe passed again on 2026-09-28:
`KHAOS_RUN_WORKSPACE_GRANT_UI=build python3 -m unittest discover -s tests -p
test_macos_xpc_sandbox.py -k
test_xpc_sandbox_scope_peer_identity_and_service_container_identity -v`
(1 test, 81.372s). It builds a temporary signed probe and exercises real macOS
signature-bound peer admission, service container identity, and the probe's bounded
request/relay checks. This build mode does not open the user Picker, so product
selected-workspace writeback remains unverified.

## 2026-09-29 selected product-bundle XPC attack result

The current interactive `KHAOS_RUN_PRODUCT_XPC_ATTACK_UI=1` probe passed in 135.293
seconds after a fresh external workspace selection. A test-only driver replaced only
the Launcher executable in a temporary copy of the locally signed product app; the
packaged `KernelProduction.xpc` was unchanged and accepted the driver's stable caller
requirement. The real service/bridge/Worker/Seatbelt Runner path committed one safe
output, denied direct live-workspace write, and rejected symlink, special-file, and
hardlink output (the hardlink was denied either during creation or at Kernel commit).
The probe cancelled the active command through its own XPC connection; the external
parent observed the exact randomized `/bin/sleep` child, which exited after cancellation.
The cancelled output was absent, a subsequent request succeeded, workspace fixture and
sibling canary were unchanged, and the committed output metadata plus deep bundle
signature were verified. The test parent also confirmed no Python bytecode cache was added
to the signed framework. This closes the tested selected-workspace XPC attack path on this
host; it does not establish Candidate admission or arbitrary Plugin execution through
the production Launcher.

## 2026-09-29 Workspace XPC source digest binding

Native Workspace XPC advanced to ABI v5 with `runner_source_sha256`. The Swift Kernel
parser hashes the decoded source's UTF-8 bytes and rejects a mismatch before bookmark
resolution; the separate Python bridge checks the digest again before starting the
Worker. A headless signed product-bundle test passed in 10.531 seconds, and its
test-only caller's deliberately wrong digest received `invalid_request` from the real,
unchanged `KernelProduction.xpc` before bookmark handling. The first interactive attempt
exposed a version mix-up: the bridge replied with Runner IPC v4 where the XPC caller
expected v5, causing `kernel_bridge_failed`. The XPC bridge now uses its own v5 version
constant while the inner Runner ABI remains v4. A later product XPC attack passed in
303.470 seconds after fresh workspace selection, exercising a matching digest through
the production bridge, Worker, and Seatbelt Runner along with safe writeback, direct
write denial, unsafe changesets, cancellation, descendant cleanup, and recovery.

The normal v5 product Launcher writeback acceptance opened its system Picker but
received no selection within 300 seconds; it timed out after 308.598 seconds and cleaned
its fixture. This is an unselected interaction timeout, not a failed Kernel assertion,
and normal Launcher v5 writeback remains unverified. Separately, the user reported
`PASS` on the earlier fixed-smoke build for
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-picker-b_oua14q/Workspace`.
That accumulated workspace now contains its original unchanged fixture and five UUID
markers. Each marker is a 33-byte regular file with mode `0600`, one link, and SHA-256
`424af2cf1970670c0feb3cb8b563daafe1d9d97d5cd50882db21af67938711e4`; the fixture
SHA-256 is `67ba479e325ce715164ee46d8bad6b8a482fc301e656dfbd6d457f08cfbfe26d`. This
supports the earlier fixed smoke's exact one-file Kernel writeback and direct-write
denial result, but it is not fresh-workspace evidence for the ABI v5 normal Launcher.
After this v5 attempt, the user also reported that the repaired Picker displayed
`PASS`. No surviving process, fresh fixture, or recorded bundle identity ties that UI
observation to the timed-out test, so it is recorded as user-observed but does not close
the automated v5 selected-workspace evidence gap.

## 2026-09-29 added-file post-clone replacement race

A new real Broker/Seatbelt test found a cleanup race in `_install_staged_file`: after
`fclonefileat` created an added-file destination, the committer recorded the path's
inode before verifying its bytes. An independent same-UID process replaced that target
with a same-size regular file in this window; the old failure cleanup misidentified and
deleted the competing file. The test initially failed with the target missing.

Cleanup identity is now recorded only after the opened inode is still the named entry
and its type, link count, mode, size, and SHA-256 match the validated changeset. The
committer then checks xattrs and the parent binding. A different-content replacement
causes `commit_outcome_uncertain`, while the competing file's content and inode remain
intact. The broker test uses a separate writer process and the real Seatbelt commit
child. It passed after the fix; all five focused new-file APFS tests also passed.
The canonical `python3 -m unittest discover -s tests -v` suite then passed all 189
tests in 366.991 seconds on this macOS host. The default suite does not open the
interactive Picker.

The post-clone race test now gives the competing file the same 0600 mode and length as
the candidate, with one link and the same owner. The digest check is therefore the
decisive content mismatch before cleanup. The real Broker/Seatbelt attack passed, and
the full `commit_child` adversarial group passed all eight tests (13.301 seconds) on
2026-09-29. The canonical `python3 -m unittest discover -s tests -v` suite then passed
all 193 tests in 375.225 seconds on this macOS host.

This closes the exercised post-clone cleanup window. It does not create global
same-UID write exclusion or a multi-file transaction; the advisory mount lock still
only coordinates cooperating Khaos committers.

## 2026-09-29 prepared replacement cleanup race

A real Broker/Seatbelt attack test found that preflight cleanup for a modified file
could blindly unlink an independent writer's replacement of the prepared temporary
name. The committer now uses `_remove_expected_entry` with the inode captured from the
created descriptor and a second exact-path Seatbelt-scoped sentinel. The atomic swap
preserves a different inode and returns `commit_outcome_uncertain`; the tested
competitor remained intact at the prepared temporary name. The focused workspace,
Seatbelt, and Broker regression set passed all 81 tests in 113.807 seconds. The
canonical `python3 -m unittest discover -s tests -v` suite then passed all 190 tests
in 368.974 seconds and does not open the interactive Picker. This addresses the
exercised cleanup window only; a
non-cooperating same-UID writer still is not globally excluded.

## 2026-09-29 product writeback Picker retry

The documented opt-in product writeback check built and launched a fresh signed
Seed bundle, then remained incomplete through its 300-second Picker window. The
disposable workspace contained only its original fixture at the last live check;
the test process and temporary bundle were subsequently cleaned. The user later
confirmed that the alert displayed `PASS`, but the run has no machine-readable result
record, the fixture did not change, and the selected path cannot be tied to the fresh
fixture and bundle identity. Record this as a user-observed UI result only; it does not
establish this run's writeback or close the selected-workspace evidence gap. The timeout
path previously raised before reading captured stderr; it now reports stderr, exit
status, and workspace entry metadata after terminating the app. A focused test verifies
that timeout diagnostics survive.

## 2026-09-29 prepared-file cleanup race after identity check

The earlier prepared-file cleanup fix covered a replacement already present when
cleanup began. A separate real Broker/Seatbelt test now pauses the isolated committer
after its initial `stat` check and immediately before the atomic sentinel exchange. An
independent same-UID writer replaces the prepared pathname during that window. Cleanup
atomically exchanges the pathname, compares the displaced inode with the one captured
from the prepared descriptor, restores a mismatch, and returns
`commit_outcome_uncertain`; the competing inode and contents remain intact. The
cleanup also revalidates the opened parent binding before mutation. The test uses the
real macOS Seatbelt commit child. This covers the synchronized pre-exchange race only;
arbitrary same-UID writers remain outside the advisory-lock boundary, and writeback is
not a multi-file transaction. If parent binding changes or the required swap primitive
fails, cleanup retains the prepared entry and reports `commit_outcome_uncertain`; inspect
the workspace before retrying. After this behavior and its retained-entry assertions were
added, the canonical `python3 -m unittest discover -s tests -v` suite passed all 192 tests
in 384.108 seconds on this macOS host. The suite does not open the interactive Picker.

## 2026-09-29 exact Picker target prompt retry

The product Launcher now includes the exact `--picker-start-directory` path in the
system Picker message for this acceptance mode. This is display guidance only; the
selected bookmark remains the Kernel's workspace authority. The signed-package and
service-authentication test passed (1 test, 8.807 seconds). A fresh interactive run
printed and displayed
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-ujujb7cq/user-selected-writeback-workspace`,
but no selection reached the test within 300 seconds. The fixture remained the only
entry (41 bytes), marker count was zero, and captured stderr contained only the
`sandbox_extension_issue_file_to_process` warning. The helper and temporary fixture
were cleaned up. This run adds no selected-workspace or writeback evidence and does
not establish whether the Picker was visible.

## 2026-09-29 exact-selection guard and user-reported PASS

The acceptance-only Launcher argument is now `--acceptance-workspace`. It sets the
Picker's initial directory and requires the selected, standardized,
symlink-resolved URL to equal that requested path before the Kernel request. A
mismatch fails with `selected_workspace_mismatch`; the selected bookmark remains
the Kernel's only workspace authority. The Launcher also emits path-free
`picker-requested` and `workspace-selected` diagnostics. The focused signed-bundle
and service-authentication check passed after these changes (1 test, 7.707 seconds).

The subsequent interactive attempt used the fresh target
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-5vshwjzj/user-selected-writeback-workspace`.
The automated run timed out, and its last workspace inspection contained only the
fixture and no writeback marker. The user reports that a popup displayed `PASS`,
but that observation cannot be correlated with this run's fresh workspace or
bundle; the test process had no success record. This interactive binary also
predated the two phase diagnostics. The current source has the diagnostics and
exact-selection guard, but has not had a successful interactive run with both.

## 2026-09-29 current-source Picker retry

The current source was rebuilt and launched with
`--acceptance-workspace` for
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-qp_x_2to/user-selected-writeback-workspace`.
The signed Launcher emitted `workspace-kernel-smoke=picker-requested`, but no
selection reached it during the 300-second window; there was no
`workspace-selected` or success diagnostic. The final inspection found only the
41-byte fixture (`entry_count=1`, `marker_count=0`). Stderr also contained
`sandbox_extension_issue_file_to_process ... Operation not permitted`; its cause
is not established. The test and app processes exited, and the temporary bundle
directory was removed. This confirms the current UI acceptance remains incomplete;
it does not establish whether the Picker was visible or explain the user's earlier
`PASS` observation.

## 2026-09-29 Launch Services launch for product acceptance

The earlier UI harness started the signed executable directly, then called
`/usr/bin/open -a` to foreground it. Two such current-source runs timed out without
`workspace-selected`; the most recent left only its 41-byte fixture. The test now
launches the signed app bundle through `/usr/bin/open -W -a` from the outset, passes
`--acceptance-workspace` with `--args`, and redirects app stdout/stderr using
Launch Services options. It waits for app exit and requires both the path-selection
and success diagnostics plus the single Kernel-written file. The headless signed-app
test using this shared Launch Services path passed in 7.827 seconds and authenticated
the Kernel XPC peer; it did not open the Picker. The acceptance Launcher also no
longer sets `NSOpenPanel.directoryURL` to its external temporary workspace before
the user selects it; the exact path remains in the message and is checked after
selection. Apple documents that open panels run in a separate process and that the
system extends the app sandbox to selected URLs ([NSOpenPanel](https://developer.apple.com/documentation/AppKit/NSOpenPanel),
[App Sandbox file access](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox)).
The resulting headless signed-app test passed in 7.926 seconds; interactive evidence
follows below.

## 2026-09-29 selected-folder recheck after user-reported PASS

The user confirmed a `PASS` alert after selecting
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-picker-b_oua14q/Workspace`.
Inspection found the original fixture from 2026-09-28 and five smoke markers, with the
newest marker timestamped 2026-09-29 01:01 local time. The current-source retry used a
different fresh `khaos-seed-app-*` target and timed out without a `workspace-selected`
record. The UI observation is retained, but those older files do not identify the
current-source binary or run; its selected-workspace result remains unverified.

## 2026-09-29 current Launch Services Picker visibility check

The current signed app launched through `/usr/bin/open -W -a` with
`NSOpenPanel.directoryURL` unset. CoreGraphics reported an on-screen, fully opaque
window owned by `Khaos Seed`, titled `Choose Khaos Workspace`. The 300-second run
still received no selection: stderr remained at `picker-requested`, the fresh
workspace retained only its 41-byte fixture, and there was no writeback marker or
`workspace-selected` diagnostic. The UI was visible; this run adds no selected-
workspace or writeback result.

The timeout cleanup initially missed a stale temporary app process because macOS
reported its executable under `/private/var` while the test path used `/var`. The
stale process was terminated. Cleanup now resolves the executable path before
matching `ps` output; `test_product_launcher_process_lookup_resolves_symlinked_temp_path`
passes and exercises that path alias. A subsequent run is needed to validate cleanup
against a live timeout. The user then confirmed seeing a `PASS` popup for this attempt.
The automated run still has no `workspace-selected` or success diagnostic, and its
fresh workspace contained only the fixture before cleanup. Record the popup as
user-observed UI evidence; it cannot be tied to this run's selected path or writeback.

## 2026-09-29 acceptance Picker navigation and preselection read probe

The acceptance-only Launcher now starts `NSOpenPanel` in the requested
workspace's parent so the exact disposable folder is visible as a selectable
entry. Before showing the panel, it opens the known fixture with
`O_RDONLY | O_NOFOLLOW` and requires `EPERM` or `EACCES`; it still checks the
resolved selected URL against the exact requested workspace before sending the
user-selected bookmark to Kernel. Apple's `directoryURL` documentation defines
it as the directory shown in the panel; App Sandbox documentation says the OS
extends access to URLs selected in the panel.

The signed product build and authenticated Kernel-service test passed (1 test,
7.795 seconds). In the opt-in interactive run, the app emitted
`preselection-read=denied` followed by `picker-requested`; CoreGraphics showed
the visible `Choose Khaos Workspace` window. No selection arrived within 300
seconds, so the focused test failed after 307.703 seconds and reported only the
41-byte fixture with zero writeback markers. The test cleaned up its temporary
bundle and workspace. This run proves the direct read-open was denied before
the panel appeared on this host; it does not prove access behavior while the
panel is open or successful selected-workspace writeback. The user's reported
`PASS` remains UI evidence from a separate run and is not tied to this fresh
workspace or bundle.

The follow-up cleanup uses one `requireWorkspaceOpenDenied` implementation for
the preselection read and post-selection write probes. Its signed-package and
Kernel-service authentication test passed (1 test, 7.967 seconds), and the
timeout-diagnostic regression passed. The default signed-product test now also
replaces only the Launcher in a temporary bundle with a test driver and submits a
bounded, validly framed `workspace.run` to the real `KernelProduction.xpc` with a
mismatched source digest and no bookmark. The service returns
`invalid_request` before bookmark handling; fixture bytes and the sibling canary
remain unchanged. The signed-product test also submits an over-depth request with
no bookmark; the Kernel rejects it, then answers a later idle-cancellation request.
The Swift parser enforces eight structural levels before Foundation parsing; the
current request schema uses at most three, and string contents do not count toward
the limit. The focused product test passed with both UI flags unset (1 test,
10.429 seconds). The optional product writeback flow runs first, before the test
replaces the temporary Launcher's executable. The canonical
`python3 -m unittest discover -s tests -v` suite, including these attacks, passed
all 193 tests in 394.905 seconds. The suite does not open the Picker or add
selected-workspace writeback evidence. A matching self-supplied digest remains
content integrity only; it does not provide approval, Manifest validation,
capability authorization, or Candidate admission.

## 2026-09-29 duplicate-field XPC rejection

Foundation converts JSON objects to dictionaries, which erase duplicate keys. The
Kernel's Workspace XPC v5 parser now requires the body to match byte-for-byte the
sorted-key serialization of the parsed object before applying its schema. This
rejects duplicate keys and alternate encodings; the shipped Swift clients already
use that encoder. The headless signed-product test sends a valid request with a
exact and escaped-name duplicates of `workspace_read_scope` with no bookmark to the
real `KernelProduction.xpc`; both require `invalid_request` before bookmark handling.
The escaped JSON key decodes to the same field name as its unescaped duplicate. The
probe then confirms the service still answers an idle cancellation. The over-depth request uses the same
Foundation encoder so its rejection exercises the structural-depth check.

The final focused signed-product test passed (1 test, 10.277 seconds), and the
canonical `python3 -m unittest discover -s tests -v` suite passed all 193 tests in 373.618
seconds. These results prove this parser boundary on the current macOS host. They do
not establish Candidate admission, capability grants, or user approval.

## 2026-09-29 selected-workspace smoke artifact recheck

The user confirmed selecting the previously supplied disposable workspace and
seeing the product app's `PASS` alert. A read-only check at 13:01:16 CST found its
fixture plus five Khaos smoke markers; each marker was 33 bytes, mode `0600`, and
single-link. The newest marker's modification time was 01:01:22 CST. This confirms
matching writeback artifacts exist in that directory, but without a run identifier
or correlated process log it does not bind those files to one specific alert or
product build. The headless XPC suite remains separate evidence and does not open
the Picker.

## 2026-09-29 post-Picker read-scope check

The acceptance Launcher now checks the same fixture through the real OS boundary twice:
the selected URL must allow `open(O_RDONLY | O_NOFOLLOW)` while its open-panel scope is
live, and the same open must fail with `EPERM` or `EACCES` after the Launcher calls
`stopAccessingSecurityScopedResource()`. It does not read fixture bytes. Either mismatch
fails closed before Kernel contact. The interactive test requires path-free
`selected-read=available` then `selected-read=denied` diagnostics before accepting Kernel
writeback and direct-write denial. Apple documents that Open-panel URLs extend the app's
sandbox and that stopping scoped access revokes it immediately
([App Sandbox file access](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox)).

The focused signed-product build and peer-authentication test passed on the current
source (1 test, 11.086 seconds). It compiles the new positive and negative checks but
does not open a Picker or prove either selected-workspace result.
The canonical `python3 -m unittest discover -s tests -v` suite then passed all 193
tests in 373.472 seconds; it also does not open the Picker.

The opt-in interactive run launched the signed product and printed the fresh workspace
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-jirbjuvz/user-selected-writeback-workspace`.
No selection arrived within 300 seconds. The captured diagnostics ended at
`picker-requested`, the workspace contained only its fixture, and the test cleaned the
temporary bundle and workspace. Neither positive nor negative post-selection read check
was therefore executed. This attempt produced no selected-workspace evidence.

The next opt-in run completed after the user selected
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-3mfj1nf_/user-selected-writeback-workspace`
and dismissed the `PASS` alert. The focused test exited successfully (1 test, 103.483
seconds). Its run-correlated diagnostics and assertions require preselection read denial,
selection, successful `O_RDONLY | O_NOFOLLOW` open while the Picker scope is active, denial
after `stopAccessingSecurityScopedResource()`, Kernel writeback, and direct-write denial, in
that order. Before its temporary root was removed, the test also required exactly one new
Kernel marker beside the unchanged fixture, mode `0600`, a single link, and successful strict
deep code-signature verification. The temporary directory no longer exists after test
cleanup, so its artifacts are test assertions rather than retained files for later inspection.
This proves the acceptance bundle's selected-scope and writeback path on this macOS host. It
does not prove production app identity or grant policy, Candidate admission, approval binding,
or the wider production Host boundary.

## 2026-09-29 new-file commit temporary-path replacement

A real Seatbelt commit-child attack found an unsafe cleanup path for added files. An
independent same-UID writer replaced the committer's open same-directory temporary pathname
before the descriptor-backed clone. The old cleanup unlinked by pathname, so the first attack
run returned success after deleting the competing file.

The Worker now pins that temporary file's device/inode from its descriptor. Before cleanup it
atomically exchanges the named entry with a separately pre-authorized sentinel, validates the
displaced inode, and restores a mismatch. The attack test returns
`commit_outcome_uncertain` and preserves the competing file's content and inode. The
descriptor-backed clone may already have installed the candidate at the destination;
post-clone failure does not attempt pathname rollback. The test passed on the real macOS
Seatbelt commit child. This covers the synchronized path-replacement window; it does not
establish global write exclusion against arbitrary same-UID processes.

## 2026-09-29 new-file clone through a detached parent descriptor

A real Seatbelt Broker test moves the destination parent outside the workspace after
the commit child opens it and immediately before the descriptor-backed APFS clone.
The test captures the OS result through an independent attacker process and confirms
the clone fails with `EPERM` or `EACCES`; the candidate destination is absent in both
the moved directory and the replacement workspace path. This demonstrates path-scoped
Seatbelt enforcement for this synchronized stale-descriptor create attempt. It does not
establish global arbitration against arbitrary same-UID workspace writers or guarantee
cleanup after a parent directory has been moved outside the authorized root.

## 2026-09-29 displaced-baseline cleanup replacement race

A real Seatbelt commit-child test replaced the old-file backup with an independent
writer's file after baseline validation and before the final `unlink`. The original
committer deleted that competing inode and reported success. It now reuses the
identity-checking sentinel exchange for baseline cleanup; a mismatch is restored,
preserved, and reported as `commit_outcome_uncertain`, while the validated candidate
remains at the destination. The adversarial test passes against the real macOS Seatbelt
commit child. This covers the synchronized cleanup window only and does not establish
global same-UID write exclusion.

## 2026-09-29 new-file post-install rollback race

A real Seatbelt commit-child test initially paused after the rollback identity
`stat` and before the pathname `unlink`; an independent same-UID process replaced
the destination in that window, and the old code deleted its inode. Apple
documents `unlink` as removing the directory entry named by its path; it has no
inode-conditional form. New-file failure cleanup therefore no longer tries to
remove the installed destination. It reports `commit_outcome_uncertain` and issues
no rollback unlink; the destination may be the candidate, a concurrent replacement,
or absent if another writer changed it. The retained regression test forces a
post-install failure while an independent process replaces the destination and
verifies that the competing inode survives in the real Seatbelt commit child. This
is not rollback and does not make a multi-file write atomic.

## 2026-09-29 new-directory cleanup race

Directory creation failure cleanup used `stat` to compare the created inode and then
called `rmdir` by pathname. An independent writer could replace the entry between
those calls, causing the Kernel to remove the writer's directory. The documented
[`rmdir(2)`](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/rmdir.2.html)
takes a pathname; the documented [`unlinkat(2)`](https://keith.github.io/xcode-man-pages/unlink.2.html)
resolves a relative pathname from a directory descriptor. Neither accepts an
expected inode, so the committer found no documented inode-conditional directory
removal primitive and now leaves the entry in place after a parent-binding or
directory-sync failure, reporting
`commit_outcome_uncertain`. Workspace-change regressions cover parent detachment,
sync failure, and replacement at the sync-failure boundary. The retained entry may
be the candidate directory or a concurrent replacement in the original parent;
after parent detachment that parent may no longer be reachable through the named
workspace path. Inspect the workspace and any known moved parent before retrying.
This conclusion is limited to the documented interfaces above; it avoids the
identified pathname deletion race but does not make writeback atomic or exclude other
same-UID writers. A real Seatbelt commit-child regression also verifies that a
directory remains after the parent-binding failure path.

## 2026-09-29 final unlink after parent detachment

A retained real Broker/Seatbelt regression now moves the containing directory out of
the selected workspace after the commit child has validated its parent binding and
the displaced baseline identity, immediately before the final descriptor-relative
unlink. The stale-directory-FD unlink fails with `EPERM` or `EACCES`; the Broker
returns `commit_outcome_uncertain`. The baseline backup remains in the detached
directory and an outside canary is unchanged. The candidate may already have been
installed before the detach, so this is a denied cleanup operation, not an atomic
rollback or a guarantee that the workspace remained unchanged. The attack test passed
three consecutive runs on the real macOS Seatbelt backend.

This closes only the path-scope question for a parent moved outside the authorized
workspace. It does not close the separate same-UID check-to-unlink replacement race
at the mutable sentinel pathname described above, and it establishes no global
same-UID write exclusion.

## 2026-09-29 final unlink identity race

The displaced-baseline sentinel exchange still has a final check-to-use window.
After `_remove_expected_entry` verifies that the exchanged path contains the
baseline inode, it calls `unlink` on that mutable name. A synchronized probe
patched that exact boundary in `serve_workspace_commit`, then used an independent
same-UID process to replace the path before the real macOS Seatbelt commit child
performed the unlink. The writer process succeeded; the commit returned success,
installed the candidate, and removed the writer's inode. This was a real Broker
and Seatbelt execution, but the one-off probe is not a retained regression test.

Apple documents `unlink(2)` as removing the directory entry named by a path; it
does not accept an expected inode. The existing
`test_commit_child_preserves_displaced_backup_replacement_before_unlink` covers
the earlier window before the sentinel's identity check and must not be read as
closing this later window. The current Runner Seatbelt profile prevents Plugin
code from directly writing the live workspace, but arbitrary unconfined same-UID
processes remain able to race the Kernel. The prototype makes no safety claim
against that writer class. Closing the gap requires OS-enforced exclusive write
authority or a different writeback boundary; another pathname identity check
cannot close it.

A focused audit of the public Darwin/XNU syscall interfaces found `unlinkat`
still takes a directory descriptor plus a pathname, while `renameatx_np` takes
source and destination names. Neither reviewed interface offers an
expected-inode compare-and-unlink operation. This is an inference from the
published syscall signatures and `unlink(2)` contract, not proof that no private
filesystem interface exists. No smaller public OS primitive was identified to
replace the final name-based removal. See Apple's [`unlink(2)` manual page](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/unlink.2.html)
and the [XNU syscall definitions](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/syscalls.master).

## 2026-09-29 live-workspace unlink, rename, and atomic-swap denial

The real end-to-end `test_runner_cannot_bypass_kernel_authority` attempts to unlink,
rename, and atomically swap two existing live-workspace entries with
`renameatx_np(RENAME_SWAP)` from both untrusted Plugin source and its fixed command.
An unconfined positive control first proves the native swap call works on the test
volume; each sandboxed operation must then fail with `EPERM` or `EACCES`. While the
Runner's `workspace.commit` request is pending, a still-running Runner thread keeps
attempting the atomic swap. The test requires at least one attempt in that interval,
requires every attempt to receive the OS denial, and verifies that the trusted
Kernel commits the snapshot modification while the swap peer remains unchanged.
This exercises destructive namespace operations at the actual Runner and command
Seatbelt boundaries together with the allowed writeback route.

This proves direct unlink, rename, and atomic-swap denial for these sandboxed
processes, including a concurrent Runner attempt while the commit request is
outstanding, on the tested host. It does not provide global write exclusion against
an independent unconfined same-UID process; the final check-to-unlink race above
remains outside this Runner/command enforcement proof.

The focused adversarial test passed three consecutive runs (one test each,
between 3.658 and 3.722 seconds). After adding the concurrent Runner loop, the
canonical `python3 -m unittest discover -s tests -v` suite passed all 200 tests in
400.769 seconds on this host.

## 2026-09-29 macOS final-entry primitive review

The documented macOS interfaces reviewed for this commit flow provide no
inode-conditional unlink. Apple describes `unlink(2)` as removing the directory
entry named by a path; XNU defines `unlinkat` with a directory FD and path, and
`renameatx_np` with source and destination paths plus flags. None accepts an
expected device/inode identity. Apple's `fcntl(2)` manual calls record locks
advisory, so a non-cooperating same-UID writer is not constrained by a lock held by
the committer. This review covers documented interfaces, not every private or
future OS facility.

The synchronized real-OS probe remains decisive: an unconfined writer can replace
the sentinel between identity validation and `unlink`. Repeating path checks,
adding an advisory lock, or wrapping the same pathname calls would not close that
window. The current Seed boundary therefore excludes arbitrary unconfined same-UID
writers; the tested Runner and fixed command remain separately denied direct
live-workspace namespace changes by Seatbelt. A broader guarantee requires a
different OS-enforced writeback principal or another mandatory enforcement
boundary, not another user-space pathname check.

Sources: Apple's [`unlink(2)`](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/unlink.2.html)
and [`fcntl(2)`](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/fcntl.2.html)
manual pages; XNU's [`syscalls.master`](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/syscalls.master)
definitions for `unlinkat` and `renameatx_np`.

## 2026-09-30 Runner direct APFS clone denial

The trusted changeset committer uses `fclonefileat` to install a verified file
from an open descriptor. The real Seatbelt end-to-end attack now probes that
same primitive from both untrusted Plugin source and the fixed command. An
unconfined parent first proves that cloning the actual Python executable into
the same-volume workspace succeeds; each sandboxed process then opens that same
source and attempts a clone into the live workspace. Both calls must fail with
`EPERM` or `EACCES`, and the candidate paths must remain absent, while the normal
Kernel-mediated snapshot commit still succeeds. The focused test passed on this
macOS host in 13.812 seconds. The canonical
`python3 -m unittest discover -s tests -v` suite then passed all 207 tests in
402.155 seconds, including this real-OS attack and the default headless signed-XPC
checks; it does not open the Picker. This adds evidence for the tested
descriptor-clone path under Seatbelt; it does not close the documented race
against an unconfined same-UID writer or prove behavior on other OS versions.

## 2026-09-30 product-bundle XPC retry without a completed selection

The opt-in product XPC attack test passed its signed-bundle and authenticated
headless bootstrap checks, then opened the Picker for
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-lhs6vh7n/user-selected-product-xpc-workspace`.
No cancellation descendant appeared within the 600-second interaction window; the
test exited after 614.107 seconds at that timeout. The workspace was not confirmed
selected, so the safe changeset, unsafe changeset, cancellation, and recovery
assertions did not complete. Process and temporary-workspace inspection after exit
found no surviving app, helper, or fixture. This does not invalidate the separate
2026-09-29 selected-workspace XPC attack pass above.

The timeout originally omitted captured test-driver stdout/stderr, so the failure
could not distinguish a Picker-stage wait from an earlier driver error. The
interactive harness now includes captured diagnostics in both missing-descendant
and overall-completion timeout failures. The deterministic
`test_product_xpc_cancellation_timeout_preserves_driver_output` regression passed
on this host; this improves test diagnosis only and does not change the security
path or add selected-workspace evidence.

## 2026-09-30 selected product-bundle XPC attack pass

The same opt-in test was rerun with a fresh temporary workspace and a user-selected
folder. It passed in 180.343 seconds. The test-only driver replaced the Launcher
inside a temporary signed app copy while preserving the signed product
`KernelProduction.xpc` and its authenticated caller requirement. The real executor
completed a safe one-file commit, denied the app's direct write after releasing the
Picker scope, rejected symlink and special-file changesets (and either rejected or
OS-denied the hardlink attack), then cancelled a live command only on its submitting
XPC connection. The test observed the unique descendant exit, verified no cancelled
output reached the workspace, submitted a recovery request, checked the exact
workspace contents and sibling canary, and revalidated the deep product signature
and signed Python framework.

This completes the selected-workspace XPC execution and cancellation evidence for
the current product service on this host, including the checks that were not reached
by the earlier 614.107-second no-selection attempt above. It does not prove
Candidate/Manifest approval, arbitrary Plugin admission through the normal product
Launcher, installation integrity against unconfined same-UID processes, or behavior
on other macOS releases. The normal product Launcher still submits only its fixed
Runner source.

## 2026-09-30 product XPC concurrent live-workspace swap denial

A follow-up interactive run completed with exit code 0 in 509.509 seconds after
the user selected the disposable workspace. In the test-only Runner source, one
thread submitted the Kernel commit while the Runner attempted
`renameatx_np(RENAME_SWAP)` between the live input and hardlink-source paths until
that commit completed. The Runner failed unless at least one attempt occurred, every
attempt failed with `EPERM` or `EACCES`, and the commit thread completed without an
error. The successful product XPC response therefore proves the tested OS sandbox
denied the concurrent live-path swaps during this commit window.

The same test parent then verified the exact workspace file set and contents,
single-link regular-file metadata, output mode, unchanged sibling-canary digest,
deep product signature, and absence of Python-framework `__pycache__` writes. This
is evidence for the current signed product Kernel service on this host; the temporary
test driver still replaces the Launcher, so this does not prove normal Candidate or
Manifest admission, installation integrity against unconfined same-UID processes,
or behavior on other macOS releases.

After this probe change, the canonical repository suite
(`python3 -m unittest discover -s tests -v`) passed all 201 tests in 402.008
seconds.

## 2026-09-30 current product Launcher writeback acceptance

The opt-in product writeback acceptance test passed in 95.427 seconds with exit
code 0 after a fresh user-selected workspace. This run used the normal locally
signed `KhaosSeed.app` Launcher, not the test-only Launcher replacement used by
the XPC attack probe. Its diagnostics confirmed preselection read denial, selection,
read access while the Picker scope was active, read denial after scope release, and
direct-write denial after the Kernel commit. The Kernel committed exactly one
0600 single-link marker. The test parent verified the fixture's original digest and
link count, the exact two-file workspace contents, deep app signature, and absence
of Python-framework `__pycache__` writes.

This closes the current normal product Launcher's selected-workspace fixed-smoke
path on this host. It still does not run arbitrary Plugin source, provide
Candidate/Manifest admission or activation approval, or establish distribution
signing and installation protection.

## 2026-09-30 product XPC exact read-scope enforcement

An interactive run of the product-bundle XPC attack test passed in 293.018
seconds with exit code 0. The test-only Runner request granted reads only for
`production-input.txt`: that read had to return the expected bytes, while a read
of the existing sibling `production-hardlink-source.txt` had to fail with the
Kernel error `path_not_readable`. The test required the Runner to report both
results before it could continue to the process and commit checks.

The same real `KernelProduction.xpc` run committed exactly one marker, denied a
direct Launcher write after Picker-scope release, rejected unsafe changesets,
denied or rejected the hardlink case, cancelled a live command only on its
submitting XPC connection, terminated the unique descendant, preserved the
cancelled output, and accepted a recovery request. The parent verified exact
workspace contents, unchanged canary, and the deep product signature.

This test run exposed that the interactive XPC harness directly spawned the
bundle executable, unlike the normal product test's Launch Services startup.
That direct-spawn run timed out with
`sandbox_extension_issue_file_to_process ... KhaosSeed.app: Operation not
permitted`; no scope assertion ran in that attempt. The harness now reuses the
existing Launch Services helper. For cancellation synchronization, the test-only
driver publishes its PID and pauses itself with `SIGSTOP`; the external test
parent resumes it only after observing the randomized descendant. This does not
change the production Launcher, Kernel ABI, or cancellation authority. The pass
proves the exact scope exercised by the test-only Runner and current product
service on this host; it does not prove Candidate/Manifest admission or arbitrary
Plugin execution through the normal Launcher.

After this change, the canonical `python3 -m unittest discover -s tests -v`
suite passed all 207 tests in 399.821 seconds. This default suite is headless;
the product XPC scope evidence above comes from the separate interactive run.

## 2026-09-30 product XPC directory-list scope

A follow-up selected-workspace Product XPC attack passed in 250.479 seconds with
exit code 0. The Runner's scope contained only `production-input.txt`; the real
Kernel returned that entry from `fs.list("")` and omitted the existing sibling
`production-hardlink-source.txt`. A direct listing request for the sibling had
to return `path_not_listable`. The same Runner also completed the scoped content
read and out-of-scope read denial before invoking the fixed command.

All existing Product XPC writeback, direct-write denial, unsafe changeset,
hardlink, active cancellation, descendant cleanup, recovery, exact workspace,
canary, and signature checks passed in the same run. This is test-only Runner
evidence through the current signed Kernel service; it does not grant any
production Plugin capability or prove Candidate admission.

The canonical `python3 -m unittest discover -s tests -v` suite then passed all
207 tests in 393.411 seconds. It is headless and does not repeat the selected-
workspace scope check.

## 2026-09-30 fixed product Launcher read/list acceptance attempt

The ordinary product Launcher still supplies fixed Runner source rather than
loading a Plugin. Its acceptance-only source now reads the exact fixture through
Kernel IPC, lists the root with only that file visible, and requires an existing
unscoped sibling read and direct listing to fail before `process.exec` and
`workspace.commit`. The no-argument request keeps the read scope empty and checks
default denial. This reuses the existing Runner SDK, bounded XPC protocol, and
Kernel scope implementation; it adds no new enforcement primitive or dependency.

The rebuilt locally signed app passed the headless product package/service test
(1 test, 14.968 seconds). The interactive writeback acceptance waited 300 seconds
without receiving a workspace selection and failed with the existing timeout
diagnostics: `preselection-read=denied` and `picker-requested`, but no
`workspace-selected`. The workspace had its two initial fixtures and no marker.
Thus the new normal-Launcher read/list path remains unverified. The PASS the user
reported for another temporary workspace does not establish this run's outcome.
The canonical headless suite then passed all 207 tests in 403.161 seconds; it
does not open the Picker or execute this product Runner path.

## 2026-09-30 Runner IPC scope-forgery attacks

The Broker retains `WorkspaceReadScope` and `WorkspaceWriteScope` outside Runner
messages and requires each filesystem operation to use its exact payload schema.
New raw-wire unit attacks attempt to inject `workspace_read_scope` into `fs.read`
and `fs.list` and `workspace_write_scope` into `fs.write`; the Broker returns
`invalid_request` for each (3 cases, 5.482 seconds).

The same three frames were sent from real Seatbelt Runner processes with empty
retained scopes. Each request stopped the Runner session with `runner_failed`
before the trusted command marker appeared; the existing workspace secret
remained unchanged (3 cases, 10.326 seconds). The positive result proves this
local Broker IPC enforcement under the tested macOS backend. It does not provide
Candidate admission, Plugin identity-bound grants, or user approval.
After these attacks, the canonical headless suite passed all 209 tests in
406.525 seconds. It did not open the Picker or revalidate the separate normal
Launcher read/list acceptance path.

## 2026-09-30 fresh fixed Launcher read/list Picker retry

After the user reported `PASS` for the earlier
`khaos-seed-app-3mfj1nf_` acceptance bundle, a fresh locally signed product was
built for the updated fixed Runner read/list check. Its new workspace was
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-107zf9i5/user-selected-writeback-workspace`.
The OS reported `KhaosSeed` as the frontmost app, but the test received no
selection or cancellation within 300 seconds and exited failed after 322.357
seconds. The workspace still contained only its two fixtures; diagnostics ended
at `preselection-read=denied` and `picker-requested`, with no marker. The prior
`3mfj1nf_` PASS remains evidence for its earlier acceptance-bundle source; it
does not establish the updated Runner read/list result. This retry adds no
selected-scope, commit, or post-selection signature evidence.

## 2026-09-30 Runner inherited secret-FD attack

A real Seatbelt end-to-end Launcher test opens a secret pipe in the untrusted
caller and marks its high-numbered descriptor inheritable. Both the Runner and
its fixed command attempt `fstat` on that descriptor and must receive `EBADF`;
the caller then reads the complete secret back, proving neither child consumed
it. The Runner exits through the Broker and commits an empty changeset. The new
focused test passed (1 test, 3.506 seconds), as did the existing host-environment
isolation test (1, 3.697 seconds) and the lower-level Seatbelt pipe-FD test (1,
1.850 seconds). The full `test_launcher.py` module passed all 28 tests in
106.587 seconds. The 209-test canonical suite was not rerun after adding this
test.

## 2026-09-30 fixed Launcher read/list Picker retry after stale-path report

The user again reported `PASS` for the earlier workspace
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-3mfj1nf_/user-selected-writeback-workspace`.
That temporary path belonged to the already-cleaned acceptance-bundle run. A new
signed product build for the current fixed Runner read/list source used
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-m3629ih1/user-selected-writeback-workspace`.
The interactive test received no selection or cancellation within 300 seconds
and failed after 311.971 seconds. Its captured diagnostics stopped at
`preselection-read=denied` and `picker-requested`; the workspace retained its
two initial fixtures and had no Kernel marker. The run therefore did not execute
Runner scoped read/list, post-scope OS denial, Kernel writeback, or the final
signature checks. The older `3mfj1nf_` PASS remains evidence for the older
acceptance bundle only and does not establish the updated normal-Launcher path.

## 2026-09-30 public Mach task-footprint setter probe

The current macOS SDK declares Apple's public
[`task_set_phys_footprint_limit`](https://developer.apple.com/documentation/kernel/1538131-task_set_phys_footprint_limit)
Mach function, but a local call through `libSystem` using the unprivileged
process's own `mach_task_self_` port returned `KERN_NO_ACCESS` (status 8; confirmed
with `mach_error_string`). The call therefore cannot set an OS-enforced limit from
the current ordinary Runner bootstrap on this host. The API targets an individual
task rather than a fork tree, so it would not supply the missing command-aggregate
quota even if access were available. No wrapper or polling substitute was added;
the aggregate memory quota remains unestablished. This complements the existing
`RLIMIT_AS` and `RLIMIT_DATA` probes, which also reject useful limits after the
current Python runtime has mapped its address space.

## 2026-09-30 Unix-socket changeset rejection and Picker report

`test_rejects_unix_socket_output_before_partial_writeback` creates an actual
AF_UNIX stream socket in the private APFS snapshot, alongside a normal added file
and a replacement for an existing file. `commit_snapshot` rejects the socket as
an unsupported filesystem entry; the existing live file remains at its original
content and the normal addition is not partially written. The focused test passed
(1 test, 1.608 seconds). This exercises Kernel changeset scanning with a real
filesystem socket.

The complementary real Seatbelt test drives a Unix-socket `bind` through the
normal Runner → `process.exec` → Kernel path. On this host Seatbelt returns
`EPERM`; the command reports that exact denial, exits successfully, and the
default Runner commits an empty changeset. A safe companion file is only created
if socket creation succeeds, in which case Kernel commit must reject the socket
changeset. The test passed (1 test, 3.569 seconds), and the full
`test_launcher.py` module passed all 29 tests (109.945 seconds). The exercised
host result is OS denial; the separate direct changeset test proves Kernel
rejection if a socket reaches the scanner.

The user confirmed selecting
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-3mfj1nf_/user-selected-writeback-workspace`
and seeing `PASS` after reopening the Picker. Accept this as user-observed
success for the displayed launcher's own gates; the current Launcher source only
shows PASS after scoped read/list, post-scope denial, Kernel writeback, and direct
write-denial checks. The path already has a recorded 103.483-second acceptance
bundle success. The separate `m3629ih1` attempt timed out before selection and
is a distinct run. At later inspection, the newly reported path, app process,
and test terminal output were absent, so the new observation cannot be bound to
an exact bundle/source digest or independently establish post-alert signature
verification. Preserve the reported PASS without assigning it to the failed
`m3629ih1` attempt.

After both regressions were added, the canonical
`python3 -m unittest discover -s tests -v` suite passed all 212 tests in 427.651
seconds. Its product XPC coverage was headless; it did not reopen the system Picker.

## 2026-09-30 navigation guidance and Product Launcher retry

Improved the opt-in test prompt to print Command-Shift-G navigation steps and
the exact workspace path, and added a timeout-regression assertion for that
guidance (1 test passed, 0.002 seconds). The next current-source signed Product
Launcher run created
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-app-rx5bn0nu/user-selected-writeback-workspace`.
System Events reported `KhaosSeed` as frontmost during the wait, while the
path-free log remained at `preselection-read=denied` and `picker-requested`.
No folder selection arrived before the 300-second deadline; the test exited
after 312.321 seconds with two fixture entries (41 and 27 bytes), no marker,
and no Runner scope, Kernel commit, or signature-check evidence. The test
cleaned the temporary artifacts. This is another interaction timeout and does
not falsify the lower-level scoped Kernel/Runner tests. The user's `PASS` report
for the older `3mfj1nf_` path remains separate evidence and is not assigned to
this run.

## 2026-10-01 canonical suite after Picker prompt regression

The current worktree passed the canonical command
`python3 -m unittest discover -s tests -v`: 212 tests, 437.331 seconds. This
includes the prompt timeout regression and real-OS sandbox/changeset checks.
Product XPC coverage in this run was headless; it did not open the system Picker
or add evidence for the normal Product Launcher read/list integration.

After reopening the Picker, the user reported selecting the
`khaos-seed-app-3mfj1nf_` workspace and seeing `PASS`. The current Launcher shows
that alert only after scoped read/list allow and deny, post-scope OS read denial,
Runner write allow and deny, Kernel writeback, and direct-write denial. This is
user-observed execution evidence for those gates. The temporary app/workspace
and test-parent output were absent at inspection, so this report cannot be bound
to an exact bundle digest or independently verify the post-alert deep-signature
assertion. The earlier 103.483-second acceptance-bundle run remains evidence for
its own build; the `rx5bn0nu` timeout remains a distinct attempt with no selection.

## 2026-10-01 final-unlink symlink target confinement

A retained real Broker/Seatbelt regression pauses after the sentinel path's
inode validation and before the commit child's final `unlink`. An independent
same-UID process atomically replaces that in-workspace path with a symlink to an
outside canary. The commit completes its validated file replacement and removes
the raced symlink entry; the canary retains its exact original bytes. This
exercises the final check-to-unlink window and confirms that pathname `unlink`
does not follow a symlink target, including under the real commit child's
changeset-scoped Seatbelt profile.

This does not close the race: a regular competing entry at that authorized
workspace name can still be removed, and an unconfined same-UID process already
has independent workspace access. It establishes only that this cleanup cannot
use a raced symlink to mutate the symlink target outside the commit scope. Apple
documents `unlink(2)` as removing the named directory entry, and XNU exposes
`unlinkat` with a directory descriptor and path but no expected inode
([Apple `unlink(2)`](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/unlink.2.html),
[XNU syscall table](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/syscalls.master)).

The focused regression passed in 11.996 seconds; all 39 Broker tests passed in
73.577 seconds, and the canonical `python3 -m unittest discover -s tests -v`
suite passed all 216 tests in 441.428 seconds. The default suite did not open
the Picker.

## 2026-10-01 App-Sandboxed Kernel image-backend check

The initial implementation attempted to create and attach the fixed-capacity
APFS sparsebundle from the App-Sandboxed Kernel XPC service. The real
`test_app_sandbox_cannot_create_or_mount_kernel_apfs_images` has unconfined
positive controls; its signed App-Sandboxed helper can write its private
temporary directory, but `hdiutil create` and the production `hdiutil attach`
command return nonzero without creating a mounted image. This is direct host
evidence for that `hdiutil` path, not proof that every image API or Seatbelt
policy is unavailable. It is no longer the current product composition: image
operations now run in the separate Snapshot Broker described below.

## 2026-10-02 App Sandbox `diskutil image attach` mount check

The signed App-Sandboxed regression now tests the exact `diskutil image attach
--plist --nobrowse --mountPoint` form against a host-created APFS sparsebundle.
The unconfined control mounts and verifies that same image using both `hdiutil`
and `diskutil`. In the sandbox, both `hdiutil create` and `hdiutil attach`
return status 1. `diskutil image attach` also returns status 1, but unlike the
`hdiutil` attempt it registers a disk image and APFS device without a mountpoint.
The helper discovers that APFS volume device from `hdiutil info -plist` and
tries `diskutil mount -mountPoint <path> <device>`; it returns status 1 and the
requested directory never becomes a mount. The unconfined test process detaches
the partially registered image and verifies the system inventory and mountpoint
are clear before deleting the disposable container data.

This proves only that the tested App-Sandboxed path cannot mount the private
APFS volume on this macOS host. A nonzero `diskutil image attach` status is not
proof that no OS-visible device was created. The probe is an ad-hoc signed app
with the App Sandbox entitlement, not the production `KernelProduction.xpc`
entitlement set or XPC execution path. The Broker remains the current tested
mount path and its broader process authority remains an open containment gap.

Apple's [DiskImageKit documentation](https://developer.apple.com/documentation/DiskImageKit)
describes image creation and management primarily for Virtualization storage.
Its documented attachment path passes the image to Virtualization through
[`VZDiskImageStorageDeviceAttachment`](https://developer.apple.com/documentation/virtualization/vzdiskimagestoragedeviceattachment);
the public API does not document mounting the image as a host filesystem. On
this macOS 27 host the runtime framework exists, but the selected Xcode 26.5
SDK contains no DiskImageKit module and `swift import DiskImageKit` fails with
`no such module`. The official page also labels the API preliminary. This does
not establish a supported host-mounted APFS replacement for the current build.
Do not dynamically bind the runtime framework or replace the bounded image with
an ordinary directory unless an available public API and real capacity/isolation
tests establish equivalent enforcement. This finding drove the separate Broker
design; that Broker's lack of process-level OS confinement is the remaining
containment gap, not the production Kernel service.

## 2026-10-01 Sandboxed Kernel access to an externally mounted APFS volume

The real App Sandbox probe creates a mount point under a signed test app's own
Application Support container. An unconfined test parent attaches the existing
64 MiB APFS sparsebundle there with `hdiutil`; the sandboxed helper reads a
host-written canary, atomically writes and reads back a second file, and the host
detaches and remounts the image to verify both persisted contents. The focused
test passed on this macOS 27 host with read, write, and write-readback all
allowed. The sandboxed process cannot create the image with the production
`hdiutil` path or mount it with the tested `hdiutil` and `diskutil` paths, though
`diskutil image attach` can register an unmounted device as described above.
This establishes that the OS file boundary permits a separate mount broker to
serve a volume inside an App Sandbox container.

The later packaged implementation uses a separate `KernelSnapshotBroker.xpc`.
The production `KernelProduction.xpc` has the App Sandbox entitlement; the
Broker does not. Its named bootstrap is Launcher-identity-bound, its anonymous
operation listener accepts the Kernel's signed requirement, and it accepts only
the canonical private storage directory inside that Kernel's container. It
holds scoped access and an exclusive lease lock through create, mount, cleanup,
and restart recovery. The real signed-product headless test exercises create,
attach, release, and the unmounted-volume check through this packaged Broker.
This narrows the Kernel's OS authority and prevents unauthenticated peers from
using the Broker, but the Broker itself remains trusted, unsandboxed code with
broader process authority; protocol and path checks are not process confinement.
See [`KERNEL_ABI.md`](KERNEL_ABI.md#product-apfs-snapshot-broker-handoff).

Apple describes [DiskImageKit](https://developer.apple.com/documentation/DiskImageKit)
as an API to create, open, and manage images, designed primarily for
Virtualization storage. The current Seed needs a host-mounted APFS filesystem;
the public API page does not describe a host mount operation, and the selected
Xcode 26.5 SDK has no `DiskImageKit` module. The existing `hdiutil` path remains
the available backend, not a claim that no other public API can ever satisfy the
requirement.

## 2026-10-02 restricted Seatbelt probe for `hdiutil`

To test whether only the Broker's `hdiutil` child can be confined, a disposable
macOS probe launched `hdiutil` under `sandbox-exec` with a deny-by-default SBPL
profile, exact temporary image/mount paths, APFS mount/unmount rules, and the
DiskImages IOKit/XPC operations present in the local Apple system profiles.
The first profile stopped at dyld startup; importing Apple's local
`dyld-support.sb` made the binary start, but restricted `hdiutil create` and
`attach` still failed with `ENXIO` (`Device not configured`). The same-host
unconfined create control and an `allow default` create control both succeeded.
No volume was left mounted and no production code changed.

This is evidence that the attempted narrow Seatbelt policy is incomplete, not
proof that every restrictive policy or public macOS API is impossible. The
Seed must keep the currently tested Broker boundary and must not silently fall
back to an ordinary directory or dynamically bind the undocumented runtime
framework. Any replacement must first demonstrate bounded storage, real mount
isolation, fail-closed behavior, and adversarial tests on the supported macOS
version. Apple's [XPC documentation](https://developer.apple.com/documentation/XPC)
identifies process separation as a privilege-isolation mechanism; the current
Broker uses that separation, while its missing OS process confinement remains
an explicit open containment gap.

## 2026-10-02 temporary App Sandbox exception probe for DiskImages

A second signed disposable app-sandbox probe added Apple's documented
temporary-exception entitlements for the DiskImages mach services and IOKit
client classes observed in the local system profiles. The first exact set
(`DIDeviceCreatorUserClient`, `DIDeviceIOUserClient`, DiskImages XPC services,
Disk Arbitration, and `amberd`) still failed `hdiutil create` and `attach`.
Kernel sandbox logs identified further denials from `hdiutil` and the spawned
`diskimages-helper`: `com.apple.system.hdiejectd.xpc`, then
`IOHDIXControllerUserClient`, `IOHDIXHDDriveOutKernelUserClient`, and the
distinct mach name `com.apple.system.hdiejectd`. Each observed mach name and
IOKit class was added only to the disposable signed probe. The final run still
did not create or mount an image; its image inventory contained no matching
image, and no volume remained mounted. It also reported denied `system-info
vfs.disk-space` and `sysctl-write vfs.generic.noremotehang` operations. These
results show that the currently documented temporary exceptions and the
observed service/class list did not yield a working sandboxed Broker on this
host. They do not prove that all possible approved entitlements or supported
backends are unavailable.

Do not add these experimental exceptions to the product signature. Apple
requires temporary-exception usage details and asks developers to file a
Feedback Assistant report when an exception works around a missing App Sandbox
feature ([App Sandbox submission guidance](https://developer.apple.com/help/app-store-connect/reference/app-uploads/app-sandbox-information),
[temporary-exception entitlement reference](https://developer.apple.com/library/archive/documentation/Miscellaneous/Reference/EntitlementKeyReference/Chapters/AppSandboxTemporaryExceptionEntitlements.html)).
The local `com.apple.diskimages*.sb` profiles are explicitly marked by Apple as
private and subject to change, so they remain diagnostic evidence rather than
a product policy dependency. The Broker containment gap remains open; continue
to prefer a supported mechanism that can confine the Broker without silently
discarding the bounded APFS capacity or isolation guarantees.

A separate host control used the current `diskutil image` CLI: `create blank`
produced a 64 MB UDSB/APFS image, `attach --plist --nobrowse --mountPoint`
mounted it at the requested directory, and `unmount` plus `eject` left no
attached image. A signed App-Sandboxed probe with the temporary mach/IOKit
exceptions above stopped during `diskutil image create blank` with status `64`
and `Couldn't match file system for APFS`; it never reached attach, and the
image inventory remained empty. This shows the host CLI path works, but the
sandboxed probe did not establish an App-Sandboxed replacement backend.

A further deny-by-default Seatbelt profile imported Apple's local `system.sb`
and added operation rules for the exact temporary storage/mount paths, observed
DiskImages mach names and IOKit classes, `vfs.disk-space` system information,
and the `vfs.generic.noremotehang` sysctl write. The policy loaded and ran
`hdiutil help`, but `hdiutil create` did not return within 45 seconds; the
process group was killed, and the image inventory showed no matching attachment
or mount. This is inconclusive, not a successful confinement proof or an
impossibility result. `system.sb` also declares itself private and unstable, so
it must not become a product dependency. The prior completed restricted
Seatbelt probe remains the only result here that reached `hdiutil create` and
returned `ENXIO`.

## 2026-10-02 real process Seatbelt for the packaged snapshot Broker

The packaged `KernelSnapshotBroker.xpc` still cannot use App Sandbox for the
current APFS create/attach path. An exact `process-exec` allowlist for
`hdiutil`, `diskutil`, and the observed `diskimages-helper` also failed to
complete the Broker's snapshot transaction. The first signed-product attempt
without `diskimages-helper` stalled; unified logs showed `hdiutil` was denied
when it tried to execute that helper. Adding the exact helper path allowed the
helper to start, but the Broker returned `snapshot_broker_rejected`. A direct
Seatbelt control using that process filter allowed `diskutil info` and returned
`EPERM` when executing `/usr/bin/true`; this checked the filter itself, not the
complete Broker transaction. The exact allowlist was removed, and the focused
signed-product test passed with the existing policy in 36.047 seconds. The
failure does not identify the later incompatible operation or prove that every
possible process policy will fail, so no additional executable paths were
allowed based on inference.

A separate process policy now uses the system `libsandbox`
`sandbox_init(3)` entry point before either Broker listener resumes. Startup exits
if the library, symbols, container identity, or profile initialization fails.
The fixed profile denies network operations, Home file data/xattrs/writes outside
the private Kernel snapshot subtree, metadata for other Home entries, data access
to standard temporary roots and `/Volumes`, and execution of Home programs. It
also denies execution below the standard Homebrew prefixes `/opt/homebrew` and
`/usr/local`, and denies the APFS Data-volume spelling of the Home directory.
Directory-data and metadata access to the exact ancestor directories needed to
traverse to the private subtree remain allowed; those ancestor rules do not
exempt file writes.
`hdiutil` and `diskutil` are still called only with Kernel-owned fixed arguments,
and their `TMPDIR` is the private storage root.

The focused signed-product test passed on the current macOS host in 26.090 seconds.
The real production Broker created, attached, released, and detached its APFS
snapshot under this policy. A test-only replacement for the Broker executable
applied the exact production policy, then attempted Home `open`/`lstat`/create,
Home directory `chmod`, reads through `/System/Volumes/Data/Users/...`, writes
to the host's default temporary path and `/tmp`/`/var/tmp`, `posix_spawn` of a Home
executable, `open(O_WRONLY)` on the signed Kernel executable, and IPv4 loopback
connect. Every operation returned `EPERM` or `EACCES`; same-host parent controls
proved the corresponding paths and socket were usable. File canaries and directory mode
remained unchanged, the Kernel digest and deep app signature remained valid, and
the image inventory returned to baseline. The product test is headless and does
not open the Picker. The canonical `python3 -m unittest discover -s tests -v`
suite passed all 235 tests in 469.450 seconds, also without opening the Picker.

A second disposable signed Broker was compiled from the production service and
main sources with only its profile text changed to invalid SBPL. The OS rejected
the real `sandbox_init(3)` call, and the service exited before listener startup;
the Launcher received no authenticated endpoint. This proves the current startup
ordering's fail-closed response to a policy parse failure, not every possible
failure mode of the private Seatbelt API.

A follow-up keeps the global process-execution allowlist rejected but denies the
two standard Homebrew prefixes. On this Apple Silicon host, the real Broker
still completed APFS create/attach/release; the same-policy signed probe first
ran `/usr/bin/true` from Homebrew's writable temporary directory as a host
control, then observed `EPERM` or `EACCES` from Broker `posix_spawn`. The
focused signed-product test passed in 41.163 seconds, and the canonical suite
passed 244 tests in 469.829 seconds. This verifies `/opt/homebrew` on this host,
not `/usr/local` on Intel or every user-writable executable path.

After the suite, no Khaos process or temporary mount/device remained. `hdiutil
info` did report seven entries at nonexistent temporary `khaos-snapshot-*`
paths with process IDs that were no longer present. There was no pre-run image
inventory baseline, so these unmounted stale records are not attributed to this
run.

The policy is an intentional but incomplete containment step. It uses
`(allow default)` with explicit deny rules rather than a full resource allowlist;
the Broker retains default authority for system paths outside the rules. The
macOS `sandbox_init(3)` manual marks this API deprecated. App Sandbox remains
unavailable for the mount implementation tested here, and no supported public
replacement was established in the probes above. Keep this residual risk visible;
do not describe the Broker as fully sandboxed, and do not treat the test as proof
for every filesystem, IPC, device, process, OS release, or installation-integrity
path.

## 2026-10-02 Broker tool process-group cleanup

The trusted Snapshot Broker now starts `hdiutil` and `diskutil` with
`posix_spawn`, a dedicated process group, an explicit environment, close-on-exec
default, and only the required standard streams. Cancellation and timeout send
`SIGTERM`, then `SIGKILL` to the whole group before reaping the group leader.
Keeping the leader unreaped during group signaling prevents its PID from being
reused as an unrelated process-group ID. Recovery and rollback tools marked as
allowed during cancellation may run under the service owner; the Broker must not
treat that owner mismatch as proof that the cleanup process is unauthorized and
kill it immediately.

The real macOS process-group test launches a shell with a `sleep` descendant,
then verifies normal leader exit, timeout, cancellation, and the OS auto-reaped
`ECHILD` path stop that descendant while leaving an unrelated process alive.
The `ECHILD` case also verifies the finish callback clears process tracking.
It runs the production runner against `hdiutil info -plist` and validates the
returned property list. The signed product-bundle XPC test exercised the real
Broker's stale-lease recovery, APFS image creation, attach, release, detach, and
OS-restriction attacks after this change. The canonical headless suite passed
236 tests in 473.447 seconds.
These checks do not open the Picker and do not correlate the previously reported
`kernel_bridge_failed` dialog with this Broker recovery issue. On 2026-10-04,
host inspection found a three-hour-old `hdiutil create` with PPID 1 targeting a
missing Khaos Broker lease directory; `hdiutil info` showed no attached image.
The exact process was terminated after confirming there was no matching mount.
The originating run could not be identified, so this records a stale-process
observation only; it does not distinguish abrupt Broker termination from an
external test interruption.

Apple's `posix_spawnattr_setpgroup` manual documents that `pgroup = 0`, with
`POSIX_SPAWN_SETPGROUP`, creates a new process group for the child
([Apple manual](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man3/posix_spawnattr_setpgroup.3.html)).
This is a cancellation/timeout boundary for descendants that remain in the
group. It does not prove cleanup after abrupt Broker termination, nor contain a
descendant that deliberately leaves the group. Those cases still need separate
real-OS evidence. The Broker's broader containment limitations described above
remain unchanged.

## 2026-10-02 Snapshot Broker process-execution allowlist experiment

To test whether the Broker could execute only `/usr/bin/hdiutil` and
`/usr/sbin/diskutil`, a temporary profile added a global `process-exec` denial
followed by literal allows for those two paths. A small direct `sandbox-exec`
check allowed an exact `/usr/bin/true` launch and denied `/usr/bin/id`, but that
did not model DiskImages' subprocess behavior. The focused signed-product
XPC test then timed out while its real Broker `createSnapshot` request remained
active; process inspection showed two `hdiutil create` leaders still present
after the test failure. They were terminated, the experimental profile and
probe changes were reverted, and the same focused test passed in 28.720 seconds.

No sandbox denial log established which operation kept `hdiutil` from
completing. The process-execution allowlist is rejected for now; the Broker
retains its previous Home-path execution denial and documented default
authority. Do not treat the direct `sandbox-exec` check as evidence that the
product Broker works with this restriction. Revisit only after identifying the
required DiskImages process behavior and proving timeout/cancellation cleanup
through the real product service.

## 2026-10-03 Snapshot Broker package-manager write denial

The process-execution-root rule left a related writable path: with
`(allow default)`, a compromised Broker could still create or replace files in
user-writable package-manager trees. The production SBPL now also denies
`file-write*` under `/opt/homebrew` and `/usr/local`, while leaving reads
available for system tools. This reuses the existing Seatbelt policy boundary;
it adds no third-party library or sandbox backend.

The signed-product XPC probe first proves that the host can create and remove a
fresh file in `/opt/homebrew/var/homebrew/tmp`. The same-identity Broker then
attempts the same create under the exact production profile and receives
`EPERM` or `EACCES`; the path remains absent. In the same focused test, the real
production Broker completes APFS image creation, attach, lease release, and
detach. The focused test passed in 30.237 seconds; the canonical unittest suite
passed 244 tests in 470.812 seconds. Neither test opens the Picker.

This evidence is limited to the writable `/opt/homebrew` canary on the current
Apple Silicon host; `/usr/local`, other macOS releases, and other system paths
are not covered. The Broker remains on `(allow default)` with explicit denies,
so this does not establish deny-by-default confinement or complete containment.

The follow-up also denies the Data-volume firmlink spellings of both package
manager roots for writes and process execution. The signed-product probe first
confirms that `/System/Volumes/Data/opt/homebrew` is the same writable directory
as `/opt/homebrew`, then runs and creates canaries through the alias as host
controls. A same-identity test Broker using the production policy helper
receives `EPERM` or `EACCES` for both operations, and production APFS snapshot
create/attach/release still succeeds.
The focused test passed in 28.856 seconds. This host exercises the
`/opt/homebrew` alias only; it does not establish `/usr/local` or other-system
coverage. The profile remains `(allow default)`.

## 2026-10-04 Snapshot Broker temporary metadata denial

The production profile now also denies `file-read-metadata` and
`file-test-existence` under standard temporary roots, except the fixed Broker
storage subtree and its path ancestors. The signed-product XPC probe confirms
the host can inspect `/var/tmp`, then requires Broker `lstat` and `access(F_OK)`
on that path to receive `EPERM` or `EACCES`. The same headless test still
completes APFS create/attach/release/detach; it passed one test in 27.928
seconds. This closes the tested temporary-root metadata/existence access only;
the Broker still uses `(allow default)` and retains authority outside its
explicit deny rules.

## 2026-10-04 Broker write-denial boundary experiment

A temporary rule denied `file-write*` across `/`, excluding only the fixed
storage subtree and its path aliases. The focused signed-product test then
timed out during the authenticated Kernel/Broker snapshot request, before the
positive APFS flow completed. The test supplied no evidence identifying which
filesystem write the XPC or DiskImages path required. The broad rule was
removed; the same focused test passed afterward in 29.549 seconds. This rejects
the rule as a working Broker policy, but does not prove that any particular
outside-storage write is required. Do not restore it until the denied operation
is identified; keep the broader `(allow default)` limitation explicit.

## 2026-10-04 Snapshot Broker process-metadata filter probe

The signed test Broker returned success when the host process's numeric
`KERN_PROCARGS2` MIB was queried under either `(deny process-info*)` or
`(deny sysctl-read (sysctl-name "kern.procargs2"))`. Those rules and the
unproven assertion were removed. The result shows that these attempted SBPL
filters do not deny this numeric-MIB path on the current host; Runner's
deny-default process profile is separate evidence and does not establish the
same restriction for the Broker's `(allow default)` profile. Do not claim
Broker process-argument isolation until a matching OS rule is demonstrated.

## 2026-10-04 same-UID writeback authority option

The final-unlink race above cannot be closed by another inode check: Apple's
`unlink(2)` removes a named entry, and XNU exposes `unlinkat(dirfd, path, flags)`
and `renameatx_np(fromfd, from, tofd, to, flags)` without an expected inode
argument. These remain pathname operations. An advisory lock or a second
pathname check does not constrain an unrelated process with the same UID.

macOS Service Management can install a `LaunchDaemon` that runs as root, but
Apple requires admin approval before launchd bootstraps it. Such a commit helper
would introduce a new privileged TCB component, installer/approval flow, and
authenticated request protocol. Seed does not add that service: the current
threat model is untrusted Runner code confined by Seatbelt, and the real Runner
attack test denies its concurrent live-workspace replacement attempts. This is
not a claim that arbitrary unconfined same-UID writers are excluded. Revisit a
privileged writer only if that broader threat model becomes a product
requirement.

Sources: Apple's [`unlink(2)`](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/unlink.2.html),
XNU [`syscalls.master`](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/syscalls.master),
and Apple [Service Management](https://developer.apple.com/documentation/servicemanagement)
and [`SMAppService.register()`](https://developer.apple.com/documentation/servicemanagement/smappservice/register%28%29) documentation.

## 2026-10-05 Seed local Agent Host model

The Agent Host now runs a bounded local llama.cpp completion in its own signed,
App-Sandboxed XPC service. llama.cpp v0.5.0 (`7fe450e`) is built with Metal,
OpenMP, and OpenSSL disabled; the builder copies its dynamic libraries and MIT
license beside the model, then signs the Agent Host separately from the trusted
Launcher. The runtime uses `--device none`, `--offline`, a private mode-0600
prompt file, bounded output, and a fixed CPU thread count. See the upstream
[build guide](https://github.com/ggml-org/llama.cpp/blob/v0.5.0/docs/build.md).

The initially available Qwen2.5-0.5B-Instruct Q4_0 model repeatedly chose the
tool branch for an ordinary text request under the bounded action grammar, so
it was not retained as the tested development model. The pinned official
Qwen2.5-1.5B-Instruct Q4_0 artifact from revision
`91cad51170dc346986eccefdc2dd33a9da36ead9` (Apache-2.0) produced a valid text
action for the same short request. Its SHA-256 is
`dcd819ff094852c38faba6873d8ff0c9d51eadb2844539e52042ae5d647bbfdb`; the
signed Agent Host bundle records the model and runtime digests/version in its
Info.plist.

The signed product's `--agent` path completed one real local text turn through
launchd-managed Agent Host XPC (`READY.`). The focused signed-product XPC test
passed (1 test, 41.693 seconds) and used a test model child to require actual OS
denials for direct read/write opens of a parent-readable canary, while checking
the canary and deep signature. This is evidence for that text turn and canary
on the tested host only. It does not establish general model quality or a
model-generated tool call; model output remains untrusted, and every tool
proposal still requires Launcher approval and Kernel enforcement.

## 2026-10-05 Agent Host tool-action probe

Two requests to the existing signed product's local Agent returned a text-only
description or `model_request_failed`; neither opened the workspace Picker or
changed a file. A temporary prompt revision required a structured `type=tool`
action for explicit file/command requests and specified relative workspace paths.
The resulting app passed deep signature verification and the headless
authenticated XPC bootstrap check, but the prompt revision did not resolve the
tool path and was reverted.

On that rebuilt app, a simple empty-file request remained pending beyond the
Launcher XPC client's configured 180-second wait. The process was stopped after
confirming no Picker had opened and the disposable workspace remained empty.
The bundled model and `llama-cli` were present in the signed Agent Host bundle.
This is an unresolved Agent Host/model request-liveness or model-generation
failure, not evidence of a Kernel writeback failure. A real model-generated tool
proposal followed by user approval and Kernel execution remains unverified.

## 2026-10-05 Runner live-workspace bypass retest

The focused real-macOS test
`python3 -m unittest discover -s tests -p test_launcher.py -k test_runner_cannot_bypass_kernel_authority -v`
passed (1 test, 3.354 seconds). Positive controls first proved native
`fclonefileat` and `renameatx_np(RENAME_SWAP)` work on the test volume. During a
real Seatbelt Runner invocation and while its Kernel commit was pending, both
Plugin code and the fixed command received OS denials for direct live-workspace
read/list/write, unlink, rename, clone, and swap attempts. The Runner still read
and listed its exact Kernel scope, changed only its private snapshot, and the
Kernel committed exactly that one modified file. The live file, rename peer,
outside canary, and Kernel source matched the expected postconditions. This
revalidates the Plugin/command boundary on this host; it does not close the
separately documented final-unlink race against an unconfined same-UID process.

## 2026-10-05 authenticated Kernel XPC retest

The focused signed-product test
`python3 -m unittest discover -s tests -p test_macos_xpc_sandbox.py -k test_seed_app_builds_and_authenticates_its_kernel_service -v`
passed (1 test, 32.282 seconds) without opening a Picker. It rebuilt the local
product, rejected wrong-signing-identity clients for both `KernelProduction.xpc`
and the snapshot Broker, and exercised the real Kernel XPC's malformed/bounded
request attacks, including source-digest mismatch and malformed or over-budget
scope requests before bookmark handling. Along with the real Seatbelt Runner
test above, this provides fresh host-local evidence for the authenticated,
bounded IPC and OS-enforced direct-write denial portions of the execution chain;
it does not address arbitrary unconfined same-UID writers or Candidate admission.

## 2026-10-05 IPC Runner cannot write the commit snapshot

The real Seatbelt regression
`python3 -m unittest discover -s tests -p test_macos_seatbelt.py -k test_runner_sandbox_cannot_access_workspace_snapshot_or_user_home -v`
passed on the current tree (1 test, 0.036 seconds). Host controls first read the
snapshot fixture and write canaries successfully; the isolated IPC Runner then
received OS denials for direct snapshot reads and writes, as well as direct live
workspace and HOME access. The sandboxed command child is the only untrusted
process with direct writable snapshot access; the trusted Broker retains its
narrow SDK-write and commit paths. The command process group is terminated
before `serve_workspace_commit()` begins. The real descendant-cleanup regression
`python3 -m unittest discover -s tests -p test_macos_seatbelt.py -k test_command_exit_kills_snapshot_writer_before_commit -v`
also passed (1 test, 2.773 seconds); a child released after its command parent
exits cannot add a late snapshot file. Together with the Runner-bypass retest
above, this closes the reviewed Runner-to-snapshot concurrent-write concern for
the tested Seatbelt path. It does not claim exclusive write authority against
unrelated unconfined same-UID processes.
