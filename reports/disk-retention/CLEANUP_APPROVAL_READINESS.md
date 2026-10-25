# M-Disk.1.2 Cleanup Approval Readiness

Date: 2026-10-25
Mode: exact-scope, read-only owner package. No historical deletion was performed.

## Owner-only package

The local owner-only directory contains the new three-candidate manifest, checksum sidecar and Dry Run. The exact private path is supplied directly in the Codex handoff and intentionally omitted from this repository report.

```text
Manifest: KHAOS_LARGE_SCRATCH_CLEANUP_APPROVAL.json
Manifest SHA-256: 7241ce17046e58d0c8fd0451f226e95c2453bc0510ec1978a94c72f1334f08dc
Dry Run: LARGE_SCRATCH_DRY_RUN.json
Dry Run SHA-256: a061f03b712b0f54e7b3a32eda16625e5aa3df77dedc0d48de265c0435cde79d
Source V2 SHA-256: 9f67da45231da9c85a36597e27bf7a400dd5fff95291df9dbc4417b84fc353f5
Candidate IDs: exactly the three historical large Scratch IDs named in this phase
```

The final manifest was created after the full regression suite with only those three IDs and reloaded through the repository's sidecar verifier. The existing read-only audit utility was run against it. It exited `2`, the expected fail-closed status when candidates are refused, and wrote a Dry Run with three candidates, zero ready, three refused and zero mutations. An earlier pre-regression manifest and Dry Run remain in the same owner-only directory under explicitly marked `PRE_REGRESSION` names; the final names above are authoritative.

## Why approval is not actionable

All three exact historical paths were missing at capture. The manifest preserves their last-known device/inode, sizes, tree fingerprints, source/build hashes and evidence bindings, while recording current identity as unavailable. The audit utility refuses each path before any process-reference check. This is not a deletion list that an owner can safely approve: there is no current target identity to authorize.

```text
Ready candidates: 0 / 3
Refused candidates: 3 / 3
Historical deletion by this run: 0
Owner cleanup approval: PENDING / NOT ACTIONABLE FOR THESE MISSING TARGETS
```

The original GGUF source, existing owner-only evidence archives, Git worktrees, DSH checkout, credentials and signing material remain protected. The 21 smaller historical roots, three unresolved tiny fixtures and any other temporary files are outside this manifest.

If any target is later found elsewhere, do not infer that it is the same artifact from its name. Record the discovery, create a fresh identity-bound manifest, reverify evidence and consumers, rerun the read-only audit, and request approval against that new SHA. No prior approval or this package carries forward.
