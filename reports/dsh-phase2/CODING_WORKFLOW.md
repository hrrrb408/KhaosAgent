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

The signed multi-step workflow and fake-result UI acceptance are `NOT_RUN`
until their owner approvals occur. The DSH protocol unit tests do not substitute
for these signed product runs.
