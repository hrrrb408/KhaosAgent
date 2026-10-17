# AGENTS.md

## Scope

This file defines repository-wide instructions for coding agents working on Khaos vNext.

Nested `AGENTS.md` files may add stricter subtree-specific rules, but must not weaken the
security invariants defined here.

The architecture source of truth is:

- `docs/Khaos vNext 架构设计文档.md`

Read the relevant design sections before making architecture or security-boundary changes.
Keep this file concise; detailed design belongs in `docs/`.

## Repository identity

This repository is the new Khaos vNext implementation:

- New repository: `https://github.com/hrrrb408/KhaosAgent`
- Legacy repository: `https://github.com/hrrrb408/Khaos-Agent`

Treat `KhaosAgent` as the only implementation target for new development.

Treat `Khaos-Agent` as a reference implementation, engineering knowledge base, bug archive,
security-test source, and source of previously learned lessons. It is not an architectural
dependency and must not be copied wholesale into the new project.

> Copy invariants and proven lessons, not legacy architecture.

## Current state

Khaos vNext is an architecture-first rewrite. Do not claim a security guarantee is implemented
until executable code and tests prove it.

Do not invent build, test, lint, packaging, or release commands that are not present in the
repository. When canonical commands are introduced, update this file in the same change.

## Mission

Khaos is a local-first, single-user, self-evolving Agent built around one fixed rule:

> Intelligence may evolve. Authority may not.

The intended system consists of an immutable Security Microkernel, a minimal untrusted Agent
Host, sandboxed Plugin Runners, a small trusted IPC/admission boundary, a Trusted Promoter,
and an evolvable Plugin Graph.

Do not rebuild the legacy Khaos Agent Runtime Platform.

## Trust boundary

Treat the LLM, Agent Host, Plugins, Candidate Plugins, generated code, project contents,
repository scripts, and third-party code executed by them as untrusted.

Only the minimum enforcement code may belong to the TCB:

- Security Kernel / Kernel Broker;
- OS sandbox backend;
- trusted IPC / Plugin admission runtime;
- Trusted Promoter;
- ABI validation required for enforcement.

Memory, Planner, Context, Verifier, Model Routing, Browser, Subagents, Skills, and Evolver
logic do not belong in the TCB.

## Security invariants

Every implementation must preserve all of the following:

1. Plugins cannot bypass the Kernel for privileged side effects.
2. Plugins cannot modify the Security Kernel.
3. Plugins cannot grant themselves additional capability.
4. Candidate Plugins cannot activate themselves.
5. Harness failure must not imply Kernel failure.
6. Missing or broken sandbox enforcement must fail closed; never silently run on the Host.
7. Plugin data access and Event subscriptions are scope-limited by default.
8. Remote-model input is an explicit data flow and must not include secrets by default.
9. Activation approval is bound to the exact Candidate content digest, Manifest digest,
   capability scope, target slot, and validity period.
10. Security boundaries rely on process separation, IPC, and OS enforcement, not Python
    objects, prompts, module boundaries, or command blacklists.
11. Data-read authority is as important as side-effect authority.

If convenience conflicts with an invariant, preserve the invariant.

## Process and IPC model

Kernel, Host, and Plugin code must not share one trusted process boundary.

Plugins run in dedicated Runner processes. SDK objects are IPC facades, not security
boundaries. Plugin code must never be imported into the trusted Kernel process.

Cross-boundary requests must use a versioned, bounded protocol with structured errors,
timeouts, cancellation, and validated peer identity.

A Manifest requests capability; it never grants capability. Do not expose a universal
`kernel` object to Plugins. Expose only narrowly scoped capability handles or facades.

Never trust caller-supplied identity, paths, approval booleans, version strings, or capability
strings without trusted-side validation.

In the current Seed ABI, a trusted workspace session enables Runner `process.exec`; the Runner
supplies bounded `argv`, while the Kernel fixes timeout, cwd, environment, read scope, snapshot,
and sandbox policy. The trusted `workspace_write_scope` limits Runner SDK `fs.write` and every
added, modified, or deleted entry in the complete changeset. A command may change the private
snapshot, but the Kernel rejects the whole commit before live mutation if any changed path is
outside this exact-path scope. The scope is still retained by the trusted workspace session; it
is not Plugin identity-bound or user-approved authority.

