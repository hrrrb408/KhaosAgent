# Gate B — Resource and Artifact Retention

## Model and runtime identity

The existing model bundle's model file is `18,556,689,568` bytes and hashes to the frozen SHA-256 `fadc3e5f8d42bf7e894a785b05082e47daee4df26680389817e2093056f088ad`. The observed llama.cpp runtime hash `134c1054f24057b12eeada8974e5e20815bba07a89ba2e79a3376c233a8b2fdd` and license hash `832dd9e00a68dd83b3c3fb9f5588dad7dcf337a0db50f7d9483f310cd292e92e` match the active freeze. Static linkage lists CPU-only libraries and no Metal framework.

The local DSH checkout is clean at `687f282e8625c6b8d11ff58211a90524be2e4317`. Its package manifest pins pnpm `11.28.5`; the current shell instead reports pnpm `10.33.0` and Node `v26.12.0`. The active freeze pins Node `v22.19.0`; the exact archived Node binary and archive hashes were not revalidated, so the full frozen runtime check is `PARTIAL`.

The active freeze file SHA-256 is `8c9685aba296d83cb3dd522ff9e7957a3074837cefd746f310689bd29c567e43`, and its holdout dataset SHA-256 is `d163fd20cff2db44cb0dc5f5260542666b098bbce403a0aafd30fa8b3e46615d`. No prompt, task, public test, hidden oracle, evaluator, or budget was changed.

## Disk preflight

The PR #47 `preflight_local_model_build` / `disk_space_preflight` helper returned `PASS` before any build or copy:

- Model size: `18,556,689,568` bytes.
- Required free space for one build: `22,559,842,173` bytes.
- Observed free space: `475,136,000,000` bytes.
- Model/app copies and build attempts in this run: `0` bytes / `0`.

The disk result allows one build if a trusted signing identity becomes available. It does not authorize repeated GGUF copies, and no build was started.

## Retention

Artifact Retention is **PARTIAL** for this attempt. The owner-only preflight record was preserved outside the repository (SHA-256 `2ff508d33a0a9b47617b2a8c64523175f3a101a6547c58ea336717082fcf2232`). No trial scratch, workspace, model output, signed-run log, or Runner evidence was created. Existing model and historical artifacts were left untouched; historical deletions: `0`.

The canonical suite passed all 457 tests in 855.134 seconds in the host-level run. Security Freeze passed both the default inventory and comparison against exact PR #47 base `e27aed3ee3f40e7a008517ab7d8242bebe25a7c2`. PR #47's exact-head Seed CI and Security Freeze runs also passed (run IDs `40175783148` and `40175783155`). These repository checks do not replace per-trial evidence capture, which could not occur because no trial started.
