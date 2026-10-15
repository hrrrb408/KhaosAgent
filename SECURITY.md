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

The development checkout and user-installed App are user writable. Code signing
can detect damaged code; it does not prevent same-UID writes, unlink, rename or
replacement. The owner can also access signing operations allowed by Keychain.
Current builds do not enable Hardened Runtime. Code-on-disk verification does
not establish running mapping integrity or exclude injection. The Snapshot
Broker retains a transitional allow-default policy with targeted denials.

Plugin Store, business state and co-located activation HMAC key are user owned.
An unconfined same-UID process can replace key and authenticated state together.
HMAC validates consistency against the key, not an independent owner. Protected
security state and general same-UID tamper resistance are **NOT PROVEN**.
No guarantees apply against administrators, root or modified system trust roots.

Do not send credentials, user data or exploit payloads through public issues.
Report a reproducible issue with a disposable fixture and sanitized diagnostics.
Do not include signing private keys or model-provider credentials.
