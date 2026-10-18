# Offline editing evaluation

## Method

The prototypes in offline_editing.py apply transformations to an in-memory mapping of fixture names to UTF-8 bytes. They do not open real paths, create a filesystem, request approval, invoke Runner, or contact a model. Test code is in test_offline_editing.py. Candidate A emulates the prompt's Python Path/replace/assert operation; B implements one exact unique string edit; C implements one small context patch and rejects other patch forms.

The same unique replacement task succeeds for A, B and C. The tests count serialized representative model actions and exercise failures. They do not measure model quality, tool-call count in a live task, filesystem safety or sandbox enforcement.

## Results

The focused offline command ran 15 tests successfully:

- Command: python3 -m unittest discover -s reports/m8-coding-tooling -p test_offline_editing.py -v
- Result: 15 tests, exit code 0.
- Coverage includes unique edit, replace-all duplicate behavior in A, ambiguity rejection in B, context disambiguation in C, changed target text, missing file, unsupported create/delete/multi-file patch, missing patch context with no result bytes, malformed and over-4-KiB patch rejection, invalid UTF-8, multiline JSON argv encoding, existing path and argument bounds, serialized action metrics, and explicit NOT_PROVEN security rows.

Representative compact JSON measurements:

| Candidate | Fields | Non-empty values including type | Bytes |
|---|---:|---:|---:|
| A | 10 | 4 | 385 |
| B | 4 | 4 | 80 |
| C | 2 | 2 | 139 |

These are byte counts for one fixture only. They count the model-facing action JSON, not the Host's later JSON-escaped argv lowering. They do not establish fewer reasoning tokens, fewer calls, better task completion, or real-model success.

The B prototype also shows two limits: it rejects a changed target when oldText is gone, but succeeds when unrelated file text has changed and oldText remains unique; it has no whole-file digest. Its edit semantics do not by themselves guarantee atomic disk writes. The product design therefore requires a real Runner test for a staged replacement strategy.

## Scenario matrix

| Scenario | Offline result | Evidence boundary |
|---|---|---|
| One unique text replacement | A/B/C succeed with same expected bytes | Pure in-memory algorithm only |
| Multiple identical targets | A replaces both; B rejects; C can use unique context | Pure in-memory algorithm only |
| Target content changed | B/C reject when expected target/context is absent | Does not detect unrelated drift |
| Missing file | B/C return TARGET_NOT_FOUND | No actual path lookup |
| Create file | B/C reject as unsupported | A is an arbitrary shell, not a bounded comparable API |
| Delete file | B/C reject as unsupported | No filesystem deletion was attempted |
| Multiple files | Minimal C prototype rejects | Does not assess Kernel multi-file commit |
| Path traversal | NOT_PROVEN | No path resolver or Kernel |
| Symlink escape | NOT_PROVEN | No filesystem or sandbox |
| Hardlink/alias | NOT_PROVEN | No inode or alias check |
| Rename/TOCTOU race | NOT_PROVEN | No concurrent actors |
| Oversized patch | Prototype rejects above 4 KiB | Bound matches current per-argument scale; no product serialization test |
| Multiline edit text | Prototype JSON-encodes text into bounded, single-line argv values | Serialization only; no product grammar or IPC test |
| Invalid UTF-8 | A/B/C return INVALID_ENCODING | Fixture bytes only |
| Unauthorized write | NOT_PROVEN | No approval or scope layer |
| User refusal | NOT_PROVEN | No Launcher or UI |
| Sandbox rejection | NOT_PROVEN | No OS execution |
| Edit then test | NOT_RUN | Algorithms return bytes only; a product test needs a separately approved next operation |

Existing Khaos integration tests are separate and cover its current trusted path: scoped reads and link denial in tests/test_launcher.py, and symlink replacement, hardlink and stale-source rejection in tests/test_workspace_changes.py and tests/test_workspace_snapshot.py. A successful Khaos suite would validate those current components, not the proposed edit adapter.

## Interpretation

The synthetic result supports a narrow engineering claim: B removes Python source construction and prevents the default replace-all behavior for one targeted edit. It does not establish that models will localize better, reach an edit sooner, run tests more reliably, or pass the original benchmark. Candidate B's whole-file drift and write-failure behavior require explicit integration decisions before production implementation.
