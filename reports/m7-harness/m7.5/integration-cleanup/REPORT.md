# Final integration — process-group test cleanup

PR #22 → #25 merged in order through protected normal merges. PR #26 targets
exact main base `2fd9c21be22e8c2dde9a92ec605e6971413d5d3c`.
Its first current-declaration canonical CI (run `38937639884`, head `38590dd`)
ran 341 tests in 794.415s with one error. Preserve `remote-ci-failure-1.log`.

The failure is at `tests/test_macos_seatbelt.py`'s second `os.killpg` in the
`finally` block, not its first real process-group kill. The leader was already
waited and the descendant output pipe checked for EOF. Darwin returned EPERM
for the subsequent cleanup signal. The repository already has reviewed
`_kill_process_group` / `_signal_process_group` handling for this condition;
the test already imports these helpers. No production repair is necessary.

Replace only the duplicated finalizer with `_kill_process_group(process)`.
Keep the initial real kill, PGID/readiness, five-second wait, one-second pipe
readiness and exact EOF assertions unchanged. Existing live-leader EPERM still
raises. Add coverage of the known-reaped-leader branch, which must not attempt
to obtain child exit information again after reaping. No blanket EPERM catch,
timeout extension, retry of execution, test skip or weakened assertion is added.

`fault-probe.py` runs this actual real-OS test while injecting EPERM only on the
second group-signal call. The first kill is real. `fault-before.json` reproduces
the old finalizer error; `fault-after.json` passes with two group-signal calls,
zero failures and zero errors. These are test-cleanup fault injections, not a
substitute for the real enforcement assertions. Reproduce after the fix with:

```bash
PYTHONPATH="$PWD" python3 reports/m7-harness/m7.5/integration-cleanup/fault-probe.py /tmp/m7-cleanup-after.json
python3 -m unittest discover -s tests -p test_macos_seatbelt.py -k process_group -v
```

`focused.log`: all four focused tests pass (0.055s), including real sandbox
fork/group confinement and kill/pipe closure. Required complete CI will run at
the new head before merge; this report does not relabel the failed run as pass.
After all five merges, rerun canonical suite and Freeze on the exact final main.

Production code delta: 0. Runtime trusted code delta: 0. One existing protected
test finalizer/branch coverage changed, with fresh exact-base declaration and
reviewed test manifest/baseline digest. All 34 runtime TCB files remain identical
to M7 start. New architecture concepts, trusted processes, IPC operations,
persistent runtime state and dependencies: 0. Removed duplication: raw test
finalizer reuses the existing cleanup helper. Existing signed lifecycle and
failed actual GLM coding records remain unchanged. Independent Code Owner
approval remains NOT_PROVEN. This cleanup defect is separate from the older
M7.3 truncated XPC fixture failure, whose underlying exception remains unknown.
