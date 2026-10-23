# Khaos × DeepSeek Harness Phase 3: Performance and Cost

Date: 2026-10-23

## Conditions

Measurements were taken on Apple M4 Pro, arm64, macOS 27.0.1, with 48 GiB
physical memory. The coding trials used a signed experimental app containing
Node `v22.19.0`, the pinned DSH runtime, and an 18.56 GB CPU-only local GGUF
model. No remote model was used.

## Measurements

| Measurement | Observed value | Boundary |
|---|---:|---|
| Signed DSH + local-model app size | `18,765,873,305 bytes` (`17.48 GiB`) | App bundle bytes from each raw trial |
| GGUF model size | `18,556,689,568 bytes` | Model SHA-256 `fadc3e5f…56f088ad` |
| Approximate bundle without model payload | `209,183,737 bytes` | Subtraction only; not a separately built app |
| Node RSS | Mean `60,197,157 bytes` (`57.4 MiB`) across 7 measurable trials; range `60,030,976–60,391,424 bytes` | A-1 reported zero due a known sampling issue and is excluded; it is `NOT_MEASURED` |
| Local llama process RSS | Mean `35,844,794,368 bytes` (`33.38 GiB`); range `33.07–33.65 GiB` | Per-process polling; not total system memory or a steady-state benchmark |
| Trial wall time | Mean `113.74 s`, range `63.29–263.05 s` | Includes signed UI review and model calls; all eight trials finished below 600 s |
| Launch-to-runtime time | `NOT_MEASURED` | XPC child stderr events were not collected by the parent runner |
| First model response / first tool proposal | `NOT_MEASURED` | Model-call diagnostics are not present in primary raw logs |
| Tool round-trip latency | `NOT_MEASURED` as a clean metric | One Runner action took about 13.968 s according to its Launcher task record, but this includes command runtime and is not isolated IPC latency |
| Model token counts / estimated cost | `NOT_MEASURED` | Local llama stderr usage was not retained as structured telemetry |
| Crash recovery time / process cleanup | `NOT_MEASURED` in Phase 3 | Phase 2 signed crash-recovery evidence was reused, not remeasured |

## Comparison

The earlier Phase 2 DSH bundle measured `198,808,888 bytes` and its standalone
Node RSS was about `52,871,168 bytes`; the earlier production-check Seed app
measured `88,240,336 bytes`. Those are older builds without the large local
model and are not hardware-identical benchmark samples. Subtracting the model
payload from the Phase 3 app gives an approximate `209 MB` package footprint,
but it is not a controlled rebuild comparison. A fair native-vs-DSH runtime
latency comparison was not performed because the model, task, instrumentation,
and build inputs were not held constant. No claim of latency parity is made.

## Cost assessment

Packaging a 18.56 GB model into the signed app adds substantial distribution
and update cost. The model process used roughly 33.4 GiB RSS on this 48 GiB
machine, leaving little memory headroom for concurrent workloads. Node itself
used about 57.4 MiB, a modest part of that footprint. The current DSH bundle
therefore does not have a reasonable default deployment profile with this
model. Candidate deployment should use an explicitly installed local model or a
separately reviewed provider boundary, with memory and package limits chosen
for the target device.

The eight trials averaged 113.74 seconds including operator UI time, but coding
success was `0/8`; this is not a usable throughput estimate for successful
work. DSH capabilities did not yet offset the local-model package and memory
costs in this experiment.
