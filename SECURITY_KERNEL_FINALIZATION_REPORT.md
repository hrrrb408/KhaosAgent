# Security Kernel Finalization Report

Date: 2026-10-16. Audit base: `12af8aa1e52b235234648b1f7eb925d648180e54`.
The product remains `Untrusted AgentHost → Trusted Launcher → Kernel → Seatbelt Runner`.
This report distinguishes tested paths, writable development assumptions and
unproven protections. No paid Apple membership, notarization, disabled system
security, new daemon or privileged service is required or introduced.

## A. TCB files and boundaries

Exact file hashes, source modes, roles and regression families are in
[`security/tcb-manifest.json`](security/tcb-manifest.json): 34 runtime TCB files,
65 build/governance inputs and one development-only enforcement backend at the
initial inventory. Counts may increase only through a declared reviewed update.
The inventory includes Launcher/Picker, shared protocols and peer identity,
Kernel XPC/Bootstrap/Python, Snapshot Broker/APFS lease handling, lifecycle,
sandbox, changesets and trusted package imports. AgentHost intelligence files,
Runner/SDK, Plugins and model runtime remain untrusted. The Python framework and
system toolchain are external runtime/build dependencies recorded per artifact,
not misleadingly enumerated as Khaos source TCB. Test-family mapping is not line
coverage or proof every input is safe.

Attacker A: Khaos sandbox-confined Agent/Plugin/Runner. B: ordinary unconfined
same UID, no administrator authorization, with existing group memberships.
C: administrator/root/system-trust modification; outside guarantees. B can modify
the source checkout, user installation, data and signing operations permitted by
Keychain. A cannot use those host freedoms merely because it shares the UID.

The manifest is not its own trust root: use the reviewed commit obtained through
an independent channel. Build/governance changes can alter future authority even
though they do not execute in the runtime TCB. Their review is separately guarded.

## B. Self deployment and signing

The existing `tools/build_macos_seed.py` is the only builder. Additions:

- Select exactly one available identity by full name or certificate fingerprint.
- Compile/copy from private source snapshots; reject source symlinks and optionally
  enforce an independently reviewed exact source SHA-256 map.
- Seal source/dependency hashes, builder digest and environment versions in
  `Contents/Resources/build-inputs.json` before final outer signing.
- Verify actual nested code against an externally supplied certificate fingerprint,
  fixed bundle IDs and configured XPC peer requirements; reject Host as Launcher.
- Publish through exclusive macOS rename, refusing existing or raced output paths.
- Reuse the same verifier via `--verify-app`; reuse `--bootstrap-check` for peer
  readiness and the canonical suite for real Seatbelt/APFS readiness.

The existing staged assembly/signing still derives stable requirements before
embedding dependent bundles and final signing. There are no post-final-sign
bundle writes. Failure removes private staging. Some embedded Python binaries
use nested ad-hoc signatures; outer Launcher/XPC identities are stable, not
ad-hoc. The build is local, architecture-specific and not byte-reproducible.
Hashes record the packaged framework; they do not authenticate a compromised
compiler, SDK, Python installation or same-UID build host. This limitation remains.

`docs/SELF_HOSTING.md` describes free Keychain Certificate Assistant provisioning,
input review, exact-product verification, install/update/rollback/uninstall and
protected-mode consent. Persistent production private keys stay in Keychain.
Existing canonical test provisioning creates a disposable self-signed identity,
exports test-only key material within its temporary fixture, then removes it and
restores Keychain search state. No key material is committed or bundled.

A fresh controlled App built with the existing local certificate. User-owned
install/restart/identical-version replacement/rollback/uninstall passed actual
Launch Services bootstrap and post-run signature checks: `self-host.json`.
This is app restart, not an OS reboot; this is replacement testing, not a distinct
release/state migration. Those broader acceptance items remain NOT PROVEN.

## C. Persistent state, keys and update audit

`activation.key` mode 0400, `activation.json` mode 0600, no-follow descriptors,
nlink/owner/schema/digest checks and HMAC do not establish a different OS owner.
A same-UID writer can unlink and replace both. Candidate/source/state files in
the user-owned store are likewise not a B-resistant trust root. Opaque Memory
business state does not become trusted simply because it persists via Kernel.
No schema, state migration or extra business database was added.

