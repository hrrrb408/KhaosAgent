# Security Kernel Finalization Report

Date: 2026-10-16. Runtime audit base:
`12af8aa1e52b235234648b1f7eb925d648180e54`.
PR #20 merged as `bc0df57203fb136696dc7f08e061d9ea44a05967`;
this revision follows the owner's subsequent scope amendment.

## A. Current objective and exact TCB

Khaos is an open-source Agent for ordinary macOS users. Default deployment is a
locally signed user-owned App under `~/Applications`. Root-owned installation,
repeated administrator authentication and comprehensive external same-UID tamper
resistance are **not** requirements of this Security Kernel Freeze.

The protected adversaries are Khaos's own untrusted AgentHost, Plugins and
Runners. They must not bypass Seatbelt, XPC identity, signatures, permission
approval, capability scope, snapshots or validated changesets; they must not
expand their authority, self-activate or autonomously alter the active Kernel.
The product remains `Untrusted AgentHost → Trusted Launcher → Kernel → Seatbelt Runner`.

Owner-authorized source development through Codex, Claude Code and other tools
is normal. Freeze is a reviewed trusted-change process, not an OS lock on the
owner's source. Arbitrary unconfined external same-UID processes, administrators,
root and changes to system trust are outside the supported guarantee.
Comprehensive protection against those actors is **not implemented**.

`security/tcb-manifest.json` records exact paths, SHA-256, source modes, roles,
permission boundaries and regression families. It distinguishes 34 runtime TCB
files, build/governance inputs and one development-only APFS backend. Runtime
sources remain byte-identical to the audit base. Launcher/Picker, shared protocol
and peer checks, Kernel XPC/Python, Broker, sandbox, lifecycle, snapshots and
changesets are trusted. Empty package markers are included because imports
execute them. AgentHost intelligence, Runner/SDK, Plugins and model runtime remain
untrusted. System/Python dependencies are recorded per artifact, not disguised as
Khaos source TCB. Family mapping is not per-line coverage.

## B. Ordinary user self deployment

The existing `tools/build_macos_seed.py` remains the only builder. It:

- selects one available non-expired Keychain identity by full name/fingerprint;
- snapshots source bytes privately, rejects symlinks and optionally requires an
  independently reviewed exact source SHA-256 map;
- seals source/dependency hashes, builder digest, versions and certificate in
  `Contents/Resources/build-inputs.json` before final outer signing;
- checks actual nested signatures, fixed bundle IDs, externally pinned signer,
  configured peer requirements, and Host not satisfying Launcher identity;
- publishes with exclusive rename, refusing existing/raced output paths;
- reuses that verifier through `--verify-app`, existing no-Picker bootstrap for
  peer authentication, and canonical real OS tests for Seatbelt/APFS readiness;
- supports explicit bounded numeric local build versions for upgrade acceptance.

No administrator or paid Apple membership is required. The documented persistent
identity route is Keychain Certificate Assistant; private keys stay in Keychain.
Canonical tests separately provision a disposable self-signed identity. Their
private fixture exports are removed, never committed or bundled. The test fixture
now saves the prior Keychain search list **before** creation, preventing an
automatically registered test identity from being mistaken for prior user state.
A deterministic registration regression covers this ordering. Nonexistent
historical test search entries were removed from user lookup metadata; all real
Keychains were retained and no private key/system trust setting was changed.

All assembly precedes final signing; failures clean private staging. Nested
Python code may use ad-hoc signatures, while Launcher/XPC identities stay stable.
No signed content is patched after final signing. This is local source deployment,
not Developer ID notarization or byte-reproducible distribution. A trusted source
review/build host/toolchain remains an assumption. Hashes inside a writable tree
are not an independent trust root; use the reviewed Git commit and external
expected inputs. Current builds do not enable Hardened Runtime.

## C. Persistent state, identity and update boundaries

Plugin state remains bounded, opaque and Plugin-owned. Candidate admission,
digest/scope/generation binding, separate approvals, isolated evaluation and
routing rollback remain unchanged. No new database, business schema, privileged
state owner, daemon/helper or persistence framework was added.

Activation HMAC/key/state consistency does not protect against a process that
owns and can replace both key and state. That external same-UID threat is outside
the current model. It is neither called implemented nor used to block closure.
Within the supported runtime model, scoped IPC and OS isolation still prevent
Plugin/Runner access to or unilateral modification of trusted lifecycle authority.
Code signing verifies identity/integrity; it is not universal file write protection.
Signing operations allowed by Keychain, runtime injection and running mappings
remain host assumptions/limits. No claim against arbitrary external same-UID or
administrator attackers is made.

## D. Acceptance and historical research

`reports/security-kernel-finalization/self-host.json` records actual ordinary-user
install, app restart, distinct build 1 → 2 upgrade, 2 → 1 rollback and uninstall
with signature and XPC checks, without administrator authentication. This proves
that supported flow; it does not claim OS reboot or state-schema migration.

Historical `same-uid.json` records successful external key/state co-replacement
and owner-readonly bundle replacement. Historical `protected-install.json` records
six EACCES filesystem denials and an explicitly authorized root-installed
1 → 2 → 1 experiment. The test parent was removed. These observations remain
for provenance, **not current deployment requirements or acceptance gates**.
Repeated administrator experiments stopped and the executable root fixture was
removed. No privileged installation/service is introduced into the normal path.
The test requiring a successful B counterexample was removed from canonical CI;
Freeze must not require preserving an out-of-scope vulnerability.

