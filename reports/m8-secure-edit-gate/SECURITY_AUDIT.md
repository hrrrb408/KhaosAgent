# Security Audit

## Scope and invariant review

This branch changes one protected test file and adds research reports. It does not modify production Python, Agent Host, Trusted Launcher, Kernel, Kernel ABI, XPC identity, Seatbelt policy, workspace authority or production prompts/actions. The fixed probe remains a test-only Shell proposal with per-fixture exact scopes.

| Required report field | Delta |
|---|---|
| Production code delta | 0 lines |
| Trusted code delta | 0 runtime TCB files and 0 runtime TCB lines |
| New architecture concepts | 0 |
| New trusted processes | 0 |
| New IPC operations | 0 |
| New persistent product state | 0 |
| New dependencies | 0 |
| Removed duplication / abstractions | 0; the change adds target-specific test cases and fixes one test fixture typo. |

The protected test inventory and declaration were updated for review; runtime TCB manifest entries, roles and boundaries remain unchanged. The regular and exact-base Security Freeze checks passed. This governance check is not an independent code-owner review.

## Evidence classification

- L3 target-specific results use real macOS Seatbelt Runner execution plus Kernel snapshot/changeset validation.
- L4 results cover only the existing v8 positive, existing v2 refusal and one separately authorized exact positive replay.
- No remote model or network recipient was used.
- No private benchmark data or Hidden Tests were read, transmitted, or modified.
- Independent Code Owner approval remains NOT PROVEN.

## Gate decision

There is no observed unauthorized live write in the tested fixtures. Full Gate A is still **NOT_PROVEN** because several required signed operations, long-payload approval reviewability, and commit-cutoff behavior lack evidence. No security guarantee is inferred from tests that were not run.
