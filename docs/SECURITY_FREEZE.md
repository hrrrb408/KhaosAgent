# Security Kernel freeze policy

Baseline: `12af8aa1e52b235234648b1f7eb925d648180e54` plus the reviewed
finalization change. `security/tcb-manifest.json` records exact SHA-256, role,
permission boundary and test mapping. Runtime TCB, build/governance inputs and
the development-only APFS backend are different classes. Tests are protected
governance inputs, not runtime TCB. The manifest and declaration cannot hash
themselves; their trust anchor is the reviewed Git commit, obtained independently.
A digest in the same writable directory is not an independent trust anchor.

Ordinary intelligence changes must leave protected files unchanged. New Kernel
files, new Swift enforcement files, workflows, tests, contracts and freeze files
are protected even if absent from the old manifest. AgentHost intelligence and
sandboxed Runner code remain untrusted. Shared AgentHostProtocol is trusted
because Launcher consumes it. Empty trusted Python package markers are included:
Python executes their future contents during trusted imports.

Run `python3 tools/check_security_freeze.py` to verify the inventory. On PRs,
CI also runs the **base commit's checker** against the proposed tree and base
inventory. A trusted change must update `security/security-change.json`, binding
the exact base SHA and sensitive file list, and explaining motivation,
invariants, authority delta, real OS regressions, trusted delta and the decision
about a new baseline. Regenerate hashes only after reviewing changed content.
A declaration is a review aid, not authorization. Never auto-update the manifest
to make a failing check green without review. Tests must pass at the proposed SHA.

## Actual single-maintainer enforcement

On 2026-10-16 the owner explicitly selected single-maintainer protection with
an acknowledged independent-review gap. GitHub main protection requires a PR and
up-to-date `security-tests` and `security-freeze` from GitHub Actions app 15368, includes administrators,
forbids force push/deletion, and requires resolved conversations. Approvals: 0;
Code Owner approval: disabled. The repository has one writable owner, who cannot
approve their own PR. CODEOWNERS routes review; it does not provide that missing
reviewer. No administrator bypass was added.

The initial PR first emitted a green `security-freeze` check, then that observed
context was added to the required checks. Do not require an unimplemented context
before its first bootstrap check exists.
Save and re-read API settings after applying changes. Settings evidence is a
dated snapshot, not permanent protection. An administrator can change settings.
A writable maintainer can rewrite Actions to emit the same context; independent
review of workflows is **NOT PROVEN**. An Agent with repository credentials has
those credentials' authority. Do not claim these gates resist a malicious owner.

To close the gap: add an independent writable reviewer, set approval count 1 and
require Code Owners, dismiss stale reviews and require last-push approval;
verify enforcement with a disposable PR. Any stronger external required workflow
or organizational policy needs a separate decision. Never bypass a blocked gate
or silently reduce required checks to deliver a change.