## Data flow

Do not broadcast raw Session, Event Bus, Config, Plugin storage, secrets, or workspace data
to every Plugin.

Keep control data, workspace data, memory data, secret data, and model-bound data separate.
Secrets must not enter normal logs, Session history, Memory, benchmarks, Candidate fixtures,
or Shadow Evaluation inputs by default.

Remote model providers are external data recipients. Sending workspace or Plugin data to a
remote model requires an explicit data scope.

## Reuse before implementation

Do not reinvent existing, well-tested infrastructure without a concrete reason.

Before implementing a non-trivial subsystem:

1. Search this repository for an existing implementation or reusable primitive.
2. Check the legacy Khaos repository for proven invariants, tests, attack cases, and useful
   low-level implementation lessons.
3. Search GitHub and upstream project documentation for maintained implementations, libraries,
   protocols, or OS primitives that already solve the problem.
4. Compare candidates against Khaos's threat model, dependency budget, maintenance quality,
   portability needs, license, and TCB impact.
5. Implement from scratch only when reuse would weaken the security model, create excessive
   complexity, introduce an unsuitable dependency, or fail the actual requirement.

Prefer proven operating-system primitives and focused libraries over custom infrastructure.

Prefer wrapping a suitable dependency behind a small Khaos-owned interface over copying,
forking, or rewriting it.

Do not vendor or copy third-party code casually. Check its license, provenance, maintenance
status, security history, transitive dependencies, and whether it executes inside the TCB.

When researching existing work, record the relevant upstream repository or documentation in
the implementation notes, ADR, issue, or pull request when that context materially affects
the design.

"Do not reinvent the wheel" does not mean "reuse at any cost." Security invariants and a
smaller trusted codebase take precedence.

## Engineering quality

Code must be concise, readable, composable, and unsurprising.

Prefer:

- small functions with one clear responsibility;
- explicit control flow;
- descriptive names;
- narrow interfaces;
- immutable values where practical;
- standard-library or already-approved primitives where sufficient;
- pure functions for deterministic transformations;
- dependency injection only where it solves a real testing or boundary problem;
- comments that explain *why*, especially around security invariants.

Avoid:

- duplicated logic;
- two functions that perform the same operation under different names;
- copy-pasted validation, normalization, serialization, or error handling;
- speculative abstractions;
- wrapper layers that only forward arguments;
- utility modules that become unrelated dumping grounds;
- clever metaprogramming in security-sensitive code;
- hidden global state;
- implicit fallbacks;
- large functions that mix policy, parsing, I/O, and orchestration.

If two code paths perform the same logical operation, extract the shared behavior into one
well-named function or component and reuse it.

There should be one canonical implementation for one piece of behavior. Do not maintain two
equivalent implementations unless the difference is intentional, documented, and required by
a real boundary such as platform-specific OS enforcement.

Before adding a new helper, search for an existing equivalent. Before adding a second code
path, determine whether the existing path should be generalized instead.

Do not create an abstraction merely because code *might* need another implementation later.
Abstract after a real second use case or a clear trust boundary appears.

Refactoring for reuse must not blur security boundaries. Trusted and untrusted code may use
similar logic, but do not move security-critical enforcement into an untrusted shared helper
just to eliminate duplication.

## Khaos Seed

Until Khaos Seed is complete, optimize for proving the security boundary rather than adding
features.

Seed should use one explicitly supported OS and one real sandbox backend. Unsupported
platforms must fail closed.

Keep Seed limited to the minimum execution path:

- Kernel Broker;
- trusted local IPC/admission path;
- isolated Plugin Runner;
- read/edit/bash-style capabilities;
- real sandboxed process execution;
- one bounded stateful Memory Plugin v1 (`remember`, `recall`, `forget`) to prove
  Plugin-owned state isolation and persistence through the existing Harness;
