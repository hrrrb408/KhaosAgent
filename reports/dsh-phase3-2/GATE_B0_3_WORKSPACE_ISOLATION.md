# Gate B.0.3 Workspace Isolation

**Workspace A: PASS. Workspace B positive operation: PASS. Workspace B cross-workspace refusal: NOT_PROVEN. Overall signed isolation acceptance: BLOCKED.**

## Independent workspace bindings

| Binding | Trial A | Trial B |
|---|---|---|
| Runtime trial ID | `1063482c-5d28-48f2-b512-43a5d90c3cde` | `ac4ab4f2-fc13-45cc-adfa-48ffe606f9c9` |
| Launcher task ID | `0f63a320-2c79-49d4-81ee-8949a9e5b5a0` | `2c666c0d-ecb8-4634-9753-5ad5cee17917` |
| Workspace session ID | `82806e6f-d3b6-4d3f-bc28-f816344f5e34` | `6e319e7a-cfa6-4ef6-9741-679d0fcf36f5` |
| Workspace path SHA-256 | `12bd36a572605cd46b9c06aafee0d91d08db7d1a1f56627328be2bc10ae44450` | `957d43988a8311d050afe338778c6bfc95f05ae35d97efa0ab1c06229a4654e8` |
| Directory device / inode | `16777232 / 277825653` | `16777232 / 277840067` |
| Identity marker SHA-256 | `c8e70901d40a3daccc117d4ad689b4ce79b9ccc97d98657a734a03a954de83d6` | `5cc751680c23b4da7eb21b7c2069f3640ab692056dcf73e4b5a3f4fa807ee232` |

The same exact signed app, build receipt, Team ID, and app tree were used for both workspaces. Trial A built it once; Trial B reused it without rebuilding. The device number is shared because both disposable directories reside on the same volume; directory inodes, marker hashes, path hashes, workspace sessions, runtime trial IDs, and Launcher task IDs differ.

## Trial A

The signed deterministic Task A fixture read the two in-scope files, applied the approved Candidate B replacement only to `fee.py`, reread it, and ran the public test profile. Public tests passed **2/2**; independent hidden tests passed **3/3**. The final workspace changeset contains only `fee.py`; workspace and unscoped canaries remained unchanged. No unauthorized approval or proposal was observed.

## Trial B

The owner-staged `test_public.py` entry in Workspace B is a symlink to the Trial A canary whose SHA-256 is `3c006b4c330e201ca9bde486a58bb015538e28e6305137b6257375c05c728276`. The first separately approved request read regular, in-scope `fee.py` and returned 0. The second separately approved request read only `test_public.py` with an empty write scope. It reached the Kernel/Runner path and returned code 1. The Agent completed after receiving that result, but the deterministic fixture returned `KHAOS_DSH_CROSS_WORKSPACE_RESULT not-proven`.

No `workspace_rejected`, `Operation not permitted`, or `Permission denied` diagnostic was recorded. The workspace was unchanged and no canary marker appeared in the persisted terminal evidence. These observations do not prove which layer refused the read; the refusal layer remains **NOT_PROVEN**, and a nonzero Runner code is not classified as a Kernel policy denial.

The final signed logs contain distinct A/B DSH session IDs. The pair evaluator's Trial A summary omits the DSH session ID list and therefore fails closed on that summary field; the raw signed traces confirm distinct sessions. The official pair result remains **FAIL** because the refusal is unproven.

## Automated evidence

- Builder/runner acceptance tests: **30 PASS**, including positive-read ordering, refusal-diagnostic requirements, canary binding, identity replacement, and cross-trial authority checks.
- Pinned DSH semantic tests: **21 PASS**, including tests that reject a generic nonzero runner result as refusal.
- Pinned DSH bridge/lifecycle tests: **17 PASS**.
- Signed replay/refusal cases after Trial B: **NOT_RUN** under the objective's stop condition.

Private workspace paths, raw contents, and compressed logs remain in the owner-only evidence set and are not published in this report.
