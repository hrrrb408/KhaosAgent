# M8.7 Plugin Architecture Matrix

This is a roadmap, not an implemented Plugin Graph or a change to normative authority.
The reviewed code baseline is PR #39 `dee62b20dc1acbd64b009d47c29dc3f42ba9fdde`.
Pinned upstream source and decision evidence are in
[DEEPSEEK_HARNESS_SOURCE_REVIEW.md](DEEPSEEK_HARNESS_SOURCE_REVIEW.md).

## Current ownership and target

Status vocabulary is literal: `IMPLEMENTED_AS_PLUGIN`, `PARTIALLY_PLUGINIZED`,
`HARDCODED`, `NOT_IMPLEMENTED`. Separate intelligence from trusted enforcement
before interpreting any target below.

| Component | Current implementation | Target owner | Current status | Decision / priority |
|---|---|---|---|---|
| Security Kernel | Python Kernel + native XPC service | Immutable Trusted Core | HARDCODED (required authority) | KEEP / P0 |
| Sandbox / scope / snapshot / changeset | `macos_seatbelt`, snapshot/changes/broker | Trusted Security Boundary | HARDCODED (required authority) | KEEP / P0 |
| Approval / trusted admission | Launcher UI + `plugin_lifecycle` | Trusted Security Boundary | HARDCODED (required authority) | KEEP / P0 |
| Required approval UI | Picker, `TrustedEditApproval`, immutable command handles | Trusted Security Boundary | HARDCODED (required authority) | KEEP / P0 |
| Plugin loading / lifecycle coordination | Candidate store + single primary slot + Runner | Minimal Harness / Plugin Runtime; admission remains trusted | PARTIALLY_PLUGINIZED | KEEP enforcement, REUSE DESIGN coordination / P1 |
| Agent Loop | `AgentHostSession.process`, Launcher continuation enforcement | Capability Plugin for intelligence | HARDCODED | REUSE DESIGN / P1 |
| Model Adapter | Apple/llama/BigModel classes in `AgentHost.swift` | Capability Plugin | HARDCODED | REUSE DESIGN / P1 |
| Coding tools | Host list/shell proposal + fixed reviewed Runner | Capability Plugin; execution stays Kernel | PARTIALLY_PLUGINIZED (Runner source path exists, Host coding producer fixed) | REUSE DESIGN / P1 after signed gates |
| Memory | `examples/memory` and Candidate B, bounded opaque state | Capability Plugin | IMPLEMENTED_AS_PLUGIN | KEEP / P0; REUSE DESIGN retrieval strategies only later |
| Context management | `AgentHistoryEntry`, `boundTaskHistory`, fixed prompts | Capability Plugin | HARDCODED (bounded history only) | REUSE DESIGN / P2 |
| Session strategy | XPC-session state, bounded in-memory history | Capability Plugin | HARDCODED; durable resume/branching NOT_IMPLEMENTED | REUSE DESIGN / P2 |
| Skills | None in production runtime | Capability Plugin | NOT_IMPLEMENTED | REUSE DESIGN / P3; explicit new scope required |
| Planner | No independent Planner | Capability Plugin | NOT_IMPLEMENTED | KEEP absent / P3; explicit new scope required |
| Evolution strategy | Explicit-feedback Memory Candidate generation, fixed A/B, approval/rollback | Capability Plugin for proposal/generation/scoring; trusted activation stays fixed | PARTIALLY_PLUGINIZED | KEEP working path, REUSE DESIGN pure scoring / P2 |
| UI extensions | No general extension mechanism | Capability Plugin | NOT_IMPLEMENTED | KEEP absent / P3 |
| Profiles / Bundles | Fixed build-time provider and single slot | Minimal Harness configuration, never authority grants | NOT_IMPLEMENTED | REUSE DESIGN / P3; no framework now |

## Migration tasks in dependency order

These are separately reviewable future tasks, not authorization to start the blocked
production Structured Edit integration. No implementation/LOC reduction is claimed now.

1. **Close inherited signed gates before touching production edit/cancellation.**
   Preserve B32/B34/B39 and exact original Kernel terminal result binding. Obtain real
   signed evidence and explicit Owner Review. Do not reuse M8.7 headless checks as L4.
2. **Separate a model response contract inside the untrusted Host.** Keep Apple,
   llama and remote model adapters distinct implementations behind the smallest actual
   common behavior. Begin with action input/output + typed failures and bounded history;
   Candidate generation is a separate operation, not a universal adapter method. Keep
   remote-data recipient/consent/key handling trusted and unchanged. Validate existing
   decoder categories, one correction, context budgets, no provider fallback, canary
   redaction and no network on refusal. No new Kernel fields/operations.