- one bounded, explicit-feedback Agent-generated Memory evolution path using the existing
  Candidate admission, isolated A/B evaluation, activation, and rollback operations;
- minimal Agent Loop and model adapter after the security path works;
- simple Session and CLI/TUI only as needed to exercise the Seed.

Seed must not add a general Memory or Storage Framework, background or automatic
evolution, an Evolver Plugin, Planner, Browser, Subagents, Scheduler, MCP, complex
Verification, Full Access, remote server infrastructure, or legacy compatibility layers.

## Security validation

Security work is incomplete until relevant real-OS adversarial tests pass.

Seed must eventually test at least:

- traversal, symlink escape, hardlink abuse, rename races, and TOCTOU;
- timeout, cancellation, descendant cleanup, daemonization, and resource quotas;
- default network denial including localhost, DNS, IPv4/IPv6, proxies, and child processes;
- secret leakage through environment, argv, inherited file descriptors, logs, and errors;
- direct OS access attempts, cross-Plugin storage access, and capability escalation;
- stale approvals, digest mismatch, Candidate self-activation, activation crash, and rollback;
- sandbox-backend failure with proof that Host execution does not occur.

Mocks, language-level facades, and command blacklists alone do not prove the boundary.

## Plugin rules

Keep the Plugin ABI small and versioned.

Candidate installation must be content-addressed. Lock Candidate content and Manifest digests
before activation approval. Any content or permission change after approval invalidates it.

Plugin business state belongs to the Plugin. The Kernel may persist it only as a bounded,
opaque Plugin-owned state blob bound to the verified logical Plugin ID. Kernel lifecycle
metadata remains minimal and is limited to what safe install, activate, run, and rollback need.

For fixed Memory evolution replay, the Kernel may return a digest of each temporary post-run
state blob. The untrusted Harness compares A/B digests for the state-mutating sample; the
Kernel does not interpret or persist evaluation state.

Do not add Core database schemas for Memory, Planner, Verifier, Evolver, or other Plugin
business data.

Shadow Evaluation should use historical replay or read-only snapshots. Shadow Candidates must
not receive production writes, mutate active state, produce external side effects, or author
their own authoritative evaluation result.

Rollback means routing future work back to the previous compatible Plugin. Do not claim it
reverses external side effects or repairs already-mutated data.

## Architecture discipline

Prefer the simplest implementation that proves the current requirement.

Before adding a Core abstraction, ask:

- What current problem does it solve?
- Does an existing implementation already solve it?
- Why can it not remain local code or a Plugin concern?
- Does it belong to Intelligence or Authority?
- What executable test proves it is necessary?
- Can the same result be achieved with less code or fewer layers?

If it belongs to Intelligence, prefer a Plugin. If it belongs to Authority, keep it small,
deterministic, and inside the trusted boundary. If it belongs to neither, consider not adding
it.

Do not recreate legacy concepts such as TaskManager, complex lifecycle state machines,
Scheduler, CompletionGate, Recovery control planes, authority-receipt hierarchies, enterprise
audit infrastructure, Gateway/RPC servers, or multi-tenant identity without a new concrete
requirement.

## TCB growth budget

The Seed's upper-level execution model is `Launcher → Kernel → Runner`. Bootstrap, Service,
Broker, Worker, Bridge, Executor, Manager, and Client names are Kernel implementation details
unless they expose distinct authority or durable state. Preserve real process and OS sandbox
boundaries; do not turn implementation labels into additional product concepts.

For every completed change, report:

```text
Production code delta
Trusted code delta
New architecture concepts
New trusted processes
New IPC operations
New persistent state
New dependencies
Removed duplication / abstractions
```

Before adding trusted code, state which invariant it protects, why it cannot live in an
untrusted layer, why an existing trusted primitive cannot serve, and whether a smaller
implementation exists. Do not add a privileged daemon, root service, kernel extension, or
larger authority framework to defend against arbitrary same-UID host processes unless the
threat model is explicitly revised.

## Working rules

