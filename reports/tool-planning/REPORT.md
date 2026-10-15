# Evidence-Grounded Tool Planning Proof

Date: 2026-10-15. Baseline main: `540d377417338ebdc36e695d6c747942b0f2cf37`.
Frozen production intervention: `aceced41c2b22c60cae14f31cc8d7e25c2864fd8`.

## Result

**Level 1: demonstrated on one fixed development experiment, with limited scope.**
On the same nested-layout v3 repository, the original prompt requested one
nonexistent source root and ended without a model test. Intervention v2
requested only a plausible test root, followed an actual source reference,
made the repair and regression edit, ran both tests, and passed independent
hidden assertions. The failed-root count decreased from 1 to 0. This is a
small intervention comparison with all attempts retained, not statistical
evidence of general reliability or a universal test-directory-first policy.

**Level 2: NOT PROVEN on the formal frozen dataset.**
The unchanged `runner-exception-classification` formal task stopped with
`invalid_agent_action` after one successful listing. No implementation was
located, no repair or focused test occurred, and hidden grading returned 1.
No further prompt tuning followed that formal result. The conditional gate
for the two predeclared follow-up tasks was not met, so they were not run.
Development successes are not counted as formal benchmark gains or Coding
Reliability Closure.

## A. Tool Planning Audit

See [AUDIT.md](AUDIT.md) for source locations, error semantics, history bounds,
budget behavior, and pinned Pi/Codex/Hermes/Oh My Pi references. Those projects
informed inspection and feedback practices; none is imported as a runtime or
dependency.

PR #18's eight calls combined several problems: an initial unverified source
layout, reuse of that failed prefix, searches that mixed exact identifiers with
generic exception words, and no remaining calls for edit/test. Existing
per-path list results, exact scopes, bounded Python reads, nonzero continuation,
and real return codes were already sufficient for useful work. Kernel authority
or additional tools were not demonstrated to be the missing capability.

History eviction and the exact rejected action fields remain **NOT PROVEN** as
causes. The current list contract intentionally does not distinguish missing
from inaccessible paths; `path_not_listable` must not be overstated. Partial
failures retain successful roots. Output truncation flags and return codes
already exist. The intervention changes how the model is instructed to use
that evidence, not what is trusted or what the Kernel reveals.

## B. Fixed development experiments

Two issue-only tasks were selected before production changes:

- **Nested layout / failed initial hypothesis:** comma-item normalization in a
  nested package, with public tests referencing the implementation. The prompt
  gives behavior and a function name, not its path. Original-prompt discovery
  requests `src/tests`; only the test root exists.
- **Exact symbol in a larger file:** one status mapping after 100 unrelated
  documentation lines. The prompt supplies behavior and exact identifiers, not
  the implementation path. This exercises bounded symbol/context selection.

Each has an untouched defect, independent hidden assertions, and a canary outside
all approved roots. The v3 public tests were validated through the real macOS
Runner under exact source/test scopes: baseline exit 1 and gold exit 0 for both.
Parent-only hidden controls also discriminate both tasks.

The first two fixture editions exposed loader/environment problems before
intervention. They remain failures/development evidence, with their limits in
the audit. They are excluded from the clean v3 comparison, not erased. In
particular, a Desktop-hosted v1 edit returned `commit_rejected`; a separate
signed-product temporary-directory write passed, but the original cause remains
unexplained. No Kernel change was made. v3 uses importlib and temporary workspaces
for both baseline and intervention.

### All real development attempts

| Version | Task | Calls | Runner seconds | Result bytes | Hidden rc | Observed outcome |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| baseline-v1 | Nested | 5 | 26.833 | 2,522 | 1 | Loader permission error, then commit rejection; no diff |
| baseline-v2 | Nested | 8 | 25.842 | 1,982 | 0 | Source and loader repair; added test class was not executed |
| baseline-v3 | Nested | 5 | 16.346 | 1,201 | 0 | Correct source/test edits; premature final response without test |
| baseline-v3 | Symbol | 1 | 3.222 | 268 | 1 | `invalid_agent_action` after list; no diff |
| intervention-v1 | Nested | 7 | 33.260 | 1,665 | 0 | Source/regression edits, 2 tests passed; failed initial root unchanged |
| intervention-v1 | Symbol | 1 | 3.215 | 268 | 1 | `invalid_agent_action` after list; no diff |
| intervention-v2 | Nested | 6 | 19.210 | 1,438 | 0 | No invalid paths; source/regression edits, 2 tests passed |
| intervention-v2 | Symbol | 8 | 39.766 | 2,353 | 0 | Failed speculative edit, then symbol/context read, repair and tests |
| denial-control-v2 | Symbol | 1 | 0.000 | 111 | 1 | Approval denied; zero execution, no replacement or diff |

