# Khaos vNext Seed

Khaos Seed is a macOS-only security prototype. It builds a sandboxed local
Launcher, a separately sandboxed untrusted Agent Host XPC service, and a signed Kernel XPC
service around the existing Seatbelt Runner path, with a separate XPC service
for APFS snapshot mounting. The Launcher offers a fixed Kernel-mediated
writeback smoke, a one-shot shell command, a persistent single-slot Plugin lifecycle, and
a small local Agent Loop. The smoke Runner receives one generated marker path for SDK
`fs.write`; acceptance runs may also receive an exact fixture read/list scope,
while an ordinary no-argument launch uses deny-all read scope. The Agent Loop
uses an on-device model and only submits user-approved bounded
tool requests to the Kernel; it is not a general coding assistant.

## Build the local app

The build requires Xcode command-line tools, a stable code-signing identity,
and a `Python.framework` runtime. The output path must not already exist.

```bash
python3 tools/build_macos_seed.py \
  --output /tmp/KhaosSeed.app \
  --signing-identity "IDENTITY"
```

Use `--keychain PATH` for an identity in a non-default keychain, or
`--python-executable PATH` to choose the embedded Python framework. The build
targets the current Mac architecture and signs the app locally. It does not
notarize or install it.

To bundle the local CPU model used by the Agent, provide a CPU-only
`llama-completion` binary with `--llama-cli PATH`, plus `--model-file PATH` and
`--model-license PATH`. Build llama.cpp without Metal or OpenSSL so the
app-sandboxed Agent Host does not initialize a GPU backend or carry an unused
HTTPS runtime:

```bash
git clone --depth 1 --branch v0.5.0 \
  https://github.com/ggml-org/llama.cpp.git /tmp/llama.cpp
cmake -S /tmp/llama.cpp -B /tmp/llama.cpp/build \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_BUILD_RPATH=@loader_path \
  -DGGML_METAL=OFF \
  -DGGML_NATIVE=OFF \
  -DGGML_OPENMP=OFF \
  -DLLAMA_OPENSSL=OFF \
  -DLLAMA_BUILD_TESTS=OFF \
  -DLLAMA_BUILD_EXAMPLES=OFF \
  -DLLAMA_BUILD_SERVER=OFF \
  -DLLAMA_BUILD_APP=OFF \
  -DLLAMA_BUILD_TOOLS=ON
cmake --build /tmp/llama.cpp/build --target llama-completion \
  --config Release -j 6
```

Then pass `/tmp/llama.cpp/build/bin/llama-completion` as `--llama-cli`. The
builder copies the binary's non-system dylib dependencies, Homebrew or source
license notices, and GGUF model into the separately sandboxed Agent Host. No
model download or remote provider is used at runtime. The tested development
model is the official Qwen2.5-1.5B-Instruct Q4_0 artifact from revision
`91cad51170dc346986eccefdc2dd33a9da36ead9` (Apache-2.0); fetch that exact
model and its license with:

```bash
curl --fail --location --output /tmp/qwen2.5-1.5b-instruct-q4_0.gguf \
  https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/91cad51170dc346986eccefdc2dd33a9da36ead9/qwen2.5-1.5b-instruct-q4_0.gguf
curl --fail --location --output /tmp/Qwen-LICENSE \
  https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/91cad51170dc346986eccefdc2dd33a9da36ead9/LICENSE
```