Keep changes narrow and cohesive. Prefer deleting unnecessary code over adding compatibility
layers.

Explain every addition to trusted code.

Before editing:

- inspect the surrounding implementation;
- search for equivalent helpers and call sites;
- identify the trust boundary involved;
- check whether the problem is already solved upstream.

While editing:

- keep one source of truth for each behavior;
- reuse existing helpers instead of duplicating them;
- extract shared behavior when duplication becomes real;
- keep public APIs smaller than their implementations;
- avoid unrelated refactors unless they are required to keep the design coherent.

After editing:

- remove dead code and obsolete compatibility paths;
- verify no duplicate implementation was introduced;
- run the relevant tests and static checks;
- add adversarial tests when a trust boundary changed;
- update documentation when a normative decision changed.

Do not introduce extra languages, daemons, databases, framework layers, or background
services merely to mirror legacy Khaos or another project.

## Security freeze

The supported runtime adversaries are Khaos AgentHost, Plugins and Runners.
Ordinary user-owned local signing/installation is the default; root-owned
installation is not required. Owner-authorized source editing with development
tools is normal. Comprehensive external unconfined same-UID tampering is out of
scope and must not be claimed implemented. Preserve all existing OS, XPC,
signature, approval and capability boundaries.

Trusted changes follow `docs/SECURITY_FREEZE.md` and require a fresh security
change declaration and reviewed manifest. Run `python3 tools/check_security_freeze.py`.
Self deployment and verification commands are documented in `docs/SELF_HOSTING.md`.
Independent Code Owner approval remains NOT PROVEN in single-maintainer mode.

## Build and test

The canonical Seed bootstrap validation command is:

```bash
python3 -m unittest discover -s tests -v
```

On macOS, this suite's signed product-bundle test also sends the real
`KernelProduction.xpc` a `workspace.run` frame with a mismatched Runner source
digest and no bookmark. The service must return `invalid_request` before
bookmark handling; this default attack check does not open a Picker.

Build a locally signed macOS Seed app with a stable code-signing identity:

```bash
python3 tools/build_macos_seed.py --output PATH.app --signing-identity ID
```

Use `--keychain PATH` when the identity is in a non-default keychain and
`--python-executable PATH` to select the Python.framework embedded into the
Kernel XPC bundle. The output path must not already exist. This creates a local,
current-architecture app bundle; it does not notarize, install, or establish a
distribution signing or updater policy. Its `--bootstrap-check` mode exercises
the named and anonymous Kernel XPC peer checks without opening the workspace picker.

To bundle the Agent's local CPU model, use a CPU-only llama.cpp build
(`GGML_METAL=OFF`, `LLAMA_OPENSSL=OFF`, `GGML_OPENMP=OFF`) and pass its
`llama-completion` binary as `--llama-cli PATH`, with `--model-file PATH` and
`--model-license PATH`. The model input is bounded to a regular file of at most
24 GiB, with its SHA-256 bound into the signed Agent Host metadata. The builder
bundles non-system dynamic libraries and
their notices into the separately signed Agent Host. Do not use the default
Metal-enabled Homebrew binary: it initializes Metal in the Agent Host despite
CPU layer settings. No model download or remote provider is used at runtime.

Run the opt-in, interactive product writeback acceptance check on macOS with:

```bash
KHAOS_RUN_PRODUCT_WRITEBACK_UI=1 python3 -m unittest discover -s tests \
  -p test_macos_xpc_sandbox.py \
  -k test_seed_app_builds_and_authenticates_its_kernel_service -v
```

It prints a disposable workspace path, opens the signed product app's Picker, and
verifies its single committed file after the success alert is dismissed. Its fixed
Runner must read only `seed-picker-fixture.txt`, list only that scoped entry, and
receive Kernel denials for the unscoped sibling read and listing before process
execution or commit. The ordinary no-argument product path keeps an empty read
scope. The test launches the signed bundle through Launch Services from the outset,
captures its path-free stderr diagnostics, and waits for the app to exit. Selecting
the disposable workspace remains a user action. Do not run it while another Khaos
Seed Picker is waiting for a selection.

