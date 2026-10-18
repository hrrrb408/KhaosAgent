# Security Invariants and Change Boundary

## Preserved invariants

- Candidate B remains an untrusted Host proposal represented by the existing Shell action. No Kernel capability or workspace authority is derived from the proposal itself.
- Read scope and write scope remain independent. B14 proves that a readable target outside the exact write scope can be changed only in the private Snapshot; the Kernel rejects the complete changeset before live mutation.
- The Kernel validates the complete added/modified/deleted set against the retained exact write scope. A nonzero Runner result and actual committed state are reported separately.
- Cancellation is classified by its observed commit stage. Before ACCEPT, cancellation aborts live mutation. After ACCEPT, the result is based on the actual completed or uncertain commit outcome; no rollback is inferred from a cancellation label.
- Complex payloads remain bounded by the existing AgentHostProtocol frame, argument-count, argument-byte, scope, and control-character checks. The Host cannot replace the visible argv with a summary.
- Remote-model input, capability grants, approval rules, and trusted runtime code remain unchanged.

## Change delta

Production code delta: 0 files, 0 lines.

Trusted code delta: 0 Runtime TCB files, 0 Runtime TCB lines. The modified Swift file is a build-governance test probe, not the production AgentHostProtocol or Launcher. The Python changes are protected tests only.

New trusted processes: 0. New IPC operations: 0. New persistent product state: 0. New dependencies: 0. Runtime authority delta: 0.

The test-only probe adds two B14/B34 tests and synthetic B38 serialization cases. Security declaration, test inventory hashes, and this evidence package are governance/report changes. No production architecture concept was added.
