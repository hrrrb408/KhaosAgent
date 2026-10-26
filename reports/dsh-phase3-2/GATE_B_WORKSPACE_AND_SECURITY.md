# Gate B — Workspace and Security

**Status: BLOCKED before workspace selection.** No disposable Task A workspace was created, no Picker opened, no signed request was approved, and no Runner operation was submitted.

The local candidate model bytes matched the frozen SHA-256 `fadc3e5f8d42bf7e894a785b05082e47daee4df26680389817e2093056f088ad` and size `18,556,689,568` bytes. The containing app failed deep signature verification with `CSSMERR_TP_NOT_TRUSTED`; the current user keychains returned zero valid code-signing identities. Its model digest is not sufficient evidence to accept the surrounding app as the authenticated execution environment.

The documented semantic-tools route binds each signed app to a specific disposable workspace. Reusing a prebuilt app with that binding is rejected, while building two fresh app bundles would duplicate the large model. The task forbids that duplication. We stopped without weakening workspace identity, scope, approval, or signature checks.

| Security / workspace measure | Result |
|---|---|
| Signed Launcher → Kernel → Runner execution | NOT_RUN |
| Workspace identity binding | NOT_RUN |
| Read and write scope enforcement | NOT_RUN |
| Approval digest check | NOT_RUN |
| Unauthorized approvals | 0 |
| Workspace mutations | 0; no trial workspace was selected |
| Historical deletions | 0 |
| Kernel authority / ABI changes | 0 |
| Production trusted runtime changes | 0 |
| Production Harness migration | NOT_AUTHORIZED; not performed |

Operator record: `codex_agent`; authorization: `Owner-delegated disposable experiment`; owner personally clicked: `NO`.
