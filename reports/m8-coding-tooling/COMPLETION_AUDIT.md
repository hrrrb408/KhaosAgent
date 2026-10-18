# M8.5.1 completion audit

## Scope

This is an architecture review with offline algorithm checks. It does not ship an editing tool or change the benchmark. The external reviews use pinned source commits; their upstream test suites were not run. No real model was called and no project content was sent remotely.

## Research inputs

| Project | Reviewed repository and exact commit | Review report |
|---|---|---|
| Codex | `openai/codex` — `8c076942cb70fba8e5c4732c23f1faabc4aed484` | `CODEX_EDITING_REVIEW.md` |
| Pi | `earendil-works/pi` — `482c1381a00d8d00bc81697e4a980c593db6803e`; confirmed as the active repository for the requested `badlogic/pi-mono` project | `PI_EDITING_REVIEW.md` |
| Oh My Pi | `can1357/oh-my-pi` — `ba85aef0b343a25f3c90b4f86628a9bd92d8414d` | `OH_MY_PI_EDITING_REVIEW.md` |

The reports trace concrete source call paths, matching and error handling, relevant tests, approval/sandbox integration, and the limits of applying each project's design to Khaos. None of their security behavior is represented as a Khaos guarantee.

## Khaos findings and decision

The current Agent Host requires the model to turn an edit into a single-line Python shell command, author exact-match logic, and supply read/write scopes. The existing Launcher displays each proposed argv and scopes for a separate decision. The existing Kernel runs the scoped command in the isolated Runner/snapshot path and validates the complete changeset before live writeback. This current path has no structured edit operation.

The preferred next design experiment is Candidate B: one existing file, exact `oldText` and `newText`, deterministic unique-match validation, and lowering to the existing shell proposal with one read path and one exact write path. The Host must JSON-encode multiline text into bounded, printable single-line argv values; it must not interpolate model text into Python source or write the workspace directly. Launcher approval and Kernel enforcement remain unchanged. Candidate C adds patch parsing and partial-application concerns without a demonstrated requirement for multi-hunk or multi-file edits.

Security compatibility is conditional. Candidate B has only been checked as an in-memory algorithm and argv serialization example. A signed Runner acceptance must still prove staged-write behavior, cleanup, before/after replacement failure handling, path and alias attacks, approval display, and changeset behavior. Exact `oldText` catches a changed target only when that text no longer matches; it does not detect unrelated file drift. B-specific OS enforcement is `NOT_PROVEN`.

The M8.4 evidence remains separate: four formal attempts, 29 approved read operations, zero source modifications, zero model test executions, zero candidates, and hidden-test PASS 0/4. c-01 recovered eight missing-text action shapes, which supports action-contract compatibility only. The coding-failure root cause and coding reliability remain `NOT_PROVEN`.

## Offline prototype

The same synthetic edit was evaluated with current shell-style replacement (A), a unique exact-text edit (B), and a one-hunk contextual patch (C). The prototype tests cover success, duplicates, changed or missing targets, unsupported file operations, malformed and oversized patches, invalid UTF-8, multiline argv serialization, existing path/argument bounds, and explicit `NOT_PROVEN` security cases. They do not touch disk or establish model quality, authorization, sandboxing, or Kernel behavior.

The example action sizes are model-facing JSON only: A 385 bytes, B 80 bytes, C 139 bytes. B's 79.2% reduction versus A is a single representative payload measurement; it excludes later nested JSON escaping and is not a model-success or tool-call result.

## Required completion statuses

| Area | Status | Evidence boundary |
|---|---|---|
| Research Closure | COMPLETE | Three pinned source reviews, Khaos path audit, A/B/C comparison, security analysis, roadmap, and offline prototype are present. |
| Codex Editing Review | COMPLETE | Pinned source and focused tests reviewed; upstream suite not run. |
| Pi Editing Review | COMPLETE | Pinned source and focused tests reviewed; upstream suite not run. |
| Oh My Pi Editing Review | COMPLETE | Pinned source and focused tests reviewed; upstream suite not run. |
| Khaos Tooling Root Cause | NOT_PROVEN | M8.4 shows action compatibility recovery without source editing; it does not establish the coding-failure cause. |
| Recommended Edit Architecture | B | A minimal single-file structured edit translated to the current shell proposal. |
| Security Compatibility | CONDITIONAL | Plausible reuse path; no B-specific signed-product or adversarial evidence yet. |
| Production Implementation | NOT_STARTED | No production Agent action or runtime code changed. |
| Coding Reliability Closure | NOT_PROVEN | No new real-model coding trial was run. |

## Change and authority accounting

```text
Production code delta: 0
Trusted code delta: 0
New architecture concepts implemented: 0
New trusted processes: 0
New IPC operations: 0
New persistent state: 0
New dependencies: 0
Removed duplication / abstractions: 0
Runtime TCB Delta: 0
Kernel ABI Delta: 0
Trusted Launcher Delta: 0
Remote Model Calls: 0
Production Agent Action Changes: 0
Independent Code Owner approval: NOT_PROVEN
```

## Verification and delivery

- Offline prototype: `python3 -m unittest discover -s reports/m8-coding-tooling -p test_offline_editing.py -v` — 15 tests passed, exit code 0.
- Canonical suite: `python3 -m unittest discover -s tests -v` — 379 tests passed in 700.111 seconds, exit code 0. This includes the real macOS Seatbelt, signed XPC, workspace changes and snapshot checks. Opt-in interactive product acceptance flows were not run.
- Security Freeze: `python3 tools/check_security_freeze.py` — verified; sensitive changes=0; independent approval is external.
- Report hygiene: 12 deliverable files checked for trailing whitespace and final newlines; staged `git diff --check` passed.
- External Codex, Pi and Oh My Pi upstream suites were not run; this task performed pinned source review and inspected relevant tests.

The research branch is `research/m8-5-1-coding-tool-architecture`, based on exact commit `23d00c762af04b20b46f818fc611bcd5db16a211`. PR #32 was rechecked as OPEN and draft at that same head, based on `feature/m8-3-action-contract-reliability`. The new research PR is [#33](https://github.com/hrrrb408/KhaosAgent/pull/33), OPEN and draft, based on PR #32's head branch `experiment/m8-4-glm53-coding-reliability`. No PR was merged.

Only `reports/m8-coding-tooling/` was added in the managed research worktree. The original checkout and its pre-existing untracked artifacts were left untouched.
