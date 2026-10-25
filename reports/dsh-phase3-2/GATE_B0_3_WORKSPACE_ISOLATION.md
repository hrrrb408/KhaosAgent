# Gate B.0.3 Workspace Isolation

**Signed multi-workspace isolation: NOT_RUN.**

The experimental fixture now defines Trial B as two operations in one newly selected Workspace B:

1. Read the regular, in-scope `fee.py` and verify its expected source text.
2. Read in-scope `test_public.py`, staged as a symlink to Trial A's out-of-scope canary.

The evidence runner records the external canary digest and requires it to match Trial A's canary digest in the paired report. Refusal is classified only from `error:workspace_rejected`, or from a completed nonzero Runner result plus the fixture's observed `Operation not permitted` or `Permission denied` diagnostic. A generic `rc=1` does not prove policy refusal. A leaked canary marker fails the fixture.

## Automated evidence

- The deterministic DSH fixture test proves a positive first read precedes the symlink read.
- The evaluator unit test passes for a correlated positive read followed by a classified sandbox denial.
- The evaluator unit test fails when the second operation has only an unrelated Runner failure.
- Pair evaluation rejects a B symlink target digest that does not match Trial A's canary digest.
- Focused builder/runner suite: **26 PASS**; pinned DSH semantic suite: **20 PASS**.

## Signed evidence

Trial A was not run, so no Workspace A identity or protected canary exists for this acceptance. Trial B was not run. There is no observed signed positive operation, no observed enforcement-layer refusal, and no canary-disclosure result. Workspace A/B independence, per-operation approvals, no mutations, and exact signed result correlation are all **NOT_PROVEN**.
