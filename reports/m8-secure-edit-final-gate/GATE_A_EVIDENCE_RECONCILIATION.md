# Gate A Evidence Reconciliation

## Evidence reuse assessment

The M8.5.2A.1 matrix distinguishes L3 (real macOS Seatbelt Runner plus Kernel changeset path) from L4 (signed Launcher, explicit user decision, XPC Kernel, Runner, and final workspace inspection). The new B14 fixture uses the fixed Candidate B script and a read scope that differs from the exact write scope; it directly proves the Kernel rejects the entire private-snapshot changeset. B34 now has deterministic L3 evidence at pre-commit, before the commit-gate ACCEPT, and after a test callback observes the committed live file. B38 adds synthetic offline serialization and bounds evidence.

Those L3 results may support the same Kernel-owned invariant where the fixed script, exact scopes, complete changeset validator, and commit implementation match. This is recorded as EVIDENCE_REUSE_PROPOSED. No original L4 requirement is waived. L4-only risks remain at the signed Launcher and XPC entry, the user-visible approval surface, the digest and request binding in the signed product, cancellation/terminal Task Record behavior, and final signed workspace observation.

## What can be reused

- Candidate B L3 positive, failure, scope, symlink, hardlink, race, cancellation, termination, and changeset evidence supports the shared Kernel/OS enforcement behavior for those exact fixtures.
- B14's new Result B is direct evidence that readable data does not receive commit authority.
- B34's commit gate test is the same real broker gate used by the product's Kernel path; it proves cancellation before ACCEPT prevents live mutation. The post-commit L3 test records the actual successful result and hashes.
- Existing `process_not_active` handling and `commit_outcome_uncertain` path are retained; no test converts them into a presumed rollback.

## What cannot be reused as L4

- A generic Kernel test does not prove Launcher approval display, XPC peer identity, request-digest binding, or that the same proposal was shown and executed in the signed product.
- A short signed operation does not prove that a long, escaped, multiline or Unicode request is fully visible and understandable.
- A user refusal before execution is not post-approval cancellation.
- A successful signed edit Task Record is not evidence for a cancellation race or an uncertain commit result.
- CI success and single-maintainer review do not replace independent Code Owner approval.

## Disposition

No Gate A requirement was lowered. B14 and B34 are PASS_L3, with inherited L4 conditions retained where they apply. B38 offline checks pass for their synthetic cases, while complex signed review remains NOT_PROVEN. B32 remains BLOCKED_PENDING_APPROVAL. The matrix marks unapproved reuse as EVIDENCE_REUSE_PROPOSED. Independent security approval is NOT_PROVEN, so the technical gate is not closed and M8.5.2B remains BLOCKED.