Code signing authenticates/detects changes; it does not deny writes. Current
products have no Hardened Runtime. Running mappings versus replaced on-disk
code, DYLD injection, a compromised signing operation and same-signer malicious
updates remain independent risks. Verification immediately before launch narrows
an accidental substitution window but is not an atomic launch or general B defense.
No automatic updater or privileged background authority was added.

## D. Real same-UID experiments and protected install

All experiments used disposable artifacts, not actual Plugin state or other apps.
`reports/security-kernel-finalization/same-uid.json` records:

- UID 501 without elevation replaced a 0400 lifecycle key and correctly formed
  activation envelope; `_read_state` accepted the changed generation (17).
  This is a valid-state authentication-root counterexample, not a confined
  Candidate self-activation success claim. Initial malformed state was rejected;
  an incorrectly sized replacement key was rejected before the corrected attack.
- Owner-readonly App files/directories were replaced through a writable parent.
- `/Applications` is root:admin 0775 and writable by this admin-group UID.
  Root ownership of the bundle alone would not stop replacement there.

The owner explicitly approved `/Library/Application Support/Khaos` and macOS
administrator authorization. `protected-install.json` records a root:wheel 0755
App and parent, non-user-writable ancestors and ACL observations. Six real B
attacks received EACCES: Launcher write-open, nested Kernel write-open, App
rename, nested XPC rename, parent rename and symlink creation. Actual install,
app restart, same-version update, rollback and post-operation signature/peer
checks passed. Uninstall removed the exact disposable apps and test parent.
No system security setting was changed; no system service was installed.

These are tested filesystem denials for protected code. They do not prove all
same-UID attacks fail. Protected state, runtime injection, hostile signing-key
use, OS restart and distinct-version migration remain NOT PROVEN. A protected
state writer would require a new, separately approved OS authority boundary;
this change does not introduce it.

## E. Freeze governance

`docs/SECURITY_FREEZE.md`, exact manifest/baseline, change declaration, base-tree
checker, security PR template, CODEOWNERS and a deterministic CI job establish a
reviewable freeze process. New trusted paths, tests and workflows are sensitive;
removing a path from a proposed manifest does not remove the base's protection.
The initial bootstrap is explicit because the base lacks a checker. A security
change declaration is not human approval. The checker never executes base/PR
code in privileged runtime processes.

GitHub was unprotected with no rulesets; only owner hrrrb408 had write access.
The owner explicitly selected single-maintainer protection with an approval gap.
The applied API evidence requires PRs, strict/up-to-date `security-tests` from
GitHub Actions app 15368, includes admins, prohibits force push/deletion and
requires resolved conversations. Approvals 0, Code Owner review disabled. No
bypass allowance was added. Freeze context will be required after its initial
main deployment. Independent approval remains NOT PROVEN; a writable owner can
change CI/settings or spoof an Actions context by rewriting a workflow. This is
not a malicious-maintainer-proof immutable kernel. Do not silently weaken gates.

## F. Security acceptance and anomalies

Canonical result: pending completion. PR-head and merged-main CI must be terminal
and matched to the actual SHAs before delivery closure.

| Required attack family | Executable mapping / evidence |
| --- | --- |
| Wrong-signer, XPC spoofing, source digest/authority injection | `test_macos_xpc_sandbox.py` signed self-signed product and XPC attacks |
| Read/write/list denials, direct Kernel/Bundle access | `test_launcher.py` Runner bypass/scope attacks and signed Broker probes |
| Symlink/hardlink/rename/TOCTOU | Launcher, Broker and real Seatbelt tests, snapshot/changeset fixtures |
| Out-of-scope complete changeset | Launcher added/modified/deleted/FIFO/socket rejection before live writeback |
| Candidate self-activation/escalation/stale/rollback | `test_plugin_lifecycle.py`, `test_memory_evolution.py` |
| Missing backend, malformed policy, snapshot unavailable | Seatbelt and signed Broker fail-closed probes; no Host fallback |
| Build tamper / wrong identity / output replacement | Signed product resource tamper and wrong certificate; `test_security_freeze.py` exclusive rename |
| B filesystem / key-state tamper | `same-uid.json`, `protected-install.json` |
| Install/restart/update/rollback/uninstall | user and protected install reports; same-version replacement only |

