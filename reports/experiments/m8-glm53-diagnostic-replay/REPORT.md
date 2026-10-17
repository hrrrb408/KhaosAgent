# M8.2 GLM-5.3 Diagnostic Replay — Preflight Blocked

**Experiment Closure:** `BLOCKED`; **Action Contract Root Cause:** `NOT_PROVEN`; **Coding Outcome:** `NOT_RUN`; **Coding Reliability Closure:** `NOT_PROVEN`.

The signed-Host diagnostic capture gate failed before remote authorization. The
formal model attempt, tool operations, diagnostic events, and independent hidden
grading are all `NOT_RUN` (zero requests and zero operations).

## Environment and PR dependency

- Worktree: `experiment/m8-2-glm53-diagnostic-replay`, based on exact PR #28
  head `fd21764381546140249d94fcf53f9737bc9d212f`.
- PR #27 remains open at `5acf90bcc0ff02e764e84150ebcebe91536ebc26`; PR #28
  remains open at the M8.1 head above. Neither was modified.
- Preflight host: macOS 27.0.1, arm64, Python 3.13.4.
- Separately built signed product:
  `/Users/huangruibang/Applications/Khaos-M8.2-Diagnostic-Preflight.app`.
- The product source selects provider `bigmodel-coding-plan`, model `glm-5.3`,
  and endpoint
  `https://open.bigmodel.cn/api/coding/paas/v4/chat/completions`. The planned
  data categories were task text, active Plugin metadata, proposed argv and
  paths, scoped file/listing text, command return codes, changed-path lists,
  and bounded stdout/stderr. No data-send authorization was requested and no
  task data was transmitted. The Launcher still displays the stale
  label `BigModel GLM-5.3-Flash Coding Plan`; that mismatch would have required
  disclosure before a new data-send authorization.

## Frozen task and model configuration

- Task: `runner-exception-classification`; prompt SHA-256
  `7a86c99de62538d4c514cb0f5fa1dd31d747701be60f03c12d4a2420736810a2`.
- Workspace baseline: `7b6af61b3925b28ef105ea521c49424344de04c5`.
- Hidden-test patch SHA-256:
  `185ea8ada844d790c0d716b2d7d921c8c4e739b238baa5d1b7b325e6fc446e16`;
  its contents were not read, printed, or sent to a model.
- Planned request settings match the prior GLM-5.3 experiment: temperature 1,
  top-p 0.95, reasoning `max`, thinking enabled with `clear_thinking=false`,
  JSON object response, non-streaming, 32,768 output tokens, existing 600-second
  request timeout, and the original one-correction policy. Tool budgets remain
  8 calls, 180 cumulative Runner seconds, 30 seconds per operation, 4 KiB per
  result, and 32 KiB aggregate. No setting was increased; see
  [experiment-config.json](experiment-config.json) for the complete record.

## Decision

The real GLM-5.3 replay did not start. The opt-in diagnostic flag can reach a signed Agent Host XPC process when supplied in that service's `XPCService.EnvironmentVariables`, but the Host's stderr file descriptor is `/dev/null`. Capturing it with `launchctl debug --stderr` requires root privileges on this machine. No bounded diagnostic line can therefore be collected from the signed service under the available non-root path.

The remote call was stopped before task data was sent. No fresh authorization was requested, no model API request was made, and no hidden grader was run. The API key environment variable was absent. The temporary user launchd environment override was removed after the probe.

