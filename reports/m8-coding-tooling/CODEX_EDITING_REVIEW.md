# OpenAI Codex editing review

## Source pin and scope

- Repository: [openai/codex](https://github.com/openai/codex)
- Reviewed commit: 8c076942cb70fba8e5c4732c23f1faabc4aed484
- Scope: model tool declaration, patch parsing/application, approval and sandbox routing, failure results, and focused source tests. This is source review at a pinned commit; no Codex build or upstream test suite was run.

## Model interface and call path

Codex exposes apply_patch as a freeform tool with a Lark grammar. Its description says the model supplies the patch body directly rather than wrapping it in JSON. The patch language names files with Add File, Update File, Delete File, and optional Move to markers. Update hunks express removed, added, and context lines; a file may contain multiple chunks.

The reviewed path is:

1. The tool declaration is created in [apply_patch_spec.rs](https://github.com/openai/codex/blob/8c076942cb70fba8e5c4732c23f1faabc4aed484/codex-rs/core/src/tools/handlers/apply_patch_spec.rs#L5-L27).
2. [intercept_apply_patch](https://github.com/openai/codex/blob/8c076942cb70fba8e5c4732c23f1faabc4aed484/codex-rs/core/src/tools/handlers/apply_patch.rs#L434-L474) recognizes and verifies an apply_patch command. A correctness failure is returned to the model; a non-patch shell command falls through to the ordinary shell path.
3. [execute_verified_patch](https://github.com/openai/codex/blob/8c076942cb70fba8e5c4732c23f1faabc4aed484/codex-rs/core/src/tools/handlers/apply_patch.rs#L476-L571) derives affected paths, selects the turn environment's filesystem sandbox policy, computes path write permissions, prepares approval, and invokes the tool orchestrator.
4. [ApplyPatchRuntime](https://github.com/openai/codex/blob/8c076942cb70fba8e5c4732c23f1faabc4aed484/codex-rs/core/src/tools/runtimes/apply_patch.rs#L76-L114) binds approval details to environment, cwd, paths, patch and computed changes. Its runtime calls the selected filesystem with a sandbox context at [run](https://github.com/openai/codex/blob/8c076942cb70fba8e5c4732c23f1faabc4aed484/codex-rs/core/src/tools/runtimes/apply_patch.rs#L157-L199).

This is more than a string replacement helper: the handler connects a model-facing patch language to policy, approval, filesystem execution, events and a model-visible result.

## Matching and error behavior

The parser resolves paths relative to the action cwd and produces typed Add, Update, Delete and Move hunks. Update content is computed from the current file read by the selected filesystem. [compute_replacements](https://github.com/openai/codex/blob/8c076942cb70fba8e5c4732c23f1faabc4aed484/codex-rs/apply-patch/src/file_update.rs#L25-L55) searches expected line sequences and reports a contextual error when they are absent. [seek_sequence](https://github.com/openai/codex/blob/8c076942cb70fba8e5c4732c23f1faabc4aed484/codex-rs/apply-patch/src/seek_sequence.rs#L1-L110) tries exact matching, then ignores trailing whitespace, trims both sides, and finally normalizes selected Unicode punctuation.

Matching is ordered from the current chunk cursor. It returns the first matching sequence; the reviewed implementation does not reject every repeated context as ambiguous. Multiple chunks therefore depend on useful context and ordering. This is a meaningful design difference from Pi's unique-oldText rule and Oh My Pi's content-tagged line anchors.

Invalid patch structure and missing context produce concrete error text. The handler returns correctness errors to the model, and runtime output includes the failure and any accumulated delta. Codex's patch code also distinguishes failures where the exact filesystem delta is unknown.

## Approval, sandbox and filesystem behavior

Policy approval is conditional. [prepare_apply_patch](https://github.com/openai/codex/blob/8c076942cb70fba8e5c4732c23f1faabc4aed484/codex-rs/core/src/apply_patch.rs#L22-L62) may auto-approve, ask the user or reject based on the action, configured approval policy and permission profile. The runtime then uses the selected platform or executor-managed filesystem sandbox; this behavior is Codex's own policy system and is not a security guarantee for Khaos.

The patch application code has an explicit no-follow option. [no_follow_rejects_leaf_and_ancestor_links_for_every_patch_operation](https://github.com/openai/codex/blob/8c076942cb70fba8e5c4732c23f1faabc4aed484/codex-rs/apply-patch/tests/suite/no_follow.rs#L12-L60) covers add, update, delete and move through symlink leaves and ancestors. [no_follow_rechecks_paths_after_verification](https://github.com/openai/codex/blob/8c076942cb70fba8e5c4732c23f1faabc4aed484/codex-rs/apply-patch/tests/suite/no_follow.rs#L63-L107) swaps a checked ancestor to a symlink and requires rejection. The runtime chooses the option based on its sandbox attempt; this does not establish that every Codex execution mode uses the same policy.

## Partial application and tests

The patch library applies hunks in order and records changes as it goes. It is not a multi-file transaction. The test [test_apply_patch_cli_failure_after_partial_success_leaves_changes](https://github.com/openai/codex/blob/8c076942cb70fba8e5c4732c23f1faabc4aed484/codex-rs/apply-patch/tests/suite/tool.rs#L377-L395) creates the first file, then fails to update a missing second file, and confirms the first file remains. This is direct evidence against treating the patch envelope as atomic.

Other relevant tests include multiple file operations, multiple chunks in one file, missing-context failure without a write, line-ending preservation, and no-follow behavior: [tool.rs](https://github.com/openai/codex/blob/8c076942cb70fba8e5c4732c23f1faabc4aed484/codex-rs/apply-patch/tests/suite/tool.rs#L44-L105), [missing context](https://github.com/openai/codex/blob/8c076942cb70fba8e5c4732c23f1faabc4aed484/codex-rs/apply-patch/tests/suite/tool.rs#L217-L234).

## Transferable lesson for Khaos

Codex demonstrates that an edit affordance can remove shell quoting and teach the model a task-specific patch grammar. The useful transferable ideas are bounded structured intent, contextual failure feedback, visible affected paths and keeping filesystem policy in a separate execution layer.

The patch language itself is not the security boundary. Codex's parser, approval policy, sandbox runtime and filesystem implementation jointly provide its behavior. Khaos must continue to use its own Launcher and Kernel scope enforcement. Codex's multi-file partial-success behavior is a reason to keep the first Khaos candidate single-file and to avoid promising transaction semantics without separate evidence.