3. **Make one alternative Agent Loop injectable at the untrusted boundary.** Reuse
   existing strict proposal/reply messages; first prove two deterministic intelligence
   strategies against the same Launcher fixture. A runtime plugin loader is not needed
   to prove the seam. Kernel/Launcher still owns every budget, approval, scope, cancel
   and terminal record. Fail a malformed proposal, Host death, repeated result, denied
   action and late reply through existing real product boundaries. Only then design
   bounded Candidate admission for a replaceable Host capability as a separate change;
   current state-only Plugin ABI cannot load a whole Harness by declaration alone.
4. **Extract pure fixed Memory scoring/history policy from trusted compilation only
   after a dedicated security review.** Never move Candidate/source/data digests,
   generation/expiry, approval decision or temporary state isolation with it. Compare
   byte-exact replay records and state continuity, forge a scorer success and verify
   that it cannot activate anything. Keep logical ID `memory`, three operations and
   opaque `khaos-memory-v1`. A new generic memory schema/database is unnecessary.
5. **Prototype Session event projection as untrusted, scoped data.** Reuse append-only
   event projection and branch ancestry designs, not an upstream raw workspace log.
   First define secret exclusion, recipient consent, bounded replay and compatibility
   tests on synthetic fixtures. Do not introduce persistent state without a new task.
6. **Evaluate tooling/profile/skills composition only for a concrete second consumer.**
   Discovery/enablement names and service identifiers must not become capability grants.
   Register/dispose local handlers in the untrusted layer, convert all effects to
   existing reviewed requests. Reject direct Host `fs`, `bash`, network or arbitrary
   extension code in trusted processes. Future tests: duplicate registration, unload
   during turn, dependency removal, stale callback, cross-Plugin data access, forged
   profile approval and rollback routing. No Cordis dependency until a bounded spike
   justifies its runtime and maintenance cost.

All adoption requires pinned source/license review and tests for the Khaos boundary.
A provider package or registry may lower intelligence maintenance cost but cannot
replace Kernel policy, secure native UI, peer identity or OS enforcement.

## Source choice, cost and next action for each capability

Pins (the aliases below always mean these exact commits, not HEAD):

- D = DeepSeek Harness `687f282e8625c6b8d11ff58211a90524be2e4317`, MIT;
  `vendor/cordis/LICENSE` also requires Shigma's MIT notice for that source.
- C = Codex `89461ea6833832b0551ce24ee32205824d5c108d`, Apache-2.0.
- P = Pi `1402973a9dbe8c627341e04c9744c54953e285ca`, MIT.
- H = Hermes `67481b6f37615e58f1434ba6a1528e4c6e9b754c`, MIT.
- O = OpenClaw `af1e1fe8d46549a344dffef1f2f6d710a714f0a2`, MIT.

The [source review](DEEPSEEK_HARNESS_SOURCE_REVIEW.md) links all five immutable trees.
Paths in the upstream column are repository-relative to that pin. Maintenance cost
is qualitative integration effort: low = existing local behavior; medium = small
untrusted seam and regression suite; high = new runtime/dependency/data/lifecycle
surface. Expected code reduction is **0 in M8.7** except the actual -31 shipped LOC cleanup (-1 additional development-only LOC);
future reductions are NOT_ESTIMATED until a scoped spike measures equivalent code.
No speculative LOC savings or new dependency commitment is made.

