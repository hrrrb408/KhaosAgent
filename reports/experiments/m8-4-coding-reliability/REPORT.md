# M8.4 controlled coding benchmark

Status: PREFLIGHT_IN_PROGRESS. Formal remote attempts started: 0. No A/C real-model comparison or coding result is claimed.

The actual dependency chain is PR #27 -> main, PR #28 -> main, PR #29 -> #28, PR #30 -> #29, PR #31 -> #30. All five PRs remain open with passing checks at their audited heads. M8.3's historical statement that PR #28 was based on PR #27 is incorrect; repository-audit.json records the current GitHub base/head SHAs. No earlier PR was modified or merged.

Frozen inputs match. Independent A/C signed products are built with common diagnostics; only the reviewed normalization block differs. Trusted components compare equal after signature removal, and all other packaged Kernel/Broker files are byte-identical. Actual signed Host diagnostic transport and parser probes pass. Canonical validation passed 376 tests in 686.398 seconds. One explicitly reviewed deterministic no-op terminal check remains before requesting fresh per-attempt remote authorization.

The initial zero-tool terminal probe returned text but exposed the Launcher's existing absence of Task Record for zero-tool tasks. The observer retained an unknown outcome; raw failure evidence is preserved locally and a sanitized summary is archived. This limitation will remain explicit in formal results.

The fixed formal order is A/a-01, C/c-01, C/c-02, A/a-02. Original task, model parameters, budgets and independent grader are frozen in EXPERIMENT_PROTOCOL.md and experiment-config.json. No previous authorization is reused. Every operation requires independent human review.
