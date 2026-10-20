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

The initial successful attack is bound to `efadf67` and remains historical.
Later fixture changes added result-block extraction and staged that helper into
the signed runtime. A subsequent clean signed run passed at
`b9414dfa2b0f777d8e6b8279ad9563231c52093b`, after correcting fixture callbacks
to read `options.messages`. No trusted code, Kernel ABI, scope, or production
build path changed.

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

On source SHA `87b75409c429210c6e7bfd49a50f8724c405ed9f`, the fallback text
showed two adapter requests, one assistant tool-call block, zero Launcher
proposals, and one `LlmError`. This narrows the failure to the DSH turn after
the tool-call response, before Launcher submission, but does not identify the
error or establish a security outcome. The failure is preserved at
`failed_attempts/signed-xpc-attack-87b7540-no-result.failed.json`. The fixture
now also captures bounded error code/message text and the final session message
shape; another signed run is needed to diagnose the LLM failure.

The next clean signed attempt on `f971d7fb0d42092ea993229ef8a8dba5c096bc94`
captured `LlmError` code `UNKNOWN` with message `messages is not iterable`.
The attack fixture callbacks passed the whole DSH request object to
`lastToolResult`, whose contract takes the request's `messages` array. This was
introduced when the helper changed from accepting a request object to accepting
messages. No Launcher proposal was submitted and no hostile-plugin assertion
ran. The attempt is retained at
`failed_attempts/signed-xpc-attack-f971d7f-no-result.failed.json`. All affected
fixture callbacks now pass `options.messages`, and the roundtrip test exercises
that callback shape. The clean signed rerun passed at source SHA
`b9414dfa2b0f777d8e6b8279ad9563231c52093b`; its evidence record is
`signed-xpc-attack-b9414df.json`.

On that SHA, direct and child-process workspace reads and writes were denied;
the dummy credential read was denied with zero credential-like environment
keys; localhost and external TCP attempts returned `EPERM`; and the published
Kernel binary write attempt was denied. The over-limit scope proposal was
rejected before reaching Launcher. The parent verified unchanged canaries and
Kernel hash, deep bundle signature, zero local TCP connections, and cleanup of
the Node process group. Child process execution itself was allowed while its
protected operations remained denied. Node RSS was 52,625,408 bytes and the
signed app bundle was 198,803,064 bytes. This run requested no Picker and made
no owner-approved Runner calls.

A clean signed rerun on exact source SHA
`a2765389989d7c4290eb754b459f2a516990d155` also passed. Its tracked evidence
is `signed-xpc-attack-a276538.json`. It records the same direct and child
process workspace denials, dummy credential denial, zero credential-like
environment keys, `EPERM` for localhost and external networking, denied write
to the published Kernel binary, blocked oversized scope, unchanged canaries
and Kernel hash, valid deep signature, zero local TCP connections, and clean
Node process-group teardown. Node RSS was 53,035,008 bytes; the signed app
bundle remained 198,803,064 bytes. No Picker or tool proposal was requested,
and no Runner call was approved. That result is historical evidence for
`a276538`, not the latest integration SHA.

The latest signed XPC attack passed on source SHA
`6962a07338da4c5ce1ddc5fa5eb3c68a62aab826`. Its tracked record is
`signed-xpc-attack-6962a07.json`. Direct and child-process workspace reads and
writes were denied; the dummy credential read and signed Kernel write were
denied; no credential-like environment key was present; localhost and external
TCP attempts returned `EPERM`; and the oversized scope was blocked. The parent
verified unchanged canaries and Kernel hash, zero local TCP connections, deep
bundle signature validity, and clean Node process-group teardown. Child process
execution itself was allowed while protected operations remained denied. Node
RSS was 52,428,800 bytes and the signed app bundle was 198,808,766 bytes. The
app, AgentHost XPC, Kernel XPC, and Snapshot Broker all reported Team ID
`UBAP6LN5AM` under signing certificate SHA-1
`81E5B3D53290732C30A9D823874EBAB6E947AB55`. No Picker or tool proposal was
requested and no Runner call was approved. This refreshes Phase 1 evidence at
`6962a07`; it does not prove owner-approved coding, cancellation, or crash and
recovery behavior.