All use real GLM-5.3-Flash, signed products, Launch Services, independent data
approval, per-operation review, Kernel execution, Seatbelt Runner, and actual
writeback. No Model Probe contributes to these outcomes. Rejected model output
is not retained; specific invalid-action fields cannot be inferred from these
records. Model API token/cost and initial-versus-corrected validity rates are
unavailable from the retained protocol evidence.

[development-evidence.json](development-evidence.json) retains every approved
or denied Proposal's argv/scopes, observation basis, returned diagnostics,
continuation, actual diff and hidden result. Proposal transcripts were recorded
from the real approval UI; output byte counts are whole bounded tool-result
envelopes, not just stdout. Full local logs and workspaces remain under
`local-evidence/runs/`. Canaries are unchanged and absent from Launcher logs;
raw API requests were not separately captured, so log absence alone is not a
claim of non-disclosure. Actual denial properties are exercised by the canonical
security suite.

### Reproduction

The two published Git bundles preserve the precise v3 initial commits.
[experiments-v3.json](experiments-v3.json) binds bundle, prompt, hidden-check
hashes and baseline/gold controls. Earlier manifests retain fixture history.

```bash
python3 reports/tool-planning/prepare_experiments.py --restore
python3 reports/tool-planning/run_experiment.py start --task nested-layout \
  --version fresh-review-attempt --app /absolute/path/to/signed-product.app
```

Review the data prompt, select only the printed disposable workspace, and review
every operation. Then use the same command with `finish` instead of `start`.
The helper refuses overwrite. Hidden assertions and gold source are restored in
parent-only locations, never the model workspace or task prompt. The locally
authorized Hermes credential is read only for the child environment; no value
is stored in arguments, reports or fixtures. A fresh restoration of both exact
commits from the bundles was checked successfully.

## C. Minimal intervention and version discipline

The final production delta is **four prompt lines in untrusted AgentHost.swift**:

1. Distinguish observed paths from guesses; start with one plausible discovery
   root and use real references. Do not repeat a failed root without evidence.
2. Rank exact task/failure symbols first; return bounded paths, line numbers and
   local context, preserving the existing output cap and symlink restriction.
3. Reserve edit/test calls and distinguish the last returned action from a test
   that has never been proposed. Execute discovered tests before claiming proof.
4. Explain existing printable argv and unique-relative-scope formatting rules.

Version 1 improved test continuation in one run but did not reduce the failed
source-root request. Version 2 strengthened single-root exploration and documented
the existing formatting contract. It was committed and built before its two
development attempts. The rejected Symbol fields remain unknown: improved v2
behavior does not establish which change caused either previous action failure.

[FREEZE.json](FREEZE.json) was written before the formal attempt. Its Host hash,
production commit, provider/model, budgets, and conditional follow-up task IDs
were fixed. No formal failure was used to retune the prompt. All intermediate
versions and unsuccessful attempts remain in the evidence.

One added deterministic prompt regression protects the generic rules and checks
that evaluation paths/answers are absent from the Host instructions. It is a
source regression check, not model-quality proof. Existing approval, strict
frame validation, scopes, bounded history, correction count and model settings
were not changed.

## D. Formal frozen task recheck

Task: `runner-exception-classification`.
Baseline: `7b6af61b3925b28ef105ea521c49424344de04c5`.
Prompt SHA-256:
`7a86c99de62538d4c514cb0f5fa1dd31d747701be60f03c12d4a2420736810a2`.
Attempt: `planning-v2-01`.

Fresh parent-only controls returned baseline `[1]`, gold `[0]`. Selected follow-up
controls also discriminate: startup baseline `[1,0]`, gold `[0,0]`; peer-socket
baseline `[1,1]`, gold `[0,0]`. See [frozen-controls.json](frozen-controls.json).
Neither gold nor hidden checks entered the model workspace.

| Step | Proposal / basis | Approval | Runner rc | Result bytes | Continuation / outcome |
| --- | --- | --- | ---: | ---: | --- |
| 1 | `list`, readScope `tests`, no write scope; initial hypothesis | Approved | 0 | 1,541 | `can_continue=true`; response accepted |
| Next model response | No approved operation | None | None | None | Host reported `invalid_agent_action`; task stopped |

