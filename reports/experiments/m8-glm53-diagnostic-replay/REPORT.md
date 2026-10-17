# M8.2 GLM-5.3 Diagnostic Replay — Capture Proven, Awaiting Authorization

**Experiment Status:** `AWAITING_EXPLICIT_REMOTE_DATA_AUTHORIZATION`; **Action Contract Root Cause:** `NOT_PROVEN`; **Coding Outcome:** `NOT_RUN`; **Coding Reliability Closure:** `NOT_PROVEN`.

The local signed-Host diagnostic capture gate now passes. One synthetic event was
captured; it is not a model event. No formal model attempt, tool operation, task
data transmission, or independent hidden grading has occurred. A fresh explicit
user authorization is still required before contacting BigModel.

## Environment and PR dependency

- Worktree: `experiment/m8-2-glm53-diagnostic-replay`, based on exact PR #28
  head `fd21764381546140249d94fcf53f9737bc9d212f`.
- PR #27 remains open at `5acf90bcc0ff02e764e84150ebcebe91536ebc26`; PR #28
  remains open at the M8.1 head above. Neither was modified.
- Preflight host: macOS 27.0.1, arm64, Python 3.13.4.
- Signed experiment product:
  `/Users/huangruibang/Applications/Khaos-M8.2-GLM53-Diagnostic-Ready.app`.
  It selects `bigmodel-coding-plan` and its Agent Host source selects
  `glm-5.3`. The per-service diagnostic flag is enabled in this signed test
  product; the normal builder output remains default-off.
- The product source selects provider `bigmodel-coding-plan`, model `glm-5.3`,
  and endpoint
  `https://open.bigmodel.cn/api/coding/paas/v4/chat/completions`. The planned
  data categories were task text, active Plugin metadata, proposed argv and
  paths, scoped file/listing text, command return codes, changed-path lists,
  and bounded stdout/stderr. No fresh data-send authorization has been given and no
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

The initial real GLM-5.3 replay preflight stopped because the app-private XPC stderr descriptor is `/dev/null` and the authorized launchd redirection attempts could not capture it.

After the owner authorized a one-time stderr redirect, I authenticated and tried `launchctl debug` against the app-embedded XPC service. The stable `gui/501/org.khaos.Seed.AgentHost` target was absent. While a signed synthetic client kept the actual product XPC alive, `launchctl list` exposed a transient `application.org.khaos.Seed...` label, but `launchctl debug gui/501/<transient-label>` still returned error 113, “Could not find specified service.” Bootstrapping a copied XPC bundle made a stable target addressable, but created a separate launchd service; the product Launcher's `NSXPCConnection(serviceName:)` continued to start its own bundle-private service. The temporary registration was removed and the stuck privileged `launchctl` client was terminated.

I also re-signed a disposable copy of the signed product with `KHAOS_AGENT_ACTION_DIAGNOSTICS=1` and `StandardErrorPath` set both at the XPC bundle's top level and inside `XPCService`. The signed Host observed the opt-in flag and returned the expected synthetic `invalid_request`, but both stderr capture attempts produced a zero-byte file. At that point the diagnostic gate remained blocked; the later OS unified-log validation below resolves the capture gate.

The real model call remains stopped before task data is sent. No fresh authorization has been requested yet, no model API request was made, and no hidden grader was run. `KHAOS_BIGMODEL_API_KEY` was absent from all preflight processes; no API key was used. The temporary user launchd environment override was removed after the earlier stderr probe.

The stderr-only capture method was abandoned after the authorized attempts failed. `AgentHostActionOutput.swift` now sends only the existing bounded, redacted diagnostic line to OS unified logging under subsystem `org.khaos.Seed.AgentHost` and category `action-diagnostics`. The opt-in flag is still required. A disposable signed NSXPC harness reused the exact Agent Host executable code from the signed product, preserved its App Sandbox and network-client entitlements, and set the documented per-service flag. The synthetic `tool_result` was rejected as `invalid_request` before model completion. The filtered unified log contained exactly one event:

```text
event=harness_state_rejected attempt=none stage=harness_state error=tool_result_without_pending_proposal
```

The event was 104 UTF-8 bytes, below the 512-byte limit, and contained none of the synthetic text. The API key was absent and the request count was zero. This proves the signed Host diagnostic transport; it does not count as a formal model attempt or model diagnostic.

