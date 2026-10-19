# M8.7 Cleanup Changelog

Comparison base: `dee62b20dc1acbd64b009d47c29dc3f42ba9fdde` (PR #39).
All counts use physical source lines (`git diff --numstat`), including whitespace/comments.

| Change | Why unnecessary / replacement | Remaining consumers | Coverage / authority |
|---|---|---|---|
| Delete `KernelWorkspaceXPC.decodeRunRequest` (11 lines) | Obsolete convenience projection since `9a17a03`; actual reader calls generalized `decodeInvocationRequest` | None, including explicit package compile lists and probes; not an ObjC selector | Full native compile, signed XPC invalid-frame/source/scope attacks; no wire/parser/authority change |
| Consolidate `BigModelSession.decode` (+17/-34, net -17) | Four duplicate emit/throw blocks and duplicate stage choices; reuse `BigModelError.diagnosticStage`, emit and throw once | Apple/local/remote provider behavior remains distinct; BigModel catch still maps same four errors | Five-case synthetic Swift decoder test; existing action output tests; no real provider call |
| Delete four unused Python imports (-4) | AST import/load analysis plus repository-wide import/attribute/patch searches found no consumers; stdlib/constant/helper aliases had no runtime use | `runner_sdk.MAX_PLUGIN_INPUT_BYTES`, `launcher._open_absolute_directory`, `broker.hashlib`, development `macos_disk_image.uuid`; no documented re-export contract or compiled consumer | No execution expressions changed; SDK/launcher/Broker/APFS regressions in complete suite; -3 shipped LOC and -1 development-only LOC |
| Add decoder regression test (+73) | Checks success and invalid JSON/shape/types/size through extracted production mapper | Test compiles production decoder verbatim; temp-only OSLog sink redirect makes redacted formatter observable | No payload canary in diagnostics, exact error/stage, one failure per attempt; synthetic evidence only |
| Update manifest/declaration/baseline digest | Test governance plus trusted deletion require fresh exact-base accounting | Base checker still governs full sensitive path set | No automatic rebaseline or normative claim upgrade; Owner Review remains PENDING |

Files deleted: **0**. Functions deleted: **1** (11 LOC); unused imports deleted: **4** (4 LOC). Whole obsolete subsystems removed: **0**.
Production code: **+17/-48 = -31 LOC**. Runtime TCB: **+0/-13 = -13 LOC**.
Untrusted runtime: **-18 LOC**. Development-only APFS backend: **-1 LOC** (not shipped). Tests: **+73 LOC**, zero attack tests removed.

```text
Production code delta             -31 LOC
Trusted code delta                -13 LOC (unused wrapper and two imports)
New architecture concepts         0
New trusted processes             0
New IPC operations                0
New persistent state              0
New dependencies                  0
Removed duplication / abstractions 4 diagnostic branches -> 1 emit/throw; 1 dead wrapper; 4 imports
Kernel authority delta            0
Kernel ABI delta                  0
Workspace scope authority delta   0
```

Before/after `readInvocation` still decodes the same envelope through the same
`decodeInvocationRequest` and `decodeWorkspaceRequest`. No enforcement code is added.
Deleting a non-consumed wrapper does not remove a validation step. The two trusted Python files each lose only an unused import line; all other 33 of 36
runtime TCB files compare byte-for-byte with the base. Manifest hashes also account for
the development-only unused import and new test. The existing baseline's historic audit metadata is retained.

Commits separate the untrusted diagnostic consolidation (`69e3721`) from the trusted
wrapper deletion (`972cba6`). The unused Python imports are isolated in `9218141`. Research/report delivery is a separate logical commit.

Full regression, freeze checks and CI results are recorded once in
[COMPLETION_AUDIT.md](COMPLETION_AUDIT.md). The first in-flight 398-test run began before
edits, so it is preliminary mixed-tree evidence, **not** an immutable exact-base run.
The first 399-test run also overlapped the final unused-import cleanup and is transition
evidence only. The subsequent 399-test run at `9218141`, with production/tests held fixed,
is the authoritative local regression for the final code tree.
No interactive signing acceptance is inferred from any headless suite.
