# A/B/C coding-tool affordance comparison

## Scope and measurement

A is the existing Khaos shell-plus-Python edit. B is a proposed one-file structured exact-text edit. C is a proposed patch string. Offline prototypes and the same synthetic edit are in offline_editing.py; 15 deterministic tests are in test_offline_editing.py.

The metric script compact-serializes one representative action for changing “return 40” to “return 42” in src/calc.py. It measures action JSON, not the model's reasoning, tokenization, actual tool success, or end-to-end task quality.

| Candidate | Model-facing top-level fields | Non-empty values including type | Example compact JSON bytes | Target semantics |
|---|---:|---:|---:|---|
| A: current shell | 10 | 4 | 385 | argv carries a Python script; read/write scopes are separately supplied |
| B: structured edit | 4 | 4 | 80 | path, oldText, newText; one existing file; one unique match |
| C: patch | 2 | 2 | 139 | one patch string with file path, context and replacement lines |

For this one example, B emits 79.2% fewer compact JSON bytes than A. That only quantifies one representative model-facing output and excludes Host JSON-escaping when oldText/newText are lowered into single-line argv values. It is not evidence that any model succeeds more often or uses fewer tool calls. B requires a new untrusted AgentHost action shape; C requires a patch action and parser.

## Feature and failure comparison

| Dimension | A: shell plus Python | B: minimal structured edit | C: minimal patch |
|---|---|---|---|
| Model writes | Python syntax, source string literals, argv JSON, read and write scopes | path and exact old/new text | patch envelope, path, hunk and context markers |
| Edit location | Whatever the generated script implements | Exact oldText substring | Hunk context plus removed lines; supports multiple chunks |
| Duplicate target | The prompt example uses str.replace, which replaces all occurrences unless the script adds a count check | Reject zero and more than one occurrence | Context may disambiguate; Codex's implementation returns the first match from its current cursor rather than always rejecting ambiguity |
| Target changed | Script-specific; prompt example reports an assertion only when no change occurred | NO_MATCH if oldText changed or disappeared; it does not detect unrelated file drift | Context mismatch returns a patch error; hunk search may be fuzzy and ordered |
| Create/delete | Arbitrary shell can do them, so it has no small edit-only contract | Reject; separate future operations would be needed | Natural patch operations, but require scope extraction and write semantics |
| Multiple files | Possible in arbitrary shell; difficult to bound or summarize | Not supported | Supported by common patch languages, with larger parsing and partial-success concerns |
| Failure feedback | Runner return code plus bounded stdout/stderr; script author chooses messages | Stable untrusted result text for not found, no match, ambiguity, encoding and no-op | Parser/matcher errors plus affected-file result; parsing and application logic are larger |
| Model test step | Separate reviewed shell call | Separate reviewed shell call; no budget increase | Separate reviewed shell call |
| Required Khaos trusted change | None for current path | None if Host lowers to the existing shell action | None only if Host lowers to existing shell; a direct patch IPC path would require separate trusted design |
| Main risk | Model must compose low-level code and scopes; arbitrary script can have accidental semantics | Script/write failure and approval readability need real Runner validation | Parser/translation size, broad multi-file changes and non-transactional commit behavior |

## Same-task offline outcomes

- Unique single replacement: A, B and C produce the same expected fixture bytes.
- Repeated old text: A's representative operation changes both matches. B refuses with AMBIGUOUS_MATCH. C succeeds only when its context identifies one occurrence.
- Changed target text and missing file: B and C return explicit failure; A's demo reports no match or target-not-found in the prototype.
- Missing patch context: C returns NO_MATCH and no result bytes. This proves only the pure in-memory prototype's behavior.
- Add, delete and multi-file patch: the minimal B interface rejects these. The small C prototype rejects file operations beyond one update. A remains an unconstrained shell proposal and cannot be fairly scored as a bounded edit API.
- Oversized patch, malformed envelope, and invalid UTF-8: the prototype rejects them before returning changed bytes.
- Unrelated content drift: the B prototype still applies when the target oldText remains unique. B has no whole-file version token; it detects the targeted precondition, not every file change.

All path traversal, alias, race, approval, sandbox and live writeback rows remain NOT_PROVEN for these prototypes. Existing Khaos tests are separate evidence for its current Runner and Kernel path.

## Decision

B is the best next design experiment because it removes script authorship and default replace-all behavior while staying single-file. Its result is a smaller model-facing shape and a clear precondition. It should be considered compatible only if its lowering uses the existing Launcher approval and exact workspace scopes, and a signed Runner test proves the chosen write strategy under failure. Keep A available as a baseline. Defer C until there is a demonstrated need for multi-hunk or multi-file edits and a separate design for error and partial-commit behavior.