Apple documents `EnvironmentVariables` as an XPC service property. That enables the diagnostic flag for a specific signed service; it does not provide a stderr capture path. See [Apple's XPCService property documentation](https://developer.apple.com/documentation/bundleresources/information-property-list/xpcservice/environmentvariables).

## Preflight evidence

- The isolated branch `experiment/m8-2-glm53-diagnostic-replay` starts at PR #28 head `fd21764381546140249d94fcf53f9737bc9d212f`. PR #27 and PR #28 remain open and untouched. PR #28's `security-freeze` and `security-tests` checks pass on that exact head.
- The source selects model `glm-5.3`; the Launcher still displays `BigModel GLM-5.3-Flash Coding Plan`. This mismatch must be disclosed before remote-data authorization; the trusted Launcher label was not changed.
- A signed Coding Plan product was built at `/Users/huangruibang/Applications/Khaos-M8.2-GLM53-Diagnostic-Ready.app`. Its per-service diagnostic flag is enabled in this experiment-only signed product. The nested build record was refreshed after the overlay. Deep signature verification, `build_macos_seed.py --verify-app`, and its Launch Services `--bootstrap-check` all passed; the bootstrap returned `kernel-and-snapshot-broker-peer-authentication=verified` with empty stderr.
- A disposable signed XPC fixture reused the exact Agent Host executable code from the signed product, preserved its App Sandbox and network-client entitlements, and supplied `KHAOS_AGENT_ACTION_DIAGNOSTICS=1` through `XPCService.EnvironmentVariables`. A signed Launcher-identity client sent one synthetic `tool_result` without a pending proposal. The Host returned `invalid_request` and emitted exactly one OS unified-log event. The event contains only fixed diagnostic fields, is 104 UTF-8 bytes, and omits the synthetic text. It is saved in [diagnostic-events.jsonl](diagnostic-events.jsonl).
- Historical stderr attempt: a disposable re-signed product copy received the opt-in diagnostic environment through `XPCService.EnvironmentVariables`. Its signed Host returned `invalid_request` for a synthetic `tool_result` without a pending proposal, with no model request or workspace access. `StandardErrorPath` at both tested plist locations left the mode-0600 capture file empty.
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

M8.2 has produced no new model behavior to attribute. The historical root cause remains `NOT_PROVEN`; Action Contract Reliability and Coding Task Completion Reliability remain separate and unresolved. The synthetic signed-XPC event proves capture only; it is not model evidence.

## Validation

- Focused Agent Host diagnostics probe — **PASS**, 1 test in 1.862 seconds.
- `python3 -m unittest discover -s tests -v` — **PASS**, 341 tests in 696.520 seconds.
- `python3 tools/check_security_freeze.py --base fd21764381546140249d94fcf53f9737bc9d212f` — **PASS**, four declared protected changes.
- `python3 tools/check_security_freeze.py` — **PASS**, current manifest inventory verified; independent Code Owner approval remains **NOT_PROVEN**.
- Signed GLM-5.3 Coding Plan product deep signature and builder verification — **PASS**.
- Signed product Kernel and Snapshot Broker peer authentication through Launch Services — **PASS**.
- Signed Host OS unified-log capture — **PASS** for one synthetic invalid `tool_result`; 104-byte redacted event, no API request.
- Frozen prompt, workspace bundle, hidden-test patch hash, and baseline refs — **PASS**; the hidden patch was only hashed, not displayed or transmitted.
- `git diff --check` — **PASS**.
- M8.2 real model request and hidden grading — **NOT_RUN**, pending fresh explicit remote-data authorization.

## Next gated action

This preflight provides no M8.2 model evidence for an Action Contract,
Correction, Context, Planning, or code-understanding change. Keep those repair
directions unselected. The signed Host capture path and local/security checks
pass. Before any model request, disclose the exact endpoint, model, data
categories, stale Launcher label, one-attempt limit, and existing per-operation
approval requirements; then obtain fresh explicit authorization. Until it
arrives, keep the replay and hidden grading `NOT_RUN`. Do not label the
historical shape failure fixed or reproduced by this preflight.

## Change accounting

```text
Production code delta: AgentHost.swift selects glm-5.3 for this replay; AgentHostActionOutput.swift sends opt-in sanitized diagnostics to OSLog
Trusted code delta: 0
New architecture concepts: 0
New trusted processes: 0
New IPC operations: 0
New Khaos-owned persistent state: 0; macOS may retain bounded opt-in OS unified-log records under platform policy
New dependencies: 0 (OSLog is a system framework)
Removed duplication / abstractions: 0
Runtime TCB delta: 0
```

The signed Host diagnostic capture gate is proven. The GLM-5.3 replay remains
`NOT_RUN` until the user explicitly authorizes the remote data flow.
