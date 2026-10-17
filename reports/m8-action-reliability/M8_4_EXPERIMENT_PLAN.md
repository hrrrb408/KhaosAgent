# M8.4 Real-Model Coding Reliability Experiment Plan

Status: plan only. No remote model call is authorized or performed by M8.3.

## Freeze before the experiment

1. Keep the original coding task, hidden tests, independent grader, and workspace baseline byte-for-byte unchanged. Record their digests before the first attempt.
2. Pin the signed Harness build, source revision, provider and exact model version. Use the same execution budget and approval policy for both arms.
3. Use separate disposable workspaces derived from the same baseline. Do not carry edits, model history, or Candidate state between arms.
4. Capture bounded diagnostics with one formal Attempt ID per run. The observer must preserve stage and error categories without model content, file contents, credentials, or command output beyond the approved bounded result fields.
5. Obtain a separate explicit authorization for the provider, endpoint, data categories, and number of attempts before any remote transmission.

## Comparison

Run the unchanged strict ten-field parser (A) and the M8.3 restricted list/shell text normalization (C). Keep prompts, correction instructions, provider JSON-object mode, task, test set, model version, environment, and budgets identical. Treat every attempt as an independent sample. Do not add B or a prompt change to this experiment; either would introduce another variable.

For each arm and attempt, record separately:

- Action Contract Acceptance: initial and correction responses accepted by the parser.
- Correction Success: whether the single format correction produced a valid action.
- Tool Execution Progress: approvals and completed Runner calls, with their return codes.
- Code Modification: whether the intended in-scope source changed and its digest.
- Model Test Execution: whether the model proposed and completed the required test command.
- Hidden Test Success: independent grader result against the unchanged hidden set.

Publish the denominator, per-attempt terminal class, missing-field categories, and confidence limits. Do not infer coding reliability from acceptance rate, tool count, stdout claims, or a single attempt. Report refusal, timeout, malformed output, and incomplete evidence separately. Preserve every raw attempt artifact without overwrite and redact credentials before archival.

## Decision rule

M8.3's protocol comparison can motivate the experiment but cannot substitute for it. Claim a real-model reliability improvement only if the predeclared independent hidden-test outcome improves under the fixed comparison and evidence capture remains complete. Otherwise report the observed result without changing the success definition.