Run the opt-in signed-product Plugin lifecycle acceptance check on macOS with:

```bash
KHAOS_RUN_PRODUCT_PLUGIN_LIFECYCLE_UI=1 python3 -m unittest discover -s tests \
  -p test_macos_xpc_sandbox.py \
  -k test_seed_app_builds_and_authenticates_its_kernel_service -v
```

This opens actual package, workspace, and approval dialogs for `activate A → run A →
activate B → run B → rollback → run A`. Follow the printed paths and expected Candidate,
Manifest, scope, and generation bindings. At the stale-generation gate, leave the A run's
generation-1 approval open while activating B, then submit that stale approval when prompted.
The test verifies the exact workspace changes and deep bundle signature in the parent process.
It requires manual Picker and approval actions; do not run it while another Khaos Seed Picker
is waiting for a selection.

Only when the owner explicitly defers the concurrent stale-approval UI check, add
`KHAOS_DEFER_PRODUCT_STALE_APPROVAL_UI=1` to this lifecycle acceptance command.
It runs sequential A → B → rollback → A and prints the stale-approval UI as
`NOT_RUN`; do not report that partial run as complete lifecycle UI acceptance.
The default full UI path and canonical headless stale-generation attacks remain
unchanged.

Run the focused opt-in signed-product Agent-to-Plugin acceptance check on macOS with:

```bash
KHAOS_RUN_PRODUCT_AGENT_PLUGIN_UI=1 python3 -m unittest discover -s tests \
  -p test_macos_xpc_sandbox.py \
  -k test_seed_app_builds_and_authenticates_its_kernel_service -v
```

This admits and activates Candidate A, then runs the Agent's Plugin proposal through
the real Launcher approval, `plugin.run`, Seatbelt Runner, and changeset writeback
path. Cancel the first Agent approval and approve the second. It checks that denial
does not change the workspace and that the bounded Runner result returns to the
Agent as untrusted model input. It requires manual package/workspace Picker and
approval actions; do not run it while another Khaos Seed Picker is waiting for a
selection.

Run the opt-in signed-product Memory Plugin v1 acceptance check on macOS with:

```bash
KHAOS_RUN_PRODUCT_MEMORY_PLUGIN_UI=1 python3 -m unittest discover -s tests \
  -p test_macos_xpc_sandbox.py \
  -k test_seed_app_builds_and_authenticates_its_kernel_service -v
```

This installs the `examples/memory` Candidate, denies one `remember`, then
approves `remember`, `recall`, `forget`, and the final empty `recall` through
separate signed Agent sessions. The Host gets those operations and fields from
the active Candidate's bounded `agent_interface`; its prompt and source contain
no Memory-specific branch. It then installs `examples/interface-probe`, whose
`publish(topic, message)` operation is different from Memory. Its summary includes
hostile prompt-like text; cancel one proposal, then approve one, and verify the
Kernel denial for its unscoped write attempt. The parent also confirms Memory state
is unchanged. No workspace Picker should appear. The test requires manual package,
activation, and invocation approvals; do not run it while another Khaos Seed Picker
is waiting for a selection.

Run the opt-in signed-product Agent-generated Memory evolution acceptance on
macOS with:

```bash
KHAOS_RUN_PRODUCT_MEMORY_EVOLUTION_UI=1 python3 -m unittest discover -s tests \
  -p test_macos_xpc_sandbox.py \
  -k test_seed_app_builds_and_authenticates_its_kernel_service -v
```

It installs A, writes production state, and opens Development Approval before the
signed test model generates and admits a state-only Candidate from A's source.
The isolated replay measures A 3/5 and B 4/5 with no regressions. The test denies
one Activation Approval and checks that A remains active, then repeats the flow
and approves B after reviewing the Proposal, actual scope, dataset, A/B record,
and rollback target. It verifies B uses the same production state, rolls back to
A, and verifies the state again. It needs one package Picker plus manual
development and activation approvals; no workspace Picker opens. Do not run it
while another Khaos Seed Picker is waiting for a selection.

