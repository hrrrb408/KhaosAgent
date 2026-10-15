# macOS source self deployment

This is local source distribution with stable local signing. It is not Apple
Developer ID notarized distribution. Do not disable SIP, Gatekeeper or Seatbelt.
Development checkout and user-owned installation remain writable by the owner.

## Obtain, review and preflight

Clone `https://github.com/hrrrb408/KhaosAgent`, fetch main, inspect the selected
commit and verify its full SHA through an independent trusted channel. Review
trusted diffs and `security/tcb-manifest.json`; run
`python3 tools/check_security_freeze.py`. This check is not independent evidence
if the source, checker and hashes were all supplied by an attacker.

Use the existing Xcode Command Line Tools (`xcrun --find swiftc`,
`xcrun --sdk macosx --show-sdk-version`) and a Python.framework Python 3 runtime.
The builder rejects unsupported OS/architecture, unavailable signing identity,
missing framework, invalid model input and existing output paths. It resolves a
full identity name or certificate SHA-1 to exactly one available non-expired Keychain identity.
Do not run unreviewed installers or repository scripts as administrator.

For a persistent free local identity, use **Keychain Access → Certificate
Assistant → Create a Certificate**, choose a unique name, Self Signed Root and
Code Signing. Keep the private key in your local Keychain, retain its fingerprint
through an independent channel and review Keychain access controls. Do not export
private keys to source, CI, logs, build directories or evidence. Apple membership
and global certificate trust are not needed for explicit designated-requirement
matching. Do not change system trust settings. Inspect identities with
`security find-identity -p codesigning`. The certificate SHA-1 is an identity
selector; build inputs and files use SHA-256. Canonical OS tests use a disposable
self-signed identity/keychain; their temporary test-only key export is removed
with the private temporary fixture and is not the production provisioning route.

## Build and inspect

Use the existing builder (substitute reviewed paths and certificate fingerprint):

```sh
python3 tools/build_macos_seed.py --output "$HOME/Applications/Khaos-v1.app" \
  --signing-identity CERTIFICATE_SHA1 --python-executable /path/to/Python.framework/Versions/3.13/bin/python3
python3 tools/build_macos_seed.py --verify-app "$HOME/Applications/Khaos-v1.app" \
  --signing-identity CERTIFICATE_SHA1
```

The builder copies source inputs into a private staging snapshot before compiling.
The signed `Contents/Resources/build-inputs.json` records source SHA-256, builder
hash, actual embedded dependency hashes, certificate, architecture, macOS, Swift,
SDK and Python versions. Symlink source inputs are rejected. Use `--build-version 2` for a distinct local update (one to three numeric
components). This is an identifier, not an anti-rollback authority. For repeat builds,
extract and independently review `source_sha256`, save that JSON object outside
the source tree, and supply `--expected-inputs /path/to/reviewed-source-map.json`.
Missing/extra/mismatched source entries reject the build. This freezes source
bytes, not a malicious compiler or same-UID host. The runtime inventory records
actual packaged dependencies; it is not an upstream provenance or reproducible
binary guarantee. Pin/review Python, Xcode and optional llama.cpp/model inputs
separately. Their trust roots remain part of the host build environment.

All assembly and metadata writes precede final outer signing. Verification checks
nested signatures, expected certificate and fixed bundle IDs, configured Kernel/
Broker/Launcher requirements, and rejects Host satisfying Launcher identity.
Publication uses macOS exclusive rename: a concurrent output or symlink is never
overwritten. Failed builds remove staging; do not use intermediate products.
The existing no-Picker bootstrap check is:

```sh
open -n -W -a "$HOME/Applications/Khaos-v1.app" --args --bootstrap-check
```

It checks named/anonymous peer authentication only. It does **not** prove APFS or
Seatbelt readiness. Run `python3 -m unittest discover -s tests -v` for actual OS
readiness/attack coverage. Follow the opt-in product acceptance in AGENTS.md for
selected workspace writes and Plugin lifecycle. Keep default/no-Picker, actual
selected-workspace, deterministic model and real-model evidence separate.

## User-owned installation, update, rollback, removal

Keep versioned apps under `~/Applications`. Verify the actual new bundle against
your independently retained certificate fingerprint immediately before launch.
Quit the old app and its task normally; preserve the old verified version; build
and verify the new app at a new path, then launch that exact path. Retain input
records and the full source commit outside the bundle. Do not patch signed bundle
contents in place or reuse a partial output. Verify after execution too.

For rollback, quit the new version, reverify and launch the retained old version.
Routing old code does not reverse external writes or promise state-schema
compatibility. This release adds no automatic updater or state migration. For
uninstall, quit the app and remove only its exact App bundle. User-owned Plugin
state is separate and retained; remove it only through a separately reviewed,
explicit data-deletion decision. Never recursively delete generic Application
Support or a guessed path.

## Ordinary user scope and authorized development

The supported default is a locally signed App under `~/Applications`, with no
root-owned installation, sudo, privileged helper or repeated administrator
experiment. Protected-install tests were stopped when the owner revised the
objective. Their existing JSON evidence is historical research, not a deployment
requirement or Freeze acceptance gate. The root test directory was removed.

Users may intentionally edit Khaos source with Codex, Claude Code or ordinary
development tools. Keep runtime AgentHost/Plugin/Runner separate from that
owner-authorized development context. Freeze requires declared review and new
hashes for trusted changes; it does not lock the owner out of their own source.
Do not auto-activate generated trusted code or treat model metadata as approval.

Arbitrary unconfined external same-UID tampering with source, installed files,
Plugin Store, key or business state is outside this version's threat model and
not implemented as a guarantee. Preserve the read/edit/run scope and actual OS
isolation for Khaos's own runtime components. The normal-user install, restart,
build 1 → 2 upgrade, rollback and uninstall acceptance requires no administrator
prompt. No new protected-state owner/broker is required by this Freeze.

## Upstream basis

- [Apple TN2206](https://developer.apple.com/library/archive/technotes/tn2206/):
  nested signing, designated requirements and self-signed identities.
- [Apple code signing procedures](https://developer.apple.com/library/archive/documentation/Security/Conceptual/CodeSigningGuide/Procedures/Procedures.html):
  Certificate Assistant local signing workflow.
- [GitHub branch protection API](https://docs.github.com/en/rest/branches/branch-protection):
  required checks, zero-review single-maintainer setting and administrator enforcement.

Legacy Khaos is engineering reference only; no legacy runtime or third-party
framework was copied. Existing signing, bootstrap, snapshot and lifecycle tests
were reused instead of adding a second deployment/runtime system.
