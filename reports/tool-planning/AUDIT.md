# Tool Planning Bottleneck Audit

Frozen audit baseline: `540d377417338ebdc36e695d6c747942b0f2cf37`.
Date: 2026-10-15. This audit precedes any production change in this experiment.

## Observations

| Area | Current implementation and evidence | Conclusion |
| --- | --- | --- |
| Path observations | `agentDirectoryRunnerSource` returns JSON keyed by requested directory, with immediate entry names/kinds/sizes or a per-root error. `discovery-05` step 1 returned both a failed `src` and successful `tests`. | Partial failure retains useful observations; an aggregate nonzero return code does not invalidate every root. |
| Error meaning | Broker `_serve_workspace_list` uses `path_not_listable` for scope rejection and snapshot lookup failures. `directory_too_large` and aggregate `directory_list_too_large` are separate. | Existing feedback distinguishes an unsuccessful root from overflow, but cannot distinguish absent from inaccessible. Never infer existence or nonexistence beyond the returned evidence. No authority-sensitive error expansion is justified. |
| Repetition | The current prompt says use observed names and do not invent filenames, but does not explicitly retire failed path hypotheses. `discovery-05` steps 4–5 reused the failed `src` prefix. | Concrete planning failure; prompt guidance is the first intervention to investigate. |
| Search | Existing reviewed shell supports Python exact-file reads, bounded symbol filtering, and searching explicitly approved subtrees. No dedicated search IPC is needed. Step 8 combined precise error identifiers with generic `Error`/`Exception`; early unrelated matches consumed its output cap. | Exact task symbols should rank ahead of generic terms; empty or truncated searches must not be treated as complete coverage. |
| History | `boundTaskHistory` keeps the first task entry and newest entries within 8 KiB, deleting older middle entries. Both remote and local adapters use it. | Older observations can disappear; exact retained content in the prior API run was not captured. History eviction as that run's cause is NOT PROVEN. No new context subsystem is warranted. |
| Budget | Launcher and Host independently enforce eight calls. Host has `toolCallsThisTurn`; the model receives only generic remaining-budget wording. | A prompt can state the fixed limit and ask the model to reserve edit/test calls. Exact trusted remaining counters are not required for the first experiment. |
| Tool results | Result JSON preserves numeric return code, added/modified/deleted counts, bounded stdout/stderr, and truncation flags. Signed step results continued after return codes 1. | Transport/continuation worked in discovery-05; do not attribute path guessing to Kernel failure. |
| Completion | All eight calls in discovery-05 were discovery/read operations; diff empty, no model test, hidden grader 1. | Tool planning and selection of useful context consumed the budget. No task-level improvement has yet been demonstrated. |

## Upstream ideas considered

These are design references, not dependencies or copied implementations.

- [Pi system prompt](https://github.com/badlogic/pi-mono/blob/eddebaeebf8168dfc31d6712b7a021e4df3b4e6a/packages/coding-agent/src/core/system-prompt.ts)
  and its read/grep tools: tool-specific instructions and bounded inspection.
- [Codex coding prompt](https://github.com/openai/codex/blob/7d33d0d93f9c751281e0f5e8e9e76353eee87ea8/codex-rs/core/gpt-5.2-codex_prompt.md):
  choose focused file/text search rather than indiscriminate reads. Khaos must use its available reviewed Python shell instead of assuming rg exists.
- [Hermes prompt builder](https://github.com/NousResearch/hermes-agent/blob/main/agent/prompt_builder.py):
  verify structure and source before modifying; missing retrievable facts should lead to tool use. Local source inspected; no Hermes service or tool registry is imported.
- [Oh My Pi read contract](https://github.com/can1357/oh-my-pi/blob/7cc912940b107eb2d771b0d106c640a8eddc9edf/docs/tools/read.md):
  make ranges and truncation explicit. Its expanded read surfaces, artifact storage, and runtime are unnecessary here.

Only generic prompt guidance will be considered after fixed development experiments.
Duplicate detection, structured feedback changes, trusted code, and new tools are deferred
unless real evidence demonstrates the simpler intervention is insufficient.

## Predeclared experiment policy

Two fixed development repositories cover nested layout/failed initial discovery (A/C)
and an exact task symbol in a larger source file (B). Each has a baseline defect,
public tests, parent-only hidden checks, fixed initial commit, and out-of-scope canary.
Run each once on the current prompt, then once on any frozen intervention. Retain all
attempts. A separate cancelled approval must stop without execution or replacement.
These tasks are development evidence, not formal benchmark scores. Formal Runner
recheck occurs only after freezing the intervention; its failures must not be used to
silently retune the same version. No task path, gold patch, hidden check, or fixed
operation sequence may enter the model's task prompt.

## Fixture preflight corrections (before production intervention)

- `baseline-v1/nested-layout` located the source but its public loader used
  `Path.resolve()`, which failed under exact Runner scopes. The approved source
  edit then returned `commit_rejected` and stopped; no live diff. The underlying
  commit cause is NOT PROVEN. The task ran in a Desktop-hosted workspace.
- A separate signed-product `--command` preflight in a fresh system-temporary
  clone successfully modified the same nested path (0 added / 1 modified /
  0 deleted). This does not establish the cause of the earlier rejection.
- `baseline-v2/nested-layout` used a temporary workspace and removed explicit
  `Path.resolve()`, but `runpy` still failed inside the exact scope. The model
  repaired the source and switched the test loader to importlib, eventually
  receiving exit 0 and hidden exit 0 after eight calls. It appended a new test
  class after `unittest.main`, so only the original public test ran. This is
  retained development evidence, not a clean prompt-intervention comparison.
- Edition v3 uses the existing documented importlib loader. Before any v3
  model attempt, both fixtures were checked through the real macOS Runner with
  exact source/test read scopes and no write scope: public baseline returned 1
  and gold returned 0 for both. Parent-only hidden controls also return 1/0.
  See `local-evidence/v3/runner-fixture-controls.json`.

All earlier editions and attempts remain intact. Edition v3 is the fixed
development comparison dataset. Its issue-only prompts are unchanged from v1;
the test loader and workspace placement changed and must not be counted as
effects of any subsequent Host prompt intervention.

## Fixed v3 baseline observations and first intervention

The v3 nested-layout run used five calls, with return codes `[1,0,0,0,0]`.
It followed an actual test-file source reference, added a regression before
the test entrypoint, and changed the correct source. Hidden checks passed.
However, it ended without a test proposal while three calls remained, referring
to a verification command that had not been proposed. The exact-symbol run
listed the correct directories, then stopped with `invalid_agent_action` before
another approval; no diff, hidden checks failed. Rejected model fields were not
captured, so the exact invalid-action cause remains NOT PROVEN.

These records justify a first prompt-only intervention: distinguish path facts
from hypotheses, use useful public-test references before assuming a source
layout, retain valid partial-list observations, avoid ungrounded failed-root
repetition, rank exact task symbols ahead of generic matches, reserve edit/test
calls, and distinguish a completed edit from an unissued test. All examples and
rules are task-independent. No correct evaluation path, symbol, answer, or
operation sequence is added. Existing shell, scopes, result flags, history,
model request configuration, approval, and budgets remain unchanged.

Production delta is three added prompt lines in the untrusted Host. Trusted
delta is zero. New architecture concepts, trusted processes, IPC operations,
persistent runtime state, dependencies, and abstractions are all zero. A new
deterministic prompt regression guards these rules and absence of evaluation
answers; it is not model-quality evidence. The same two v3 repositories will be
run once with this intervention; the formal frozen Runner task follows only
after version freeze and development evidence review.
