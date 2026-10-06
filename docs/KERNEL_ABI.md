# Kernel Runner ABI v7

This document records the current development ABI between the one-shot Kernel
worker and its isolated Runner. Runner ABI v7 executes one untrusted Python
`run()` entrypoint and adds bounded Plugin input, opaque logical-Plugin state,
and bounded Plugin output to the existing Runner path. The separate native
Workspace XPC operation ABI v10 provides a minimal, fixed-slot Candidate
lifecycle and state-only invocation around that Runner. This is Seed product
behavior, not a complete production Plugin platform.

The transport, session, operation, and Native macOS Workspace XPC sections below
define the current normative wire contracts. The dated sections after the ABI
specifications preserve historical test evidence; they do not change the
contract.

## Transport and envelope

The Kernel and Runner exchange length-prefixed UTF-8 JSON on private anonymous
pipes. A separate one-time macOS AF_UNIX handshake checks both OS peer PIDs
before framed messages begin. Pipes do not carry descriptor-passing ancillary
data. The Runner SDK reads replies from standard input and writes requests to
standard output; its public functions do not accept descriptor overrides.
After the ping, the Kernel sends one `plugin.start` frame containing up to
10 KiB of UTF-8 source and, for a product Plugin invocation, one optional
bounded JSON object input. The Runner executes it inside its Seatbelt process;
Python source execution is not itself a security boundary.
The product `--plugin-install` path captures a strict Manifest and source
through a trusted package Picker and asks the Kernel to admit an immutable,
content-addressed Candidate. A separate user confirmation activates the exact
Candidate, Manifest, and normalized capability-scope digests at the reviewed
slot generation. The Kernel fixes the slot to `primary` and validity to 30 days.
`--plugin-run` asks the Kernel to load source and scopes from that active slot;
the request cannot supply either. `--plugin-rollback` routes future runs to the
verified previous Candidate. Product Plugin input is untrusted business data,
not authority. The Kernel retains the Plugin state root and logical `plugin_id`
separately from Candidate code and activation metadata; Runner state operations
have no namespace or path argument.

The Runner Seatbelt profile is default-deny and grants no Mach service lookup;
it permits only the exact private AF_UNIX peer socket. A real macOS attack test
first resolves the active LaunchServices Mach service from the unsandboxed test
process, then confirms the Runner lookup returns
`BOOTSTRAP_NOT_PRIVILEGED` (1100). The same profile still permits the
peer-PID-checked Unix socket and denies loopback and unrelated Unix sockets.
This proves the process-level Mach lookup restriction; separate signed-XPC
tests exercise peer-identity rejection.

Each request has exactly these fields:

```json
{"version":7,"request_id":"32 lowercase hex characters","operation":"...","payload":{}}
```

Each response is either:

```json
{"version":7,"request_id":"...","ok":true,"result":{}}
```

or:

```json
{"version":7,"request_id":"...","ok":false,"error":{"code":"..."}}
```

Frames are limited to 64 KiB and eight structural JSON nesting levels. Plugin
input is limited to 8 KiB and six structural nesting levels. State blobs are
limited to 32 KiB; Plugin output is limited to 8 KiB. The depth check ignores
braces and brackets inside JSON strings and does not rely on the Python
decoder's recursion behavior. Calls use bounded receive and send deadlines;
`process.exec` is capped at 30 seconds, and a Runner session accepts at most
128 filesystem requests and 32 Plugin state requests.

## Session order

1. The Kernel sends `ping`; the Runner validates the nonce and responds.
2. The Kernel sends one `plugin.start` frame with bounded source and optionally
   a bounded JSON object input. Source-only development runs call `run()`;
   product Plugin invocations with input call `run(input)` and must return one
   JSON object through `plugin.output`.
3. A product Plugin may issue up to 32 `state.read` / `state.replace` requests
   and up to 128 scoped filesystem requests through the same Runner pipe. The
   Kernel supplies the logical Plugin identity from the active Candidate and
   the private state root from trusted product configuration. Neither state
   operations nor Plugin input can select a namespace or path. State contents
   are opaque to the Kernel.
4. Workspace-capable runs retain the existing scoped `fs.read`, `fs.list`,
   `fs.write`, optional `process.exec`, and `workspace.commit` flow. The Kernel
   enables `process.exec` only when the active Manifest allows it. It retains
   timeout, cwd, environment, snapshot, scopes, and sandbox policy. The Runner
   cannot change those values. `process.cancel` remains bound to the active
   command request ID.
5. A state-only product Plugin has no workspace bookmark, read scope, write
   scope, or `process.exec`. It uses the existing Worker and Seatbelt Runner
   against an empty private snapshot, returns its bounded Plugin output, and
   ends with a zero-entry changeset; it does not send `workspace.commit`.
6. When a workspace-capable run sends `workspace.commit`, the Kernel validates
   the retained snapshot before any writeback.
   Broker tests verify that a nonempty `workspace.commit` payload receives
   `invalid_request`; a real macOS Seatbelt integration attack lets the
   Runner-selected command write an uncommitted snapshot file, then sends a
   forged changeset and alternate
   workspace. The session fails, the snapshot file is not written back, and an
   outside canary remains unchanged. `workspace.commit` is terminal: after the
   Kernel replies, the Worker closes both Runner pipes and waits up to five
   seconds for the Runner to exit, then kills it if it is still running. A
   post-commit Runner write is rejected by Seatbelt, and a late SDK write fails
   on the closed IPC pipe. Runner cleanup timeout cannot change a successful
   trusted commit result; a real macOS test confirms a Runner that spins forever
   after commit is killed while the committed file and success result are kept.

The v7 session accepts command `argv`, but does not accept a caller-selected
workspace, cwd, environment, directory descriptor, read/write scope, capability
string, or approval boolean from the Runner. The selected workspace and snapshot
remain trusted parent state. The current one-shot operation order and scope do
not establish a user approval model.

Filesystem operation payloads also use exact schemas: `fs.read` and `fs.list`
accept only `path`; `fs.write` accepts only `path` and `data_base64`. A Runner
cannot attach `workspace_read_scope` or `workspace_write_scope` to an operation.
Raw-wire Broker tests require those attempts to receive `invalid_request`; a
real macOS Seatbelt Runner test additionally requires the session to fail before
`process.exec` runs or any snapshot write reaches the live workspace.

The trusted Launcher can cancel its active `workspace.run` request with one
`workspace.cancel` frame bound to that request ID. The Worker checks it before
the Seatbelt probe, while the probe runs, during snapshot entry and file-chunk
copying, while the command runs, and until the commit child crosses its
pre-mutation gate. A cancelled snapshot is discarded before Runner launch.
This launcher-to-worker control frame is separate from Runner `process.cancel`.

The development launcher's `workspace_read_scope` is a bounded list of
workspace-relative paths retained by the Worker. An empty list denies all
Runner-mediated `fs.read` and `fs.list` calls and all command reads from the
private snapshot. A file path permits that baseline file; a directory path
permits its baseline subtree. Listing an ancestor of an allowed path returns
only entries on paths covered by the scope. The workspace root cannot be
granted as a path. The list is limited to 128 paths and 4 KiB of encoded path
data. The OS command profile grants reads only for baseline regular files and
directories selected by the scope; symlinks, missing roots, and symlink or
non-directory ancestors receive no command read rule. This is still not a
Plugin identity-bound or user-approved capability.
A real macOS integration test confirms the command can read scoped data,
cannot read an unscoped sibling, and cannot escape through an in-scope symlink
or by replacing an allowed file with a symlink. The test also attempts to
hardlink an unscoped file under an allowed directory; it accepts OS denial of
link creation and, if creation succeeds, requires the alias read to be denied.
The command can write file data and create entries throughout the private
snapshot, so the Seatbelt profile also denies `file-write-unlink` on unreadable
baseline files/subtrees after its broad write grant, and protects directory
ancestors of exact-file read roots. Together these restrictions prevent
deleting/renaming unreadable baseline paths and block `rename` or APFS
`RENAME_SWAP` from moving their content onto a readable path. An empty scope,
or one with no root tied to a safe baseline entry, denies snapshot entry
movement. The real macOS regression covers `os.replace`,
`RENAME_SWAP`, scope-parent directory moves, and case/Unicode-normalization
aliases resolved by the host volume. If the scope is empty or none of its roots
can be tied to a safe baseline entry, snapshot entry movement is denied. Scope
rule limits apply to these movement guards too; overflow fails closed before
command execution.
Scope matching uses the exact Unicode spelling of each path component. The
Kernel does not normalize Unicode or fold case: callers should use names returned
by `fs.list`, and a different spelling that the filesystem aliases to the same
entry is denied before lookup.

The development launcher's `workspace_write_scope` is a list of exact
workspace-relative entry paths. It does not allow descendants or authorize a
directory tree. Runner SDK `fs.write` uses it to replace or create only a
regular file in the private snapshot, with no-follow path traversal and a
32 KiB content limit. Existing files retain their permission bits; new files
use mode `0600`. The request returns the byte count and SHA-256 of the supplied
content. Writes never target the selected live workspace directly.

At commit, the Kernel compares the complete validated changeset against the
same scope. Every added, modified, or deleted filesystem entry must exactly
match a listed path; a parent entry does not authorize descendants. An empty
scope permits only a no-op commit. Creating a directory tree requires listing
each new directory and file; deleting a tree requires listing each removed
entry. If any changed path is missing, the entire changeset is rejected before
the live-path mutation gate. These checks apply to command output as well as
SDK writes. The scope is retained by a trusted development launcher; it is not
user approval or a Plugin-bound capability grant.

The Runner-selected `process.exec` operation may write file data and create
entries throughout the private snapshot so coding commands can run tests,
formatters, and project scripts there. Seatbelt denies unlink/rename of unreadable
baseline entries and their protected subtrees to preserve read scope. The command
cannot write the live workspace or outside paths under Seatbelt. The Kernel treats
the entire resulting snapshot diff as untrusted input, validates it, and commits
only if every changed entry is in `workspace_write_scope`; it rejects out-of-scope
output as one unit before live mutation. This exact-path scope is still an
implicit trusted-launcher session parameter, not user approval or a
Plugin-bound capability grant.

