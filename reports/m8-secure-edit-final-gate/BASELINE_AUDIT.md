# M8.5.2A.2 Baseline Audit

Audit performed 2026-10-18 against GitHub and the isolated worktree.

## Repository and branch

- Repository: hrrrb408/KhaosAgent.
- PR #35 is OPEN and Draft at head 9dac79839da1d2d7c1c29027136f85eb85c28bce; its exact stacked base is PR #34 head 6724d5ac5e52e1c157f3701f30009ed81b55fb90.
- PR #35 reported security-freeze=SUCCESS and security-tests=SUCCESS at audit time. GitHub reported no review decision; independent Code Owner review remains NOT PROVEN.
- The isolated worktree branch test/m8-5-2a2-final-gate-resolution is based on 9dac79839da1d2d7c1c29027136f85eb85c28bce. Its parent is 6724d5ac5e52e1c157f3701f30009ed81b55fb90.
- origin/main was 27ef0b4787f807fc76ffd7ba9cdb467ffc9a2f27 at audit time. The user checkout is a separate branch with untracked artifacts; it was not modified.

## PR chain reviewed

| PR | State | Head | Base | Checks at audit |
|---|---|---|---|---|
| #27 | OPEN | 5acf90bcc0ff02e764e84150ebcebe91536ebc26 | main 27ef0b4787f807fc76ffd7ba9cdb467ffc9a2f27 | security-freeze, security-tests SUCCESS |
| #28 | OPEN | fd21764381546140249d94fcf53f9737bc9d212f | main 27ef0b4787f807fc76ffd7ba9cdb467ffc9a2f27 | security-freeze, security-tests SUCCESS |
| #29 | OPEN | 3cdf26e1933dbcf9896dcd83a0cb6e05eadff92b | #28 head fd21764381546140249d94fcf53f9737bc9d212f | security-freeze, security-tests SUCCESS |
| #30 | OPEN | 6c5791264f64f2d171ad23deabf47ae684fc7ac4 | #29 head 3cdf26e1933dbcf9896dcd83a0cb6e05eadff92b | security-freeze, security-tests SUCCESS |
| #31 | OPEN | f5631de1b5ebb056af28bbd145757b6f76053154 | #30 head 6c5791264f64f2d171ad23deabf47ae684fc7ac4 | security-freeze, security-tests SUCCESS |
| #32 | OPEN | 23d00c762af04b20b46f818fc611bcd5db16a211 | #31 head f5631de1b5ebb056af28bbd145757b6f76053154 | security-freeze, security-tests SUCCESS |
| #33 | OPEN | 1d1457f43f788d30f6fa4f48890b900ef9406c07 | #32 head 23d00c762af04b20b46f818fc611bcd5db16a211 | security-freeze, security-tests SUCCESS |
| #34 | OPEN | 6724d5ac5e52e1c157f3701f30009ed81b55fb90 | #33 head 1d1457f43f788d30f6fa4f48890b900ef9406c07 | security-freeze, security-tests SUCCESS |
| #35 | OPEN, Draft | 9dac79839da1d2d7c1c29027136f85eb85c28bce | #34 head 6724d5ac5e52e1c157f3701f30009ed81b55fb90 | security-freeze, security-tests SUCCESS |

The PRs were inspected as the current stacked history, not as proof that an earlier PR's evidence transfers to this task. No existing PR was edited or merged.

## Preserved signed artifacts

| Evidence | Path | SHA-256 | Scope |
|---|---|---|---|
| Signed positive v8 | reports/m8-secure-edit/gate-a-signed-runner-v8.json | 9a14057dcef79ad7ca3285768a84fe4ae1607ca8f3723dbc845f89086df8b7bb | Historical short fixed replacement |
| Signed refusal v2 | reports/m8-secure-edit/gate-a-signed-refusal-v2.json | f07a2dd6ac77f0df9dacb74fb3498b3311ada0bf60bd5b04b066cddac8a8d1fd | Historical pre-execution denial |
| PR #35 authorized replay | reports/m8-secure-edit-gate/gate-a-signed-runner-replay.json | f8dbb965666f2c8c6c235b93b27a31c3afa011ed981cb7c5d079417438c745d8 | One short fixed replacement; preserved unchanged |
| A2-REPLAY-01 | reports/m8-secure-edit-final-gate/SIGNED_TEST_REPORT-A2-REPLAY-01.json | 9f085c07125e379e512e8f347016396907ae6f89532cb8cdbc9f31730d5c94f6 | One separately authorized replay for this task |
| Preserved setup failure | reports/m8-secure-edit-final-gate/SIGNED_TEST_REPORT.json | 50ca0ec493fe1c98d9a785f3368f7062c69f7a97e58284f941f775e46be03bfc | Zero proposal approvals and zero Runner execution |

## Normative inputs and result

The audit used AGENTS.md, docs/SECURITY_FREEZE.md, docs/SEED_THREAT_MODEL.md, docs/KERNEL_ABI.md, the M8.5.1 and M8.5.2 reports, the M8.5.2A.1 Gate A matrix and completion/cancellation/reviewability reports, and the relevant Runner, Kernel, Launcher, and test sources. The inherited Gate A matrix explicitly requires L4 for selected path, alias, cancellation, lifecycle, and reviewability claims. This report does not replace those requirements with L3.

The base user checkout remains untouched. The new worktree contains only test-probe edits and reports before the security-freeze declaration is refreshed. No production component, ABI, Seatbelt rule, Launcher UI, or authority path has been changed.