Run the opt-in signed-product BigModel Memory evolution acceptance separately
from the deterministic Model Probe and local-model acceptance. Set
`KHAOS_BIGMODEL_API_KEY` in the test process environment without writing it to
the command line or evidence file. Choose `KHAOS_BIGMODEL_PROVIDER=bigmodel` for
the standard API or `bigmodel-coding-plan` for a Coding Plan key, then run:

```bash
KHAOS_RUN_PRODUCT_BIGMODEL_MEMORY_EVOLUTION_UI=1 \
KHAOS_BIGMODEL_EVIDENCE_PATH="$PWD/bigmodel-memory-evolution.json" \
python3 -m unittest discover -s tests \
  -p test_macos_xpc_sandbox.py \
  -k test_seed_app_builds_and_authenticates_its_kernel_service -v
```

The remote product has no local fallback. Only the untrusted Agent Host receives
the network-client entitlement; macOS does not restrict that entitlement to the
provider hostname. The user feedback, bounded Plugin metadata/results, and
post-Development-Approval baseline source are sent to BigModel. Preserve the
separate deterministic and local-model results; API output does not replace
protocol regression evidence or local-model evidence. The test requires manual
package selection and separate development/activation decisions; do not run it
while another Khaos Seed Picker is waiting for a selection.

Run the deterministic signed-product Bounded Autonomous Coding Loop acceptance
separately from the real BigModel product acceptance:

```bash
KHAOS_RUN_PRODUCT_CODING_LOOP_UI=1 \
KHAOS_CODING_LOOP_EVIDENCE_PATH="$PWD/coding-loop-deterministic.json" \
python3 -m unittest discover -s tests \
  -p test_macos_xpc_sandbox.py \
  -k test_seed_app_builds_and_authenticates_its_kernel_service -v
```

This builds a disposable signed product with the deterministic Agent Host model
probe. It first checks that a malformed local-model response fails closed with
no Runner operation and remains unknown without a Launcher task record, then a
seven-call final response. Offline observer tests separately verify JSON-stage
and repeated Action-shape diagnostics. Its one-task coding fixture includes
hostile README instructions, a scope-denied canary read, a test that prints a
fake success string before failing, an edit, inspection, correction, and
successful retest. It also checks
a successful scoped read followed by a denied write mid-task with no next
approval, Picker cancellation, the 8-call budget, and Agent Host termination
during an approved exit-1 command whose in-scope write is committed while the
command and Host processes are then confirmed exited. Each task receives a
separate bounded terminal summary; the failure probes and seven-call case are marked synthetic and
does not count as model coding success. It requires
manual workspace selection and per-operation decisions; approve only the
displayed scopes in the disposable fixtures. The report does not contain raw
model prompts, command output, API credentials, or workspace file contents.

Run the signed-product coding acceptance with the real local model separately
from the deterministic probe and BigModel test. Point `KHAOS_REAL_MODEL_APP`
at a signed Seed app that bundles the local `llama-cli`, model, and license:

```bash
export KHAOS_REAL_MODEL_APP="$HOME/Applications/Khaos Coding Test.app"
KHAOS_RUN_PRODUCT_REAL_MODEL_CODING_LOOP_UI=1 \
KHAOS_REAL_MODEL_CODING_LOOP_EVIDENCE_PATH="$PWD/coding-loop-local-model.json" \
python3 -m unittest discover -s tests \
  -p test_macos_xpc_sandbox.py \
  -k test_seed_app_builds_and_authenticates_its_kernel_service -v
```

This uses the same disposable failing-test repository and requires manual
workspace selection plus separate review of every proposed operation. The
evidence records the local model mode, actual command return codes, scoped
changeset, and parent-process retest. It does not send project data to a remote
provider. Preserve this report separately from deterministic and BigModel
reports.

To exercise the remote-data refusal in the signed product without transmitting
task content or using an API key, run this separate UI acceptance:

