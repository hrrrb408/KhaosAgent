# Python to Swift Candidate B Compatibility

## Result

**PASS for the declared wire-string format.** Candidate B string arguments use Python's canonical `json.dumps(value, ensure_ascii=True, separators=(",", ":"))` representation. The production Swift parser now validates that exact representation and recovers the original string. Raw-Unicode JSON is equivalent JSON but is rejected as noncanonical input.

## Executed evidence

- Focused command: `python3 -m unittest discover -s tests -p test_macos_xpc_sandbox.py -k test_trusted_candidate_b_preview_parser_is_bound_and_fails_closed -v`
- Result: 1 test passed on macOS.
- The Python standard library generated 20 requests; the production Swift `TrustedAgentRunnerSource` wrapper and `TrustedCandidateBPreview.parse` processed each request.
- 16 requests were accepted and decoded byte-for-byte to their Python input values; 4 malformed/over-bound requests were rejected as `PREVIEW_INCOMPLETE`.
- Coverage includes Chinese, emoji, non-BMP scalars, multiline source, CRLF and LF, quotes, backslashes, tab/backspace/form-feed, literal `\\u` text, empty replacement, the exact 4096-byte argument boundary, 4097-byte overflow, 128/129-byte path boundary, fixed-script mutation, raw-Unicode noncanonical encoding, DEL, U+2028/U+2029, and U+10FFFF.
- Evidence: [Python/Swift golden fixtures](python-swift-golden-fixtures-final.json). Each case records Python inputs and encoded argv, Swift's actual Runner source and digest, the decision, decoded values when accepted, and the frozen invocation request digest used in the preview summary.
- The signed-review fixture separately constructs an eight-argument request with Python's encoder, uses argv[7] at exactly 4096 ASCII bytes, and confirms the production Swift parser accepts the full request before it is placed into the signed product flow.

## Defect evidence

The pre-fix run rejected valid Chinese, emoji, and non-BMP Python encodings while accepting an equivalent raw-Unicode spelling. The corrected run accepts Python's output and rejects the alternate spelling. The canonicalizer reproduces Python's short escapes, lowercase `\\u` escapes, and surrogate-pair encoding; fixed-script, scope, digest, and size validation remain unchanged.

## Boundary

The production Host's Structured Edit producer is still `NOT_STARTED`. This result proves the request format and production parser interoperate; it does not prove that a future Host producer uses this encoding or that any real model can generate reliable edits.
