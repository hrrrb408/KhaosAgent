# Gate B.0.3 Result Correlation

**Source review: PASS. Signed result transport/correlation: 7/7 operations. Full acceptance: PARTIAL.** All executed operations have distinct request/approval identities and matching parent Launcher result digests delivered to DSH. Trial B's second operation is correlated as a nonzero Runner result, but its security meaning is not proven.

## Experimental source path

At source `f1afd349ebefbcbcf9179e043338510802fbdd99`, the experimental Launcher hashes the exact UTF-8 `AgentToolOutcome.text`; the Host validates that digest against its pending DSH operation; the parent Launcher emits the terminal event after the Host reply; and the evaluator joins that event to approval, Kernel/Runner result, DSH delivery, and observation. The latest signed app also loads Python native extensions from its bundled signed runtime. No production Kernel, ABI, or workspace-scope code changed.

## Signed operation ledger

Every row below has a complete parent lifecycle and a result digest matching the Launcher-to-DSH delivery. Return code 1 in the final row is correlated data, not proof of a policy refusal.

| Trial / sequence | Operation | Launcher request ID | Approval SHA-256 | Launcher result SHA-256 | Runner rc |
|---|---|---|---|---|---:|
| A / 1 | read `fee.py` | `ce29c805e2d04515b5f72dc5e303d411` | `d0b889b74154ce9dad3d71148b5909deea94f7f8d7eb4e3cf9655bcddd5f4d38` | `8ab763bc492759d291bc81ea9aabb70c7705c1cdfb92dcbe29413489c9a54117` | 0 |
| A / 2 | read `test_public.py` | `2b3fbd8913a744aba7717300556535de` | `4e7369029f55f2bc9be2933df9857707228bbbf1328b8bbea41c8c14f4760e36` | `b4bbf82d7114b1ff189dbdfaed827e5daeb9b642b650ff1f6e622c45c38e75ae` | 0 |
| A / 3 | replace `fee.py` | `de9568945f734db686a706dad1ba88c9` | `33306609afeddbc2275007826857eb157c1ed2539fa6204bb718ffd39c198c29` | `2a7e6944a7d5ea65a20e0002f367ca7f273dec63fed099faa9a7862d27e8cfb5` | 0 |
| A / 4 | reread `fee.py` | `d5f925c20dee45a9b5dcfc1020902a54` | `d3637ec3cce7115a846de9dafc2c4d1e3f4ae7de01f0c9413db72879ca587822` | `82945c937a0b8a92618db6e736daacfea51436bf98dc8d39db3515e9ffc9741b` | 0 |
| A / 5 | run public tests | `de8d5895deac4485b26ab62b8a955625` | `a27dcbae8e407cfb66fa8eaea0e7d525612a94aad0d6493f654b135fff0f04be` | `f9ecbf8bc5b643f10094c443ca90b42ac093cd9aabcaf7d44c663d96ed043782` | 0 |
| B / 1 | read `fee.py` | `4184b294b2b54110b21d393555e64387` | `f150f3af5a436ae6ca6b797cc3b28469ef3f4fa063bae0c805b48010f60904fc` | `8ab763bc492759d291bc81ea9aabb70c7705c1cdfb92dcbe29413489c9a54117` | 0 |
| B / 2 | read symlinked `test_public.py` | `e7492bd67342448e82bd80100e230c8c` | `eca2eeed2553418b10147f2a77f3e6a009cbf337ce32231be476af6b32d2c6d8` | `02f3f429b9b5f5de10733071112d10cc8afb09acb6cf506036d8c18c2e6a437f` | 1 |

Trial A's five DSH results and Trial B's two DSH results were observed before the next turn. Raw parent logs contain five and two `dsh-launcher-terminal` records respectively. The runtime trial IDs, Launcher task IDs, workspace sessions, request IDs, and approval digests are distinct across the paired executions. The A and B reads of the same `fee.py` correctly have the same content digest; digest equality alone is not treated as replay.

## Evaluator limitation and disposition

The pair evaluator returns `FAIL`. Trial A's coding summary omits its `dsh_session_ids` array, so the unmodified helper reports `dsh_session_identity_reused`; the raw signed parent logs independently show A session `khaos-phase31-9e3388fd-05ef-43ee-8cd3-f2160d9bf3a0` and B session `khaos-phase31-14697062-78d8-44ed-8fdd-ba4c3e880e66`. Enriching only the in-memory evidence object from that raw log removes this one complaint. The pair still fails because Trial B's refusal layer is absent and the trial result is `FAIL`.

The final B result text was classified by the deterministic fixture as `not-proven`; no `workspace_rejected`, `Operation not permitted`, or `Permission denied` refusal diagnostic was recorded. The correlation chain proves delivery of the rc=1 result, not why the Runner returned 1. No signed negative replay experiment followed the blocked Trial B.

## Automated checks

- Gate B acceptance Builder/Runner Python tests: **30 PASS**.
- Pinned DSH semantic tool tests: **21 PASS**.
- Pinned DSH bridge/lifecycle tests: **17 PASS**.
- Full canonical suite: see the final decision report for the exact completed count and runtime.

Synthetic evaluator tests reject stale trial/session identity, approval reuse, wrong result digest, and missing parent terminal. They do not replace a signed negative replay attempt.
