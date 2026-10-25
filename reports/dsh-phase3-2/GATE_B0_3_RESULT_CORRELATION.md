# Gate B.0.3 Result Correlation

**Engineering source review: PASS. Signed runtime correlation: NOT_RUN.**

## Source path reviewed

The current experimental path binds the exact Launcher result text and its request context:

1. The experimental Trusted Launcher hashes the UTF-8 bytes of `AgentToolOutcome.text`.
2. The Host validates that digest against the received text and the pending DSH operation correlation.
3. After receiving the Host reply, the parent Launcher emits its terminal event with runtime trial, task, request, approval, Kernel, Runner, and result digest fields.
4. The DSH tool adapter carries the trusted digest into delivery telemetry; the evaluator joins the delivery to the operation-specific terminal result and request record.

The initial compiler failure was in the Host validator's missing explicit Swift `return`. The bounded source fix compiles in the fresh signed build; it does not change the validation expression. Prior historical signed failures remain `FAIL` and were not reinterpreted.

## Evidence status

- Focused builder/runner tests: **26 PASS**.
- Pinned DSH semantic tests: **20 PASS**.
- Pinned DSH bridge/lifecycle tests: **17 PASS**.
- Foreign-trial result with the same content digest: synthetic evaluator test **REFUSED** because its runtime trial identity does not match.
- Missing parent terminal and wrong result digest: synthetic evaluator tests **REFUSED**.
- Signed parent terminal records and signed DSH delivery: **NOT_RUN** because no workspace trial was launched.

Equal content hashes are not treated as unique operation identities. Request ID, runtime trial ID, approval digest, and the matching parent/DSH records remain necessary for correlation. The passing synthetic tests do not replace signed execution evidence.
