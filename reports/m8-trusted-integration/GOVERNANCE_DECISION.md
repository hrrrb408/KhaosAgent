# M8.5.2A.5 Governance Decision

- Version: 1
- Decision date: 2026-10-19
- Decision ID: M8.5.2A.5-GOV-01

## Decision

The project owner authorized Codex to make the narrowly scoped Trusted Launcher,
Candidate B preview, active-task cancellation, related test, and Security Freeze
changes on the independent branch `feature/m8-5-2a5-trusted-ui-cancel-implementation`.
This is owner-authorized source development. It is not Runtime Agent Self-Modification
and does not authorize any Runner operation.

The decision replaces the earlier independent-review prerequisite **for beginning
this source-development work only**. It does not rewrite earlier Gate A results or
claim that independent review occurred.

## Required controls

- Development Authorization: `OWNER_AUTHORIZED`
- Security Freeze: required
- Canonical regression suite: required
- Relevant real-OS tests: required
- Signed acceptance: required where applicable; each Runner operation still needs
  its own user decision
- Owner Review: required before merge
- Independent Code Owner Review: `NOT_PERFORMED — SINGLE_MAINTAINER_MODE`

Kernel authority, Kernel ABI, Seatbelt policy, workspace scope authority, and runtime
approval semantics remain unchanged. This governance decision adds no permission,
process, IPC operation, dependency, or persistent product state.

## Binding and status

At implementation start, PR #38 was confirmed OPEN and Draft at exact head
`12c75d75c1464aabd631b092e07903631f692ff6`. This change is stacked on that head.
The project owner's review of the resulting diff remains `PENDING`; no merge or
deployment is authorized by this decision.