## Operations

### `plugin.start` (Kernel to Runner)

The source-only payload is `{"source":"..."}`. A product invocation uses
`{"source":"...","input":{...}}`. Source is nonempty and no larger than
10 KiB encoded as UTF-8. Optional input is a JSON object, no larger than 8 KiB
in canonical UTF-8 JSON and at most six structural nesting levels. The Kernel
validates only encoding, framing, size, and nesting; it does not interpret
operation names or business fields. The Runner executes a module-level
`run()` or `run(input)` inside its own process. The Kernel does not import or
compile the source. Source and input are untrusted; OS Seatbelt restrictions
and Kernel-side IPC validation remain the enforcement boundary.

### `state.read`

Request payload is exactly `{}`. The Runner SDK accepts no Plugin ID, namespace,
path, or lifecycle selector. The Kernel binds the request to the logical Plugin
ID retained from the verified active Candidate. A successful response is
`{"present":true,"data_base64":"..."}` or, when no blob exists,
`{"present":false,"data_base64":""}`. Decoded state is an opaque blob of at
most 32 KiB. The Kernel does not parse its business schema.

### `state.replace`

Request payload is exactly `{"data_base64":"..."}`. Decoded content is at
most 32 KiB and must use canonical base64. The Kernel serializes access to the
logical Plugin's private state file and atomically replaces the complete blob:
write a private temporary file, `fsync` it, rename it over the prior file, and
`fsync` the containing directory. A crash before replacement leaves the prior
blob; a crash after replacement leaves the new blob. If durability is uncertain,
the Kernel reports `plugin_state_outcome_uncertain` and fails closed. It rejects
symlinks, hard links, wrong owners or modes, oversized files, and malformed
state-domain directories.

The private state root is separate from the Candidate store, activation record,
and workspace. It is namespaced first by the signed caller requirement and then
by the validated logical Plugin ID, not by Candidate digest or generation.
Candidate A and its replacement Candidate B therefore use the same state for
the same `plugin_id`; another Plugin ID resolves to a different directory.
Neither Runner nor Agent Host receives the state path. The state root is
user-owned Application Support data and is not protected from arbitrary hostile
same-UID software that can modify that directory.

### `plugin.output`

Request payload is exactly `{"data_base64":"..."}`. The decoded result must be
canonical UTF-8 JSON whose top-level value is an object, no larger than 8 KiB
and no deeper than the general eight-level frame limit. The Kernel validates
only generic framing and JSON properties. It returns this value to the Agent
Host as untrusted data; it is not an authoritative evaluation or state result.
The operation is terminal for that Plugin invocation.

### `fs.read`

Request payload:

```json
{"path":"src/main.py"}
```

The path is relative to the retained snapshot root. Absolute paths, empty paths,
empty components, `.` and `..` are rejected. Path walking uses directory file
descriptors and no-follow opens. The leaf must be a single-link regular file;
symlinks, hard links, directories, special files, and paths outside the snapshot
are rejected. One response contains at most 32 KiB of file bytes as canonical
base64:

```json
{"data_base64":"..."}
```

The path must also be within the Kernel-retained `workspace_read_scope`.
Out-of-scope paths receive the same `path_not_readable` error as unsafe or
unavailable paths. Errors include `invalid_request`, `path_not_readable`, and
`file_too_large`.

### `fs.list`

Request payload:

```json
{"path":"src"}
```

The empty string lists the snapshot root. It uses the same relative, no-follow
path walk. A response contains at most 128 entries and at most 4 KiB of UTF-8
encoded names, sorted by UTF-8 bytes. Each entry has `name`, `kind`, and `size`.
`kind` is `directory`, `file`, `symlink`, or `other`. Each entry includes a
`size` value: regular files have their byte length; other kinds use `null`.
Symlink targets are never returned. Directory entries that cannot be encoded as
strict UTF-8 are rejected during scanning; the ABI does not expose replacement
or escaped aliases for filesystem names.

The directory must be within or be an ancestor of an allowed scope path. For
an ancestor listing, entries outside the scope are removed before the result is
sent. An empty scope denies every directory listing. Out-of-scope directories
receive `path_not_listable`.

Errors include `invalid_request`, `path_not_listable`, and
`directory_too_large`.

### `fs.write`

Request payload:

```json
{"path":"src/main.py","data_base64":"..."}
```

The path must exactly match an entry in the retained `workspace_write_scope`.
The Kernel rejects missing or unsafe parent directories, symlinks, hard links,
special files, and writes larger than 32 KiB. A successful write atomically
installs staged bytes into the private snapshot and returns `written_bytes` and
`sha256`; it does not write to the selected live workspace. An out-of-scope or
unsafe target returns `path_not_writable`.

### `process.exec`

Request payload:

```json
{"argv":["/usr/bin/env","sh","-c","...optional command arguments..."]}
```

The payload schema contains exactly `argv`: 1–128 strings whose combined UTF-8
encoding is at most 32 KiB. The Kernel rejects any extra field and revalidates
the arguments before spawn. It launches them in a separate Seatbelt process
with cwd bound to the private snapshot, a sanitized environment, the retained
timeout and read scope, and OS resource limits. The Runner does not choose those
policies or the workspace. Command output remains untrusted until the complete
snapshot changeset passes Kernel validation and `workspace.commit`.

### `process.cancel`

Request payload:

```json
{"process_request_id":"request id of the active process.exec"}
```

Only one control frame is accepted while `process.exec` is active. A mismatched
or inactive request receives `process_not_active`. A successful acknowledgement
means the command process group was killed and its direct launcher reaped.

### `workspace.commit`

