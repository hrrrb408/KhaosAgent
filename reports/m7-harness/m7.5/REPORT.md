# M7.5 — fixed real coding benchmark recording

Base: M7.4 `d93a52c`. This batch completes recording/integrity comparison of the
already authorized original-task replay, not another model experiment. The sole
new remote-data authorization was consumed by `m7-2-context-01`; no additional
model call, grader rerun, prompt tuning, hidden-test edit or scope expansion is
performed here. The existing prepare/grade/event-capture primitives are reused.

## Frozen controls checked against current artifacts

`audit.json` has 15 passing offline checks: original prompt bytes (including its
newline), original root baseline, unchanged parent-only hidden patch, exact
configured provider/model, five trusted budgets, one explicitly approved list
scope, unchanged raw run/grade records, empty candidate diff, failed hidden
verdict retained, unchanged current Host/action source since the frozen build,
unchanged signed build record, clean actual workspace and all 34 runtime TCB
files byte-identical to the M7 starting baseline. The actual frozen signed app
also passes `build_macos_seed.py --verify-app` now without launch/model access.

Controls remain baseline `7b6af61b3925b28ef105ea521c49424344de04c5`, prompt
`7a86c99de62538d4c514cb0f5fa1dd31d747701be60f03c12d4a2420736810a2`, hidden patch
`185ea8ada844d790c0d716b2d7d921c8c4e739b238baa5d1b7b325e6fc446e16`, provider
`bigmodel-coding-plan`, model `glm-5.3-flash`, original endpoint
`https://open.bigmodel.cn/api/coding/paas/v4/chat/completions`. Budgets are still
8 calls / 180 cumulative Runner seconds / 30 per call / 4 KiB per result /
32 KiB aggregate. The new M7.3/M7.4 changes are test diagnostics/oracles/explicit
UI deferral and reports; no post-result production change invalidates the freeze.

## Comparable original-task outcome

| Observation | planning-v2-01 | M7 m7-2-context-01 |
| --- | --- | --- |
| Original prompt/baseline/hidden patch | same | same |
| Product source | aceced41 | 0a2a37aa |
| Provider/model | BigModel Coding Plan / GLM-5.3-Flash | same configured ID |
| Tool proposals / approved / executed | 1 / 1 / 1 | 1 / 1 / 1 |
| Approved operation | list tests; no write scope | list tests; no write scope |
| Actual returncodes | [0] | [0] |
| Runner time / bounded result bytes | 3.374 s / 1,541 | 3.196 s / 1,541 |
| Source changes / model tests | none / none | none / none |
| Terminal observation | invalid_agent_action | invalid_agent_action_wire_contract_after_correction |
| Original parent hidden test | exit 1 | exit 1 |
| Coding outcome | failed | failed |

`comparison.json` keeps machine-readable controls and observations; `events.json`
keeps only the existing fixed event labels/counters/timestamps. The exact accepted
list request/digest is in `../m7.2/frozen-replay.json`. The rejected next action
was neither approved nor executed; raw rejected model data was not logged, so
its individual invalid fields remain NOT_PROVEN. The category identifies the
actual failed gate, not a guessed model payload. Successful listing, orderly
Launcher exit 0, deterministic success or a passing baseline command cannot be
counted as a repaired coding task.

The same host and configured provider profile make these attempts useful for
bounded comparison, but the products intentionally differ in Host behavior.
Remote hosted weights are not pinned; separate model latency, token count and
cost are unavailable. Event intervals include approvals and polling, not pure
inference. The small Runner-time difference is not a performance claim. No
causal claim that history eviction produced either failure is supported.

## Preserve failures and distinguish evidence classes

`attempt-inventory.json` preserves the eight existing API attempts for this task,
including discovery failures, denial, budget exhaustion, the old formal recheck
and the sole M7 replay. Every available hidden returncode is retained. Discovery-04
has no grading record and is explicitly unknown, not silently counted as pass or
rerun. Historical records without full tool payloads/source metadata remain
unknown; missing values are never invented. Original local archives remain
untouched, including all preflight/development runs.

The earlier 12 API and 12 local formal records remain in the dataset's existing
`published-runs`; their 0/12 results and eight non-discriminating baseline passes
are historical results, not new M7 scores. The current follow-up is one failed
API task, not a new 12-task comparison or model ranking. No additional model work
is inferred from the user's separate UI authorization.

Deterministic helper tests prove retention/rejection behavior; the fixed signed
probe proves bounded tool sequencing and observed OS/approval behavior; corrected
UI fixture oracles prove the acceptance harness matches its current deterministic
probe; the actual remote replay still failed coding and hidden checks. These
four categories remain separate. Coding Reliability Closure remains NOT_PROVEN.

## Change budget

Production code delta: 0.
Trusted code delta: 0.
New architecture concepts: 0.
New trusted processes: 0.
New IPC operations: 0.
New persistent runtime state: 0 (recording artifacts only).
New dependencies: 0.
Removed duplication / abstractions: 0; reused existing frozen prepare/grade/events
and the original failed replay instead of creating another benchmark engine.

No normatively new security promise is added. Complete PR-head checks are tracked
on the stacked PRs; the full taskbook matrix and the one owner-deferred UI item
are recorded in `../COMPLETION_AUDIT.md`.
