# Khaos Coding Reliability Dataset v1

Frozen on 2026-10-14 from the public `hrrrb408/KhaosAgent` Git history. This is a
Khaos-specific reliability sample, not a cross-project coding leaderboard.

## Frozen contents

- `manifest.json` records 12 task prompts, categories, exact source and base
  commits, public test paths, focused test commands, and SHA-256 hashes.
- `frozen/<task-id>.bundle` contains each repository snapshot at the commit
  immediately before its fix. Each bundle has one synthetic root commit, so later
  commits and their objects are unavailable to the Agent. Git bundles keep the
  fixed baselines portable without embedding nested `.git` directories in this
  repository.
- `private/<task-id>/gold.patch` preserves the source fix for the grader.
- `private/<task-id>/source.patch` contains the source-only reference change.
- `private/<task-id>/hidden-tests.patch` preserves test changes from the fix.
  These private files are siblings of the task workspaces and must never be
  selected as the Agent's workspace.
- `runs/` is reserved for one disposable clone per task and model.

The frozen snapshot checks and `git apply --check` passed for all reference
patches. See `validation/results.json` for the gold-test summary and
`validation/baseline-discrimination.json` for the baseline-versus-gold checks;
raw validation logs and temporary grader workspaces remain local. The Agent
receives only the prompt from the manifest and the selected
task repository. Start each run by cloning its bundle from the manifest into a
fresh workspace; do
not reuse a model's edited repository for the other model.

## Evaluation controls

Use identical prompt text, task order, source commit, Khaos product build,
workspace root, operation budget, Runner budget, and per-operation approval
policy for both models. Keep local model time, Runner time, and approval wait
time separate. Preserve every attempt, including failed, denied, timed-out, or
budget-exhausted attempts.

Use only the public tests during model work. After the attempt, make a separate
grader copy, apply the hidden test patch, and run the recorded focused test
commands. Keep gold patches out of both model workspaces and model prompts.
Tasks that ask for test-harness changes are scored separately from production
code correctness and require the mutation/fault-injection checks recorded in the
manifest.

The model-facing task workspace is the task directory itself. Do not select the
dataset parent or `private/` directory in the workspace Picker; the Kernel's
normal scope and approval rules must remain in effect.

## Selection and limits

Tasks cover IPC bounds, scoped package access, macOS model API compatibility,
trusted-path refactoring, Runner diagnostics and exception handling, a peer
socket race, nested image cleanup, and three test-harness reliability cases.
They are recent real Khaos maintenance changes, selected before either formal
model run. The tasks come from one public repository and several share the
Runner subsystem, so aggregate results must not be generalized to unrelated
software projects. The public source history also means pretraining
contamination cannot be ruled out.

SWE-bench Verified was considered because it is based on real GitHub issues and
provides fixed base commits and test patches. Its documented evaluation setup
uses Docker, but this machine currently has no running Docker daemon. This local
dataset keeps the intended Khaos code and OS-test environment without adding a
benchmark dependency or changing the trusted product.

## Product and architecture scope

Dataset preparation changes no Khaos production code, trusted code, processes,
IPC operations, persistent product state, dependencies, or authority. Model
edits remain confined to disposable task clones. The signed product and its
normal AgentHost → Launcher → Kernel → Runner path are used unchanged.
