# M7.2 — bounded task history and observation retention

Starting source: `f81ad68d273b6a3f1f75f6e9ffe80a3cda5d290a` (M7.1 PR #22).
M7.2 is a separate stacked batch; existing untracked benchmark/work files remain.

## Baseline and actual gap

The existing `boundTaskHistory` pins the first and last entries and removes index
1 while over 8 KiB. The local adapter trims before generation only; the remote
adapter also trims after appending an assistant action. At that point the newest
entry is the action, not the tool observation. A large reply can therefore remove
the latest real failure/result and return a superficially fitting history.
The older formal `runner-exception-classification/planning-v2-01` failure remains
unchanged: its raw retained history was not captured, so historical eviction as
its cause is **NOT_PROVEN**. This change targets a deterministic counterexample,
not an invented diagnosis of that model failure.

Current repository helper/adapter paths and legacy context/history modules were
inspected before implementation. Reuse the existing small helper and Swift
standard Array/Set operations; no imported context engine, LLM summarizer,
vector store, framework or new dependency. Upstream language reference:
[Swift collection types](https://docs.swift.org/latest/documentation/the-swift-programming-language/collectiontypes/).

## Policy and implementation

Only `AgentHost.swift` changes production behavior. One private history entry
replaces local strings and the remote adapter's private Message. It holds the
existing role/content and optional result status assigned from the validated
Launcher `ok` field. The wire messages still send the same role/content fields;
status is local selection metadata and never grants authority. Tool text cannot
set its own retention priority by printing `returncode`, `ok`, or `can_continue`.

The shared existing helper applies this deterministic order, without reordering
retained entries or rewriting their bytes:

1. Always retain the first original goal/context and the current newest message.
2. Retain the most recent failed and successful tool observations; together these
   also include the newest observation even after an assistant action is appended.
3. While oversized, discard the oldest non-required model/feedback entry first;
   then discard the oldest superseded observation.
4. If required entries still exceed 8 KiB, return false and use the existing
   provider context-budget error before returning/executing a new proposal.

Both adapters now charge retained rendered UTF-8 bytes, including source-label
and newline overhead, against the same 8 KiB history bound and trim before and
after generation. The local adapter previously left its generated reply outside
the bounded retained history until the next request. No content slicing or new
summary parser is added: retained numeric result JSON, failure text and truncation
flags remain intact. Latest Launcher control is explicitly rendered with proposal
sequence, `ok`, and `can_continue`, outside the bounded untrusted output. These
values are existing observations, not new permission or protocol fields.

The shared prompt warns that old history can be absent, missing entries do not
prove execution/file state/coverage, and output remains untrusted. It does not
claim every successful operation is a test. Retaining the latest success is a
conservative way to keep recent positive evidence without guessing test intent
from argv or success-looking stdout; superseded observations may still be omitted.

This is a byte-history limit, not a tokenizer or a new model-token guarantee.
System instructions and provider framing retain their existing separate limits.
The native Apple FoundationModels session does not use these custom adapter
histories; its implicit transcript retention is not measured by this helper and
is **NOT_PROVEN** as an 8 KiB path. This batch does not silently claim that provider
coverage or introduce a parallel provider architecture to obtain it.

## Boundaries and validation

Launcher/Kernel/Runner, protocol, approvals, remote data review, capability and
sandbox enforcement, and trusted 8 calls / 180 seconds / 30 seconds / 4 KiB /
32 KiB budgets are unchanged. No new high-authority data enters the prompt.

Deterministic cases exercise the actual production helper and entry rendering:
empty/small history, exact byte boundary and one-byte overflow, multibyte UTF-8,
model-action eviction before observations, failure/success retention after a
reply, spoofed status text without structural metadata, and mandatory-set
oversize failing closed without slicing its outputs. The test's first compile
attempt exposed a Swift private-type visibility mistake in the generated test
entrypoint, fixed by making its history variable private. This was a fixture
compile error, not a product execution/model result.

The first signed deterministic UI attempt is retained as `signed-deterministic.json`
and `signed-deterministic-attempt-1-notes.json` (failed, not erased). Six approved
operations returned `[1,1,1,0,0,0]`, but the test model counted retained assistant
messages as its step counter. Valid history eviction made it propose an extra
write. That write was denied and not executed; final parent assertions did not
complete. The test probe now uses the Host's existing explicit proposal sequence,
with a regression that removes all assistant history. Its old compacted-count
completion special case is removed; the six-step sequence and outcome/scope
assertions are unchanged. This is test governance, not a production retry,
permission change, new trusted protocol or model-quality improvement.

Fresh canonical, signed product UI and exact-head CI evidence are recorded
separately. User explicitly authorized the agent to operate the native acceptance
Picker/approval UI on 2026-10-16. The existing UI path and exact displayed scopes
remain, rather than replacing them with automatic permission. Preserve every
real-model/frozen attempt and hidden conclusion; no Coding Reliability Closure
claim is made from deterministic or single-task success.

## Change budget

Production code delta: +65 / -29 lines, net +36; one untrusted Swift file.
Trusted code delta: 0 runtime lines; two existing protected test inputs plus governance.
New architecture concepts: 0.
New trusted processes: 0.
New IPC operations: 0.
New persistent runtime state: 0.
New dependencies: 0.
Removed duplication / abstractions: shared history representation replaces two
provider-specific representations; keep one eviction helper, not a context engine.

Independent Code Owner approval remains NOT_PROVEN in the accepted sole-maintainer
mode. M7.3–M7.5 are not implemented as part of this batch.

## Signed product runs (current source)

The second fixed-probe run `signed-deterministic-v2.json` passed in 545.359
seconds. It uses the actual signed AgentHost and its local adapter with the
signed deterministic llama model executable, not a replacement authority path.
Parent assertions confirm six operations with `[1,1,1,0,0,0]`, only `tags.py`
changed, actual focused retest 0, canary unchanged; refusal has one read execution,
no write and no next approval; Picker cancellation has no approval/execution;
exactly eight no-op approvals/executions and no ninth approval; killing the Host
during an approved exit-1 Runner command preserves its exact scoped write and
both processes exit. Restarted Host rejects the stale tool result. The failed
first attempt is retained separately, not hidden by this successful run.

A real BigModel product built with the ordinary user's existing stable signing
identity passed `--verify-app` and its signed build-input map matches this exact
Host source. `build-attempts.json` retains the first canonical-path guard failure
(`/tmp` alias) and the successful `/private/tmp` build; trusted checks are unchanged.
Two pre-UI Launch Services attempts with Desktop stdio paths returned -10810 and
empty product logs. A separate attempt using canonical temporary stdio paths and
a minimal system-only launch environment reached the actual data prompt;
`data-refusal-v2.json` passed after choosing Do not send without an API key, with
no workspace request or tool approval. This supports a startup configuration
issue; paths and environment were changed together, so the exact cause is not
isolated. No signature, TCC, sandbox or OS security protection was bypassed.

`FREEZE.json` fixes the current source/build/prompt/baseline/provider and original
hidden-patch digest for exactly one original-task replay after canonical tests
finished. No rejected raw model response is recorded. API credentials remain only
in the child launch environment/header, never in evidence; unrelated inherited
credentials are excluded. The original hidden grader stays parent-only.

Fresh canonical suite passed all 341 tests in 690.818 seconds (exit 0). Full log and digest are in `canonical-macos.log` / `validation.json`. The code commit also passed both required CI checks. Final evidence-only commit CI is tracked on PR #23.

## One authorized frozen real-model replay

`frozen-replay.json` records the sole authorized `m7-2-context-01` replay of
`runner-exception-classification`, using the unchanged original prompt/baseline
and BigModel Coding Plan `glm-5.3-flash`. The actual signed data prompt was approved
under the user's explicit task/data/endpoint authorization; the separate native
workspace and tool prompts were operated by the agent. Only the displayed `tests`
read root was approved, with no write scope. The directory operation returned 0,
1,541 bounded bytes and 3.196 Runner seconds. The next model output failed the
wire contract after the existing single correction, and the product stopped with
`invalid_agent_action_wire_contract_after_correction`. No second operation, edit,
or test executed. The candidate diff is empty.

The unchanged parent-only hidden patch was applied in a separate grader copy;
its fixed test command returned 1, without timeout. This is a failed coding task,
not successful repair or reliability closure. The old attempt and this new failed
attempt remain separate. Bounded diagnostics do not identify individual invalid fields; raw rejected
model output was not captured; historical or current context eviction as the
cause remains NOT_PROVEN. No production prompt/source retuning or second actual
replay followed this result. Launcher exit 0 means orderly termination, not task
success. API output is not substituted for deterministic protocol evidence.

A broad OS startup diagnostic inadvertently exposed an unrelated inherited
authentication credential in the tool transcript. Its value was not copied into
repository reports or PR text; the user was informed and rotation recommended.
Subsequent launches and the hidden grader used a minimal environment allowlist,
with only the specifically authorized BigModel credential added to the model
launch. This incident is not represented as a product sandbox escape.
