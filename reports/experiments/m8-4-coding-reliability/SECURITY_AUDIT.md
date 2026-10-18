# M8.4 security audit

Runtime TCB delta: zero. No Launcher, Kernel, Kernel ABI, Seatbelt, XPC identity, snapshot, changeset, admission or lifecycle source changed. The untrusted Host adds only opt-in fixed response/normalization/acceptance diagnostic events. The external observer retains bounded metadata, rejects payload fields, and marks overflow. The build-governance change explicitly configures that existing Host-only diagnostic environment before signing; normal builds remain default-off.

Production Host diagnostics delta: +40/-4 lines (all untrusted); external observer +42/-2; packaging builder +13/-4 build-governance lines. Canonical suite PASS: 376 tests in 686.398 seconds, exit 0. Current exact-base Security Freeze check passed against PR #31 head f5631de1b5ebb056af28bbd145757b6f76053154 with nine declared build/test/governance changes. Every runtime TCB manifest entry is retained. Tests, builder configuration and governance hashes were reviewed explicitly; independent Code Owner approval remains NOT_PROVEN.

Frozen benchmark/grader/gold/hidden inputs are unchanged. Hidden content remains outside model workspaces. No remote request has started, no tool has been automatically approved, and original M8 failure evidence remains unchanged. The final signed one-operation terminal/refusal check remains pending independent review; security acceptance is not yet final.

New architecture concepts: 0. New trusted processes: 0. New IPC operations: 0. New persistent product state: 0. New dependencies: 0. Existing preparer, grader, product launcher and terminal observer are reused; A has only the bounded source-block removal and no competing production parser.
