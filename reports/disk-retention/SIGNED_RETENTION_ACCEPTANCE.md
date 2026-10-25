# M-Disk.1.1 Signed Retention Acceptance

Date: 2026-10-24
Operator: `codex_agent`
Authorization: owner-delegated disposable experiment
Owner personally clicked: `NO`

Every successful run used a locally signed, approximately 199 MB deterministic App with no GGUF and no network entitlement. Each successful operation was reviewed in the signed UI against the printed task, disposable workspace, request digest, command and scopes. Historic candidates were never selected, modified, or deleted.

## Signed scenarios

| Scenario | Result | Evidence |
|---|---|---|
| Read → Edit → Test and repair | PASS; independent Task A hidden verification passed. Runner exit codes `[1,0,0,0]`; canary unchanged; only the scoped file changed. | `signed-semantic-repair.json`, SHA-256 `f94395bfc7aafc508965bb6744faa3b400335c663e5f249e0dda18a7c7db7785` |
| Runner failure despite fake success output | PASS; actual Runner return code `1`, DSH Session received structured failure, and the next turn was observed. Workspace mutations: `0`. | `signed-semantic-failure.json`, SHA-256 `327d70d2b741aa195fd3acd63a4790f4d14540b469ccc62b3b412c7dc781925c` |
| Import/syntax error in public test fixture | PASS as a failure-result integrity case; Runner return code `1`, result was `unverified`, Session delivered it to the next turn, and mutations were `0`. | `signed-semantic-runtime-exception.json`, SHA-256 `e6c84e8b59f78ea04483aa8b17c059218e7b02a129ba521ba9b8e9e9387d8208` |
| Node crash and fresh-task recovery | PASS; distinct tasks and requests, first task ended `dsh_runtime_failed`, fresh task completed, and no Node process remained after teardown. | `signed-node-crash.json`, SHA-256 `429b741c81cde5c20a99a433cb60d698a28c9a9c1e5d802f025cc21b6360f50b` |
| Pre-commit cancellation | PASS; exact Candidate B `tags.py` preview was approved, then Cancel was clicked at the signed barrier. Kernel returned `process_cancelled`, commit was `not_committed`, and no Runner execution occurred. | `signed-cancellation-precommit.json`, SHA-256 `aa8777de49c67fae4e88da0265dc611beece54e64fb528c986472eb7a367e6de` |
| XPC crash and fresh-task recovery | PASS; a committed scoped edit was followed by an XPC transport failure while delivering its result. The original Kernel commit remained recorded; a fresh task with a distinct task/request ID then read the edited file. Both operations committed, the canary was unchanged, and Node processes after teardown were `0`. | `signed-xpc-crash-recovery-2.json`, SHA-256 `147f4c2049d5a39dd667f4122a6119e5602aff33415c1aac01bbf172df6162aa` |

The XPC recovery evidence binds first task `d0f0bcca-27c1-42c2-8c38-8eee54af0065` / request `1176fad488db45f6b34765817f067476` to the committed `tags.py` edit (Kernel return code `0`, digest `bd8fec1636f89afda7ff4fe06cf382edc92e63350824030a05acbc20470440de`). The later read used fresh task `2dc0b604-a2fd-4553-b8c8-17c0bcb4d6fc` / request `7498c3e8fc54473d8a6dc73b2ae19677`, digest `a33a39a4731d67e0cd5496b6bdb2284fead5924adb4ddd8d06934e258ba2fa0b`. The first result delivery had one transport failure; the Kernel result was not rewritten or replayed.

Each successful record has a private `.retention.json` sidecar with `CLEANED_AFTER_EVIDENCE_PRESERVED`. Deep signature verification passed. The final V2 manifest was recaptured after these runs and compared all 27 historic roots to the earlier V2 inventory; candidate identities and tree fingerprints remained unchanged, and process-reference checks were clear at capture time.

## Refusal, timeout, and orchestration evidence

An earlier `xpc-crash` attempt stopped at the workspace Picker: the Picker was cancelled (`workspace-selection-cancelled`), so no Kernel operation ran. A subsequent read request was denied after the transport error. It was not an XPC recovery pass and did not display the operation mismatch described in the first report draft. Evidence: `signed-xpc-crash.failed.json`, SHA-256 `ec69b234060ae7830ed1203a1f2d539e90cb0695aa877fa3147ea16552099e17` (diagnostic bundle 680,536 bytes). No Runner or Kernel task record was created.

An intentional 30-second approval-timeout run selected the exact disposable workspace and displayed the fixed `tags.py` edit request, but the request was left unapproved until the bounded deadline. The expected result was `FAILED_ATTEMPT`; no Runner operation was approved and no Kernel task record was created. Evidence: `signed-approval-timeout.failed.json`, SHA-256 `816db52a2d8324ad4876f08fe50200eab33679e5703f9217f99cb5960d721127`. Its complete 679,665-byte evidence bundle was preserved; the invocation Scratch was then cleaned with sidecar status `CLEANED_AFTER_EVIDENCE_PRESERVED` (sidecar SHA-256 `ef57fac900e4a112b0a4ff70f4b70fdf87c20c80257c48bc43f87ff4e8a93536`).

A recovery build attempt from the dirty report worktree was rejected by the builder's clean-source preflight before an App launched. The incomplete-evidence failure record and 24 KiB Scratch were intentionally retained because the retention utility could not prove evidence completeness. This was an orchestration failure, not a signed UI test. Do not clean this Scratch manually.

## Unit-tested fail-closed cases

The 29 dedicated retention tests exercise archive failure/incomplete evidence, source mutation during capture, exact identity and tree changes, path replacement, symlink/hardlink rejection, active process references, unavailable process checks, candidate nesting, evidence overwrite refusal, and safe cleanup of a test-owned temporary directory. These are unit tests, not signed UI evidence. Archive-failure handling, identity substitution, and live/unavailable-reference refusal were not exercised in the signed UI; full signed lifecycle coverage is therefore partial.

```text
Successful signed scenario groups: 6
Signed bounded refusal/timeout evidence: 2 (Picker cancellation; approval timeout)
Preflight orchestration failure: 1 (no App launched; incomplete-evidence Scratch retained)
Signed lifecycle matrix: PARTIAL; remaining fail-closed cases are unit-only
Evidence preservation for completed runs and timeout: PASS
Historical Scratch selected, modified, or deleted: 0
Model or full large App copied: 0
Kernel authority changes: 0
```

The signed evidence validates the covered clean-up and recovery paths; it does not close the lifecycle cases with unit-only coverage. No cleanup authorization is inferred. Phase 3.2.2 large unattended model runs should remain paused until exact-head CI is green and the remaining signed lifecycle cases are closed or explicitly accepted as a documented limitation.
