# Security boundary analysis for editing candidates

## Authority chain

Every candidate starts with an untrusted model proposal. Candidate B adds a deterministic untrusted Host translation; it does not write the workspace directly. The proposed chain is:

Model intent → Host shape validation and fixed translation → existing Launcher review → existing Kernel workspace.run → isolated Runner and snapshot → whole changeset validation → live writeback only when allowed.

The model chooses path and content, but does not choose approval, authority, sandbox policy, workspace root, timeout or Kernel identity. The Host must derive readScope and writeScope from the single edit path and reject malformed or ambiguous paths; it must never trust model-provided scope fields for B. The Launcher review remains independent for every operation. The Kernel remains the enforcement authority.

This chain is only a design. M8.5.1 does not implement or exercise the edit action.

## Invariant review

| Invariant | B design requirement | Existing evidence and remaining limit |
|---|---|---|
| Host cannot expand scope | Generate exactly one read and one write path from the validated target; do not accept scopes in edit payload | Existing Launcher and Kernel retain scopes; the B adapter is not implemented |
| No implicit write grant | Every edit becomes a shell proposal with an explicit one-time Launcher decision | Existing approval path; not yet exercised with an edit action |
| Missing path cannot select a file | Reject empty path; never search for a substitute or use cwd defaults | Deterministic Host validation still needs tests |
| No change without approval | No Runner invocation before Launcher approval; denial stops the task | Existing denial result says the command was not executed; future end-to-end test required |
| Traversal and aliases | Do not treat string normalization as enforcement; rely on exact Kernel scope, no-follow snapshot access, OS sandbox and changeset validation | Existing tests cover current path; B-specific signed-product proof is NOT_PROVEN |
| Symlink/hardlink escape | Do not follow links in the adapter; trust only existing OS and Kernel checks | Khaos has current Runner and snapshot attacks; new serialization and write behavior still need proof |
| Race/TOCTOU | Do not rely on a check-then-write path guard; use existing sandbox/snapshot/commit mechanism and test replacement races | Existing attacks cover current mechanisms; B's write staging is NOT_PROVEN |
| Hidden tests | Never add test-directory or repository-root read scopes automatically | B can request only its target file. Kernel scope is path-based, not semantic hidden-test classification; keep hidden fixtures outside the authorized workspace or inaccessible |
| Patch is not authority | Treat oldText/newText and any patch as untrusted data, never as approval or permission; JSON-encode text into bounded argv values without source interpolation | Existing Host and Kernel boundary; serialization and bounds are only prototyped |
| Changeset gate | Keep write scope exact to the target; reject any added, modified or deleted path outside it before live mutation | Existing KERNEL_ABI contract and tests; no B integration test yet |
| No capability expansion | Do not add Kernel capability, operation, IPC or protocol field | Proposed shell lowering uses existing operation |
| Remote data | No remote model call in M8.5.1; a future remote run must retain the product's separate explicit data approval | No data was sent for this review |

The Kernel ABI distinguishes directory read roots, which cover their subtree, from exact write entries, which do not. The model-facing B action should therefore carry one file path, never a directory scope. The Kernel revalidates process output and commits only when every changed entry is in the retained exact write scope. See [KERNEL_ABI read/write scopes](https://github.com/hrrrb408/KhaosAgent/blob/23d00c762af04b20b46f818fc611bcd5db16a211/docs/KERNEL_ABI.md#L174-L234) and [process.exec](https://github.com/hrrrb408/KhaosAgent/blob/23d00c762af04b20b46f818fc611bcd5db16a211/docs/KERNEL_ABI.md#L354-L368).

## Failure behavior

B must fail before any replacement when the path is missing or outside the existing path bound, an encoded argv item exceeds 4 KiB, the file is unreadable or invalid UTF-8, oldText is empty, oldText is absent, oldText occurs more than once, or the replacement would be a no-op. Multiline oldText/newText must be JSON-encoded into printable single-line argv values and decoded by the fixed script. These outcomes are bounded Runner text or Host validation, not new trusted ABI errors.

Approval denial means no Runner execution. Sandbox rejection or Kernel scope denial must stop the operation and must never trigger Host fallback. A normal nonzero command may still produce a snapshot commit frame in the existing Launcher wrapper. Therefore the fixed adapter must stage the complete replacement before swapping it into the snapshot, and the signed Runner acceptance must test failures before and after that swap. Until those tests pass, no atomic-edit claim is allowed.

No candidate may automatically rerun after failure or denial. Each later edit or test is a separate proposal and approval. Test execution remains a separate shell action and spends the existing eight-call budget.

## No new trusted code

M8.5.1 changes no Security Kernel, Launcher, Kernel ABI, scope enforcement, Seatbelt, XPC identity, Snapshot Broker, changeset validator, persistent state, runtime dependency or production Agent action. Candidate B's future parser and fixed script are untrusted AgentHost behavior. If empirical testing shows that B cannot preserve the existing security path without changing a trusted component, stop and open a separate design review instead of changing that component here.

## Security compatibility status

CONDITIONAL. The lowering has a plausible route through the existing approval and scope enforcement, but it has not been implemented or exercised as a signed product action. Candidate-specific atomic staging, JSON argv encoding and bounds, approval display, and hostile path tests remain required. The offline prototype is not security evidence.
