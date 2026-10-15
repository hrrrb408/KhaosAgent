# Security status

Khaos Seed supports macOS and real Seatbelt enforcement. Its model is
`Untrusted AgentHost → Trusted Launcher → Kernel → Seatbelt Runner`.
See [threat model](docs/SEED_THREAT_MODEL.md), [self hosting](docs/SELF_HOSTING.md),
[freeze policy](docs/SECURITY_FREEZE.md) and the
[finalization evidence](SECURITY_KERNEL_FINALIZATION_REPORT.md).

Sandboxed Agent/Plugin/Runner authority is limited by process boundaries,
authenticated IPC, exact scopes, private snapshots and validated changesets.
A passed test establishes only its exercised attack path. Missing sandbox or
snapshot readiness must fail closed; no Host fallback is supported.

## Supported threat model

The protected adversaries are Khaos's own untrusted AgentHost, Plugins and Runners.
They must not bypass Launcher approval, authenticated Kernel admission, exact
capability scopes, sandbox enforcement, or trusted changeset validation; they
must not alter the active trusted Kernel or activate themselves.

An ordinary macOS user installs a locally signed App under `~/Applications`.
Root-owned installation and administrator authentication are not prerequisites.
The owner may intentionally develop and modify source using Codex, Claude Code
or other tools. That authorized development is outside the runtime adversary
model; Freeze classifies and reviews authority changes, not blocks the owner.

Comprehensive resistance to an arbitrary unconfined external process of the same
UID is **OUT OF SCOPE and not implemented**. User-owned installation/source and
Plugin Store/key/state may be changed by that UID. HMAC does not establish a
separate OS owner. Code signing verifies identity/integrity; it is not filesystem
write protection. Administrators/root/system trust modification are outside the
supported guarantee too. Current builds lack Hardened Runtime; do not claim
injection or running-mapping integrity. The Snapshot Broker retains a transitional
allow-default policy with targeted denials. These limits do not permit weakening
Seatbelt, XPC, signatures, approval or isolation for supported runtime adversaries.

Do not send credentials, user data or exploit payloads through public issues.
Report a reproducible issue with a disposable fixture and sanitized diagnostics.
Do not include signing private keys or model-provider credentials.
