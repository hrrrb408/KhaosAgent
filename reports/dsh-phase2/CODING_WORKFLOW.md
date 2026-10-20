# DSH Phase 2: Read, Edit, Test Acceptance

Date: 2026-10-20

The deterministic DSH Agent Loop fixture operates on a disposable Python
workspace. The DSH model fixture first reads `example.py` and
`test_example.py`, uses the actual read result to propose an edit to
`example.py`, then uses the actual edit result to propose a focused unittest
command. Every operation goes through the signed Launcher and Kernel path and
requires a separate owner approval.

Run on macOS:

```bash
python3 tools/run_dsh_xpc_attack_acceptance.py \
  --dsh-source /tmp/khaos-dsh-687f282 \
  --node-archive /tmp/node-v22.19.0-darwin-arm64.tar.xz \
  --signing-identity "<Apple Development identity>" \
  --mode coding \
  --evidence-path "$PWD/reports/dsh-phase2/coding-read-edit-test.json"
```

Select the printed workspace in the signed Picker. Approve exactly the displayed
read, edit, and test operations. The script verifies three distinct approvals,
three successful Runner results, DSH's use of the actual passing test result,
the exact `example.py` content, unchanged test and sibling canary files, and
the Launcher task record.

The companion `--mode fake-result` acceptance runs one approved command that
prints `Ran 1 test` and `OK` before returning status 1. DSH must observe the
failed status rather than treating success-looking output as a passing test.
It is a separate signed run and should have its own evidence file.

## Current evidence

The first signed coding attempt at source SHA
`efadf67a35bb70e0441f737af457a619e7c8aae3` completed two real, separately
approved operations: scoped Read and Edit. The edit committed only
`example.py`. The DSH fixture then stopped before proposing Test because it
stringified the outer `ContentBlock[]`, escaping the structured Launcher
result's quotes before checking `ok`. The original failure record is retained
at `failed_attempts/coding-efadf67.failed.json`; it is a failed attempt, not a
workflow pass.

The result reader now extracts text blocks before interpreting the Launcher
JSON. A focused regression test passes in the 8/8 pinned DSH suite. Commit
`ddf41dae96ff1f5d5547d021d77fa68be64afc5b` also stages the helper in the
temporary signed runtime build. The signed app built successfully at that SHA
but no workspace selection reached the app before the acceptance timed out.
The run record is `failed_attempts/coding-ddf41da-picker-timeout.failed.json`.
It remains `FAILED_ATTEMPT`, not an approval denial or a completed workflow.
Its disposable workspace was
`/private/var/folders/l3/00y511gj4q55gj2z6zdqzrs00000gn/T/khaos-dsh-xpc-attack-ajumqdsy/coding-workspace`.
The preserved Launcher log contains only the initial tool proposal and Picker
request; no Runner operation was submitted.

Three subsequent pre-acceptance failures are also preserved under
`failed_attempts/`: the first exposed the missing helper copy in the bundle
stager, the second was caused by an untracked failure record making the
builder's required clean-worktree check fail, and the third timed out at the
workspace Picker before any operation was submitted. The earlier failure
record was moved out of the checkout before the successful build. The stale
app process from the first signed attempt was terminated after confirming its
binary path was inside that attempt's private scratch directory.

Fake-result UI acceptance and the completed signed Read → Edit → Test flow
remain incomplete. The DSH protocol unit tests do not substitute for those
signed product runs.