The request payload is `{}`. The Kernel rescans and validates the snapshot
changeset and requires every added, modified, or deleted entry to exactly match
the trusted `workspace_write_scope` before applying it to the selected live
workspace. Any omitted path rejects the whole changeset before the live mutation
gate. Directory paths do not grant descendants. The Runner does not choose the
destination or provide an authoritative changeset. Before
the Worker snapshots the selected workspace, it rejects overlap with its imported
Kernel package and every enclosing macOS `.xpc` or `.app` bundle. The trusted
Launcher opens the accepted root directory and passes that descriptor across the
process boundary. The Worker copies from that pinned directory object and rejects
the request if the canonical workspace path no longer names the same device/inode.
On macOS it obtains the pinned directory's current path with `fcntl(F_GETPATH)`;
this verifies the name binding without reopening ancestors that App Sandbox has
not authorized. The path is compared with the canonical name resolved from the
user-selected bookmark, and a detached or retargeted root fails closed. Apple
documents [`F_GETPATH`](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/fcntl.2.html)
as returning a descriptor's path.
Before writeback, the Kernel rescans the live tree against the captured baseline, including the
workspace root stat signature and its device/inode identity.
The snapshot borrows the pinned source-root descriptor until its context ends.
The Runner does not inherit that descriptor. The one-shot trusted commit child
preserves it across descriptor cleanup and duplicates it for the source-tree
baseline scan and mutations; path-based root opens remain checks that the
authorized root has not been detached or replaced, not a source of new authority.
The macOS commit child receives exact Seatbelt read and write scopes derived
from that validated changeset. It can read changed source files and the
pre-generated same-directory temporary entries needed to verify swaps, plus
directory paths required for descriptor-relative traversal. It receives no
recursive live-workspace read rule, so an unchanged sibling's contents remain
unreadable. Required directories can be enumerated to resolve those paths; this
exposes names in the directly used directories, but does not grant content or
metadata reads of unlisted child files. Newly installed files and regular-file temporaries
receive exact write rules; existing entries and directory paths receive only
create/unlink rules. The workspace receives no recursive write rule. The
private staging root remains writable for staging and cleanup. This limits the
commit child's OS authority; it does not provide exclusive write control
against other same-UID processes. A combined read and write scope larger than
8,192 rules or 1 MiB of generated allowlist text fails closed before live
mutation.
For added files, the Worker pins the same-directory temporary file identity from
its open descriptor and uses a separately pre-authorized sentinel path to remove
that temporary entry. If a concurrent replacement is detected, it restores and
preserves the competing entry and returns `commit_outcome_uncertain`; the
descriptor-backed clone may already have installed the candidate at the destination.
After a new-file clone has changed the live workspace, a later validation failure
does not trigger a pathname-based rollback. The Kernel issues no rollback unlink
and returns `commit_outcome_uncertain`; the destination may be the candidate, a
concurrent writer's replacement, or absent if another writer removed it. Inspect
the workspace before retrying.
If creating a new directory is followed by a parent-binding or directory-sync
failure, the Kernel likewise returns `commit_outcome_uncertain` and leaves the
entry in its original parent, which may have been detached from the named workspace.
The documented macOS [`rmdir(2)`](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/rmdir.2.html)
and [`unlinkat(2)`](https://keith.github.io/xcode-man-pages/unlink.2.html)
interfaces remove a path or a path relative to a directory descriptor; neither
takes an expected inode. From those interfaces, the committer found no documented
inode-conditional directory removal primitive, so it avoids a `stat`-then-`rmdir`
rollback that could remove another writer's replacement. Inspect the workspace
and any known moved parent before retrying.
For modified files, the displaced baseline is removed through the same
identity-checking sentinel exchange. If its recovery path is replaced during
cleanup, the competing entry is preserved and the Kernel returns
`commit_outcome_uncertain`; the validated candidate may already be installed at
the destination. The displaced entry is checked after the atomic exchange, but
that check and the following pathname-based `unlink` are separate operations.
An unconfined same-UID writer can replace the checked path in between, causing
the Kernel to remove that replacement and report success. Apple documents
`unlink(2)` as removing the link named by its path; it has no expected-inode
argument. The retained Broker attack covers replacement before the sentinel's
identity check, not this final check-to-unlink window. A real Seatbelt
commit-child attack replaced the checked path with a symlink to an outside
canary immediately before `unlink`; the commit removed only the symlink entry
and the canary bytes remained unchanged. This proves that cleanup does not
follow a raced symlink target, but a regular replacement inside the authorized
workspace can still be removed. The Runner's Seatbelt profile denies direct
live-workspace writes, but Seed does not establish exclusive write control
against arbitrary same-UID processes.
Success returns counts of added, modified, and deleted entries. A rejected changeset
returns `commit_rejected` only when the Kernel establishes that no live workspace
entry remains from the attempt. If preflight cleanup can leave a destination-
adjacent temporary entry, or writeback may have changed live entries, it returns
`commit_outcome_uncertain`. That result can mean temporary artifacts remain or
some changeset entries were applied and others were not; Khaos does not roll
back a multi-file commit. Abrupt committer termination can also leave
same-directory temporary entries and private staging data because there is no
crash-recovery protocol yet. Inspect the live workspace and temporary entries
before retrying or cleaning them.

## Security boundary and remaining work

The Runner cannot open the snapshot directly. `fs.read` and `fs.list` are
explicit Kernel-mediated data flows; their results are still untrusted workspace
data. They do not classify secrets and do not authorize sending content to a
remote model. Runner ABI v7 retains a trusted logical Plugin ID only in the
Kernel Broker; it is not sent to the Runner as an identity or namespace field.
The development `workspace.run` path still enables `process.exec` for one
trusted workspace request. The product `plugin.run` wrapper resolves source and
scope from the active Candidate inside the trusted Kernel before invoking this
ABI. The local Agent Host never calls lifecycle operations directly. The trusted
Launcher reads `plugin.state`, shares only minimal active-Candidate metadata with
the Host, and revalidates a returned Plugin proposal before approval.

## Native macOS Workspace XPC operation ABI v10

`khaos/macos/KernelWorkspaceXPC.swift` contains the shared bounded wire,
bookmark-transfer implementation, and `KernelWorkspaceBootstrapEndpoint` protocol
for the native Workspace XPC contract.
`khaos/macos/KernelWorkspaceService.swift` owns one-operation admission, cancellation,
and binding cancellation to the submitting `NSXPCConnection`. It requires a trusted
executor callback. `khaos/macos/KernelWorkspacePythonExecutor.swift` is the shared
fixed executor: it starts the bundled Python bridge in a separate process and passes
only the request stream, pinned workspace-root descriptor, and request-bound
cancellation descriptor. `khaos/kernel/workspace_xpc_bridge.py` validates the bounded
Workspace XPC v10 envelope and calls the current Runner IPC v7
`run_workspace_command()` path. The bounded `workspace.run` payload carries a
separate `workspace_write_scope`; the product Launcher source supplies one
generated marker path and makes its fixed Runner verify an exact `fs.write` plus
an out-of-scope sibling denial. The same signed XPC service handles the fixed
Candidate lifecycle operations below. The Python workspace path reads
the source APFS type and case semantics from its pinned root descriptor with
Darwin `fgetattrlist`; a real HFS+ volume is rejected. For brokered snapshots,
the Python executor relies on the authenticated live Snapshot Broker lease for
image, APFS device, capacity, and mount validation instead of repeating
`hdiutil`/`diskutil` queries inside the App Sandbox. It retains local checks for
the lease path, owner, marker, and mounted state, then checks source and
snapshot mount identity before exposing the copy. The canonical suite passed
all 244 tests on 2026-10-02 (473.402 seconds), including real case-sensitive
and case-insensitive APFS checks, real HFS+ rejection, and the signed-product
headless XPC test. It does not open the Picker. A subsequent user-reported
selection and alert dismissal has no correlated process output, workspace
digest, or app signature result; it does not establish interactive XPC success.
A fresh corrected product XPC run opened the Picker but timed out after 600
seconds without a user selection (629.559 seconds total). Its driver output
stopped after `production-xpc-picker-requested`; no selected-workspace XPC or
Runner checks ran. Interactive XPC success remains unverified. See
[`SEED_THREAT_MODEL.md`](SEED_THREAT_MODEL.md).
`khaos/macos/KernelWorkspaceBootstrap.swift` provides the shared peer-authenticating
bootstrap. `khaos/macos/TrustedWorkspacePicker.swift` provides the shared AppKit
directory-selection and bookmark-creation helper.
`khaos/macos/KernelWorkspaceServiceMain.swift` fixes the composition by binding the
bootstrap to the Python executor without accepting an executor from IPC. The build-mode XPC test compiles and signs this entrypoint into a temporary bundle. A headless positive probe starts it, retrieves its anonymous endpoint, and receives `process_not_active` for a random idle-cancellation request. A second headless call submits a plain bookmark (`options: []`) for a random directory under the sandboxed app's own Application Support without opening the picker; the fixed `KernelProduction.xpc` executor returns `workspace_rejected`, and the test confirms the input is unchanged with no output or bypass file. This is negative evidence for this fixed entrypoint and app-container fixture, not a selected-workspace execution or proof about other XPC services. A separate unbundled run confirms missing bundle peer requirements cause startup to exit before serving. The repository can now build a locally signed `KhaosSeed.app` with a sandboxed Trusted Launcher and this XPC service. Its headless package test starts both XPC layers and rejects a same-identifier client with a different signing identity. An earlier user-selected product bundle completed its fixed no-change smoke but carried `com.apple.security.files.bookmarks.app-scope`; a later fresh product built with the reduced entitlements also displayed `PASS` after external workspace selection, with the fixture unchanged. That smoke proves only the fixed `/usr/bin/true` → Kernel XPC → Runner → exact zero-change commit path. Post-run deep signature verification found Python `__pycache__` files added inside the signed framework. Fixed isolated Python launches now pass `-B`; the executor also sets `PYTHONDONTWRITEBYTECODE=1` for non-isolated descendants. The focused package test passed, and the canonical suite passed all 185 tests in 361.049 seconds. The user later confirmed the reduced-entitlement product app displayed PASS; its fixture SHA-256 (c00d07fbc2916475914e8ccf2fbbb10c255a41ebc775898bb4ca2294df614659) was unchanged, post-run codesign --verify --deep --strict passed, and the signed Python framework contained no __pycache__. This establishes only the fixed zero-change route. This dated package record predates the separate snapshot Broker implementation documented below. The bundle is still not installed or notarized, and there is no distribution signing, updater, Candidate admission, durable grant policy, or user approval model.

`khaos/macos/KernelWorkspaceClient.swift` is the shared outbound XPC connector. It
reads the expected signing requirement from the signed caller bundle through
`XPCPeerIdentity`, applies it to both the named bootstrap connection and the returned
anonymous endpoint connection before `resume()`, and fails closed if the requirement
is missing. The endpoint target carries the same requirement into the second connection.
The 109.723-second focused XPC rerun reached the end of its existing request and peer
assertions; it failed only in an inline package-builder identity preflight. That
packaging check was separated and the standalone Seed bundle test passed in 7.395 seconds:
it built and strictly verified the app, started the embedded service through both XPC
layers, and confirmed a same-identifier wrong-signer client was rejected by macOS. This
validates a local test-signed bundle, not distribution signing or the selected-bookmark
operation. The last canonical suite pass (184 tests, 402.372 seconds) predates the client
refactor and was not rerun; the interactive Picker was not opened.

For `workspace.cancel`, the service matches both the active request ID and the
submitting `NSXPCConnection` before writing to that operation's cancellation pipe.
The fixed executor delegates only the pipe's read end to the Python bridge; the
bridge forwards cancellation into the existing Worker and Seatbelt process-group
cleanup path. This does not let the Runner choose or broaden the command. The
`KernelProduction.xpc` cancellation attack is present in the interactive test probe,
but its end-to-end result remains unverified until a fresh user-selected bookmark
test completes.

The named bootstrap and anonymous workspace endpoint use distinct signed bundle
requirements. A nonblank `KhaosBootstrapRequirement` restricts which peer may retrieve
the endpoint from the named service; a nonblank `KhaosWorkspaceCallerRequirement`
configures the anonymous listener and restricts who may call `workspace.run`. The service applies
`NSXPCConnection.setCodeSigningRequirement` to the named connection before resuming it
and `NSXPCListener.setConnectionCodeSigningRequirement` to the anonymous listener.
The requirements come from the signed service bundle, never from an IPC argument. A
transferred endpoint does not grant invocation authority because its listener still
checks the caller. The test bundle exercises both roles with real OS code-signing
checks; a sandboxed sibling XPC service in the same app is rejected from the named
bootstrap while the signed app client succeeds. These are temporary test identities and
do not establish production identity or installation.
Apple documents these APIs in the [incoming connection](https://developer.apple.com/documentation/foundation/nsxpcconnection/setcodesigningrequirement%28_%3A%29),
[anonymous listener](https://developer.apple.com/documentation/foundation/nsxpclistener/setconnectioncodesigningrequirement%28_%3A%29),
and [TN3127](https://developer.apple.com/documentation/technotes/tn3127-inside-code-signing-requirements).

The trusted client must authenticate the Kernel service as well. Before resuming either
the named bootstrap connection or a connection made from its returned endpoint, it applies
the matching Kernel service requirement stored in the signed Launcher bundle. Missing or
blank requirements fail closed; an untrusted peer must not receive a workspace bookmark or
request stream. The headless signed test Launcher pins `KernelExecution` and
`KernelProduction` by their designated code-signing requirements. A real connection to a
reachable sandboxed sibling service under the wrong identity fails with
`NSXPCConnectionCodeSigningRequirementFailure`, before the sibling method runs; the
correct `KernelProduction` peer still answers the bootstrap probe. This is current-host,
test-bundle evidence, not a shipped Launcher or release identity. Apple documents this
client-side use in the [`NSXPCConnection.setCodeSigningRequirement` example](https://developer.apple.com/documentation/foundation/nsxpcconnection/setcodesigningrequirement%28_%3A%29).

### Candidate lifecycle operations

The outer `NSXPC` method version remains `8`; the JSON operation envelope and
bridge response version are `10`. The exact operation schemas are:

| Operation | Exact payload | Workspace bookmark | Kernel behavior |
|---|---|---:|---|
| `workspace.run` | `timeout_seconds`, `runner_source`, `runner_source_sha256`, `workspace_read_scope`, `workspace_write_scope` | Required | Existing bounded one-request workspace path |
| `plugin.admit` | `manifest_base64`, `source_base64` | Forbidden | Validate and store a content-addressed Candidate; return digest/scope summary |
| `plugin.activate` | `candidate_digest`, `manifest_digest`, `scope_digest`, `expected_generation` | Forbidden | Verify bindings and generation, then activate fixed `primary` slot for 30 days |
| `plugin.state` | empty | Forbidden | Return verified active/previous metadata without source bytes |
| `plugin.rollback` | the same four fields as activation | Forbidden | Verify the previous Candidate and generation, then route future runs to it |
| `plugin.run` | `plugin_id`, `candidate_digest`, `manifest_digest`, `scope_digest`, `expected_generation`, `input` (object or null), `workspace_required` | Required only for a Candidate with workspace scope or `process.exec` | Match active identity/digests/generation under the lifecycle lock; verify `workspace_required` against Manifest; state-only calls require an object input; pass bounded untrusted input and the retained Plugin ID into the existing Broker/Runner path |

Lifecycle operations reject unexpected fields and transfer bytes. In
particular, `plugin.run` accepts only the reviewed Plugin identity,
Candidate digests, generation, bounded business input, and a workspace-required
bit; it never accepts source, state path, state namespace, or scope from its
caller. An input object is accepted only on the no-workspace state-only route;
workspace-capable runs carry `null`. The Kernel checks those
bindings and resolves the Candidate under the same store lock, so a concurrent
slot switch between confirmation and the run request fails as stale. Admission
and activation use the same signed Launcher-to-Kernel XPC endpoint as workspace
operations; there is no new trusted process or endpoint. The Kernel store is a
per-caller-requirement directory beneath the user's `Library/Application
Support`, with read-only content-addressed Candidate files revalidated when
loaded, plus a serialized and atomically replaced activation record. The record
retains active and previous Candidates, generation, approval ID, and fixed
expiry. Its HMAC detects edits
only while the key remains intact; the user-owned store does not resist an
arbitrary same-UID process that can alter both key and data.

Plugin business state lives under a separate per-caller-requirement
`PluginState-*` root and a validated logical Plugin ID directory. It is one
opaque bounded blob, separate from Candidate content and activation metadata.
Candidate replacement keeps the state for the same logical `plugin_id`; a
different Plugin ID resolves to a different directory. The Kernel state API
does not parse Memory's canonical JSON format.

The Launcher confirms exact Candidate, Manifest, and scope digests plus the
fixed slot and validity before activation; the Kernel independently checks the
digests and reviewed generation. No caller-supplied `approved` field exists.
Rollback is bound to the previous Candidate's exact digests and reviewed
generation. It only changes routing for future runs; it cannot reverse effects
of prior runs.

**2026-10-05 signed-product lifecycle evidence:** The headless
`test_seed_app_builds_and_authenticates_its_kernel_service` test passed against
the locally signed product's real `KernelProduction.xpc`. It admitted two
different Candidate contents, rejected a Manifest digest mismatch and stale
generation, activated each exact Candidate, read back persisted active/previous
state, rejected a forged approval field, rejected a wrong or stale rollback
target, then rolled back to the first Candidate. It also confirmed lifecycle
metadata does not reveal source and that `plugin.run` without a workspace
bookmark is rejected. The test cleans its signer-namespaced Application Support
store. It does not open the Picker or run the persistently activated Candidate
in a selected workspace; the current product `--plugin-run` Picker route still
needed a correlated end-to-end run as of this 2026-10-05 record; the following
2026-10-06 acceptance closes that evidence gap for the tested host and product
composition.

**2026-10-06 signed-product positive execution evidence:** The opt-in
`KHAOS_RUN_PRODUCT_PLUGIN_LIFECYCLE_UI=1` run of
`test_seed_app_builds_and_authenticates_its_kernel_service` passed against a
disposable locally signed product app, its production `KernelProduction.xpc`,
the persistent Candidate store, Seatbelt Runner, and existing Kernel changeset
commit path (455.805 seconds). With real package/workspace Pickers and user
approval, it admitted and activated A, ran A, activated and ran B, rejected a
held generation-1 A run as `stale_approval` after B became generation 2,
rolled back to A, and ran A again. The test parent checked workspace bytes and
the exact allowed output/evidence set after each run; it also checked scoped
input/listing, unapproved-read denial, Runner denial of lifecycle-store and
direct live-workspace access, Picker-scope release, and deep bundle signature
verification after each operation. In the canonical suite, the
`plugin.run` schema test rejects caller-injected source, read scope, and write
scope, while the bridge resolves source and Manifest scopes from the active
Candidate under the store lock. The canonical suite passed 276 tests in
497.746 seconds. This is positive execution evidence for the current macOS host
and temporary signed test copy; it does not claim release signing or protected
installation.

The real macOS test `test_real_runner_executes_a_b_rollback_a_and_cannot_self_activate`
also proves the replacement sequence using the stored Candidate bytes and the
existing Kernel `run_workspace_command()` → Seatbelt Runner → changeset commit
path: it activates and runs A, activates and runs B, rolls back, then runs A
again. Each Candidate attempts to list and chmod the Candidate store, read and
append to activation state, and look up the live `com.apple.cfprefsd.agent`
Mach service. Those operations are denied in the Runner; an unconfined
positive-control lookup succeeds. Its only committed writes are the exact
Manifest paths. This validates the Python Kernel/Runner composition on this
host, not the signed Launcher's selected-workspace `plugin.run` XPC flow.

### Agent Host Plugin invocation proposal

The AgentHost XPC protocol is version 3. The Launcher includes only
`plugin_id`, `candidate_digest`, and `generation` (or `null`) in each user-turn
and result frame. The Host may return `text`, a `shell` proposal, or a `plugin`
proposal. The exact Plugin proposal fields are `plugin_id`, `candidate_digest`,
`generation`, and a bounded JSON object `input`; extra fields are rejected. In
particular, the Host cannot provide Runner source, Manifest bytes, read/write
scopes, state namespace/path, capability, approval, or lifecycle operation
names. These metadata values identify a proposal and do not grant authority.

Before presenting an Agent proposal, the Launcher performs a fresh `plugin.state`
read and requires all three proposal values to match the current active Candidate
and slot generation. No active Candidate or any mismatch is denied as a stale
proposal before workspace selection or approval. The approval dialog shows the
actual Candidate, Manifest and scope digests, generation, capability and exact
read/write paths from trusted state, the exact canonical invocation input, and
the request digest. Only after approval
does the Launcher send the existing `plugin.run` request; source and scope remain
resolved by the Kernel. If the slot changes after the Launcher's comparison,
the Kernel's existing store-lock generation check rejects the stale run.

The bounded `WorkspaceResult` returned from Plugin execution is encoded to at
most 16 KiB before it is sent to the Host. Plugin output is untrusted model
input. A user denial is returned as a denial result and does not submit
`plugin.run`. The Host protocol has no activation, rollback, admission, or other
lifecycle mutation response. Stateful execution adds only the bounded Runner
operations `state.read`, `state.replace`, and terminal `plugin.output`, plus a
separate Plugin-owned state domain; it adds no trusted process or general
storage framework.

### Product APFS snapshot broker handoff

The outer Kernel XPC method version is `8`. Before submitting `workspace.run`
or `plugin.run`,
the signed Launcher registers one `NSXPCListenerEndpoint` for the snapshot broker on
the same authenticated Kernel connection. Kernel binds the pending endpoint to that
connection, consumes it for that connection's next request, and clears it if the
connection is interrupted or invalidated. The endpoint is out-of-band XPC metadata; it
is not a caller-supplied identity, capability string, or field in the bounded JSON
request. The JSON operation frame is version `9`.

The current signed product keeps `KernelProduction.xpc` outside App Sandbox:
a signed App Sandbox helper on this Mac received `sandbox_apply: Operation not
permitted` while trying to apply the nested Seatbelt policy required for its
untrusted Runner. The Kernel remains fixed trusted enforcement code. The signed
headless product check passes for this composition. A selected-workspace XPC
attack subsequently observed its cancellation child and received
`process_cancelled`, but the test-only driver's recovery request omitted the
required Broker endpoint. After that test-only correction, the interactive
signed-product XPC attack passed in 116.146 seconds, including selected
workspace writeback, forbidden direct access, cancellation, recovery, exact
workspace contents, and deep product code-signature verification. It does not
prove Candidate admission or an installed, protected Kernel.

The signed app's named `KernelSnapshotBroker` XPC service accepts its bootstrap call
only from the Launcher designated requirement and returns an anonymous operations
endpoint. Kernel connects to that endpoint only after installing the Broker's
designated code-signing requirement; the anonymous listener accepts the Kernel
requirement only. Broker operation ABI version `2` carries a file URL for a fixed
private directory beneath the per-user OS temporary root. The Broker requires the expected canonical
temporary path, validates directory ownership and mode, and retains an exclusive
service lock through the snapshot lease.
Release, cancellation cleanup, and service restart recovery must unmount the matching
image before removing lease state and closing the lock. A caller that cannot establish
this path receives an error; the Kernel does not use an unrestricted Host snapshot
fallback.

Before resuming either listener, the Broker applies a process Seatbelt policy with
`sandbox_init(3)`. Policy setup failure exits the service before it accepts connections.
The policy denies network access, file reads/xattr reads/writes throughout
`/Users`, temporary paths outside the fixed private storage subtree, `/Volumes`,
and process execution from `/Users`. This includes
`/Users/Shared` and its `/System/Volumes/Data/Users` APFS Data-volume alias.
Directory ancestors needed to traverse into that storage subtree retain
directory-data and metadata access, but regular-file data and writes outside the
subtree remain denied within those protected roots. Non-`/Users` Home layouts retain a Home-only rule.
`hdiutil` and `diskutil` still use fixed Kernel-owned paths
and arguments; `TMPDIR` is set to the private storage root. A signed-product negative
test substitutes a malformed policy in a disposable Broker bundle; `sandbox_init(3)`
rejects it, the real service exits before listener startup, and the Launcher receives
a failed bootstrap instead of an endpoint.

The real signed-product headless acceptance creates and attaches the APFS image through
the packaged Broker, reaches it through an authenticated test Kernel, releases the
lease, and checks the image is no longer mounted. This proves the tested handoff and
cleanup on the current macOS host. A second real signed-product attack replaces only
the Broker executable with a test-only probe that applies the same production policy.
Its host-positive-controlled read, metadata, write, directory-mode change, temporary
write through `/tmp`/`/var/tmp` spellings, `/Users/Shared` executable, Kernel write-open, and
loopback operations all receive OS permission denials. This is not a complete minimum-
privilege sandbox: `(allow default)` retains access to system paths outside the
explicitly denied roots, the Broker has no App Sandbox entitlement, and `sandbox_init(3)`
is deprecated. The evidence is limited to the listed operations on the tested macOS
host; it does not establish confinement for every OS resource or release/install
integrity. The test is headless and does not prove selected-workspace Picker
authorization or product Launcher writeback. The signed-product restriction test
passed in 29.192 seconds; the canonical unittest suite passed 237 tests in
471.837 seconds on the same host.

The temporary-root deny list also covers the Data-volume spellings
`/System/Volumes/Data/private/var/folders`,
`/System/Volumes/Data/private/tmp`, and
`/System/Volumes/Data/private/var/tmp`; the authenticated storage subtree keeps
matching Data-volume aliases in its narrow exception. The existing signed
product probe confirms the host can write through `/System/Volumes/Data/private/tmp`
(`samefile` with `/tmp`) and requires the Broker OS denial. That focused test
passed in 28.858 seconds. This verifies the exercised alias on the current host;
the Broker still uses `(allow default)` outside its explicit deny rules.

Broker process execution is also denied below the standard temporary roots and
their Data-volume aliases. The signed-product probe confirms the host can run a
copy of `/usr/bin/true` from `/System/Volumes/Data/private/tmp`; Broker
`posix_spawn` must receive `EPERM` or `EACCES`, while real APFS snapshot
create/attach/release/detach continues to work. The focused headless test passed
in 29.283 seconds. The direct executable canary covers `private/tmp` on this
host; this policy extension does not make the Broker deny-by-default.

Before executing the fixed Runner, the Kernel's real Seatbelt readiness probe uses
the same authenticated APFS lease supplied for that workspace request. It creates its
disposable source fixtures in a temporary directory under the Broker lease directory,
beside the mounted `volume`, then copies them to the distinct APFS volume mounted there.
The source therefore remains on the lease's host backing filesystem, as required by the
real separate-device check; placing fixtures inside the mounted volume would correctly
fail that check. The Broker removes the source directory with the lease after unmounting,
including during interrupted-request cleanup. The probe snapshot lives in the lease's
`seatbelt-probe` directory, and the subsequent workspace snapshot uses its normal
`workspace` directory. The XPC executor sets Python's `TMPDIR` to the authenticated
Broker lease directory. The readiness-probe source fixtures and workspace staging
therefore use a writable lease-local root while the snapshot mount remains a
separate APFS volume. Snapshot validation checks that same lease root and still
rejects a mismatched storage location.
The probe remains mandatory and retains its real OS positive and negative checks; absent
or invalid Broker lease data still fails closed. Its path-free failure diagnostics
distinguish runtime setup, temporary directory creation and cleanup, fixture directory
creation, fixture contents, and result verification without forwarding OS error text or
local paths.

The signed Launcher and Kernel XPC intentionally omit App Sandbox network client and
server entitlements. Apple defines these as the permissions to open outgoing
connections and listen for incoming connections ([client](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.network.client),
[server](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.network.server)).
If the outer App Sandbox returns `EPERM` or `EACCES` while the readiness probe sets up
its host loopback control, the probe still runs its sandboxed Runner connection
attempt and requires that attempt to receive an OS permission error. When host
loopback is available, the probe also proves the host control works before checking
the Runner denial. The standalone real-Seatbelt attack continues to exercise the
default-deny profile against a live loopback listener outside App Sandbox.

`workspace.run` carries operation ABI version `9`, a request ID as two fixed-width
unsigned 64-bit values, and an `NSFileHandle` for a stream socket. Request
fields and the workspace bookmark stay out of XPC object decoding. The client
sends a bounded Workspace XPC v9 `workspace.run` frame followed by one bookmark:

```text
uint32 request_frame_length
Workspace_XPC_v9_workspace.run_frame
uint32 bookmark_length
workspace_bookmark_bytes
```

The request frame contains the exact IPC envelope: `version`, `request_id`,
`operation`, and `payload`, with `timeout_seconds`, `runner_source`,
`runner_source_sha256`, `workspace_read_scope`, and `workspace_write_scope` in
the payload. Command `argv` is selected later by the Runner over authenticated
Runner IPC and is not accepted in the outer XPC request.
`runner_source_sha256` is exactly 64 lowercase hexadecimal characters and must equal
SHA-256 of the decoded `runner_source` UTF-8 bytes. The payload also carries separate
`workspace_read_scope` and `workspace_write_scope` lists. The Swift Kernel parser validates it
before reading the bookmark; the separate Python bridge rechecks the binding before
starting the Worker. A mismatch returns `invalid_request` before bookmark resolution or
Runner launch. This is content-integrity binding only: the current fixed Launcher
computes the digest for its built-in source; there is no user approval, Manifest digest,
Candidate admission, or capability grant bound to it for direct `workspace.run`.
The separate `plugin.admit`/`plugin.activate` operations bind installed content and
scope; `plugin.run` reads them from Kernel state. The bridge forwards validated
source and remaining operation fields into the existing Runner IPC v6 path. The inner
request ID must match the fixed-width ID on the outer XPC call.
The JSON body is limited to eight structural nesting levels before Foundation parses it;
the current envelope reaches at most three. The bounded byte scan ignores braces and
brackets inside strings. Over-depth requests fail as `invalid_request` before bookmark
handling, keeping parser work within the small schema the service accepts.
The body must also byte-match Foundation's `.sortedKeys` serialization of its parsed
object. This fixed local ABI encoding rejects duplicate object fields (which a dictionary
would otherwise collapse), alternate key order, and other noncanonical encodings before
schema validation or bookmark handling. The shipped Swift clients use the same encoder.
Before reading the bookmark, the native parser also validates both scope lists: each
list has at most 128 paths and 4 KiB of encoded path bytes (including one delimiter byte
per path); every path is nonempty, relative, has at most 64 components, and contains no
empty, `.` or `..` component or NUL. Duplicate paths are rejected by exact UTF-8 bytes.
The downstream Python Worker independently repeats these checks before it constructs a
snapshot. An empty scope list remains valid and denies that class of access.
All integers are big-endian. Before parsing the stream, the service queries the
AF_UNIX socket's `LOCAL_PEERPID` and requires it to match
`NSXPCConnection.processIdentifier` for the authenticated method caller. This
rejects a valid frame carried by a socket whose peer is another process. Apple
documents the connection PID in [`NSXPCConnection.processIdentifier`](https://developer.apple.com/documentation/foundation/nsxpcconnection/processidentifier);
XNU defines `LOCAL_PEERPID` as the local-socket peer PID query in
[`bsd/sys/un.h`](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/un.h).
The sender half-closes its write side to delimit the frame, then retains the
descriptor until the XPC reply so macOS still exposes the peer PID during
admission; closing the peer first makes the tested query return `ENOTCONN`.
The service also requires a stream socket, bounds each length before allocating
its body, and validates the exact request schema and field limits before reading
the bookmark. The IPC JSON body and bookmark each
have a 64 KiB maximum; the bookmark must be nonempty. The complete transfer has
a five second absolute deadline and must end at EOF. Malformed request framing or
an ID mismatch returns `invalid_request`; truncated, oversized, stalled, or
malformed bookmark input returns `invalid_bookmark`, all before bookmark
resolution or executor launch.

The sender applies the same request and bookmark limits before copying either
body into its stream; an oversized client bookmark fails with `EMSGSIZE` without
invoking the XPC endpoint. Real raw XPC attacks bypass this helper to send an
oversized request length, a request whose inner ID differs from its outer ID, an
oversized bookmark length, and a stalled bookmark transfer. Each attack is
rejected before the descriptor probe marker appears.

The wire can carry only one bookmark blob for each `workspace.run`. The test
adapter resolves that blob as its operation root and opens its two fixed probe
subdirectories relative to the held root descriptor with `openat`, `O_DIRECTORY`,
and `O_NOFOLLOW`; the caller cannot present independent roots for the descriptor
probe and the clean snapshot/commit workspace. Real XPC attacks replace each
child directory with a symlink to a sibling outside the bookmarked root; both
requests fail before either probe starts, and the outside canary remains intact.
Production executor composition, durable grant management, and approval policy remain
unimplemented.

The shared `TrustedWorkspacePicker` presents a directory-only `NSOpenPanel` and
returns the original selected URL so its trusted caller can stop the panel scope,
plus a bookmark to transfer to Kernel. The Kernel
transfer bookmark is created from the original `NSOpenPanel` URL with
`bookmarkData(options: [])`, preserving the panel's implicit scope for transfer
to the XPC service. The test helper canonicalizes its fixture path only to compare
the selected directory with the expected disposable root.

In the product acceptance path, `--acceptance-workspace` sets the Picker's
starting directory to the requested folder's parent and names the exact folder
in the message. Before presenting the panel, the Launcher must fail to open the
known fixture with `O_RDONLY | O_NOFOLLOW`; only `EPERM` or `EACCES` counts as
denial. After selection, it compares the returned URL with the exact requested
workspace before sending the bookmark to Kernel. Apple documents
`directoryURL` as the directory shown in the panel and says the system extends
the app sandbox to URLs selected in the panel ([`directoryURL`](https://developer.apple.com/documentation/appkit/nssavepanel/directoryurl),
[App Sandbox file access](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox)).
The 2026-09-29 interactive retry recorded `preselection-read=denied` and
`picker-requested`, and the Picker window was visible, but no selection reached
the Launcher within 300 seconds. This proves pre-panel denial for that signed
build and host only; it does not establish access behavior while the panel is
open or successful writeback for this run.
The current Picker write-denial probe checks access directly before and after
revoking the panel scope; it does not issue a second read-only bookmark. The
one-shot transfer bookmark is not persisted. Apple documents this bookmark form
for passing access between processes, while long-lived access requires a separate
security-scoped bookmark flow in the [App Sandbox file access documentation](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox).

The real XPC probe sends an oversized bookmark and a slow partial frame. It
sends half the outer length, waits four seconds, then sends the remaining length
and one body byte while keeping the socket open. The service must return
`invalid_bookmark` within seven seconds of the call, before the descriptor probe
marker appears; a valid request then succeeds on the same XPC connection. This
exercises the absolute deadline across header and body reads and confirms the
single-operation slot is released after timeout.

The client creates an AF_UNIX socketpair and transfers its read handle through
XPC. Apple documents `NSFileHandle` as a secure-codable wrapper for descriptors,
pipes, and sockets. The endpoint still authenticates the XPC caller by its
configured code-signing requirement. The shared service validates and decodes
the request but leaves execution to its fixed executor. The shared Python executor
is `KernelWorkspacePythonExecutor`; only its ad-hoc signed test-bundle composition is
established, so this ABI does not establish a shipped Kernel service or grant policy.

The focused parser probe sends a complete, valid invocation over a real socketpair
while supplying a different expected peer PID. The OS peer credential mismatch
returns `invalid_request` before the frame is parsed. A separate cross-process
attack uses the sandboxed sibling `UntrustedHost.xpc` to create a socketpair,
write a valid `workspace.run` request prefix without a bookmark, half-close its
write side, and transfer the reader descriptor through the authenticated app to
Kernel. The client checks the descriptor's `LOCAL_PEERPID` equals the sibling
service's XPC process ID and differs from the authenticated app PID. Kernel returns
`invalid_request` before parsing; accepting the peer would instead reach the
missing-bookmark error. Build mode runs this attack without opening the picker.
The focused parser mismatch case is only an in-process parser check; the separate
descriptor-relay case exercises the authenticated XPC boundary without passing a
bookmark or invoking the executor.

Replies are UTF-8 JSON in `Data`, limited to 64 KiB. Success carries the matching
version and request ID with `ok: true` and `output`; failure carries `ok: false`
and a short structured error code. The client requires an exact key set, matching
request ID and version, and correctly typed values. The fixed-width XPC request
ID is rendered as 32 lowercase hexadecimal characters in the bounded JSON
reply. Oversized output is replaced with `response_too_large`.

When the local Seatbelt readiness probe fails, the Kernel may return one of the
finite path-free codes `sandbox_unavailable_probe_child`,
`sandbox_unavailable_probe_readiness`, `sandbox_unavailable_probe_snapshot`, or
`sandbox_unavailable_probe_verification`. The product Launcher presents these
as the existing generic `sandbox_unavailable` result; exception text and
workspace paths never cross the ABI.

Only one workspace operation may be active. `workspace.cancel` carries the same
version and two fixed-width request ID values. A mismatched or inactive ID receives
`process_not_active`; a successful `cancel_accepted` reply means the request was
delivered to the existing trusted workspace cancellation path, not that cleanup
has already completed. The final `workspace.run` reply reports
`process_cancelled` after that path stops execution and prevents writeback. The
real XPC probe tests a stale-ID cancellation, a matching cancellation, and the
absence of both committed output and a direct-write bypass file.

The service retains its active-operation slot until the Worker has returned and
its private workspace cleanup has finished. A new `workspace.run` may therefore
receive `operation_busy` after a cancellation or disconnect; callers should retry
within their bounded operation deadline instead of treating cancellation
acknowledgment as slot release.

The active operation is bound to the authenticated `NSXPCConnection` that
submitted it. A second connection cannot cancel it, even when it presents the
same request ID. The service listens for connection interruption and
invalidation and forwards either event through the same trusted cancellation
pipe. If the cancellation reaches the Kernel before its commit cutoff, the
operation stops without writing back; it cannot undo a commit that already
passed that cutoff. Because an invalidated connection cannot receive a terminal
reply, the caller must treat its outcome as unknown until it inspects the
workspace or starts a new operation. A real XPC test invalidates the caller
during a 20-second sandbox command, confirms no output was committed, and then
completes a new request through the still-running Kernel. The test also confirms
that a second same-identity connection cannot cancel the active request.

A separate adversarial test starts `workspace.run` from the authenticated
`HostClient.xpc`, waits for its descriptor-probe marker, and has that helper
terminate itself with `SIGKILL`. The outer Host observes the XPC interruption;
a newly launched helper then completes another request through the same Kernel.
The crashed request leaves neither its expected output nor a bypass file in the
workspace. This exercises caller-process failure after request admission; it
does not test Kernel-worker or operating-system failure.

The earlier test-only picker probes and the compound interactive Product XPC
attack driver have been retired. One interactive product writeback acceptance
remains: it uses the normal signed Launcher and Picker to check scoped Runner
read/list and write allow/deny, Kernel commit, and direct Launcher read/write
denial after the Picker scope is released. The signed-product XPC parser and peer
identity attacks remain headless. Lower-level real-OS tests continue to cover
Runner live-workspace denial, unsafe changesets, and cancellation; they do not
claim those checks ran through the same selected-workspace Product XPC request.

In the historical probe, the selected `NSOpenPanel` URL initially granted
read/write scope to the Picker process. It first opened and closed the fixture
input with `O_WRONLY` as a positive control, called
`stopAccessingSecurityScopedResource()`, then required a fresh `O_WRONLY` open
to fail with `EPERM` or `EACCES`. It did not create or resolve a second
read-only bookmark. KernelExecution received the original one-run `options: []`
bookmark and performed the validated commit. A separate sandboxed
`UntrustedHost.xpc` receives only the path; it can write inside its own app
container, but the OS denies its workspace write. Apple documents revoking
open-panel scope and passing an implicit-scope bookmark between processes in
[App Sandbox file access](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox).

In a 2026-09-28 selected run, this direct write-denial check and the
KernelExecution one-file commit assertions completed before the test failed in
the separate KernelProduction attack group. That group had attempted to transfer
an explicit `.withSecurityScope` child bookmark; the probe now uses `options: []`
for this one-run XPC transfer as well. A subsequent interactive attempt received
no selection within 300 seconds, so the corrected child-bookmark transfer and the
full KernelProduction unsafe-changeset/cancellation sequence remain unverified.
The test helper still declares `com.apple.security.files.bookmarks.app-scope`
for its independent unselected app-container bookmark rejection check; the local
product app no longer needs that entitlement. The product app's separate
user-selected no-change smoke succeeded, but does not prove positive changeset
writeback in this test composition.

The OS peer-requirement setup and bounded Workspace XPC ABI are shared Khaos
sources in `khaos/macos/XPCPeerIdentity.swift` and
`khaos/macos/KernelWorkspaceXPC.swift`. The test services remain under `tests/`.
After adding the sender-side bound, the build-mode XPC test passed in 54.080
seconds on 2026-09-27. The interactive picker/sibling-scope attack passed in
69.477 seconds after both the ABI move and bound change, confirming valid user
bookmarks still reach the Kernel. The canonical suite passed all 181 tests in
317.673 seconds on that final code state. No production XPC service or Trusted
Launcher is packaged.

A user-requested clean interactive rerun passed in 72.619 seconds. Its assertions
confirmed the selected root, sibling XPC workspace-write denial, Kernel safe
writeback, unsafe changeset rejection, and the exact two-path workspace delta.

The XPC operation/cancellation service was then extracted from the test executable
to `khaos/macos/KernelWorkspaceService.swift`; test-only bookmark read probes and
the Python executor adapter remain under `tests/`. The build-mode XPC attack passed
in 53.586 seconds, the interactive picker/sibling-scope attack passed in 130.694
seconds, and the canonical suite passed all 181 tests in 305.833 seconds. The tests
compile and exercise the shared service through real XPC, while peer-authenticating
bootstrap and production bundle installation remain unimplemented.

Bookmark scope resolution is now shared in `khaos/macos/KernelWorkspaceRoot.swift`.
It holds security-scoped access for the full descriptor operation, validates both
original and refreshed bookmark lengths through the ABI's single bound, opens the
selected root without following symlinks, and accepts a refreshed bookmark only when
its opened root has the same device and inode. Fixed child directories are opened
relative to that root with `openat`, `O_DIRECTORY`, and `O_NOFOLLOW`. The test executor
now calls this shared code instead of maintaining a second resolver. The build-mode
real XPC test passed in 53.484 seconds and the canonical suite passed all 181 tests in
303.552 seconds on 2026-09-27. This does not add a production executor or shipped
Kernel service. A post-extraction interactive picker rerun remained in the foreground but
received no folder selection within its 300-second deadline; the test cleaned up its helper
and fixture, so external user-grant success has not yet been re-proved against this extracted
source.

A fresh interactive rerun on 2026-09-27 passed in 201.018 seconds. The user-selected
bookmark resolved through the extracted root helper, the XPC Kernel committed the expected
output, and the path-only sibling XPC remained unable to write the selected file. The same
real XPC operation independently created symlink, hardlink, and FIFO changesets; Kernel
rejected each before writeback, preserved the prior output and outside canary, and wrote
none of the candidate paths. This closes the earlier test-evidence gap for the extracted
resolver on this host; the picker, executor adapter, and signed bundle remain test-only.
The build-mode XPC test passed in 67.871 seconds, and the canonical 181-test suite
passed in 324.414 seconds on 2026-09-27.

A focused XPC run on 2026-09-27 also passed in 68.555 seconds with an untrusted Runner
source that called `fs.read` and `fs.list` over the same admitted workspace operation.
It read only the scoped `input.txt`, received `path_not_readable` and `path_not_listable`
for an unscoped file, and saw that file omitted from the root listing. The command then
ran through `process.exec` and the same validated `workspace.commit` path. This exercises
the data-read boundary across the XPC-to-Runner composition; it does not add production
capability approval or a shipped executor. The canonical suite then passed all 181 tests
in 326.951 seconds on 2026-09-27.

After a successful request, the picker probe reads the expected Kernel output and
prints its report to stdout. It does not write a report into the selected workspace;
the interactive test compares the before/after paths and expects only
`kernel-workspace/output.txt` and the trusted descriptor-probe marker
`kernel-descriptor-scope/descriptor-probe-started.txt` to be added. The marker
is created by the Kernel's test probe to show that descriptor validation ran;
the picker app itself writes neither path.

This probe authenticates its test peers with OS code-signing requirements and
current executable cdhashes. Its ad-hoc identity, temporary workspace and
one-shot bookmark flow do not provide production grant persistence, revocation,
publisher identity, capability approval, Candidate admission, or exclusive
control of a live user workspace.

The focused XPC probe now also requests `fs.read("../sibling-secret.txt")` through
the authenticated Runner IPC path and receives `path_not_readable` before command
execution or commit. That build-mode run passed in 69.088 seconds. A user-requested
interactive picker rerun passed in 137.345 seconds with a bookmark matching the fresh
fixture; it also verified path-only sibling XPC write denial and Kernel validation of
the output changeset. The picker, executor adapter, and signed bundle remain test-only.
The canonical suite then passed all 181 tests in 329.005 seconds with the traversal
denial included.

On 2026-09-27 the shared Workspace XPC ABI was advanced to carry the actual bounded
Runner IPC v4 `workspace.run` request and one scoped bookmark in the same stream.
Real XPC attacks rejected an oversized request length, empty `argv`, a mismatched
inner request ID, and oversized or stalled bookmark input before executor launch.
The focused build-mode XPC test passed in 68.982 seconds, and the canonical suite
passed all 181 tests in 320.241 seconds. The requested interactive retry brought
`WorkspaceGrant` to the foreground, but received no selection or cancellation within
300 seconds; its helper and fixture were cleaned up. This ABI v4 run therefore has
no fresh user-selected grant or positive Kernel writeback evidence. The executor
adapter, Trusted Launcher, and production Kernel service remain unimplemented.

The subsequent peer-PID binding passed the focused build-mode XPC test in 71.164
seconds, including a real socketpair parser mismatch check. A user-requested picker
reopen then brought the signed helper to the foreground but received no directory
selection or cancellation within 300 seconds. The test terminated the helper and
removed that run's fresh temporary workspace; this attempt adds no grant or
writeback evidence.

A fresh interactive rerun on 2026-09-27 completed in 123.070 seconds. The selected
workspace bookmark reached the XPC Kernel, which committed the expected output;
the path-only sibling XPC remained unable to write into the workspace, and unsafe
changesets were rejected without changing prior output or the outside canary. The
test also confirmed the exact workspace path delta. This proves the current
test-only Picker and signed XPC composition on this host; it does not establish a
production grant flow or Trusted Launcher.

After extracting the directory picker into `khaos/macos/TrustedWorkspacePicker.swift`,
the interactive XPC test passed again on 2026-09-27 in 100.706 seconds. The signed
test app exercised the shared picker, transferred the selected bookmark to Kernel,
confirmed path-only sibling XPC write denial, and verified safe commit plus unsafe
changeset rejection and the exact workspace path delta. The picker app and executor
composition are still test-only; durable grants and production packaging remain absent.
The canonical suite on this code state passed all 181 tests in 338.241 seconds.

The next XPC run passed the real cross-process stream-relay attack in headless
build mode in 71.439 seconds. A fresh interactive picker run passed in 139.630
seconds: it confirmed the selected bookmark reached Kernel, the path-only sibling
could not write the workspace, the relayed descriptor was rejected before request
parsing, and safe/unsafe changeset handling remained intact. The canonical suite
passed all 181 tests in 346.503 seconds on 2026-09-27. The picker app and executor
remain test-only.

On 2026-09-28 the shared fixed executor was added at
`khaos/macos/KernelWorkspacePythonExecutor.swift`, with its bounded Python process
bridge in `khaos/kernel/workspace_xpc_bridge.py`. It uses `posix_spawn` with
close-on-exec defaults and an explicit descriptor allowlist; the bridge validates
the XPC-delivered Runner IPC v4 request and invokes the existing Kernel launcher,
which starts a separate Worker and Seatbelt Runner and validates writeback. The
signed `KernelProduction.xpc` in the test app is the only composition exercised so
far. A fresh user-selected workspace test passed in 145.998 seconds: scoped input
read succeeded, direct live-workspace write failed, a validated output was committed,
and symlink/FIFO changesets and hardlink attempts were rejected before candidate
paths reached the real workspace. The hardlink probe accepts either OS denial at
link creation or Kernel rejection at commit and checks that prior output and the
outside canary remain unchanged. This evidence covers only the shared executor path
inside the current ad-hoc test bundle; it does not establish a shipped service,
Trusted Launcher, durable grant policy, capability admission, or user approval.
The implementation follows Apple's
[descriptor-spawn file-action documentation](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man3/posix_spawn_file_actions_adddup2.3.html)
and [process-spawn documentation](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/posix_spawn.2.html).
A follow-up interactive XPC run after correcting pipe-descriptor close ownership
passed in 334.921 seconds and exercised the same shared-executor checks. The
canonical suite then passed all 181 tests in 332.225 seconds on 2026-09-28.

On 2026-09-28 the signed test probe was extended to cancel through
`KernelProduction.xpc`, reject cancellation from a different XPC connection,
verify the command descendant exits, verify cancelled snapshot output is not
written back, and run a no-change request afterward to prove service recovery.
The focused headless XPC test compiled the probe and passed in 74.228 seconds;
the canonical suite passed all 181 tests in 328.892 seconds. A fresh interactive
retry passed its APFS/XPC preflight but received no directory selection within
300 seconds and cleaned its helper and fixture. Therefore the new production-path
cancellation assertions have not run and are not security evidence yet.
An earlier retry stopped before the picker when the APFS probe reported ambiguous
image identity; a later retry passed that preflight without code changes, so the
cause of that one failure remains undetermined.

On 2026-09-28, a fresh selection using the current read-only Picker bookmark
path reached the XPC/Worker path but the helper returned `NSPOSIXErrorDomain`
code 1 before emitting its assertions; no successful commit or denial result was
collected. The next diagnostic run did not receive a folder selection and timed
out. The test probe now labels Kernel-bookmark creation and read-only-bookmark
resolution errors; this diagnostic change passes the focused build-mode test but
the selected-workspace flow remains unverified. The Kernel transfer bookmark was
then switched to the original `NSOpenPanel` URL with `options: []`; build-mode
passed in 119.557 seconds. The next interactive run received no selection within
300 seconds and timed out after 408.694 seconds, so the corrected selected-bookmark
path and Kernel writeback remain unverified.

On 2026-09-28, after the user confirmed the fixed product app's zero-change PASS, the
current WorkspaceGrant interaction was reopened against a new temporary workspace.
The helper was frontmost, but no selection arrived within 300 seconds; the focused test
timed out after 379.907 seconds and removed its fixture. This attempt ran no selected
workspace denial, commit, unsafe-changeset, or cancellation assertions. The product
smoke and this unselected test remain distinct evidence.

## 2026-09-28 fixed product writeback smoke

`TrustedWorkspaceLauncherMain.swift` now runs a fixed shell command that creates one
UUID-named marker in the private snapshot with an empty workspace read scope. It asks
the Kernel to commit only after the command exits successfully, then accepts only a
result with one added file and no modified or deleted files. The Picker explains the
write and the success alert names the committed file. This remains a fixed smoke
operation, not Candidate execution.

The source package test and canonical suite passed after this change (185 tests,
354.277 seconds); the focused real Seatbelt positive/negative writeback test and
headless XPC build-mode test also passed. The current source has now been rebuilt
into a fresh local app and passed the product package/XPC test, deep signature
verification, and a read-only bootstrap check (`kernel-xpc-peer-authentication=verified`).
Bootstrap also emitted `sandbox_extension_issue_file_to_process` on stderr but exited
successfully; the warning is not yet attributed. The user reported seeing PASS after selecting
`/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-seed-picker-b_oua14q/Workspace`,
but inspection found only `seed-picker-fixture.txt` and no UUID marker. That report
cannot establish that the newly changed product binary ran or committed non-empty
output. No Picker was opened from the fresh bundle, so its non-empty writeback remains
unverified. Do not upgrade the earlier zero-change product evidence based on that PASS.

## 2026-09-29 product-bundle XPC attack result

The focused interactive test passed in 135.293 seconds on this macOS host after a
fresh external workspace selection. It replaced only the Launcher executable in a
temporary copy of the locally signed product app with a test-only driver; the
packaged `KernelProduction.xpc` remained unchanged and the driver still satisfied
the service's designated caller requirement. The real service and Python bridge
committed one expected file, rejected symlink and special-file changesets, and
rejected hardlinks either at OS creation or at Kernel commit. Direct live-workspace
write was denied. The same run tested connection-bound cancellation: the exact
randomized command child was observed by the external parent, cancellation caused
the descendant to terminate, cancelled snapshot output was absent from the live
workspace, and a following request succeeded. The parent also checked fixture and
canary bytes/link counts, committed-file content/mode/link count, deep code
signature, and absence of Python bytecode caches.

This closes the selected-workspace attack assertions for the tested local product
XPC composition and host. It does not establish Candidate admission, arbitrary
Plugin execution through the production Launcher, distribution signing, installation
protection, or behavior on other macOS versions.

## 2026-09-29 source digest-bound XPC v5

ABI v5 adds `runner_source_sha256` and keeps the inner Runner IPC at v4. The Swift
Kernel parser rejects a source/digest mismatch before it reads the workspace bookmark;
the Python bridge rechecks the digest before starting the Worker. The headless signed
product-bundle test passed in 10.531 seconds. Its test-only caller sent a validly framed
request with an incorrect digest to the real, unchanged `KernelProduction.xpc`, which
returned `invalid_request` before bookmark handling.

The product-bundle interactive XPC attack passed in 303.470 seconds after a fresh
workspace selection. A matching digest traversed the production service, bridge, Worker,
and Seatbelt Runner. The test verified safe writeback, direct live-workspace denial,
unsafe changeset rejection, connection-bound cancellation, descendant cleanup, service
recovery, canary integrity, and the deep bundle signature. The test-only driver replaced
only the Launcher executable in a temporary product copy. This validates the digest
binding on that request path; it does not establish user approval, Manifest/capability
admission, Candidate activation, or arbitrary Plugin execution through the normal
Launcher.

The subsequent normal Launcher writeback test opened its Picker but received no
selection within 300 seconds; it timed out after 308.598 seconds and cleaned its
fixture. It adds no selected-workspace writeback evidence for the ABI v5 Launcher path.
The earlier user-reported PASS and marker files belong to a previous fixed-smoke build
and do not fill this evidence gap. The user later reported that the repaired Picker
displayed `PASS`. This is user-observed UI evidence, but no surviving process, fresh
fixture, or recorded bundle identity ties that popup to the timed-out v5 acceptance run;
the automated v5 selected-workspace result therefore remains unverified.

After these ABI v5 changes and tests, the canonical
`python3 -m unittest discover -s tests -v` suite passed all 188 tests in 365.615
seconds. The default suite does not open the Picker, so it does not resolve the
normal Launcher's selected-workspace v5 evidence gap.

After the later Launch Services visibility check, the user again confirmed seeing a
`PASS` popup. The test still captured no `workspace-selected` or success diagnostic, and
the fresh fixture had no committed marker before cleanup. This repeated UI observation
does not establish that the current v5 acceptance run completed.

## 2026-09-29 product XPC request-boundary attacks in the default suite

The default signed-product test now replaces only the Launcher in its temporary
bundle with a test driver and sends the real `KernelProduction.xpc` a bounded
`workspace.run` frame whose source digest does not match and whose stream contains
no bookmark. The service returns `invalid_request` before bookmark handling; the
test verifies that the disposable fixture bytes and sibling canary remain
unchanged. It also sends a bounded over-depth JSON request without a bookmark and
requires the service to reject it, then answer a later idle-cancellation request.
The Swift parser checks an eight-level structural limit before Foundation parses
the body; the current `workspace.run` schema reaches at most three levels, and
braces or brackets inside strings do not count. With both UI flags unset, the
focused test passed in 10.429 seconds. These are real product-service input-boundary
checks, not Candidate authorization; a matching self-supplied digest still needs
trusted admission and capability approval. The canonical
`python3 -m unittest discover -s tests -v` suite passed all 193 tests in 394.905
seconds. The suite does not open the Picker or add selected-workspace writeback
evidence.

## 2026-09-30 normal product Launcher selected-workspace writeback

The opt-in acceptance test completed with exit code 0 in 95.427 seconds after
the user selected its fresh workspace in the normal locally signed `KhaosSeed.app`.
The same run verified read denial before selection, read access while the Picker
scope was live, read denial after the Launcher released that scope, one validated
Kernel marker writeback, and direct Launcher write denial after scope release.
Before cleanup, the test parent checked the unchanged fixture digest and link
count, exact two-file workspace contents, marker bytes/mode/link count, deep app
signature, and absence of `__pycache__` in the signed Python framework.

This verifies the fixed product smoke on this host. The Launcher still runs only
its fixed Runner source; the result does not establish arbitrary Plugin execution,
Candidate/Manifest admission, activation approval, installation protection, or
distribution signing. The default suite still does not open the Picker.

## 2026-09-30 selected Product XPC file and directory-list scope

The interactive product-bundle XPC attack passed in 250.479 seconds. The
test-only Runner was granted read scope for `production-input.txt`. Through the
real signed `KernelProduction.xpc`, it read that file, received
`path_not_readable` for an in-scope sibling outside that exact path, and listed
the workspace root. The root response contained only the authorized file name;
a direct listing request for the sibling returned `path_not_listable`. The
Runner had to satisfy all four assertions before it could issue `process.exec`
or `workspace.commit`.

The same run preserved the existing writeback, OS-denial, unsafe changeset, and
connection-bound cancellation checks. This verifies the bounded `fs.read` and
`fs.list` scope semantics through the selected-workspace product-service path on
this host. The test-only Runner source is not a Candidate admission or
user-approved Plugin capability grant.

## 2026-09-30 fixed Launcher read/list integration attempt

The current fixed product Runner now has an acceptance-only branch whose source
digest covers a bounded `fs.read` of `seed-picker-fixture.txt`, a root `fs.list`
that must expose only that name, and direct read/list denials for an existing
unscoped sibling. It reaches the fixed command and Kernel commit only after those
checks. The request grants exactly that one read path only when the trusted
Launcher was started with `--acceptance-workspace`; an ordinary no-argument
launch sends an empty read scope and the Runner checks that read and root listing
are denied. This remains fixed acceptance code, not Plugin admission.

The rebuilt signed product passed the headless package/service test (1 test,
14.968 seconds). Its interactive acceptance did not complete: after 300 seconds,
the test had received only `preselection-read=denied` and `picker-requested`, with
no `workspace-selected` diagnostic. The temporary workspace still had only its
two input fixtures and no writeback marker. Therefore no Runner `fs.read` or
`fs.list`, Kernel commit, or post-selection signature assertion ran. A user-
reported PASS from a different temporary workspace cannot be attributed to this
build. The separate Product XPC tests above prove the underlying Kernel scope
behavior with test-only Runner source, not this normal Launcher integration.
After this source update, the canonical headless suite passed all 207 tests in
403.161 seconds; it does not open the Picker or execute this product Runner path.

## 2026-09-30 Runner filesystem scope-injection attacks

The Broker's raw Runner IPC rejects additional grant fields in filesystem
payloads. Unit attacks add `workspace_read_scope` to `fs.read` and `fs.list`, and
`workspace_write_scope` to `fs.write`; all three receive `invalid_request`. The
real macOS Seatbelt Runner attack sends the same three frames with empty retained
scopes, requires the session to fail before the fixed command marker appears, and
checks that the workspace secret remains unchanged. The canonical headless suite
after these attacks passed all 209 tests in 406.525 seconds. This verifies the
Broker/Runner scope boundary on this host; it does not establish product Picker
read/list integration, Candidate admission, or user approval.

## 2026-10-01 final-unlink symlink race

The real Broker/Seatbelt commit-child test pauses after the recovery path's
inode check and before final `unlink`. An independent process atomically puts a
symlink to an outside canary at that in-workspace path. The commit child
completes the validated file replacement and removes the symlink entry; the
canary bytes remain unchanged. This covers the out-of-scope symlink-target
attack at this check-to-unlink point. It does not close the race against a
regular replacement within the authorized workspace, and the full canonical
suite remains headless with respect to Picker selection. The Broker module
passed 39 tests in 73.577 seconds; the canonical 216-test suite passed in
441.428 seconds on this host.

## 2026-10-01 signed-product Seatbelt readiness probe

The signed Kernel XPC readiness-probe layout introduced here originally placed its
source fixture inside the authenticated APFS lease and its copy in `seatbelt-probe`.
That layout was later found to conflict with the snapshot's separate-device check:
source and destination were on the same mounted volume. The current layout keeps the
source in the XPC service's validated Broker lease root (`TMPDIR`) and the copy
in the Broker lease, as described in the current implementation record above. It still
uses one Broker image and does not rely on a global host temporary directory. The XPC
executor takes that temporary root from the Broker storage directory it created and
validated for the request.
Path-free stage codes distinguish probe I/O failures without returning local
paths or OS error strings. In the earlier App Sandbox composition, a host loopback
listener could fail with `EPERM` or `EACCES`; the readiness probe still requires the
Seatbelt Runner's loopback attempt to fail with an OS permission error; other
listener failures remain fatal.

The signed headless package/XPC checks and real Seatbelt probe tests passed, and
the canonical `python3 -m unittest discover -s tests -v` suite passed all 235
tests in 471.439 seconds. The latest opt-in interactive product writeback run
timed out after 300 seconds with only `preselection-read=denied` and
`picker-requested`; it recorded no `workspace-selected` or writeback marker.
The user later reported selecting a workspace from a different temporary run
and dismissing its result alert. The test processes and both temporary roots
have since been removed, so that UI observation has no surviving exit status,
fixture, or product identity tying it to this acceptance run. It is not counted
as current selected-workspace writeback evidence. No Picker process remains
running.

## 2026-10-03 Product XPC missing Snapshot Broker rejection

The signed-product XPC test now sends a digest-matched Runner request whose
source attempts to create a host-writable `/Users/Shared` canary while omitting
the request's Snapshot Broker endpoint. The host test process first proves the
canary path is writable. The real `KernelProduction.xpc` responds with exactly
`snapshot_broker_not_configured`, and the canary remains absent. The
`KernelWorkspacePythonExecutor` rejects this condition before bookmark
resolution and Python bridge launch. This is executable evidence for the
missing-endpoint path; it does not cover every sandbox failure or prove
selected-workspace execution. The focused signed-product test passed in 27.918
seconds, and the canonical suite passed all 244 tests in 471.613 seconds. The
new check is headless and opens no Picker.

## 2026-10-03 path-free Seatbelt readiness error stages

The Worker reports one of four finite internal error codes for a failed
Seatbelt readiness probe: child launch, readiness, snapshot, or verification.
The signed XPC service carries only the fixed code; the product Launcher maps
all four back to the existing generic `sandbox_unavailable` result. Exception
text, OS error strings, and local paths do not cross the ABI. The updated
signed headless XPC check and the stage-mapping/allowlist tests passed. The
canonical `python3 -m unittest discover -s tests -v` suite passed all 247
tests in 459.405 seconds. This does not provide selected-workspace Product XPC
execution evidence: prior selected runs rejected before Runner/cancellation,
and the later diagnostic interaction has no correlated retained output.

## 2026-10-03 selected-workspace snapshot path opening

A correlated signed Product XPC selection reached the trusted bridge but
returned `sandbox_unavailable_probe_snapshot`. App Sandbox denied a Python
process's attempt to open the `/Users` ancestor. The service's fixed error
code disclosed no workspace path. The
snapshot directory opener now handles an ancestor `EPERM`/`EACCES` on macOS
by opening the exact resolved directory and comparing `F_GETPATH` from that
descriptor with the expected path. A mismatch fails closed; mount and inode
checks remain in force. The signed App Sandbox helper verified direct access
to its own source and APFS mount even though `/Users` was denied. This is a
path-opening correction, not new IPC authority or selected-workspace XPC
writeback evidence. A fresh run still returned the same code, although OS
logs showed the probe child running. The snapshot wrapper was also catching
errors from the probe body and mislabeling them as snapshot creation. It now
maps only context-entry errors; a body-error regression covers the distinction.
The `/Users` denial is confirmed, but it has not been shown to cause the
current Product XPC failure.