Runner time was 3.374 seconds. No diff or model test exists. Parent-only hidden
grading returned 1 over the unchanged frozen focused command. The approved
Runner operation itself succeeded; this is an action-protocol failure, with
specific rejection fields **NOT PROVEN**, not an observed Kernel or XPC transport
failure. See [frozen-recheck.json](frozen-recheck.json) for event timestamps,
approval binding, diagnostics, empty diff and independent grading.

The formal workspace was cloned to a system-temporary location after the earlier
write preflight; PR #18 used a Desktop-hosted workspace. Along with the changed
Host prompt, this is an explicit intervention difference. The task prompt,
baseline, tests, hidden grader, model provider, approval rules and budgets remain
the same. Do not describe the Harness as completely unchanged.

## E. Reliability comparison

| Measure | PR #18 original Runner | Current original Runner | Clean development evidence |
| --- | --- | --- | --- |
| Calls | 8 | 1, then action failure | Nested: 5 original / 6 v2; Symbol: 1 original / 8 v2 |
| Invalid path requests | Initial failed root plus repeated failed-prefix hypotheses | No failed path before stopping | Nested failed roots: 1 → 0 |
| Source location | Not located | Not located | Nested relevant read: call 3 original / call 4 v2; Symbol body: call 5 v2 |
| First actual source edit | None | None | Nested call 5 in both; Symbol call 6 v2 (call 3 speculative edit failed) |
| Model test | None | None | Nested none → call 6; Symbol none → calls 7–8 |
| Hidden result | 1 | 1 | Both v2 development repairs pass; Nested original source already passed hidden checks |
| New formal Coding success | No | No | Development examples are reported separately |

The original Runner's lower call count is caused by earlier failure and is not
an efficiency improvement. The clean nested comparison demonstrates fewer
invalid paths and completion of verification; its additional call performed
previously missing work. The Symbol run demonstrates recovery from a failed
speculative edit and successful bounded context acquisition, but still wastes
one call by editing before reading the implementation. No aggregate success
rate, statistical claim, or Codex/Claude-level capability comparison is justified.

The two predeclared formal follow-ups are **NOT RUN** because the primary task
failed before implementation location. Their successful discrimination controls
are not model scores. No easier formal replacement was selected.

## F. Next bottleneck

Investigate **action validation failure and its bounded correction feedback**.
The formal task and two earlier Symbol attempts stop at `invalid_agent_action`
without preserving which field class failed. Existing generic correction cannot
provide that missing attribution. A future experiment should identify a fixed,
non-sensitive rejection category at the untrusted Host and measure whether its
existing single correction becomes useful. Do not expand parsing permissiveness,
approval, scope, output, calls, or the architecture to hide invalid actions.

## Security validation and accounting

The canonical command `python3 -m unittest discover -s tests -v` passed
**335 tests in 685.451 seconds**, exit code 0. This includes the signed-product
headless source/admission checks, real OS adversarial tests and the added prompt
regression (334 baseline tests plus one). `git diff --check` passed. Both fixture
commits were restored from their bundles and verified exactly. Recorded Python
argv transcriptions were checked for syntax without executing them. An exact
credential-value scan of the 82 new report/log/source artifacts found no key
value. These are validation checks, not additional model-quality samples.
Model-quality results are not CI success gates.

| Item | Delta |
| --- | --- |
| Production code | +4 / -0 prompt lines in untrusted Host |
| Trusted code | 0 |
| New architecture concepts | 0 |
| New trusted processes | 0 |
| New IPC operations / Kernel authority | 0 |
| New persistent runtime state | 0; evaluation fixtures/reports are artifacts |
| New dependencies | 0 |
| Removed duplication / abstractions | Evaluation launch orchestration shares one helper; no new product abstraction |

The `Launcher → Kernel → Runner` path, independent remote-data authorization,
per-operation approval, 8 calls, 180/30 Runner seconds, 4 KiB single/32 KiB total
results, 8 KiB process output, and scope semantics are unchanged. The refusal
control proves zero execution and no retry after a denied operation. Broader
OS-denial properties depend on the actual canonical adversarial tests and the
existing threat-model limits, not model confidence or this prompt.

PR #18's intermittent `sandbox_unavailable_probe_snapshot` remains an independent,
unattributed runtime stability issue. It was not addressed by this change and a
passing rerun must not be described as its root-cause fix.
