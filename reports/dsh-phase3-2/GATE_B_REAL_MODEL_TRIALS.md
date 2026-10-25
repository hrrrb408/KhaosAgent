# Phase 3.2.2 Gate B — Real-Model Trials

## Decision

**Gate B: NOT_RUN. Preflight status: BLOCKED.** This run did not start a Task A trial, create a trial workspace, launch a signed app, or invoke the model.

The verified GitHub baseline was PR #47 head `e27aed3ee3f40e7a008517ab7d8242bebe25a7c2`, stacked on PR #46 head `7ed01f726387755181cfbadad33967f35d9d2f72`. Both PRs were open Drafts and unmerged when checked. The experiment branch was created from the exact PR #47 head.

The active `benchmark-freeze-v4.json` SHA-256 is `8c9685aba296d83cb3dd522ff9e7957a3074837cefd746f310689bd29c567e43`. Its H01–H08 holdout digest is `d163fd20cff2db44cb0dc5f5260542666b098bbce403a0aafd30fa8b3e46615d`. This run was limited to frozen Phase 3.1 Task A; no holdout or A–D replay was started.

| Planned label | Trial started | Workspace / Task / Launcher Request IDs | Result |
|---|---:|---|---|
| `gate-b-task-a-01` | No | Not generated | NOT_RUN |
| `gate-b-task-a-02` | No | Not generated | NOT_RUN |

Counts: trials started `0/2`; completed `0/2`; real-model invocations `0`; end-to-end successes `0/2`.

## Blocking preflight

The only local bundle containing the frozen model bytes has the expected 18,556,689,568-byte model SHA-256 `fadc3e5f8d42bf7e894a785b05082e47daee4df26680389817e2093056f088ad`, and its signed Host metadata records that same digest. The containing bundle fails `codesign --verify --deep --strict` with `CSSMERR_TP_NOT_TRUSTED`; no valid code-signing identity is available in the current user keychains, and the bundle has no accepted `build-inputs.json` record. It therefore cannot supply an authenticated signed model app for this run.

The existing semantic-tools acceptance route binds a signed app to each fresh workspace and rejects a prebuilt app for workspace-bound real-model trials. Its builder embeds the model in the resulting app. Building both fresh trial apps would copy the 18.56 GB model for each trial, which this task explicitly forbids. No validated one-app route preserving the required workspace identity binding was available. We did not weaken that binding or copy the model.

The pinned Node archive and binary were available and matched their frozen hashes; pnpm `11.28.5` ran under the pinned Node `v22.19.0`. The upstream DSH commit exists at `deepseek-ai/deepseek-harness@687f282e8625c6b8d11ff58211a90524be2e4317`, but no local DSH checkout was used because the signed-app preflight had already failed.

No hidden-test result, model output, signed Runner result, or AgentLoop terminal state is claimed. Prior Phase 3.2 and Phase 3.2.1 attempts remain historical and are not counted in this batch.
