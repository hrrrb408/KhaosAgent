# M8.1 — Security and TCB audit

## Runtime boundary

Production edits are confined to `khaos/macos/AgentHost.swift` and
`khaos/macos/AgentHostActionOutput.swift`, both untrusted Agent Host code. The
Host does not become an authority source. It still returns a typed proposal to
the existing Launcher; the Launcher continues to review each operation and the
Kernel continues to enforce exact scopes, sandbox policy, and workspace
changesets.

No changes were made to Kernel permissions, Seatbelt, XPC identity, workspace
scope enforcement, Snapshot Broker, changeset validation, Plugin admission,
activation approval, or `AgentHostProtocol.swift`. No new process, trusted IPC,
dependency, or persistent runtime state was added.

## Diagnostic data limits

Structured diagnostics are disabled by default and require
`KHAOS_AGENT_ACTION_DIAGNOSTICS=1` in the Agent Host environment. They go only
to Host stderr. The implementation rejects unsafe event error codes and emits
fixed stage/event labels, bounded counts, and missing names from the fixed
Action key list only. Unknown key names and values are never emitted. Each line
is capped at 512 bytes. Existing task and tool-call limits bound model-attempt
events to 216/session; one extra harness-state event is permitted, for 217
events maximum. No diagnostic code sends a model request or uploads data.

The original M8.0 evidence and hidden-test inputs were not changed. M8.1 makes
zero remote model calls. `KHAOS_AGENT_ACTION_DIAGNOSTICS` was absent from normal
focused and signed-product test processes; the compiled helper test explicitly
checks disabled output, then enables the flag only for its synthetic canary
case and verifies that neither canary names nor values appear.

## Fail-closed checks

The model output decoder continues rejecting malformed JSON, non-object JSON,
missing or extra keys, wrong field types, oversized model content, unsupported
Action types, invalid action fields, prohibited post-tool actions, and repeated
failed commands. The single correction remains format-only and is revalidated
before the existing Launcher approval boundary. A trusted `can_continue=false`
result still prevents another proposed tool action.

Host task-state rejection is logged at most once per Host session and retains
the existing `invalid_request` response. Tool-budget exhaustion is attributed
to `harness_state`; it is not called a model shape failure. These diagnostics
are informational and have no branch into acceptance, scope, or approval code.

## Security Freeze

The fresh declaration binds base
`27ef0b4787f807fc76ffd7ba9cdb467ffc9a2f27` and exactly five sensitive paths:
the two changed offline test files plus `security/security-change.json`,
`security/tcb-manifest.json`, and `security/freeze-baseline.json`. Their hashes
are updated from the reviewed working files. Runtime TCB manifest entries
remain byte-for-byte unchanged. The base-aware checker reports five declared
sensitive changes; the no-argument checker verifies the current manifest.
Independent Code Owner approval remains **NOT_PROVEN** in single-maintainer
mode, as recorded by the repository policy.

## Scope and limits

The canonical suite passed all 341 tests, including the Host helper probe and
the headless signed-bundle authentication test. The deterministic signed-product
coding acceptance also passed denial, Picker-cancel, budget, and Host-exit
writeback checks. This is evidence for a Host-only diagnostic and existing
approval regression, not a claim that all possible output or same-UID attacks
are prevented. The diagnostic does not reveal the old M8.0 raw response, which
remains unavailable. No model-quality or Hidden Test success claim follows from
deterministic helper or signed-product checks. See [TEST_REPORT.md](TEST_REPORT.md)
for commands and evidence boundaries.
