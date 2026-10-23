# Khaos × DeepSeek Harness Phase 3: Real Model Integration

Date: 2026-10-23

## Result

**PASS for the bounded local-model integration; remote-provider integration was
not run.** A locally bundled GGUF model was invoked from the signed experimental
AgentHost through the pinned DSH model adapter and `AgentLoop`. The generated
tool proposals reached the signed Trusted Launcher. The only approved Runner
operation returned its real non-zero result. No model input or workspace data
was sent to a remote service in the eight benchmark trials.

The bundle records only the model alias `bundled-cpu`, not the upstream model
name or training lineage. The artifact is content-bound by SHA-256 below, so the
model was real and reproducible by digest, but this evidence does not identify
it as a particular DeepSeek or GLM model.

## Runtime path

```text
Pinned DSH AgentLoop + Cordis capability tool (untrusted)
             │ bounded model completion / tool proposal
             ▼
Local CPU llama.cpp child (offline, inside experimental AgentHost XPC)
             │ validated DSH completion
             ▼
Existing signed Trusted Launcher and per-operation UI
             ▼
Existing Security Kernel XPC → Seatbelt Runner → validated changeset
```

The Khaos capability tool accepts one bounded `{argv, readScope, writeScope}`
proposal. It cannot authorize a request or call Kernel RPC. Proposals still go
through the existing signed Launcher and Kernel path. The AgentHost and Node
child had no network-client entitlement in these local runs. The model adapter
uses a bounded JSON grammar and maps output only to a final response or the
single registered Khaos tool.

Limits recorded in the signed build: 2,048 completion tokens per call, at most
12 calls per task, 600 seconds per task, 56 KiB request/response bounds, and a
CPU-only llama.cpp process with `--offline`, `--device none`, and four threads.
Prompts and local model files were held in the signed app or private temporary
directories; prompt files were mode `0600` and removed after each call. Only
the synthetic benchmark prompt and returned synthetic tool text entered the
model context.

## Bound inputs and artifact

| Input | Bound value |
|---|---|
| Khaos PR #43 base | `fd6747abd9ba785f784126dd848112cffa782163` |
| PR #43 base's base (PR #41) | `b08ab11e01663d2b26304cb541efb5361dea0417` |
| DSH | `687f282e8625c6b8d11ff58211a90524be2e4317` |
| Node | `v22.19.0`, archive SHA-256 `1c3a9e78da501bbc1f0c99fbbb69bb7c722bc7a9bf30128b21ea502f3905892a` |
| Local GGUF | 18,556,689,568 bytes; SHA-256 `fadc3e5f8d42bf7e894a785b05082e47daee4df26680389817e2093056f088ad` |
| llama.cpp runtime | `0.5.0-dev` build 1, commit `7fe450e`; CPU-only |
| llama executable | SHA-256 `6a7ab29739b3dc68e11e6bfcde2116a19fcb68c883bc96199bd8e5d674b6b327` for the seven `55ac27c` trials; A-1 trial executable hash is recorded in its raw evidence |
| Benchmark data | SHA-256 `033f5d9c776f025e21642911b6d13e2afcc32b876a39fab377ae0a6279dc5091` |
| Signed experimental app | 18,765,873,305 bytes; team `UBAP6LN5AM`; deep strict signature verification passed |
| Source binding | Seven trials use `55ac27c5553ea91c64d5c47ad85907008079dc08`; A-1 was run at `26d6747fb7f371e98a89f1cc8a438a9a6146aace` after the local output parser fix. The signed runtime integration sources were unchanged between those SHAs. |

Each raw trial includes the build record digest, component hashes, signature
result, DSH/Node/model hashes, and compressed Launcher logs with hashes under
`reports/dsh-phase3/raw/`.

## Remote provider boundary

The Phase 3 benchmark selected the local model, so it used no API key and no
remote model request. A separate experimental BigModel bridge build was
exercised with signed-peer and bridge-protocol probes; it is not part of the
eight coding trials and those probes did not call a remote provider. Its test
build gives network-client entitlement only to the dedicated experimental
bridge XPC; AgentHost and Node remain network-denied. This bridge is not in the
production Seed builder and is not approved for production use. Remote model
quality, remote data consent, endpoint enforcement by macOS, and production
network policy remain **NOT_RUN / NOT_AUTHORIZED**.

## Evidence boundaries

- The local model was actually invoked: 17 sampled llama child process starts
  across eight trials. The count is process sampling, not complete provider
  call/token telemetry.
- The real DSH AgentLoop code path produced signed Launcher proposals. A-1
  shows a Runner result with return code 1 followed by another model proposal.
  Primary records do not contain the AgentLoop's full internal message history;
  detailed session continuity is therefore only partially instrumented.
- API keys, token counts, and cost are absent for the local route. Model token
  and cost values are `NOT_MEASURED` rather than inferred.
- The owner did not operate the UI. Signed UI operator records state
  `operator=codex_agent`, `owner_personally_clicked=false`, and
  `authorization=Owner-delegated disposable experiment`.
