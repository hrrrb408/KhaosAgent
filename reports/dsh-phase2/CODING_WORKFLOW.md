# DSH Phase 2: Read, Edit, Test Acceptance

Date: 2026-10-23

## Read → Edit → Test

The deterministic DSH fixture completed a real three-step coding loop in the
signed product. Each proposed operation was reviewed separately by the
codex_agent operator under the user's explicit delegation. The fixture used a
disposable Python workspace containing example.py, test_example.py, and an
unscoped sibling canary.

1. Read: Python read example.py and test_example.py, with those two files as
   the only read roots and an empty write scope.
2. Edit: Python changed only example.py from answer() returning 100 to
   returning 200. Both the read and write scope contained only example.py.
3. Test: Python imported the fixture and ran the unittest for example.py and
   test_example.py. The read scope contained only those two files and the
   write scope was empty.

All three requests returned Runner code 0. DSH consumed the actual successful
test result. The parent verified the final source, the test file, and the
unscoped canary. No DSH operation changed another path. Full per-operation
argv, scope, request IDs, digests, and decisions are in
[signed-ui-operator-decisions-5abf5d3.json](signed-ui-operator-decisions-5abf5d3.json);
the signed result is
[coding-read-edit-test-5abf5d3.json](coding-read-edit-test-5abf5d3.json).

## Fake-result handling

A separate signed run approved one command that printed the success-looking
text Ran 1 test and OK, then exited with code 1. The actual Kernel result
reported the failure and return code; DSH classified the fake-success case as
PASS only because it observed both the misleading output and the real failure.
Evidence: [fake-result-5abf5d3.json](fake-result-5abf5d3.json).

## Boundaries

The standard signed workspace-selection flow performs a separate Kernel
writeback smoke check in the disposable directory before the DSH workflow.
Its unique output file is not part of any DSH proposal or read scope. The test
workspace is disposable; all claims about the three-step DSH loop are based
on the three task-recorded Runner operations above.

This deterministic signed workflow proves the pinned fixture's real
Tool Proposal → Launcher approval → Kernel → Runner → Tool Result loop. It
does not measure real-model coding quality or authorize unattended approvals.
