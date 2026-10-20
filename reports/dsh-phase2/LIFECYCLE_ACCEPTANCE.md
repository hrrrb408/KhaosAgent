# DSH Phase 2: Lifecycle Acceptance

Date: 2026-10-20

The test-only XPC override runs the DSH runtime in its own process group. It
rejects overlapping frames, bounds frames, returns a failed Host operation
without retrying it, stops the Node process group when the XPC session closes,
and accepts only a fresh `user` operation after a failed runtime. Old
`tool_result` frames are rejected once the prior request is no longer pending.

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

All signed cancellation and Node crash/recovery cases remain `NOT_RUN` until
the owner completes their UI actions and the scripts emit their evidence
files. DSH's AbortSignal is only an untrusted adapter signal; the Launcher task
record and original Kernel reply remain the authority for completion.
