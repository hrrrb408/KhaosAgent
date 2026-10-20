# DSH Phase 2: Signed XPC Security Acceptance

Date: 2026-10-20

## Scope

The security probe runs a Cordis plugin loaded dynamically by the pinned DSH
runtime inside the signed `KhaosAgentHost.xpc`. It attempts direct and child
process file reads/writes, reads a dummy credential canary, inspects inherited
environment variable names, opens the signed Kernel binary for writing,
executes a child process, attempts localhost and external TCP connections, and
starts a descendant process. It also submits an over-limit scope proposal.

The untrusted plugin reports bounded operation outcomes only. The parent
process verifies canary hashes, the Kernel binary hash, deep bundle signature,
actual local listener connections, AgentHost parent PID, Node process-group
cleanup after XPC teardown, and the over-limit request result.

## Run

On macOS, use the repository's stable code-signing identity and the pinned
inputs:

```bash
python3 tools/run_dsh_xpc_attack_acceptance.py \
  --dsh-source /tmp/khaos-dsh-687f282 \
  --node-archive /tmp/node-v22.19.0-darwin-arm64.tar.xz \
  --signing-identity "<Apple Development identity>" \
  --mode attack \
  --evidence-path "$PWD/reports/dsh-phase2/signed-xpc-attack.json"
```

The script creates and signs a disposable app, launches it through Launch
Services, and deletes the app only after the run. It has no approval UI in the
attack mode. A successful result records the exact Khaos SHA, build record,
Node and DSH pins, app size, process IDs, canary checks, TCP connection count,
and signature verification.

## Current evidence

The signed XPC attack is `NOT_RUN` until the command above completes on macOS.
The earlier standalone signed runtime probe is not evidence for this XPC
service. A failed real XPC attempt must be retained and analyzed; it must not be
replaced with a rerun that hides the failure.