See the [llama.cpp build and CLI documentation](https://github.com/ggml-org/llama.cpp/blob/v0.5.0/docs/build.md)
and the [pinned official Qwen model card and license](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/tree/91cad51170dc346986eccefdc2dd33a9da36ead9).

The builder copies only the Seed's reviewed Python modules into the trusted
Kernel XPC bundle; adding a new module to the repository does not implicitly
add it to that bundle. The signed-product test checks the exact packaged set.
The bundle omits the source-tree-only `khaos/kernel/macos_disk_image.py` direct
APFS backend. Product execution requires an authenticated Snapshot Broker lease;
missing lease data fails closed instead of enabling direct image mounting in the
Kernel service.

Launch `KhaosSeed.app` to select a disposable workspace and run the fixed smoke
operation. The picker explains that the app will create one uniquely named test
file. A pass requires the Kernel response to report exactly one added file and
no modified or deleted files, then requires the Launcher to receive `EPERM` or
`EACCES` when it attempts a direct `O_WRONLY` open of that committed file after
releasing the Picker scope. The alert names the committed file. Diagnostics
contain path-free result codes, not workspace paths or command output.

To run one shell command in a private workspace copy, use the signed app binary:

```bash
/tmp/KhaosSeed.app/Contents/MacOS/KhaosSeed \
  --command 'cat input.txt > result.txt' \
  --read input.txt \
  --write result.txt
```

The Picker selects the workspace. A separate confirmation displays the full
command, exact read and write paths, and a digest of the one-run request before
the Launcher releases its Picker scope. The command runs through the existing
Runner and Kernel path. A successful command commits only changes listed by
`--write`; any extra changed path rejects the whole commit. An empty read scope
denies workspace data reads; an empty write scope permits only a no-change
commit. The command is limited to 512 UTF-8 bytes, eight
scope paths in total, and a 30-second process timeout. The result alert shows
change counts and a bounded local preview of stdout and stderr. A failed command
does not request a commit.

This command mode has passed Swift type checking and the signed app's headless
build/XPC check. A real Seatbelt test confirms the shown `cat` command can read
only its input and commit the scoped output; direct reads of the unscoped sibling
and newly written output remain denied to the command. The signed app's new
command UI has not yet been exercised through a selected-workspace interactive
run. Some shell tools, including `/bin/cp`, try to copy extended attributes and
may fail under the current metadata-write denial. It does not install or
activate a Plugin.

To install and activate a Plugin package, run:

```bash
/tmp/KhaosSeed.app/Contents/MacOS/KhaosSeed --plugin-install
```

Choose a package folder. The example package is
[`examples/seed-writer`](examples/seed-writer). A package has exactly
`manifest.json` and `plugin.py` as its admitted inputs. The manifest must be
canonical sorted-key JSON (an optional final newline is accepted), with
`abi_version: 6`, a lowercase ASCII ID, `process_exec: true`, and exact
`read` / `write` path arrays. The Launcher captures both regular, single-link
files without following symlinks, caps their sizes at 4 KiB and 10 KiB, and
releases the package Picker scope. The Kernel validates and stores the package
as a read-only, content-addressed Candidate, then revalidates its content when
loading it. The activation confirmation
shows its Candidate, Manifest, and capability-scope digests, the requested
read/write paths, the fixed `primary` slot, and the 30-day validity. The Kernel
accepts activation only for those exact digests and the slot generation shown
before the confirmation. Candidate state persists under the signed product's
Application Support namespace.

To run the active Candidate, choose a workspace and approve the displayed
Candidate digest, scopes, validity, and invocation:

```bash
/tmp/KhaosSeed.app/Contents/MacOS/KhaosSeed --plugin-run
```

The request binds the review to the active Candidate digests and slot
generation. The Kernel loads source and scope from its active slot; the run
request cannot provide either. To route future runs to the previous Candidate,
run:

```bash
/tmp/KhaosSeed.app/Contents/MacOS/KhaosSeed --plugin-rollback
```

Rollback changes the active slot and does not undo workspace changes or other
effects from earlier runs. The Manifest requests scope; only the trusted
Kernel grants it to the isolated Runner.

For an interactive local conversation, start the signed Launcher from a terminal:

```bash
APP="/tmp/KhaosSeed.app"  # use the --output path from the build command above
"$APP/Contents/MacOS/KhaosSeed" --agent
```

The Agent Host uses the bundled local llama.cpp CLI and GGUF model on CPU when present;
without a bundled model, it uses Apple's on-device Foundation Model when
available. It has no remote fallback. The launchd-managed XPC service has its
own App Sandbox, no user-selected file or network entitlement, and a different
code-signing requirement from the Launcher accepted by Kernel XPC. It receives
only conversation text and bounded tool results over a 64 KiB XPC protocol.
It proposes `argv` plus exact read/write paths; the trusted Launcher validates
the proposal, selects one workspace, shows the command, scopes, and invocation
digest, and asks for approval for each operation. The Kernel retains those
scopes, runs the command in the existing Seatbelt Runner, and commits only the
approved exact-path changeset. The Host never receives a workspace path or
bookmark. Each command is capped at 30 seconds; the in-memory session ends
after eight user turns.

The signed product package check sends a real `--agent` turn through the
launchd-managed Agent Host XPC service. A bundled test model attempts direct
read and write opens on a parent-readable canary; the service must report both
OS denials. The production Agent loop uses the same XPC and sandbox path.

The example Plugin completed a signed two-Picker product run on this Mac: the
Kernel reported one added file, and the workspace output and deep app signature
were checked. That run used an earlier bundle whose shell printed a `getcwd`
denial while the Kernel commit succeeded. The current source sets the command's
working directory to its private snapshot; the rebuilt signed app passed deep
signature and headless XPC checks, but its Picker flow has not been rerun. The
current local model completed one text turn through Agent Host XPC; a
model-generated tool request has not yet been verified end to end.

The no-Picker canonical suite passed 250 tests in 485.373 seconds, including
the example Plugin's allowed write and default-denied write, and the
output-metadata alias attack.

To check only the signed XPC bootstrap without opening the picker:

```bash
/tmp/KhaosSeed.app/Contents/MacOS/KhaosSeed --bootstrap-check
```

## Validation

Run the repository suite with:

```bash
python3 -m unittest discover -s tests -v
```

The focused local app packaging test builds a temporary signed app, starts its
Kernel service, and verifies rejection of a wrong-signing-identity client:

```bash
python3 -m unittest discover -s tests \
  -p test_macos_xpc_sandbox.py \
  -k test_seed_app_builds_and_authenticates_its_kernel_service -v
```

The optional product writeback check opens a directory picker. Select the
disposable workspace printed by the test, then dismiss the success alert:

```bash
KHAOS_RUN_PRODUCT_WRITEBACK_UI=1 python3 -m unittest discover -s tests \
  -p test_macos_xpc_sandbox.py \
  -k test_seed_app_builds_and_authenticates_its_kernel_service -v
```

The focused test also sends headless malformed, over-budget, and caller-asserted
authority requests to the signed Kernel XPC service. It exercises real XPC
Candidate admission, exact-digest activation, stale-generation rejection,
persisted slot state, rollback, and missing-bookmark rejection for `plugin.run`.
This lifecycle check does not open a Picker or execute a Candidate in a selected
workspace. Real Runner isolation, writeback rejection, and cancellation attacks
run in the canonical suite. The single interactive route is the product
writeback acceptance above; it exercises the selected-workspace XPC path without
a second test-only Picker driver.

## Current status

The packaged Seed currently exercises a fixed, locally signed smoke path:
the Launcher obtains a user-selected workspace bookmark, authenticates to the
embedded Kernel XPC service, and asks the Kernel to commit one validated marker
from a private snapshot. Its fixed Runner also exercises bounded `fs.read` and
`fs.list` in acceptance mode with a one-file fixture scope; an ordinary
no-argument launch passes an empty read scope. The one-shot command mode now
uses the same XPC request and Kernel commit path with user-reviewed scopes.
The product is not yet a general coding assistant. The Launcher provides one
persistent `primary` Candidate slot with explicit activation, execution, and
rollback confirmations; the local Agent Host does not manage or invoke Plugins.

`KernelProduction.xpc` has no App Sandbox entitlement: a signed App Sandbox
helper on this Mac cannot apply the nested Seatbelt policy needed for the
untrusted Runner. The Kernel service is trusted enforcement code and remains in
the TCB. The separate snapshot-mount Broker is also not App-Sandboxed because
macOS rejects this backend's `hdiutil create/attach` operations from an
App-Sandboxed helper. It applies a custom Seatbelt policy that denies network
access, user files, temporary paths outside its fixed private storage subtree,
mounted volumes, and execution from `/Users`, `/opt/homebrew`, and `/usr/local`.
It also denies signals to processes outside its own sandbox. This is partial OS
confinement: the policy starts with `allow default`, so
authority outside the tested deny rules remains. See the
[Seed threat model](docs/SEED_THREAT_MODEL.md) for the tested denials and limits.

On 2026-10-04, the canonical headless suite passed 250 tests in 484.088 seconds.
After fixing a test-only recovery request that omitted the Snapshot Broker
endpoint, the interactive signed-product XPC attack passed in 116.146 seconds.
It verified the selected workspace's exact contents and committed file mode,
direct OS access denials, unsafe changeset rejection, cancellation and recovery,
and deep code-signature integrity. This is evidence for a local temporary signed
product copy, not Plugin admission or a protected installation. The dated
attempts below remain historical records of earlier builds and failed runs.

On 2026-09-30, the selected-workspace acceptance passed on this Mac in 95.427
seconds. It verified read denial before selection and after Picker-scope release,
read access while the scope was active, one Kernel-committed `0600` marker, and
direct Launcher write denial after scope release. The fixture, exact workspace
contents, deep app signature, and absence of Python-framework cache writes were
also checked. This earlier run predates the fixed Runner read/list checks and does
not verify them. The canonical
`python3 -m unittest discover -s tests -v` suite passed all 207 tests in
393.411 seconds on the same host; the default suite does not open the Picker.
See the [Seed threat model](docs/SEED_THREAT_MODEL.md) and
[backend research log](docs/SEED_BACKEND_RESEARCH.md) for test scope and limits.

The updated fixed Runner requires the selected fixture read and filtered root
listing to succeed, and requires direct read/list requests for an existing sibling
to be denied before it requests process execution or commit. A fresh signed-bundle
acceptance attempt built and passed its headless package/service check, but the
interactive run timed out before the user selected its workspace. Its diagnostics
stopped at `picker-requested`, so that run proves no selected-scope, writeback, or
post-selection signature result. The user's report of PASS referred to a
separate temporary workspace and does not change this run's timeout. The later
user-observed PASS for the updated Launcher is recorded below, without attributing
this timeout to a successful run.
After this source update, the headless canonical suite passed all 207 tests in
403.161 seconds; it does not open the Picker or cover the uncompleted product
Runner read/list assertions. After adding real Runner scope-injection attacks,
the canonical suite passed 209 tests in 406.525 seconds, still without opening
the Picker.

The signed-product XPC probe now includes the Picker-scope and direct live-read
checks described above. The updated Swift probe compiled in the signed-product
headless test, and the canonical suite passed all 217 tests in 440.185 seconds.
The latest opt-in XPC run reached the Picker but received no folder selection;
after 614.303 seconds, diagnostics contained only `picker-requested`, and the
temporary app and workspace were removed. That attempt adds no selected-workspace
direct-read, writeback, or post-run signature evidence. A PASS reported for the
separate `user-selected-writeback-workspace` Product Launcher run does not
complete this XPC attack run.

A separate interactive retry for the updated read/list path used a new signed
app and workspace (`khaos-seed-app-107zf9i5`). The OS confirmed `KhaosSeed` was
frontmost, but no selection reached the test within 300 seconds; diagnostics
stopped at `picker-requested` and the workspace had no writeback marker. That
attempt remains a timeout and is distinct from the later user-observed PASS.

The real-Seatbelt test
[`test_workspace_root_descriptor_is_not_inherited_by_runner_or_command`](tests/test_launcher.py)
passed separately in 3.743 seconds: both untrusted processes observed `EBADF` for
the trusted live-workspace root FD, while the Kernel completed an empty commit and
the workspace fixture and outside canary remained unchanged. The same focused
write-scope test passed in 3.728 seconds after adding post-commit direct-write
denial and rejection of a late `fs.write`. A real-Seatbelt test also confirmed a
Runner that loops forever after commit is killed while its successful commit
result is preserved (8.698 seconds). After the lifecycle fix, all 31
`test_launcher.py` tests passed in 125.383 seconds, along with all seven
`test_worker.py` tests in 0.007 seconds. The full canonical
`python3 -m unittest discover -s tests -v` suite then passed all 216 tests in
441.428 seconds on 2026-10-01. It does not open the Picker, and its signed-product
XPC checks do not verify a selected-workspace product run.

After reopening the Picker, the user reported selecting the
`khaos-seed-app-3mfj1nf_` workspace and seeing `PASS`. The current Launcher shows
that alert only after its scoped Runner read/list allow and deny checks, the
post-scope OS read denial, Runner `fs.write` allow and deny checks, Kernel
writeback, and direct-write denial. This is user-observed execution evidence for
those gates. The temporary app and workspace were removed and no test-parent
result remains, so this report cannot be bound to an exact bundle digest or
independently confirm that run's post-alert deep-signature check. The earlier
103.483-second acceptance-bundle result remains separate evidence for its own
build. The `rx5bn0nu` timeout was a different run and still has no selection
evidence.

The trusted `workspace_write_scope` limits Runner SDK `fs.write` and every
added, modified, or deleted entry in the complete committed changeset. It is an
exact path list with no descendant grants; an empty list permits only a no-op
commit. Commands may write anywhere inside the private snapshot, but the Kernel
rejects the entire commit before live mutation if any changed path is outside
the list. Creating or deleting a directory tree requires listing each changed
entry. The launcher retains this scope; it is not user approval or a
Plugin-bound capability grant.

Seatbelt denies unlink/rename of unreadable baseline entries and protected
scope ancestors so file movement cannot widen read access. A real macOS test
shows an authorized command output reaches the selected workspace, while a
second command that also emits an out-of-scope file is rejected and neither
file is written back. Direct writes to the live workspace and an outside
canary are also denied ([tests](tests/test_launcher.py)).

A real Broker/Seatbelt race test also replaces the final recovery pathname with
a symlink to an outside canary immediately before `unlink`; the validated
workspace change commits and the canary bytes remain unchanged. This proves
that `unlink` does not follow that raced symlink target. A regular replacement
at the in-workspace recovery name can still be removed by a non-cooperating
same-UID writer; this is not global write exclusion.

## Not implemented or not guaranteed

- A selected-workspace `--plugin-run` through the signed product Launcher and
  Kernel XPC is still awaiting correlated runtime evidence. The signed-product
  test exercises admission, activation, stale-approval rejection, and rollback;
  a separate real macOS Seatbelt test runs persisted Candidate A, then B, then A
  after rollback through the Kernel Runner path. That test also confirms a
  Candidate cannot read or write lifecycle storage or look up the tested live
  Mach service.
- Trusted Promoter, multiple Plugin slots, Plugin-based Memory/Context/Tools,
  and protection from arbitrary same-UID edits to user-owned Application
  Support state.
- App Sandbox enforcement for the snapshot-mount Broker. The signed-product
  headless test proves its authenticated APFS lease and cleanup path on this Mac,
  but the Broker process itself retains broader authority and remains trusted code.
- Global exclusion of unconfined same-UID workspace writers. Seatbelt denies the
  tested Runner and fixed-command live-workspace write paths, but the reviewed
  public macOS APIs provide no inode-conditional final `unlink`/`rmdir`; an
  independent same-UID writer can still replace the workspace-local recovery
  entry during cleanup. The real symlink-race test confirms that this does not
  follow an outside symlink target.
- Distribution signing, notarization, installation, or updater policy.

See the [Seed threat model](docs/SEED_THREAT_MODEL.md) for tested properties
and the [backend research log](docs/SEED_BACKEND_RESEARCH.md) for OS primitive
research and detailed run history.
