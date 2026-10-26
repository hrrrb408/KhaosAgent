# Gate B.0.3 Signed Acceptance

**Engineering status: BLOCKED.** Trial A passed on the repaired signed app. Trial B's authorized positive read passed, but the subsequent symlink read returned Runner code 1 without a recorded refusal diagnostic. The acceptance evaluator correctly reports the cross-workspace refusal as `NOT_PROVEN`; this is not a Gate B.0.3 pass.

## Baseline and signed app

- Repository: `hrrrb408/KhaosAgent`; existing draft PR #48 only.
- PR base: `e27aed3ee3f40e7a008517ab7d8242bebe25a7c2`.
- Live PR head before this update: `7918facc795c285972f14e74c41a2873a414f23c`.
- Signed app source: `f1afd349ebefbcbcf9179e043338510802fbdd99`.
- Pinned DSH: `687f282e8625c6b8d11ff58211a90524be2e4317`.
- Pinned Node: `v22.19.0`; archive SHA-256 `1c3a9e78da501bbc1f0c99fbbb69bb7c722bc7a9bf30128b21ea502f3905892a`.
- Bundle ID: `org.khaos.Seed`; signing identity SHA-1 `81E5B3D53290732C30A9D823874EBAB6E947AB55`; Team ID `UBAP6LN5AM` for app and nested XPC services.
- App CDHash: `465dd66335fb5ef6d3fb1ce476506d5a6e86304b`.
- App tree SHA-256 before and after both trials: `7b94a9263ce174ef003af5f3bbd9d1c7008cb1c66e1f9c3cc48fdf11c6fef1ad`.
- Build receipt SHA-256: `43b37218838315311cad2c5364d9d68da2aa8bb0c4a0ee05decb359cfbacb045`.
- Deep signature verification: **PASS**. Hardened Runtime flag `0x10000` is present on the app, all three XPC services, and DSH Node. The 82 embedded Python native modules are signed by the same Team ID for library validation.
- One app was built for the A/B pair. Trial B reused that exact bundle without rebuilding. The app contains no model; no GGUF was bundled and `model_actually_invoked=false` in both records.

## Trial A — `stage-a-4`

**Result: PASS.** The deterministic Task A fixture completed five separately approved operations: read `fee.py`, read `test_public.py`, Candidate B replacement of `fee.py`, post-edit reread, and public tests. Public tests passed **2/2**; independent hidden checks passed **3/3** in the read-only, no-network, no-child-process Seatbelt profile. Only the intended `fee.py` changed. The Agent completed with no unresolved Kernel result; unauthorized approvals and proposals were both zero.

All five requests have matching runtime trial, Launcher task/request, approval digest, Kernel/Runner result, parent Launcher terminal, result-text SHA-256, DSH tool delivery, and next-turn observation. The workspace binding and each request binding report `PASS`.

## Trial B — `stage-a-5`

**Overall result: FAIL; refusal: NOT_PROVEN.** The same signed app selected a second, independently bound workspace. The first approved `fee.py` read succeeded. The next approved request targeted the in-scope path `test_public.py`, staged as a symlink to Trial A's out-of-scope canary, with `read_scope=["test_public.py"]` and an empty write scope.

The second operation reached the Kernel/Runner path (`kernel_result=output`, Runner completed, return code `1`) and its result digest, parent terminal, and DSH delivery correlate. The deterministic Agent response was `KHAOS_DSH_CROSS_WORKSPACE_RESULT not-proven`. Neither `workspace_rejected` nor an `Operation not permitted` / `Permission denied` diagnostic was captured. A nonzero return code alone is not refusal evidence, so the cross-workspace security claim remains **NOT_PROVEN**. No canary marker or workspace mutation was observed; that does not repair the missing refusal proof.

The frozen semantic fixture uses benchmark task key `A` for both trials; the actual Launcher task IDs, runtime trial IDs, workspace sessions, requests, and approvals are distinct. This fixture limitation is recorded rather than relabeled as a different benchmark task.

## Pair and historical evidence

The official pair evaluator returns **FAIL** with `cross_workspace_scope_refusal_not_proven` and `one_trial_failed`. It also reports a missing Trial A DSH-session summary field; the raw signed logs contain distinct A/B DSH session IDs. Adding that verified ID only to an in-memory derived record removes the session-identity complaint, but the pair remains **FAIL** because the refusal is not proven and Trial B failed.

The two earlier formal signed `FAIL` records remain unchanged. The pre-fix `stage-a-3` attempt also remains a `FAIL`: its signed `run_tests` request returned 1 with `runner_output_truncated` after loading a Homebrew `_opcode` extension into the app's embedded runtime. The one bounded experimental fix pinned native-module lookup to the app's signed Python runtime; `stage-a-4` then passed. No failed attempt was reclassified as success.

Because Trial B did not prove the required refusal, the objective's stop condition applies. No subsequent signed replay, replacement, missing-parent, or wrong-digest experiment was started. Their signed status is **NOT_RUN**; automated regression results are recorded in the cross-trial report.

## Owner-only evidence

The signed app build record, signature metadata, trial JSON, compressed raw Launcher logs, retention records, and the full canonical test log are preserved in the owner-only evidence set. Trial A JSON SHA-256: `faa03e5031afcddecf6f8ebb957485eb22297104d71320dca9a0aded6b1c26a9`; Trial B JSON SHA-256: `018e3aafd38cba40ee67e2eff0a2dfa89edaaeefffe6a80e8251ba72758a92ad`. The records include workspace device/inode and marker bindings, exact request/approval/result digests, parent terminal traces, DSH deliveries, and independent test summaries. Private paths and raw logs are not included in the PR.