## E. Executable Freeze governance

`docs/SECURITY_FREEZE.md`, manifest/baseline, exact-base change declaration,
base-tree checker, security template, CODEOWNERS and CI classify trusted changes.
The checker consults base inventory, protects new authority paths, uses NUL-safe
Git paths (including the Chinese normative document), and rejects undeclared
changes or digest drift. Deleting a proposed manifest entry does not remove base
protection. A declaration alone is not human authorization.

Actual main protection requires PRs and up-to-date `security-tests` plus
`security-freeze` from GitHub Actions app 15368, includes administrators, forbids
force push/deletion and requires resolved conversations. Initial freeze was
bootstrapped only after its first green check existed. No admin bypass was added.
The owner explicitly accepted single-maintainer mode: required approvals 0,
Code Owner review disabled; independent Code Owner approval remains **NOT PROVEN**.
A writable owner can change CI/settings. These controls do not resist a malicious
owner and must not be advertised as independent review or arbitrary host tamper
protection. Normal authorized source changes remain possible through this process.

## F. Real OS tests and anomalies

Historical final PR #20 tree: local **341/341, 668.472 s**; PR CI
**341/341, 802.047 s**, plus green Freeze; merge `bc0df572...` has identical tree.
The current scope/fixture revision requires fresh canonical and exact-SHA CI
results before delivery. See the attached follow-up PR and Actions results;
post-merge main CI is independently checked, not replaced by PR success.

| Attack family | Executable coverage |
| --- | --- |
| Wrong signer/XPC spoof/source and authority injection | real signed-product/XPC tests in `test_macos_xpc_sandbox.py` |
| Unauthorized read/write/list and direct Kernel/Bundle access | Launcher/Runner scope attacks and signed Broker probes |
| Symlink/hardlink/rename/TOCTOU | real Launcher, Broker, Seatbelt and changeset tests |
| Snapshot/complete changeset escape | added/modified/deleted/FIFO/socket rejection before live mutation |
| Candidate self-activation/escalation/stale approval/rollback | Plugin lifecycle and Memory evolution tests |
| Backend, malformed policy or snapshot unavailable | fail-closed Seatbelt and signed Broker probes; no Host fallback |
| Build tamper, wrong identity, publication replacement | signed resource/fingerprint attacks and exclusive-rename tests |
| Source Freeze and signer fixture hygiene | base inventory, Unicode path, source-map and Keychain ordering regressions |

Retained anomalies: initial identity preflight wrongly used `find-identity -v`
for local self-signed certificates; fixed without adding system trust. A historical
root fixture reused stdout and received appended bootstrap lines; private output
files fixed it before that experiment was retired. One administrator wait timed
out before installation. The signer fixture saved search state too late; this
revision fixes it. No Kernel timeout, retry, authority or isolation change occurred.

Earlier snapshot readiness failure before a symlink assertion remains unexplained
(despite a later same-SHA pass). Classify it as availability/coverage uncertainty,
not a successful later attack assertion. Current probes fail closed and never
fall back to Host. No blind Kernel retries or timeout expansion were added.

## G. Remaining limits

Independent review gap; trusted build host/toolchain; current lack of Hardened
Runtime and Broker allow-default residual policy; historical readiness flake;
OS reboot and state-schema migration not exercised. External unconfined same-UID
or administrator tampering is expressly outside scope, not an acceptance blocker.
Future Developer ID/notarization, update revocation or broader host resistance
requires a separate project and threat-model decision. No protected-state broker
or new OS authority boundary is required or proposed for this Freeze.

Upstream basis and normal install/update/rollback/removal instructions are in
`docs/SELF_HOSTING.md`. Legacy Linux privileged installers were inspected and
not copied. No third-party code or dependency was added.

## H. Closure decision

| Item | Scoped decision |
| --- | --- |
| Ordinary-user Self-Hosting Security | PASS for documented trusted-host local signing/verify/install/app restart/upgrade/rollback/uninstall |
| Scoped AgentHost/Plugin/Runner authority and Kernel protection | PASS for mapped real OS paths; exact-SHA CI is required for each delivered revision |
| Arbitrary external same-UID comprehensive tamper resistance | OUT OF SCOPE; not implemented and not required |
| State protection against arbitrary external same UID | OUT OF SCOPE; not implemented and not required; runtime Plugin isolation remains required |
| Security Kernel Freeze governance | Technical single-maintainer controls applied; independent Code Owner approval NOT PROVEN as explicitly accepted |
| Final closure | CONDITIONAL on the disclosed independent-review/readiness limits; not conditioned on root-owned installation or external same-UID protection |

### TCB growth budget

Runtime production/trusted code delta: **0** (all 34 source digests unchanged).
Prior builder delta +165/-82; development/CI checker +98. This revision changes
scope contracts and test hygiene, removes the root experiment driver and an
out-of-scope canonical counterexample requirement. No runtime architecture
concepts, trusted processes, IPC operations, persistent state or dependencies.
One canonical artifact verifier serves build and explicit verification; no second
builder, updater, security-state framework or privileged installation path.
