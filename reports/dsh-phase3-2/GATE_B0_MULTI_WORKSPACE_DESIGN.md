# Gate B.0 Multi-Workspace Design

## Existing limitation

The current semantic-tool builder consumes an owner-only workspace manifest and
injects its Trial ID, canonical path, path digest, device/inode, marker digest,
and fixture digests into `TrustedWorkspaceLauncherMain.swift` before signing.
That creates a different signed app for every trial. The runner also rejects a
prebuilt app for these modes. Fixture digests are checked again before each
approval, which prevents an approved edit from being followed by a read of the
edited file.

## Binding and authority

The replacement keeps the signed bundle independent of trial paths. Each task
gets fresh runtime identifiers in the experimental Trusted Launcher:

| Identity | Source and lifetime | Purpose |
|---|---|---|
| App identity | Existing bundle identifier, signer, source receipt, and deep signature | Stable app verification |
| Runtime Trial ID | Launcher-generated UUID for one task | Correlate one isolated task |
| Task ID | Existing Launcher-generated UUID | Bind Host turns and task records |
| Workspace Session ID | Existing UUID created with the actual Picker selection | Bind the selected bookmark session |
| Launcher Request ID | Existing fresh XPC request ID per operation | Bind one operation |
| Approval digest | Existing SHA-256 of the exact encoded Kernel invocation | Bind one user decision to its request, bookmark, and scopes |
| Result digest | Existing DSH Launcher-to-Host result digest chain | Correlate only the result for that request and task |

The user-selected `NSOpenPanel` URL and its security-scoped bookmark remain the
source of workspace access. The Launcher creates an in-memory binding after it
resolves that fresh bookmark and starts its scope. It records the selected
canonical path digest, directory device/inode, and the bounded marker's digest
and device/inode. It rechecks those values before approval, after approval, and
after the Kernel result. A new task clears the prior `TrustedWorkspaceSelection`
and binding. Cancellation or identity mismatch invalidates the binding and
prevents later requests from reusing it.

The workspace marker and the external manifest are correlation evidence only.
The manifest is not embedded in the app or passed to the Launcher as authority.
Trial labels supplied by the test driver do not enter the runtime binding.
Fixture content digests remain in the external evidence so the runner can
describe changes; they do not block in-scope edits or subsequent reads.

The existing Kernel continues to receive the user-selected bookmark, exact read
and write scopes, fresh request ID, and invocation covered by the approval
digest. Existing Kernel scope checks, Launcher approval, bookmark resolution,
device/inode validation, and Kernel result handling remain in force. The
runtime binding is an additional experimental Launcher check, not a grant.

## Prebuilt app policy

A prebuilt app is accepted only after deep/strict code-signature validation
against the caller's expected certificate, all existing nested bundle and
designated-requirement checks, and validation of the signed build receipt. The
receipt must match the current Khaos source SHA and builder, pinned DSH SHA,
local no-model mode, semantic-tool mode, and the generic runtime-binding schema.
It must contain no disposable workspace identity. The app tree digest and
signature identity are captured before launch and checked again after launch;
the runner never rewrites the prebuilt bundle.

Two trials use the same prebuilt bundle in separate fresh Launcher sessions.
Each selects its own disposable workspace and receives new Trial, Task,
Workspace Session, and Request IDs. Evidence must show separate approvals,
different workspace identities, no cross-workspace scope, and no old result
accepted by the second trial.

## Platform primitive

This design reuses the repository's `TrustedWorkspacePicker` and existing
security-scoped bookmark flow. Apple documents that the selected URL is the
user-granted resource and that resolved security-scoped URLs require balanced
`startAccessingSecurityScopedResource()` / `stopAccessingSecurityScopedResource()`
calls ([App Sandbox file access](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox),
[Foundation URL security scope](https://developer.apple.com/documentation/foundation/url/startaccessingsecurityscopedresource%28%29)).
No new permission API, dependency, or production Kernel operation is introduced.

## Evidence boundary

Unit tests exercise the manifest/evidence validator and source overlay, including
stale identities, replaced workspace/marker, stale approval, result digest
mismatch, and old-session replay. They do not prove macOS Picker, XPC, Kernel,
Runner, or signature behavior. The signed acceptance must separately reuse one
unchanged small signed app for two workspaces and record both real operations.
