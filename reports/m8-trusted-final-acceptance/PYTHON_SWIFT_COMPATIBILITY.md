# Python to Swift Candidate B Compatibility

## Result

**PASS for the declared Candidate B string format.** Both `oldText` and `newText` are encoded as Python's canonical `json.dumps(value, ensure_ascii=True, separators=(",", ":"))` strings. The production Swift parser accepts that spelling and rejects equivalent raw-Unicode JSON as noncanonical input.

## Executed evidence

- Focused command: `python3 -m unittest discover -s tests -p test_macos_xpc_sandbox.py -k test_trusted_candidate_b_preview_parser_is_bound_and_fails_closed -v`.
- Result: one macOS test passed.
- Python's standard library generated 20 requests. The production Swift `TrustedAgentRunnerSource` and `TrustedCandidateBPreview.parse` accepted and decoded 16 valid cases byte-for-byte, and rejected four malformed or over-bound requests as `PREVIEW_INCOMPLETE`.
- Cases cover ASCII, Chinese, emoji, non-BMP scalars, multiline source, CRLF/LF, quotes, backslashes, tab/backspace/form-feed, literal `\\u` text, empty replacement, 4096-byte acceptance and 4097-byte rejection, path bounds, fixed-script mutation, raw-Unicode noncanonical spelling, DEL, U+2028/U+2029, and U+10FFFF.
- Golden inputs and parser output: `python-swift-golden-fixtures-final.json`. Each record includes Python input, encoded argv, the actual Runner source and digest, Swift decision and decoded values, and the frozen invocation digest.
- The signed review fixture is a test-only deterministic AgentHost model probe. Python generated the expected eight-element argv with the standard library; the probe's encoder output matched every argv element exactly. `argv[7]` is exactly 4096 encoded bytes and decodes to a 4064-byte replacement. The short signed prompt marker is 35 UTF-8 bytes so the fixture fits the existing AgentHost context limit. This validates the signed probe route and parser; it is not a production AgentHost Structured Edit implementation.
- The signed product's actual complete-details screen displays the same 8-element request shape, 4096-byte `argv[7]`, 4064-byte decoded replacement, `tags.py` read/write scopes, Runner source SHA-256 `a0ad6da379656c639353c2acbb05da0ef91851c3f3977140a9bcc79cba948f33`, Request ID, and request digest. The signed UI decision and refusal outcome are tracked in `SIGNED_UI_ACCEPTANCE.md`.

## Defect evidence

The pre-fix parser rejected valid Chinese, emoji, and non-BMP Python encodings while accepting an equivalent raw-Unicode spelling. The fix reproduces Python's short escapes, lowercase `\\u` escapes, and UTF-16 surrogate-pair encoding. Fixed-script identity, scope, digest, and size validation remain unchanged.

## Boundary

Production Structured Edit is still `NOT_STARTED`. The compatibility result proves Python-encoded strings interoperate with the production Swift parser, and the signed test probe presents the same bytes. It does not prove a production Host producer or real-model coding reliability.
