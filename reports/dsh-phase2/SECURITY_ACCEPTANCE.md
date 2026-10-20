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

The signed XPC attack passed on macOS for Khaos source SHA
`efadf67a35bb70e0441f737af457a619e7c8aae3`, PR #41 base
`b08ab11e01663d2b26304cb541efb5361dea0417`, and DSH SHA
`687f282e8625c6b8d11ff58211a90524be2e4317`. The successful external evidence
record is `/tmp/khaos-dsh-phase2/signed-xpc-attack-efadf67.json`.

Observed results: direct and child-process workspace reads and writes were
denied; the dummy credential read was denied and no credential environment key
was present; localhost and external TCP attempts returned `EPERM`; the
over-limit scope proposal was blocked; and the hostile Cordis plugin's attempt
to open the signed Kernel binary for writing was denied. The parent verified
matching Kernel hashes before and after, unchanged external canaries, deep app
signature, zero local TCP connections, and Node process-group cleanup after XPC
teardown. Child process execution itself was allowed, and its protected file
operations remained denied. No Launcher workspace Picker or tool proposal was
requested and there were zero owner-approved Runner calls.

This attack is bound to `efadf67`, not the later coding acceptance source SHA
`ddf41da`. The
later commits add result-block extraction to the untrusted DSH fixture and copy
that helper into the experimental build staging directory. No trusted code,
Kernel ABI, scope, or production build path changed. A signed attack on
`ddf41da` remains required before treating it as current-head evidence.

An earlier signed run at `a7a1074` launched the hostile XPC checks but used a
staging Kernel path that the builder removes after publish. Its Kernel probe
returned `ERROR_ENOENT`, so that attempt is retained as a failed fixture run,
not as Kernel write-denial evidence. The corrected run above exercised the
published signed Kernel and passed. The earlier standalone signed runtime
probe remains separate from this XPC evidence.

A later signed attempt on source SHA `8544e29cb351af7b6071a725afdf2d7c013145fa`
built and launched but returned the fixture fallback `DSH produced no final
text response`; the Launcher recorded zero proposals, so the hostile-plugin
checks did not run. It is preserved at
`failed_attempts/signed-xpc-attack-8544e29-no-result.failed.json` and is a
`FAILED_ATTEMPT`, not XPC enforcement evidence. A diagnostic retry was then
stopped by the builder's clean-worktree preflight before signing because a
test-only diagnostic edit was still uncommitted; that is separately recorded
at `failed_attempts/signed-xpc-attack-8544e29-clean-tree-preflight.failed.json`.
The experimental runtime fixture now waits on DSH's `Agent.whenIdle()` contract
and reports bounded request, message, and error-type counts. That adjustment
has not yet produced a new signed attack result.

The first clean diagnostic build on source SHA
`d1848f66756b4f918b1e6bc70194e1116d1addc4` again returned no final DSH text and
zero Launcher proposals. Its diagnostic object was discarded at the Swift
Host boundary because the reply protocol forwards only the `text` field. The
failed result is preserved at
`failed_attempts/signed-xpc-attack-d1848f6-no-result.failed.json`. The fixture
now places only those bounded counters and error type names in its empty-reply
text so the next run can expose where the DSH turn stopped. No hostile-plugin
checks passed on this SHA.
