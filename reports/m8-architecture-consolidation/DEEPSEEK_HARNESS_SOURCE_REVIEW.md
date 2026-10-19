# M8.7 DeepSeek Harness Source Review

Reviewed 2026-10-19, after evidence-based cleanup and the preliminary full regression.
This is static source research. No upstream install script, package manager, runtime,
model, benchmark or upstream test suite was executed. Nothing was vendored into Khaos.
Khaos's own executable regression is reported separately.

## Immutable source set and provenance

| Alias | Repository | Exact commit / license | Reviewed scope |
|---|---|---|---|
| D | [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness/tree/687f282e8625c6b8d11ff58211a90524be2e4317) | `687f282e8625c6b8d11ff58211a90524be2e4317`; MIT (DeepSeek); vendored Cordis MIT (Shigma) | Cordis + Loader, loop, tools, Session, JSONL, projection, context/compaction, LLM, profiles, bundles |
| C | [Codex](https://github.com/openai/codex/tree/89461ea6833832b0551ce24ee32205824d5c108d) | `89461ea6833832b0551ce24ee32205824d5c108d`; Apache-2.0 | task lifecycle, cancellation, approval/execution orchestration |
| P | [Pi](https://github.com/badlogic/pi-mono/tree/1402973a9dbe8c627341e04c9744c54953e285ca) | `1402973a9dbe8c627341e04c9744c54953e285ca`; MIT | bounded scope of loop hooks, tool dispatch and Session projection/branches |
| H | [Hermes](https://github.com/NousResearch/hermes-agent/tree/67481b6f37615e58f1434ba6a1528e4c6e9b754c) | `67481b6f37615e58f1434ba6a1528e4c6e9b754c`; MIT | tool registry, Skills catalog, curated Memory entry |
| O | [OpenClaw](https://github.com/openclaw/openclaw/tree/af1e1fe8d46549a344dffef1f2f6d710a714f0a2) | `af1e1fe8d46549a344dffef1f2f6d710a714f0a2`; MIT | plugin tool contracts, ownership, registry retirement |

D was fetched with `git clone --depth 1`; `git rev-parse HEAD` fixed the commit above.
Its commit date is 2026-10-17T15:22:43+08:00; root version `0.2.1-rc.2`.
Other SHAs came from GitHub's commit API, followed by exact-SHA Git tree inspection
and retrieval of the named files from `raw.githubusercontent.com/<repo>/<sha>/...`.
All four trees reported `truncated: false`. Sources were read outside the Khaos tree.
The primary README still labels the project a developer preview; `SAFETY.md` says
there has been no security audit and it must not be the sole control for untrusted
workloads. Those limits also constrain this review: activity and tests are not an audit.

## 1. Cordis: registration, services, dependencies and cleanup

The relevant Cordis is **the vendored fork at D**, not an assumed npm/latest version.
`vendor/cordis/package.json` declares `@deepseek-ai/cordis` 4.0.5. Its source is pinned
by the same Git SHA as the Harness. The Loader is vendored alongside it (1.0.6).

| Question | Actual source / mechanism | Khaos applicability |
|---|---|---|
| Register a Plugin | [`vendor/cordis/src/registry.ts`](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/vendor/cordis/src/registry.ts), `RegistryService.plugin`: normalize function/class/object `apply`, key runtime by callback, create one Fiber per application | Separate declaration from live instance ownership in untrusted coordination; callback identity is not Candidate content identity |
| Load executable code | `vendor/loader/src/config/entry.ts:223`, `_init`: import module namespace through parent tree, unwrap exports, patch child context, call registry | Loader imports are ordinary Host code execution. Never load such modules into trusted Kernel/Launcher |
| Unload | `vendor/cordis/src/fiber.ts`, constructor-owned `dispose`, `_unload`, `await` | Join cleanup and stop accepting new work before release. Khaos Kernel kill/cleanup remains authoritative |
| Dependencies | `registry.ts` `Inject.resolve` normalizes array/object/inherited metadata; `fiber.ts:598–692` `_checkImpl`, `_refresh`, `_setEpoch` bind required service implementation IDs to a lifecycle epoch | Availability drives loading, not YAML row order. Missing/replaced service stops/restarts dependents; not permission granting |
| Provide Service | `service.ts` constructor calls `ctx.reflect.provide`; `reflect.ts:277` stores implementation under a scope symbol, rejects duplicate provider, registers cleanup and notifies dependents | Service definition/provider/consumer split can remain a small untrusted interface; no universal Kernel object |
| Subscribe Events | `events.ts` typed `Context` augmentation and `on/once/emit/parallel/serial/bail/waterfall` dispatch | Event payload type and dependency realm are useful organization, not data-read authorization |
| Revoke effects | `fiber.ts:417` `effect` owns disposers; nested collected effects unwind in reverse order, repeat disposal joins/no-ops; `_unload` awaits all owned cleanup work | Borrow disposer ownership and stale-epoch handling for future Host handlers; never claim it reverses external effects |
| Compose config | `context.ts` `extend/isolate/intercept`, `service.ts` resolves ancestor intercept config; Fiber validates config via Standard Schema before start | Config cannot alter trusted scope, expiry, approved digest or capability ceiling |
| Replace capability | Isolated service realm + required implementation epoch change, registry lifetime and config update | Intelligence replacement may be routing; verified Candidate admission/activation is still separate |
| Failure cleanup | Fiber startup catches failure, marks inactive, unloads effects, logs cleanup errors; async setup/disposal barriers and epochs avoid late activation | Exception handling is cooperative, not process crash containment or hard cancellation |

`Context` is a JavaScript Proxy over a shared service graph; `isolate` changes service
lookup labels, not address spaces, OS access or secret availability. `events.ts` permits
`global` listeners to bypass contextual filtering. Khaos cannot interpret typed events
or a Cordis isolate realm as a sandbox or broadcast raw Session/Plugin data to it.
The root effect owner, service unregister notification and dependency reload form one
lifecycle; adding parallel Manager/Registry abstractions in Khaos would duplicate it.

## 2. Why the Agent Loop is replaceable

[`packages/core/agent-loop/src/index.ts`](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/core/agent-loop/src/index.ts)
defines `AgentLoop extends Service implements AgentFactory` with explicit dependencies
on agents, sessions, llm, tools, systemPrompt and sessionProjections. It provides
`agentLoop`; it is not baked into Cordis. `FactoryOwnership` tracks create/resume work,
live agents and teardown. Agent teardown stops the machine, unregisters it and unwinds
its scoped resources; `dispose()` stops admission and joins owned work. Bundle config
selects the implementation supplying that service.

The actual driver is [`agent.ts`](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/core/agent-loop/src/agent.ts),
`ReactLoopAgent`, not merely a loop diagram:

1. `preStep` claims inbox input, assembles prompt/context, runs the `agent/pre-step`
   waterfall and rechecks the AbortSignal. A rejection can close a turn without a step.
2. `turn` records start, runs steps and always settles step/end and turn/end. On step
   failure, `ToolCallRecovery` supplies missing results so replay does not leave open
   tool calls. Abort cause is distinct from ordinary structured error.
3. `prepareRequest` applies the `agent/request` waterfall and resolves a bound provider
   via `llm.prepareCall`. Config and request content are snapshotted/frozen. Retrying
   a model call does not mean repeating prompt assembly or implicitly approving a tool.
4. The step owns stream settlement and tool calls. Finalization records one coherent
   durable result; live stream/UI state is not a durable success receipt.
5. `agent/turn-stopping` may add next-step work; otherwise inbox state determines
   whether the driver becomes idle. Interrupt and shutdown use AbortControllers and
   ownership drains. This is cooperative Host behavior, not Khaos Kernel cancellation.

`tool-calls.ts` implements exclusive barriers and a bounded parallel pool, reclassifies
unstarted calls against live registration, commits outcomes in model order, and drains
started calls on abort/failure. This is useful reference behavior but **not needed in
current serial eight-proposal Seed**, and is not adopted as a new Scheduler.
Relevant source tests inspected by path: `tests/cancel.spec.ts`, `shutdown-drain.spec.ts`,
`request-freeze.spec.ts`, `tool-calls.spec.ts`, `resume.spec.ts` under the same package.
They were not executed here.

Khaos can first expose its existing action/reply seam inside the untrusted Host and
prove an alternative loop against the same strict Launcher protocol. Launcher must
retain independent proposal/time/result budgets, frozen reviewed invocation, user
consent, scope and terminal status. Current state-only Candidate ABI is not sufficient
to install a whole Host loop; that future admission change needs its own security task.
Replacing loop intelligence must never replace the Launcher or Kernel authority.

## 3. Tool registry and execution pipeline

[`packages/core/tools/src/index.ts`](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/core/tools/src/index.ts)
contains the registry and executable pipeline, with schema support in `schema.ts` and
`json-schema.ts`. `ToolRuntime.register` validates declared output schema/rendering,
reserved names and timeout values, inserts into scope layers and returns an owned
disposer. Discovery/prompt assembly reads visible tool declarations; scoped tools can
shadow global definitions while duplicates within a layer fail.

`prepareExecution` runs extensible pre-execute policy, handles ask/deny/cancel, then
monotonic guards that can deny but cannot force an allow. Missing approval support
for ask denies. It snapshots identity/arguments and rechecks caller cancellation.
Around-dispatch wrappers can replace signals, but the caller's original signal is
fused back before dispatch. The body is **`await tool.execute(exec.arguments, exec)`**
in the Host process (`dispatchToolBody`, around line 1589). Results are normalized,
validated against declared output, post-processed, deep-frozen and emitted. The
source contract explicitly acknowledges that same-process code cannot be hard-killed.

Borrow schema/discovery/result separation and exact registration ownership. Do not
adopt Host policy events as trusted approvals. In Khaos a tool must produce a bounded
capability proposal, then pass **Trusted Launcher approval → Kernel → sandboxed Runner**.
Tool display names, schemas, registry enablement and Profile configuration grant zero
authority. Model result text cannot replace original command return codes or Kernel
commit outcomes. Tool removal during a turn and stale callbacks need tests before
any dynamic registry is introduced.

## 4. Session, context, replay, resume and branching

- [`packages/core/session/src/index.ts`](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/core/session/src/index.ts):
  `Session` owns contiguous immutable events and a model-visible surface.
  `deriveMessages` incrementally projects surface nodes, rebuilding on content
  generation/replacement; turn boundaries without a surface marker are not messages.
  `registerMessageProjection` contributes pure interpreters with lifetime ownership.
- `session/src/surface.ts` and `fork.ts`: a fork copies an exact inclusive event
  prefix, records inherited cutoff and appends synthetic closures for open tails.
  This is conversation branching, not rollback of OS effects or live Plugin state.
- `packages/session/session-projection/src/index.ts`: registered pure synchronous
  `init/apply` folds drive per-session state and optional cropped client views.
  The registry owns event subscriptions/watermarks; domains own only the computation.
- `packages/session/session-persistence-jsonl/src/index.ts`, `format.ts`, `storage.ts`,
  `generation.ts`: handle-based create/open, contiguous event validation and immutable
  version-named generations; migration publishes a verified successor instead of
  silently overwriting source history. Compression, leases and workers are separate
  implementation costs, not requirements for Khaos's current in-memory Session.
- Agent Loop `resume` restores a validated session and ownership before creating a
  live driver. `SessionPreparation` and repair distinguish interrupted histories.
- `packages/core/system-prompt/src/index.ts`: ordered section/context/tool/variable
  providers feed prompt assembly. `compaction/compaction-basic/src/index.ts` attaches
  at pre-step and request-error events, delegates summarization to `summarizer.ts`,
  and records durable surface replacements. `runtime-context.ts` handles per-step
  runtime context admission.

The valuable idea is one event source with pure projections and explicit branch cuts,
not a second mutable conversation cache. Khaos already has bounded task history and
separate Kernel lifecycle state. Durable sessions/compaction are future untrusted
capabilities; they must exclude secrets and obey model recipient data scope. Upstream
model-request reconstructability must not imply permission to log raw workspace or
credentials. Do not replace opaque Memory state with a Session/Core business database.

## 5. Model adapters

[`packages/llm/llm/src/index.ts`](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/llm/llm/src/index.ts)
separates `LlmAdapter` from `LlmRuntime`. `registerAdapter` owns provider routes via an
effect; a disposed registration cannot replace routes. `prepareCall` captures the
adapter, resolves capabilities/config, freezes the request-facing result and returns
a bound dispatch, preventing a later registry change from silently changing that call.

`packages/llm/llm-deepseek/src/host.ts` constructs an adapter and registers it with
`ctx.llm`; `adapter.ts` separates provider protocol serialization/SSE translation,
credentials/connection callbacks, file/image handling, idle watchdog and stream abort.
The API-key plugin is a separate package. Provider replacement does not require Cordis
core changes. This is richer than Khaos's three fixed adapters, but much of its image,
replay, telemetry and discovery machinery is unnecessary for Seed.

Recommendation: design a minimal untrusted action/typed-error boundary using existing
Swift and strict JSON. Keep remote data consent and recipient identity trusted;
never port upstream attachment/files/credential access or transparent retries without
an explicit scope. Current BigModel/local/Apple behavior stays unchanged in M8.7.

## 6. Profiles, bundles, config and replacement

`packages/boot/app-boot/src/profile.ts` implements manifest/profile discovery and ordered
bundle patches; `composeEntries` uses the same entry patch engine as boot.
`profile-plugins.ts` reconciles package dependencies and enabled bundles. A bundle
manifest declares patch files; a Profile lists ordered bundles plus a user patch.
`packages/bundle/base/cordis.patch.yml` contains actual model, tools, Session, sandbox,
approval and Agent service rows. Whole-row config replacement and later overlays
permit replacing service providers without editing the framework. Runtime activation
still follows service availability, not row order.

`vendor/loader/src/config/entry.ts` performs actual module import/registration. Dynamic
config can contain executable `!!js` expressions; hot reload is supported in selected
profiles. Those are not safe trusted configuration inputs in Khaos. Coding/Research/
Personal Assistant/Memory/Self-Evolution profiles could eventually compose untrusted
capabilities, but their names and enablement must never grant scopes or activation.
No Profile, Bundle, loader, HMR or generic dependency framework is implemented here.

## 7. Trust-model comparison and reuse boundary

| Dimension | D source finding | Khaos decision |
|---|---|---|
| Plugin runtime | Cordis callback/Fiber, service realms, ordinary module imports | REUSE DESIGN for untrusted lifetime coordination; keep separate Runner admission |
| Loop | Ordinary `AgentLoop` provider using narrow declared services | REUSE DESIGN; untrusted replaceability only after bounded seam tests |
| Tool registry | Host functions, composable pre/guard/post policy | Reuse schema/ownership concepts; do not trust Host policy as permission |
| Session/context | Event projection, plugins and persistence providers | Future intelligence/data concern with scoped redacted views |
| Model | Adapter registry and captured per-call route | Future untrusted adapter seam; keep trusted remote-data consent |
| Sandbox | D has sandbox/policy/subprocess providers, but plugin composition can change Host behavior | KEEP Khaos native identity, OS enforcement, exact scopes and fail-closed Kernel |
| Runtime self-modification | Profile patches, dynamic module loading, HMR/plugin management | May change untrusted code only; never replace signed trusted enforcement |
| Evolution admission | No equivalent of Khaos exact Candidate + Manifest + scope + generation + expiry approval was established by the reviewed loop/registry paths | KEEP Khaos admission/evaluation/activation; do not claim D lacks all evaluation mechanisms outside reviewed scope |
| Reversible effects | Unregister callbacks/services and await owned tasks | Useful cleanup; cannot reverse an executed command or mutate production state back |

Forbidden transfers: no Kernel internal object to Plugins; no Host-supplied scope or
approval authority; no bypass of full changeset validation; no replaceable trusted
Kernel through config; no unadmitted high-privilege Plugin; no raw Session/global
secret broadcast. Use upstream process utilities only as reference, never as a silent
Host execution fallback. The presence of upstream sandbox features is not evidence
that its trust model equals Khaos's independent fixed security boundary.

## 8. Focused supplementary source research

Each row refers to the exact SHA in the immutable-source table, not a floating branch.
These are narrow source findings, not generic product rankings or claims of testing.

| Source | Actual implementation read | Useful lesson / excluded cost |
|---|---|---|
| C / Apache-2.0 | `codex-rs/core/src/tasks/mod.rs` (`SessionTask`, task-owned cancellation tokens, uniform finish), `tasks/lifecycle.rs` (start/stop/abort/error contributors), `tools/orchestrator.rs` (approval, sandbox selection and separately reviewed retry) | Distinguish original outcome, lifecycle settlement and new retry approval. Do not copy Rust task/runtime/permission stack or unsandboxed escalation options into Seed. Khaos's original Kernel result remains authoritative. |
| P / MIT | `packages/agent/src/agent-loop.ts` (`runLoop`, `prepareRequest`, `finishTurn`, schema-validated tool dispatch, truncated-call refusal and AbortSignal); `packages/coding-agent/src/core/session-manager.ts` (`buildSessionProjection`, `buildSessionContext`, append-only parent/leaf history and compaction) | Smaller loop-policy seams are a better first comparison than importing D's whole service graph. Borrow event/context separation and exact branch ancestry; tools are ordinary functions and need Khaos IPC adaptation. |
| H / MIT | `tools/registry.py` (`register`, `deregister`, `dispatch`, handler calls and scoped overlays), `tools/skills_tool.py` (`_skill_catalog`, tiered discovery, cache copies and frontmatter), `tools/memory_tool.py` (`memory_tool`, `_memory_tool`, bounded validation and curated writes) | Reuse Skills discovery as a future design; consider tiny pure Python helpers only after dependency/license tests. Do not replace `remember/recall/forget` or `khaos-memory-v1` with Hermes user-profile/add/patch/remove store, Host writes or its opt-in approval gates. |
| O / MIT | `src/plugins/loader.ts` is a facade; real researched behavior is `registry-registrars-tools-hooks.ts` (`registerTool`: declared contract names/context version), `registry-lifecycle.ts` (owner/borrower distinction, revoke admission and retirement cleanup) | Explicit ownership and stale-invocation rejection are useful. The Gateway registry, loader caches and custody graph are far larger than one Seed slot; do not reproduce them. A registration contract is not an OS capability. |

## 9. License, dependency and maintenance cost

At D, root and selected packages declare MIT; Cordis retains Shigma's MIT notice.
Any future copied substantial source needs the relevant notices and provenance;
root MIT does not erase vendored/third-party obligations (`THIRD_PARTY_NOTICES.md`).
C uses Apache-2.0, so any future source adoption must review notices and modifications.
All other sampled root licenses are MIT. **No copied source or dependency is added now.**

Measured package metadata at D (runtime `dependencies` / peer entries, not a flattened
transitive install count): Cordis 2/2 (optional loader/include peers), Loader 2/2,
Agent Loop 4/9, Tools 3/11, Session 3/2, JSONL 8/3, DeepSeek adapter 5/11, app-boot 8/6.
Examples include `@standard-schema/spec`, CosmoKit, Schemastery, zod, scope/agent/session
services, Typert/native infrastructure, p-limit and profile module resolution.
The source workspace has 342 `packages/*/*/package.json` files. Root declares Node
`^22.19.0 || >=24.0.0` and pnpm 11.28.5. These are actual integration/build/upgrade
costs, not proposed Khaos dependencies. Directly using this TypeScript graph would
add a language/runtime and package ABI maintenance burden to existing Swift/Python.
No transitive vulnerability audit, compatibility run or benchmark is claimed.

Concrete recommendation: KEEP Khaos security/lifecycle primitives; REUSE DESIGN for
untrusted loop, model, event projection, tool schema and lifetime ownership. REUSE
SOURCE remains a gated future possibility for small isolated pure helpers; none was
proven lower-cost than design reuse in this language/runtime boundary. REPLACE is
not justified for any current enforcement component or working Memory Plugin. Do not
force every decision category to have an adoption merely to fill a matrix.

The actionable component matrix, adoption gates, cost/reduction estimates and ordered
tasks are in [PLUGIN_ARCHITECTURE_MATRIX.md](PLUGIN_ARCHITECTURE_MATRIX.md).
