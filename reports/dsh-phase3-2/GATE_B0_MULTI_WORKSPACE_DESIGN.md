# Gate B.0 Multi-Workspace Design

## Existing limitation and implementation

The prior semantic-tool builder embedded each trial's workspace path, path digest, device/inode, marker digest, and fixture digests into `TrustedWorkspaceLauncherMain.swift`. A new workspace therefore changed the signed app build inputs. The experimental builder now creates a generic signed app with no trial or workspace identity, and the acceptance runner can reuse it only after deep/strict signature checks and validation of the exact-source build receipt.

At runtime, each task receives fresh identifiers in the experimental Trusted Launcher:

| Identity | Source and lifetime | Purpose |
|---|---|---|
| App identity | Bundle identifier, signer, build receipt, and deep signature | Stable verified app |
| Runtime Trial ID | Launcher-generated UUID per task | Bind one task's evidence |
| Task ID | Existing Launcher-generated UUID | Bind workspace requests and task records |
| Workspace Session ID | Existing UUID created with the actual Picker selection | Bind the selected bookmark session |
| Launcher Request ID | Existing fresh XPC request ID per operation | Bind one operation |
| Approval digest | Existing digest of the exact encoded Kernel invocation | Bind one user decision to its request, bookmark, and scopes |
| Result digest | SHA-256 of the exact UTF-8 `AgentToolOutcome.text` | Correlate the Launcher result with DSH delivery |

The user-selected `NSOpenPanel` URL and its security-scoped bookmark remain the source of workspace access. The Launcher creates an in-memory binding after resolving and starting the fresh bookmark scope. It records the selected canonical path digest, directory device/inode, and the bounded marker digest/device/inode, then rechecks those values before approval, after approval, and after the Kernel result. A new task clears the previous selection and binding. Cancellation or identity mismatch invalidates the binding and prevents later requests from reusing it.

The external manifest, workspace marker, trial labels, and result hashes are correlation evidence only. None grants directory access. DSH can propose operations but cannot choose or authorize a workspace. Fixture content changes do not alter directory identity and do not block an in-scope edit followed by a reread.

## Result correlation correction

The first signed attempts exposed a capture defect: the experimental Host's `dsh-launcher-terminal=` line was written by a separate XPC process and was absent from the parent Launcher stderr captured by the evidence runner. The evaluator also compared the DSH JSON-content digest (`result_sha256`) to the raw UTF-8 Launcher text digest (`launcher_result_sha256`), which are different digest inputs.

The source correction computes the raw text digest in the experimental Trusted Launcher, carries it as bounded non-authoritative trace metadata, and has the experimental Host verify it against the received text. After an AgentHost reply is received, the parent Launcher emits a bounded terminal record with that digest. The evidence runner joins that record to the DSH terminal and tool-result events by runtime trial, Launcher task/request, approval digest, and the same raw text digest. A missing, duplicated, mismatched, or non-parent terminal record fails closed. This metadata does not grant authority and does not replace the Kernel's original result.

## Existing authority and prebuilt app policy

The existing Kernel continues to receive the user-selected bookmark, exact read/write scopes, fresh request ID, and approval-bound invocation. Kernel scope checks, Launcher approval, bookmark resolution, device/inode validation, and result handling remain in force. Runtime binding supplements these controls and cannot grant a capability.

A prebuilt app is accepted only after deep/strict signature validation against the expected signer, existing nested-bundle and designated-requirement checks, and signed receipt validation for the current Khaos source SHA, builder, pinned DSH SHA, no-model mode, semantic-tool mode, and generic runtime-binding schema. The app tree and signature are checked before and after a trial; the runner does not rewrite the bundle.

This design reuses the existing `TrustedWorkspacePicker` and security-scoped bookmark flow. Apple documents that the selected URL is the user-granted resource and that resolved security-scoped URLs require balanced `startAccessingSecurityScopedResource()` / `stopAccessingSecurityScopedResource()` calls ([App Sandbox file access](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox), [Foundation URL security scope](https://developer.apple.com/documentation/foundation/url/startaccessingsecurityscopedresource%28%29)). No new permission API, dependency, or production Kernel operation is introduced.

## Evidence boundary

Unit and evidence-validator tests cover workspace replay/replacement, stale approvals, scope mismatch, result digest mismatch, missing or wrong-source terminal records, and cross-trial identity reuse. They do not establish signed Picker, XPC, Kernel, or Runner behavior.

One unchanged no-model signed app was used with two separately selected workspaces. Trial A completed the expected read/edit/reread/test operations, and Trial B submitted the authorized symlink read. Both evidence files returned `FAIL`: the app's parent process did not yet emit the trusted terminal record expected by the evaluator, and the B task ended incomplete after its one-operation budget. The result-correlation source correction was made after those trials and has not been exercised in a new signed app. Therefore signed multi-workspace acceptance, exact B refusal correlation, and cross-trial replay refusal remain `NOT_PROVEN` in the signed UI.