Apple documents `EnvironmentVariables` as an XPC service property. That enables the diagnostic flag for a specific signed service; it does not provide a stderr capture path. See [Apple's XPCService property documentation](https://developer.apple.com/documentation/bundleresources/information-property-list/xpcservice/environmentvariables).

## Preflight evidence

- The isolated branch `experiment/m8-2-glm53-diagnostic-replay` starts at PR #28 head `fd21764381546140249d94fcf53f9737bc9d212f`. PR #27 and PR #28 remain open and untouched. PR #28's `security-freeze` and `security-tests` checks pass on that exact head.
- The only source change is the one-line Agent Host model selection change from `glm-5.3-flash` to `glm-5.3`. The Launcher still displays the stale label `BigModel GLM-5.3-Flash Coding Plan`; that mismatch would need to be disclosed before any future authorization.
- A signed Coding Plan product was built at `/Users/huangruibang/Applications/Khaos-M8.2-Diagnostic-Preflight.app`. Deep signature and builder verification passed. Its `--bootstrap-check`, launched through Launch Services, returned `kernel-and-snapshot-broker-peer-authentication=verified` with empty stderr. The built product remains diagnostics-off by default.
- A disposable signed XPC fixture, derived from the product's Agent Host service bundle, added the documented per-service environment value `KHAOS_AGENT_ACTION_DIAGNOSTICS=1` and preserved the Host entitlements. A signed client sent a synthetic `tool_result` without a pending proposal. The XPC Host returned `invalid_request`, and the flag was observed in that Host process. This path rejects before model completion and did not send a task or call a model API.
- The fixture's Host stderr descriptor was `/dev/null`; the filtered unified-log query yielded no M8.1 diagnostic line. `launchctl debug ... --stderr` returned `This subcommand requires root privileges: debug`. The actual product bundle was not configured with the diagnostic variable, and its Agent Host service was not started during the bootstrap check.
- The frozen prompt SHA-256 matches M8.0 (`7a86c99d…6810a2`). The hidden patch SHA-256 matches (`185ea8ad…446e16`) and its contents were not read, printed, or transmitted. The exact baseline commit is present as `HEAD` and `refs/heads/main` in the frozen task bundle; it is not present as an object in this PR #28 checkout. The benchmark dataset was not modified.

## Historical evidence and conclusion

The M7 GLM-5.3-Flash run (`m7-2-context-01`) completed one approved list
operation with return code 0, made no edits, ran no model tests, then terminated
with `invalid_agent_action_wire_contract_after_correction`; its independent
hidden test returned 1. M8.0 GLM-5.3 completed six approved operations, all
return code 0, made no edits, ran no model tests, then terminated with
`invalid_model_output_shape`; its hidden grader failed. Both historical runs
used the frozen task prompt, baseline, hidden patch, endpoint, and stated
budgets. Their models and product source commits differ, hosted model weights
are not pinned, and sampling is stochastic, so this is historical comparison,
not a controlled causal experiment. See [comparison.json](comparison.json).

M8.0 ended with `invalid_model_output_shape` after six approved operations that returned code 0; it made no edits and failed the independent hidden grader. Its rejected response was not retained. The evidence does not identify a missing or extra field, establish whether the initial or correction response failed, or show that context construction caused the failure.

M8.2 produced no new model behavior to attribute. The historical root cause remains `NOT_PROVEN`; Action Contract Reliability and Coding Task Completion Reliability remain separate and unresolved. The offline diagnostic tests pass, but that does not substitute for a collectable signed-XPC diagnostic event or real-model evidence.

## Validation

- `python3 -m unittest discover -s tests -v` — **PASS**, 341 tests in 695.275 seconds.
- `python3 tools/check_security_freeze.py` — **PASS**, sensitive changes 0; independent approval remains external.
- Signed product deep verification — **PASS**.
- Signed product Kernel and Snapshot Broker peer authentication — **PASS**.
- Signed XPC diagnostic flag propagation in the disposable fixture — **PASS**.
- Signed XPC diagnostic stderr capture — **BLOCKED** (`/dev/null`; redirection command requires root).
- M8.2 model request and hidden grading — **NOT_RUN**.

## M8.3 direction

This blocked preflight provides no M8.2 model evidence for an Action Contract,
Correction, Context, Planning, or code-understanding change. Keep those repair
directions unselected. First establish a reviewed, bounded way to collect the
existing diagnostics from the actual signed Agent Host under the current trust
boundaries; then obtain fresh data-send authorization and run the single frozen
attempt. Do not label the historical shape failure fixed or reproduced by this
preflight.

## Change accounting

```text
Production code delta: 1 model identifier string in untrusted Agent Host
Trusted code delta: 0
New architecture concepts: 0
New trusted processes: 0
New IPC operations: 0
New persistent state: 0
New dependencies: 0
Removed duplication / abstractions: 0
Runtime TCB delta: 0
```

The next M8.2 attempt needs a reviewed, explicit, bounded diagnostic capture path that works for the signed Agent Host XPC without root privileges. Until that gate is proven, the GLM-5.3 replay remains `NOT_RUN`.
