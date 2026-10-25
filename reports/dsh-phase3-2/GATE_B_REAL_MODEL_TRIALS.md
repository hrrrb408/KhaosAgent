# Phase 3.2.2 Gate B — Real-Model Task A Trials

## Decision

**Gate B: NOT_RUN. Phase status: BLOCKED before either trial started.** The signed model app failed deep strict code-signature trust verification, and the current user keychain search list contains no valid code-signing identity. The existing app was not launched, and no real-model inference occurred.

This report counts only this Gate B attempt. Historical Task A attempts, deterministic Gate A runs, fixtures, and CI results are not included as current trials.

## Trial ledger

| Trial | Trial ID | Task ID | Workspace / Launcher IDs | Model calls | Result |
|---|---|---|---|---:|---|
| 01 | `gate-b-task-a-01` | Task A | Not created | 0 | `NOT_STARTED` — signed-runtime preflight blocked |
| 02 | `gate-b-task-a-02` | Task A | Not created | 0 | `NOT_STARTED` — signed-runtime preflight blocked |

For both trials, public tests, independent hidden tests, AgentLoop terminal state, no-progress behavior, Kernel result delivery, and end-to-end success are `NOT_RUN`. No disposable workspace was created or selected, no Launcher request was submitted, no approval was shown, and no Runner process was started.

## Frozen inputs checked

- Active manifest: `benchmark-freeze-v4.json`, SHA-256 `8c9685aba296d83cb3dd522ff9e7957a3074837cefd746f310689bd29c567e43`.
- Frozen holdout dataset SHA-256: `d163fd20cff2db44cb0dc5f5260542666b098bbce403a0aafd30fa8b3e46615d`.
- Frozen Phase 3.1 Task A dataset SHA-256: `033f5d9c776f025e21642911b6d13e2afcc32b876a39fab377ae0a6279dc5091`.
- DSH source HEAD: `687f282e8625c6b8d11ff58211a90524be2e4317`, clean checkout.
- Model SHA-256: expected and observed `fadc3e5f8d42bf7e894a785b05082e47daee4df26680389817e2093056f088ad`, `18,556,689,568` bytes.
- The bundled llama.cpp runtime and model-license hashes match the freeze. Static linkage lists CPU libraries only and no Metal framework.
- Frozen runtime requires Node `v22.19.0` and pnpm `11.28.5`. The current shell reports Node `v26.12.0` and pnpm `10.33.0`; the exact frozen Node archive and binary were not revalidated.

The existing model bundle reports Team ID `UBAP6LN5AM` and Candidate CDHash `e467021676ede58181d9c151d51102039df352adb60ff8da71a9198805f6044b`. `codesign --verify --deep --strict` returned `CSSMERR_TP_NOT_TRUSTED`; its signing authority is unavailable, Gatekeeper assessment returned an internal Code Signing error, and `security find-identity -v -p codesigning` found zero valid identities. This trust failure does not by itself establish that the bundle was modified. The bundle is not accepted as Gate B execution evidence.

## Operator and evidence

- Operator: `codex_agent`.
- Authorization: owner-delegated disposable experiment.
- Owner personally clicked: `NO`.
- UI approvals / model invocations / Runner operations: 0 / 0 / 0.
- Owner-only preflight evidence was retained outside the repository. Its SHA-256 is `2ff508d33a0a9b47617b2a8c64523175f3a101a6547c58ea336717082fcf2232`.

The two trial IDs remain unstarted. No retries, prompt changes, alternative model, synthetic response, or hidden-test feedback were used.

Repository checks after the preflight reports were staged: the canonical suite passed all 457 tests in 855.134 seconds in the host-level macOS run; Security Freeze passed both default inventory and comparison against exact PR #47 base `e27aed3ee3f40e7a008517ab7d8242bebe25a7c2`. The initial sandboxed suite invocation was blocked by host-operation `EPERM` errors; it was not treated as a code result. These checks do not count as Task A trials.
