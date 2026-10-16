# M7.4 — existing trusted execution boundary regression

Base: `c17d26c` (M7.3 diagnostic/governance follow-up; initial runs used c97bb05; partial UI used identical runtime/test content based on 1a34864). The aim is to verify existing guarantees, not add Kernel
features. Architecture §11.1, the current ABI, AGENTS.md and SECURITY_FREEZE.md
remain authoritative. Runtime and authority are unchanged; one protected UI-test expectation and an explicitly owner-deferred partial mode are described below.

## Boundary-to-test map

| Boundary | Existing executable regression |
| --- | --- |
| Seatbelt fail closed, missing backend and no fallback | `test_missing_backend_fails_closed_without_fallback`, real Seatbelt confinement tests; signed product Broker invalid-policy rejection |
| Exact read/write scope and full changeset rejection | Launcher scoped read/list, modified/deleted/unscoped output, symlink/hardlink/FIFO tests; actual signed writeback smoke |
| Direct Kernel / Bundle / live workspace access | Actual signed sandbox Host/AgentHost/Broker canary probes; Plugin lifecycle Runner denials of activation state, Candidate store and live workspace |
| XPC peer identity | OS signature/CDHash/PID mismatch probes, real named/anonymous peer checks; M7.3 signed request/connection cancellation and disconnect tests |
| Per-operation approval | Actual signed Agent Plugin denial followed by a separately approved invocation; M7.2 every-operation coding scope checks |
| Candidate identity, Manifest, scope, Generation | Signed lifecycle reviewed digests and stale-A approval after B activation; headless production XPC lifecycle attacks |
| Separate activation approval | Actual signed package Picker then separate Candidate activation review, distinct from invocation reviews |
| Rollback / invalid rollback / crash | Actual signed A→B→A routing; `test_invalid_rollback_target_does_not_change_state`, expired/wrong-target approvals and atomic activation crash tests |

The canonical suite contains the focused test names and all underlying real OS
checks; logs identify each actual test and verdict. Pure validation/mutation tests
are not relabeled as OS enforcement. The signed UI fixture's parent checks exact
workspace hashes, single links, canary bytes, Candidate/Manifest/scope/generation,
and deep signature after each completed operation. Rollback restores routing;
it does not undo writes or external effects already committed by B.

## Preserved attempts

Attempt 1 reached and passed the actual signed workspace writeback alert (run
`6f7a5e6e-a497-4e5c-ac5d-ff4fd7f2eb6b`). Candidate A was separately activated.
At the first Agent Plugin invocation review, the parent terminal gate read EOF:
its driver had been started with a heredoc, consuming/closing inherited stdin.
The parent failed and cleaned the disposable app/store before the invocation
was approved or executed. `signed-product-attempt-1.json` and its log retain this
failure. The corrective action changes only driver launch to a saved temporary
Python script with an open PTY; no product/test source, timeout, approval or
assertion is changed. A repeated test fixture run is not a remote-model benchmark
retry and contains no remote data flow.

## Change budget

Production code delta: 0.
Trusted code delta: 0 runtime lines; one existing protected test assertion plus governance.
New architecture concepts: 0.
New trusted processes: 0.
New IPC operations: 0.
New persistent runtime state: 0 (test/audit artifacts only).
New dependencies: 0.
Removed duplication / abstractions: 0; existing enforcement and acceptance paths
are reused. No alternative XPC Picker/approval automation path is introduced.

Independent Code Owner approval remains NOT_PROVEN under single-maintainer
protection; arbitrary external unconfined same-UID tampering is still outside
the supported runtime guarantee. M7.5 records the fixed benchmark outcome without
substituting deterministic success for actual model coding success.

Attempt 2 preserved the open terminal and reached the actual Agent Plugin denial
and separately approved invocation. The Host received `added=2, modified=0,
deleted=0`; the parent then failed because it expected an obsolete English
sentence (`Plugin result confirms two approved files were added.`). The existing
probe now renders numeric changeset counts. Correct only that exact expectation
to `Plugin result changeset counts: added=2, modified=0, deleted=0.`; keep
`verify_plugin_result`, digest/generation/scope checks, denial-before-execution,
workspace/canary hashes and deep signature assertions intact. This is a proven
test-oracle mismatch, not a Kernel defect or model coding success. The fresh
security declaration binds c97bb05 and the four sensitive files; only this test
digest changes in the manifest, with every runtime hash retained. Both failed
attempts remain committed. A third fixture run uses the corrected assertion.

Attempt 3 passed the corrected Agent result check and parent workspace/canary/
signature checks for A. The parallel stale-A / activate-B phase could not be
completed with the available CUA selector: identical bundle-ID instances always
attached to A, and macOS window listing was unavailable. While trying to leave
window overview, the operator sent Escape to A and cancelled its pending review;
B's untouched package Picker was then explicitly cancelled. The parent correctly
failed generation `1 != 2`. No B activation or stale-approval rejection is claimed
for this attempt. `signed-product-v3.json` and log retain it. The owner explicitly
chose to complete other work and leave the parallel stale-approval UI unaccepted.
This is distinct from the production Kernel's automated stale-generation tests.

The fresh pre-diagnostic canonical suite passed 341 tests in 698.347 seconds,
including the same signed shared-service XPC test that failed once remotely.
Its log/hash and exact test-input digest are in `validation.json`; the remote
M7.3 failure remains separately retained and unresolved from its truncated output.

## Owner-deferred concurrent UI only

The owner chose to finish all other work and retain the concurrent stale-approval
UI as unaccepted. A documented opt-in environment value,
`KHAOS_DEFER_PRODUCT_STALE_APPROVAL_UI=1`, runs the existing sequential A/B/rollback/A
helpers and emits `signed-product-stale-approval-ui=NOT_RUN owner-deferred`. The
default complete UI branch retains every original stale-review assertion.
Canonical headless production XPC stale-generation tests run independently even
in partial UI mode. No approval is bypassed or automated by this flag; A/B
activation, invocation and rollback still use their actual separate native dialogs.
This test-only branch is needed to finish the non-deferred interactions without
misrepresenting the CUA-blocked concurrent test as passed. It is not a second
production implementation. AGENTS.md documents the partial evidence boundary;
the final declaration binds the actual PR base c17d26c and exactly AGENTS, this test and governance.
Freeze inventory verification passes (5 sensitive paths). Governance tests pass
4/4. A short-SHA invocation of the checker first failed exact-base matching;
passing the declaration's full base SHA verifies without changing policy.

The fourth signed product test completed successfully in 253.868 seconds. Actual
native reviews performed: A activation, first Agent Plugin invocation denied
with no mutation, new independent invocation approved, normal A run, separate B
activation, B run, separate rollback approval, then A run at generation 3. Parent
assertions verified exact Candidate/Manifest/scope/generation after every phase,
only the two per-Candidate files changed, the unapproved canary stayed identical,
activation/Candidate/live-workspace direct access was denied, and deep signatures
remained valid. The signed writeback smoke also passed with acceptance run
`b417b08a-89f4-4b8e-9310-489bfde6312a`.

`signed-product-v4.json` explicitly records full lifecycle UI acceptance as false
and the concurrent stale-approval UI as NOT_RUN; all non-deferred sequential
checks passed. The test's zero exit is not used to erase that missing UI step.
Every earlier failed run remains separate. No real-model coding claim is derived
from these fixed-probe results.