| Capability / current Khaos implementation | Relevant upstream source + pin/license | Decision and security impact | Expected reduction / maintenance | Next action / priority |
|---|---|---|---|---|
| Kernel / `worker`, native XPC, Seatbelt | C `codex-rs/core/src/tools/orchestrator.rs` (Apache-2.0); D `packages/sandbox/sandbox-policy/src/index.ts` (MIT, composition reference only) | KEEP; upstream policy/retry is not trusted Khaos admission; no authority migration | Trusted runtime -13 LOC now (wrapper + two imports); low to retain, high to replace | Preserve signed identity, scopes, parser, cleanup / P0 |
| Approval/cancellation / Launcher + command handle + edit preview | C `tasks/lifecycle.rs`, `tasks/mod.rs`, `tools/orchestrator.rs` (Apache-2.0); D `packages/core/agent-loop/src/agent.ts` (MIT) | KEEP trusted implementation, REUSE DESIGN outcome/ownership distinctions; Host abort is not Kernel commit result | 0; low to keep, high for security change | Close B32/B34/B39 with actual signed evidence, separate task / P0 |
| Plugin coordination / single slot Candidate lifecycle + Runner | D `vendor/cordis/src/{registry,fiber,reflect}.ts`, `vendor/loader/src/config/entry.ts` (MIT); O `src/plugins/registry-lifecycle.ts` (MIT) | KEEP Candidate authority; REUSE DESIGN effect ownership/stale callbacks in untrusted layer | 0; medium seam, high full loader/custody graph | Prove one concrete second consumer before registry abstraction / P1 |
| Agent Loop / fixed `AgentHostSession.process` | P `packages/agent/src/agent-loop.ts` (MIT); D `packages/core/agent-loop/src/{index,agent}.ts` (MIT) | REUSE DESIGN; never move Launcher budget, continuation/approval or terminal truth to a loop | 0; medium local seam, high Cordis runtime import | Two deterministic Host strategies through existing wire contract, denial/late-reply/Host-death attacks / P1 |
| Model adapter / Apple, llama, BigModel fixed classes | D `packages/llm/llm/src/index.ts`, `packages/llm/llm-deepseek/src/{host,adapter}.ts` (MIT) | REUSE DESIGN bound call + adapter contract; remote recipient/data consent stays trusted | Untrusted mapper -17 LOC now; medium seam, high complete model graph | Typed output/errors and one-correction equivalence, no fallback or consent change / P1 |
| Coding tool / list/shell + fixed Runner | D `packages/core/tools/src/{index,schema,json-schema}.ts` (MIT); P agent-loop tool hooks (MIT) | REUSE DESIGN discovery/schema/result separation; cannot call Host execute functions directly for privileged effects | 0; medium proposal seam, high full registry | Existing Launcher → Kernel → Runner, per-call exact scope; defer Structured Edit to Gate A / P1 |
| Memory / installed `examples/memory` Candidate, opaque state | H `tools/memory_tool.py` (MIT); D Session projections (MIT, retrieval design only) | KEEP working `remember/recall/forget` and `khaos-memory-v1`; reject Hermes replacement store/schema | 0; low retain, high migration | No new Memory framework; consider a future algorithm-only Candidate with existing A/B and rollback / P0 |
| Context / fixed `boundTaskHistory`, prompts | D `packages/core/system-prompt/src/index.ts`, `packages/compaction/compaction-basic/src/{index,summarizer}.ts` (MIT); P session-manager (MIT) | REUSE DESIGN pure projection; no raw workspace/secret input expansion or new model recipient | 0; medium pure policy, high LLM compaction/persistence | First compare synthetic bounded histories; pinned original task/observations and control flags must survive / P2 |
| Session / in-memory XPC task history | D `packages/core/session/src/{index,fork,surface}.ts`, `packages/session/session-persistence-jsonl/src/{index,generation}.ts` (MIT); P `packages/coding-agent/src/core/session-manager.ts` (MIT) | REUSE DESIGN event lineage/branch cuts; don't equate replay with authority or state rollback | 0; high persistent data/schema maintenance | New scope required before durable storage; redact and bound event views, synthetic interrupted-tail replay tests / P2 |
| Evolution strategy / Host Candidate generation + fixed Memory replay | D AgentLoop/service replacement and pure projection (MIT); existing Khaos Candidate lifecycle is stronger fit | KEEP admission/activation; REUSE DESIGN pure scoring extraction only; D registry is not equivalent digest-bound approval | 0; medium pure scorer, high approval change | Separate security review, forged-score denial and production-state continuity; no automatic evolution / P2 |
| Skills / absent | H `tools/skills_tool.py` (`_skill_catalog`) and `tools/registry.py` (MIT) | REUSE DESIGN tiered discovery and schema declarations; REUSE SOURCE not yet selected because helper pulls Hermes config/session/path utilities | 0; medium bounded reader, high whole skill/tool integration | When explicitly scoped, dependency-isolate a pure Python catalog helper; reject traversal/symlinks and treat prompt text as untrusted / P3 |
| Profiles/Bundles / absent | D `packages/boot/app-boot/src/{profile,profile-plugins}.ts`, `packages/bundle/base/cordis.patch.yml` (MIT) | REUSE DESIGN ordered composition only; reject executable config/HMR in trusted layer and profile-derived scope grants | 0; high full Node loader, medium small declarative composition | No implementation now; justify concrete modes and trusted permission invariance first / P3 |
| Planner / absent | No dedicated Planner implementation researched; P loop hooks can host future policy (MIT) | KEEP absent; do not infer Planner need from upstream features | 0; no current maintenance | Require explicit problem and executable benefit before new strategy / P3 |
| UI extensions / absent; required approval UI remains trusted | O tool contract/presentation registrations (MIT), D `packages/core/tools/src/presentation.ts` (MIT, source type declarations) | REUSE DESIGN data-only presentation; KEEP authoritative approval rendering/binding | 0; medium data renderer, high dynamic privileged UI | Future untrusted views cannot obscure exact request, approve, or replace trusted prompt / P3 |

REUSE SOURCE and REPLACE were evaluated, not silently omitted. No whole upstream
component satisfies both minimal integration cost and current Khaos authority/data
contracts well enough to justify either in this milestone. A future pure helper may
qualify after an isolated dependency/license/test comparison. Replacing working
Kernel, Memory or cancellation code merely for popularity is rejected.
