# Candidate B Implementation Readiness

1. **Can Candidate B keep a single-file exact scope?** Yes for the tested fixed Staged Replacement: readScope and writeScope can both be exactly tags.py. B14 additionally proves that changing another readable file does not grant it commit authority.
2. **Can it use the existing Staged Replacement safely?** The tested script's unique-match, same-directory temporary file, exclusive create, fsync, atomic replacement, cleanup, exact scope, and complete changeset behavior pass the named L3 fixtures. This does not authorize production integration by itself.
3. **Can nonzero exit and commit outcomes be reported accurately?** The L3 suite separates process status from the actual changeset and final file state. B34 records commit-stage results. A post-commit error can be outcome-uncertain; no rollback is inferred.
4. **Can users accurately review the real operation?** The exact short ASCII request has signed evidence. Complex multiline, Unicode, escaped, and near-limit payload review in the signed dialog is NOT_PROVEN.
5. **Does this task require a Trusted Launcher change?** No production UI change was made. The existing dialog displays argv, scope, and encoded invocation digest; complex review still needs L4 evidence or a separately reviewed design.
6. **Does this task require a Kernel ABI change?** No. No production request or response field changed.
7. **Must workspace permissions be expanded?** No. Exact read/write scopes were retained.
8. **Does an unclosed security condition remain?** Yes: original Gate A L4 obligations for selected adversarial signed paths/lifecycle, B32 post-approval cancellation, B34 signed cancellation Task Record consistency, and B38 complex UI review remain NOT_PROVEN or BLOCKED_PENDING_APPROVAL.
9. **May M8.5.2B start?** No. M8.5.2B remains BLOCKED until technical Gate A requirements and review governance close.
10. **If a later Gate A decision permits M8.5.2B, which untrusted Host files are the current M8.5.1 recommendation?** AgentHost.swift for the edit instruction, constrained action grammar, and fixed translation; AgentHostActionOutput.swift to validate the exact shape and lower it into the existing AgentShellProposal. This is a scoped proposal from the existing architecture report, not authorization to edit either file now. Do not change AgentHostProtocol.swift, Kernel ABI, Launcher, Kernel, or Seatbelt policy in the M8.5.2A.2 task.

Independent Code Owner approval remains NOT_PROVEN in the single-maintainer configuration.

## Decision

The existing architecture can enforce the tested exact-scope and commit semantics without a production edit feature, wider authority, or trusted-code changes. The evidence does not prove every inherited signed-product condition. Candidate B production Edit integration is NOT_READY; do not treat this package as Gate A approval.