The first local run exposed a signed-product build regression: `find-identity -v`
excluded the temporary local self-signed certificate because it was not globally
trusted. `initial-product-failure.log` retains the failure. The fix queries all
identities, accepts an explicitly selected non-expired self-signed identity without
changing global trust, rejects ambiguous selections/expired certificates, and
still verifies actual signatures and externally pinned fingerprints. Three
builder unit tests and the real signed product test (46.125 seconds) passed
including wrong-certificate and signed-resource-tamper rejection. Do not interpret one green run as
explaining readiness flakes. The earlier PR #18 same-SHA retry passed after a
snapshot readiness failure before the intended symlink assertion; root cause
remains unproven. Real APFS mounting has external OS lifecycle/resource state;
canonical failures must be classified by stage. Readiness failure is availability
failure with no execution, not successful enforcement of a later attack. Keep
that separate from fail-closed safety. No Kernel timeout/retry/fallback changes
were made here. Production readiness remains conditional on that unresolved risk.

## G. Remaining risks and future distribution

Independent review; writable build toolchain; Keychain operation authority;
user-owned security/business state and replay; missing Hardened Runtime;
Snapshot Broker allow-default residual policy; launch-time race/running mappings;
OS-reboot and distinct-version migration acceptance; unexplained readiness flake.
Developer ID distribution would separately require paid identity management,
notarization/stapling, distribution/update trust and revocation policy; none is
implied by local self-signed acceptance. See upstream Apple/GitHub references in
`docs/SELF_HOSTING.md`. Legacy `scripts/install-native-tcb.sh` was inspected at
`03cf742d6b5fb16dc746ceb6443fc4d23a6f1eff`: it creates Linux service UIDs and
privileged launchers/capabilities, unsuitable for this fixed macOS Seed and not
copied. No external library/framework/dependency was introduced.

## H. Closure decision

| Status | Decision |
| --- | --- |
| Self-Hosting Security | NOT PROVEN for full requested acceptance; bounded deployment exercised, distinct-version/OS reboot and toolchain provenance gaps remain |
| Scoped Agent/Runner Tamper Resistance | NOT PROVEN pending current canonical and CI evidence |
| Unprivileged Same-UID Tamper Resistance | NOT PROVEN overall; user-owned counterexamples succeed; protected filesystem cases deny |
| Protected Security State | NOT PROVEN; co-replacement counterexample succeeds |
| Security Kernel Freeze Governance | NOT PROVEN for independent review; single-maintainer technical protection applied |
| Security Kernel Final Closure | CONDITIONAL; do not declare comprehensive freeze/tamper completion |

### Protected-state boundary requiring a separate decision

The current ordinary-UID Kernel cannot both mutate activation state and make that
same state unwritable to every unconfined process of its UID using POSIX modes.
Root-owned immutable state alone would stop legitimate activation/rollback.
A possible future design is a separate OS authority owner with a narrow signer-
authenticated state broker: read verified activation, compare-and-swap generation,
and approve activation/rollback bound to exact content/scope. It must not accept
Plugin business schemas, arbitrary paths or arbitrary execution. This would cost
at least one new trusted process/identity boundary, bounded IPC operations,
protected key/generation persistence, installation policy and real spoof/replay/
crash/rollback tests. Exact operations and failure recovery need a separate ADR.
No daemon/helper, root-running Kernel or new trust root is approved or implemented
by this report. A Keychain ACL alone is not asserted sufficient while same-UID
signing operations and runtime injection remain unproven.

### TCB growth budget

Production code delta: builder +165/-82 lines (net +83); no runtime edits.
Trusted code delta: runtime enforcement 0; build helper net +83, development/CI checker +98 lines; documents/fixtures separately inventoried.
New architecture concepts: 0 runtime; source freeze/deployment governance artifacts.
New trusted processes: 0. New IPC operations: 0. New persistent runtime state: 0.
New dependencies: 0. Removed duplication: one canonical artifact verifier replaces
private final verification and serves both build and explicit verification CLI.
No planner, manager, new service, authority grant or Plugin business schema.
