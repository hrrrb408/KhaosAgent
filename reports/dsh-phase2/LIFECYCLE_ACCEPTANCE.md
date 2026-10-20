# DSH Phase 2: Lifecycle Acceptance

Date: 2026-10-20

The test-only XPC override runs the DSH runtime in its own process group. It
rejects overlapping frames, bounds frames, returns a failed Host operation
without retrying it, stops the Node process group when the XPC session closes,
and accepts only a fresh `user` operation after a failed runtime. Old
`tool_result` frames are rejected once the prior request is no longer pending.

## Cordis capability lifecycle

This signed mode exercises the pinned Cordis `ToolRuntime` inside the test
AgentHost XPC. It does not request a workspace, open a Picker, submit a
Launcher proposal, or require owner approval. It checks single registration,
duplicate registration rejection, removal on unload, rejection of a late
result after unload, rejection of calls after unload, and closure after a
terminal Launcher result.

Run on macOS with the pinned DSH and Node inputs:

```bash
python3 tools/run_dsh_xpc_attack_acceptance.py \
  --dsh-source /tmp/khaos-dsh-687f282 \
  --node-archive /tmp/node-v22.19.0-darwin-arm64.tar.xz \
  --pnpm /tmp/khaos-dsh-corepack/pnpm \
  --signing-identity "<Apple Development identity>" \
  --mode plugin-lifecycle \
  --evidence-path "$PWD/reports/dsh-phase2/cordis-plugin-lifecycle.json"
```

## AgentHost XPC failure and recovery

This owner-driven signed run terminates the test AgentHost XPC after the
Kernel has committed the first task's scoped edit, while the XPC is delivering
that original result. Select the printed disposable workspace and approve the
edit. Then approve the second task's separate `tags.py` read after the Launcher
connects to a fresh AgentHost XPC:

```bash
python3 tools/run_dsh_xpc_attack_acceptance.py \
  --dsh-source /tmp/khaos-dsh-687f282 \
  --node-archive /tmp/node-v22.19.0-darwin-arm64.tar.xz \
  --pnpm /tmp/khaos-dsh-corepack/pnpm \
  --signing-identity "<Apple Development identity>" \
  --mode xpc-crash \
  --evidence-path "$PWD/reports/dsh-phase2/agenthost-xpc-crash-recovery.json"
```

The acceptance checks one transport failure, two unique task and request
identities, the first task's committed Kernel result and XPC failure reason,
the new task's own successful result, unchanged canary, no automatic retry,
and no surviving Node process from the terminated XPC. This is separate from
the Node child-crash check below.

## Signed cancellation

The acceptance builder reuses `tests/signed_cancellation_fixture.py` against a
private source snapshot. The production builder and production source tree are
not overlaid. Candidate B uses the fixed script exported by the existing
trusted parser probe, exact `tags.py` read/write scopes, and one Launcher
approval. The script requires the owner to select the disposable workspace,
review the signed Candidate B preview, approve it, and click **Cancel task** at
the named barrier.

Run each case separately so its evidence stays bound to one signed app and one
timing barrier:

```bash
python3 tools/run_dsh_xpc_attack_acceptance.py \
  --dsh-source /tmp/khaos-dsh-687f282 \
  --node-archive /tmp/node-v22.19.0-darwin-arm64.tar.xz \
  --signing-identity "<Apple Development identity>" \
  --mode cancellation --cancellation-case b32 \
  --evidence-path "$PWD/reports/dsh-phase2/cancellation-b32.json"
```

Repeat with `--cancellation-case pre-commit` and
`--cancellation-case post-commit`, changing the evidence filename. The script
waits for the actual signed cancellation acknowledgement. For pre-commit it
releases the fixture barrier only after the exact original XPC request's
cancellation is observed in the Kernel event file. Post-commit must leave the
committed edit in the workspace. B32 must show no Kernel submission or Runner.
Each report checks the original Kernel result, task record, Candidate B
approval, one request identity, and DSH's terminal-result receipt.

## Node crash and recovery

This user-driven check crashes Node after the first actual Kernel result is
returned to the Host. It then sends a second task through the signed product,
which must use a fresh AgentHost connection and unique task/request identities.
Approve the two displayed read operations independently:

```bash
python3 tools/run_dsh_xpc_attack_acceptance.py \
  --dsh-source /tmp/khaos-dsh-687f282 \
  --node-archive /tmp/node-v22.19.0-darwin-arm64.tar.xz \
  --signing-identity "<Apple Development identity>" \
  --mode node-crash \
  --evidence-path "$PWD/reports/dsh-phase2/node-crash-recovery.json"
```

The script checks that the first Kernel result remains recorded, the failed
AgentHost turn is not retried, the next task completes, and Node process groups
are gone after XPC teardown. It does not turn the Node crash into evidence for
every possible abrupt AgentHost termination or IPC race.

## Current evidence

The signed Cordis capability lifecycle run passed at source SHA
`81923b77e0c632291cdc317e396a62edca75fba1`. Its record is
`cordis-plugin-lifecycle-81923b7.json`. The signed app, AgentHost XPC, Kernel
XPC, and Snapshot Broker all reported Team ID `UBAP6LN5AM`; the signing
certificate SHA-1 was `81E5B3D53290732C30A9D823874EBAB6E947AB55`. Deep bundle
signature verification passed, the Kernel hash stayed unchanged, no Picker or
proposal appeared, no Runner approval was requested, and the Node process group
exited after XPC teardown. All seven lifecycle checks passed. This is signed
Cordis/Host-process evidence; it does not exercise a real workspace operation
or prove XPC crash recovery.

The first signed build attempt at source SHA `4be7cf27ff8a76ef518517fc692e5fe8c424d5f7`
failed before signing because the new runtime helper was hashed but omitted
from the temporary DSH staging directory. The failure is retained at
`failed_attempts/plugin-lifecycle-4be7cf2.failed.json`; staging was fixed before
the passing run.

Signed cancellation, Node crash/recovery, AgentHost XPC crash/recovery,
Read → Edit → Test completion, and fake-result acceptance remain `NOT_RUN` or
incomplete pending their separate owner UI actions. DSH's AbortSignal is only
an untrusted adapter signal; the Launcher task record and original Kernel
reply remain authoritative for completion.