```bash
env -u KHAOS_BIGMODEL_API_KEY KHAOS_RUN_PRODUCT_BIGMODEL_DATA_DENIAL_UI=1 \
KHAOS_BIGMODEL_DATA_DENIAL_EVIDENCE_PATH="$PWD/bigmodel-data-denial.json" \
python3 -m unittest discover -s tests \
  -p test_macos_xpc_sandbox.py \
  -k test_seed_app_builds_and_authenticates_its_kernel_service -v
```

Review the named BigModel endpoint and data categories, then choose `Do not
send`. This route has no API key and verifies the Launcher denies the task
before an Agent Host turn, workspace Picker, or shell approval. It is refusal
evidence only; it does not establish successful remote-model coding quality.

Run the real BigModel signed-product coding acceptance separately. Set the API
key in the test process environment without writing the value to the command
line or evidence file, choose the matching provider, and run:

```bash
read -s "KHAOS_BIGMODEL_API_KEY?BigModel API key: "
export KHAOS_BIGMODEL_API_KEY
KHAOS_RUN_PRODUCT_BIGMODEL_CODING_LOOP_UI=1 \
KHAOS_BIGMODEL_PROVIDER=bigmodel \
KHAOS_BIGMODEL_CODING_LOOP_EVIDENCE_PATH="$PWD/coding-loop-bigmodel.json" \
python3 -m unittest discover -s tests \
  -p test_macos_xpc_sandbox.py \
  -k test_seed_app_builds_and_authenticates_its_kernel_service -v
```

Use `KHAOS_BIGMODEL_PROVIDER=bigmodel-coding-plan` for a Coding Plan key. This
build has no local-model fallback. Before sending the task, the signed Launcher
shows a separate prompt naming BigModel, its endpoint, and the data categories
that may be sent: task text, active Plugin metadata, proposed argv and requested
paths, scoped file/listing text, command return codes, changed-path lists, and
bounded stdout/stderr. The user must approve that data flow and then review each
shell operation independently. Cancel the data prompt to verify that no task
or workspace content is sent. Preserve its evidence separately from the
deterministic probe; neither result substitutes for the other.

The canonical suite includes headless product-bundle source-digest, duplicate-field,
over-depth JSON, malformed/over-budget scope, and caller-authority attacks against
the real Kernel XPC service. Scope attacks use a valid Runner source digest and no
bookmark; each must receive `invalid_request` before bookmark handling. Keep selected-
workspace interaction consolidated in the documented signed-product acceptance checks
above;
lower-level real-OS Runner and cancellation attacks remain in the canonical suite.

Discover any future build, lint, formatting, packaging, or release commands from repository
files; do not guess them.

Before finishing a change, run every relevant repository-provided test, lint, formatting, and
security check. Add or update tests for changed behavior. For security-boundary changes,
include adversarial tests.

Report any checks that could not be run and why.

Never claim a security property that was not exercised by executable evidence.

## Documentation

Repository documentation is the system of record. Update the relevant design document in the
same change whenever a normative security or architecture decision changes.

Expected focused documents include:

- `docs/Khaos vNext 架构设计文档.md` — architecture constitution;
- `docs/KERNEL_ABI.md` — trusted wire/API contract;
- `docs/SEED_THREAT_MODEL.md` — Seed threat model and attack cases;
- `SECURITY.md` — supported guarantees and limitations;
- `README.md` — human-facing overview and setup.

`AGENTS.md`, the architecture design, and the current contract sections of `docs/KERNEL_ABI.md`
are normative. `docs/SEED_THREAT_MODEL.md` records enforcement evidence and limitations;
dated run entries are historical evidence. `docs/SEED_BACKEND_RESEARCH.md` is a research log,
not an implementation contract. Keep `README.md` current for users, but do not use it to
override a normative security contract.

## Definition of done

Implementation, tests, and documentation must agree.

For security-sensitive work, "it works" is not enough: the prohibited path must also fail
under the real enforcement mechanism.

A change is not complete if it introduces avoidable duplicate logic, parallel implementations
of the same behavior, dead compatibility code, or an unnecessary new abstraction.

For the current phase, prefer a smaller proven Seed over a broader unproven platform.
