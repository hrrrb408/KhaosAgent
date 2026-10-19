# Signed Candidate B UI Acceptance

## Result

**B38: PASS_L4 for this exact complex refusal fixture.** The user opened the complete details, scrolled to the bottom, returned to Preview, and denied the request with Escape. The test recorded no Kernel submission, zero Runner executions, unchanged fixture state, and a matching request digest in the Launcher Task Record. This proves reviewability and refusal behavior for this request; it does not prove successful execution.

Evidence: `signed-candidate-b-review-final4.json` and `signed-candidate-b-review-final4.log`. One signed product test passed in 569.792 seconds.

## Signed build and request

- Source head: `e43c00912fb2129718e99fef8c16b7cb1a8d4025`.
- App: `/Users/huangruibang/Applications/khaos-seed-app-7ofh5mf_/KhaosSeed.app`; bundle ID `org.khaos.Seed`; arm64.
- Build record SHA-256: `5f3cc2ebbebdd10d6bebf6a5698142e74c4b75285f9267e4eefabea494f72d46`.
- Deep strict code-signature verification: `true`; code requirement: `identifier "org.khaos.Seed" and certificate leaf = H"aff19dc48e04ec1bec4e905c3359bafa4907176e"`.
- Launcher SHA-256: `b7d871be1690953b5fc995d96b91f664e633930f47d22dc903377a83b72cc749`.
- Agent Host SHA-256: `4c8b8c0f958058a3fb2f32a391dc1f9837d44332679fa8aa1254bbeb0e5e3f68`.
- `KernelProduction.xpc` SHA-256: `b38a2947a5adb8a096428b1cfd4e4d2e98eadb5251847e9f99a092538f4aeaf9`.
- Build input SHA-256 for test-only `AgentHostSandboxModelProbe.swift`: `25f2163d573bd41a3029504121d5d07d0258993e9ced9cf484a78371dc91d428`; acceptance harness SHA-256: `3b115dfcbbc89288ff05be50fbe43b8aa3510b89f21469fcc94d1e4f5c85916b`. Both are included in the build record.
- Disposable workspace: `/Users/huangruibang/Applications/khaos-seed-app-7ofh5mf_/coding-loop-workspace`.
- Request ID: `65ba1a5e39574f50ade0d83ac0a4bf42`.
- Request SHA-256: `db95fa135f9780a3f7a6ab854ffb08796faa8a15ad5bec40b565bd2c4de6048d`.
- Runner source SHA-256: `a0ad6da379656c639353c2acbb05da0ef91851c3f3977140a9bcc79cba948f33`.
- Fixed Candidate B script SHA-256: `844abf29679477569fe00efa10ecb7cd314cea94fe8c4b2e2e1a95b381d55d79`.
- Actual argv: eight arguments; `argv[7]` is 4096 bytes and decodes to a 4064-byte replacement. `argv[6]` decodes to the 41-byte old text. Full argv is preserved in the evidence JSON.
- Exact read scope: `tags.py`. Exact write scope: `tags.py`.
- User decision: denied with Escape. Launcher Task ID: `247954b0-13a4-49bc-a6d6-aa7920e7e273`; workspace session ID: `e40988ad-90b2-4a7d-91e8-3a3be84db755`.

The UI contains Chinese, emoji, multiline Python, quotes, backslashes, tab, backspace, form-feed, CRLF/LF, a bidirectional control, and a replacement at the argument limit. The complete details view exposed argv, decoded old/new text, exact scopes, Runner source digest, Request ID, and request digest; the pane was scrolled to its bottom before denial.

## Outcome evidence

- Launcher Task Record: approval `denied`; Kernel result `not_submitted`; Runner execution `not_started`; commit outcome `not_committed`; cancellation was not requested; command return codes `[]`.
- The Task Record `invocation_sha256` equals the digest displayed in the complete-details view.
- Agent Host terminal result: `task_cancelled`, reason `user_cancelled_or_denied`; one proposal, one approval presentation, one denial, zero tool executions, and zero Runner command return codes. The terminal capture records one refusal `tool_result_returned`; that is not an executed command.
- Actual changed paths: none. The test asserts `tags.py` and canary bytes are unchanged, the workspace Git status is clean, and no staged-edit temporary entries remain.
- Final fixture file hashes, reconstructed from the exact fixture literals after those equality/cleanliness assertions: `README.md` `bf6bad43758a2123242ba7bbbfe5a8646bf2e12dba406f5e2a7b8b02f86093af`; `tags.py` `476ac287f5ed529f016a1ba705a336abb57f38156da8a097a2a0ddbed2e5f164`; `test_tags.py` `f50441252b716c062dfcac6be7c3f3f720f6f7e3bac684bfdc80f79679e73cc8`; `unscoped-canary.txt` `c93bf773ec839b0100117429b1a824238579d7332c24cf48d2bd1f20242ba5ef`. Canonical JSON manifest SHA-256 for this path-to-hash map: `c36730214f6d8d85c4511d1581c6497f2dbf88797f976e7c4cb6a9cc32d35fbe`. These per-file hashes are derived because test cleanup removes the disposable directory after the unchanged-byte checks.

## Failed attempts retained

- `signed-candidate-b-review.json`: interrupted during unrelated preflight; no Picker or Runner evidence.
- `signed-candidate-b-review-final.json`: exceeded AgentHost context before the workspace Picker; no workspace or Runner evidence.
- `signed-candidate-b-review-final2.json`: reached a Picker but non-TTY test input closed before the gate could be acknowledged; no Runner evidence.
- `signed-candidate-b-review-final3.json`: fixture was selected, but the terminal Return gate was not acknowledged. It failed after 637.431 seconds before the Candidate decision and is not B38 evidence.

After the successful final4 test exited, a separate generic app Picker asking to create a unique test file remained visible. It was not part of B38 and was not selected or approved.

## Result boundary

This proves B38 reviewability and refusal for this exact complex request. It does not prove B37 approved execution for the complex request; historical B37 evidence applies only to the exact short request. It does not prove B32/B34/B39 signed cancellation-at-stage behavior.
