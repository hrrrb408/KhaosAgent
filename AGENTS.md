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
- minimal Agent Loop and model adapter after the security path works;
- simple Session and CLI/TUI only as needed to exercise the Seed.

Seed must not add Memory, Planner, Browser, Subagents, Scheduler, MCP, complex Verification,
self-evolution, Full Access, remote server infrastructure, or legacy compatibility layers.

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

Plugin business state belongs to the Plugin. Core may persist only minimal trusted activation
metadata required for safe install, activate, and rollback behavior.

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
`--model-license PATH`. The builder bundles non-system dynamic libraries and
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

The canonical suite includes headless product-bundle source-digest, duplicate-field,
over-depth JSON, malformed/over-budget scope, and caller-authority attacks against
the real Kernel XPC service. Scope attacks use a valid Runner source digest and no
bookmark; each must receive `invalid_request` before bookmark handling. Keep selected-
workspace interaction consolidated in the product writeback acceptance above;
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

## Definition of done

Implementation, tests, and documentation must agree.

For security-sensitive work, "it works" is not enough: the prohibited path must also fail
under the real enforcement mechanism.

A change is not complete if it introduces avoidable duplicate logic, parallel implementations
of the same behavior, dead compatibility code, or an unnecessary new abstraction.

For the current phase, prefer a smaller proven Seed over a broader unproven platform.
