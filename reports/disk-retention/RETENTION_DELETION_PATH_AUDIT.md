# M-Disk.1.4 — Retention Deletion-Path Audit

Scope: `experimental_artifact_retention.py`, `run_dsh_xpc_attack_acceptance.py`, `build_dsh_xpc_acceptance_app.py`, `audit_experimental_artifacts.py`, their direct cleanup call sites, and the three recorded experiment source revisions.

## Current deletion paths

- `cleanup_invocation_scratch()` accepts only a directory directly under the resolved default temp root, with the expected Khaos invocation prefix, owned/private parent, expected device/inode and tree fingerprint, and clear `lsof` references. It atomically renames to a random quarantine name, rechecks identity/tree/references, then uses fd-relative `shutil.rmtree` with symlink-attack resistance. Refusal restores the original name when possible.
- Its only production-in-repository caller in the experimental acceptance driver passes the local `scratch` and identity tuple created by that same invocation's `tempfile.TemporaryDirectory(prefix="khaos-dsh-xpc-attack-")`. The driver detaches Python's finalizer before making the explicit preserve-or-clean decision. It does not load or enumerate old manifests to find paths to delete.
- The helper does not carry a separate invocation nonce; current ownership is supplied by the sole caller's local `TemporaryDirectory` object and freshly captured identity. No other call site was found. This conclusion is limited to the inspected repository call graph, not arbitrary same-user code.
- The signed App builder rejects an existing output `.app` path before creating anything. It retains a successfully completed output App; on failure it best-effort removes only the output path it just created and its own `mkdtemp(prefix="khaos-dsh-xpc-acceptance-")` staging tree. `ignore_errors=True` means an interrupted or failed cleanup can leave a partial build; it cannot select the three historical scratch roots.
- `audit_experimental_artifacts.py` exposes only exact-manifest validation/dry-run behavior and does not mutate candidates.

## Historical source and task evidence

The three recorded Phase 3 source revisions contain the acceptance driver's `TemporaryDirectory(prefix="khaos-dsh-xpc-attack-")` creation. In each revision, the `--preserve-scratch` branch detaches the finalizer, and the failure-record path also detaches it after writing the failure record. They contain no `cleanup_invocation_scratch()` or explicit `shutil.rmtree()` call. This is direct evidence that the old driver intentionally retained its own failed Scratch; it does not identify any later removal. A later invocation's `TemporaryDirectory` instance still refers only to that later invocation's unique path. The M-Disk retention-helper revision that created the copied diagnostics is not independently bound in the three original trial indexes, so it cannot be used to attribute a historical deletion.

The build-input records and signed Runner logs are preserved separately and verified in `EVIDENCE_PROVENANCE_DECISION.md`. They bind the experiment and its recorded Runner events, but do not record a later filesystem deletion operation, process, or timestamp.

The exact-target process check found no current process command line referring to the missing paths. The bounded macOS log query timed out; it provides no deletion event. No process was terminated and no system privilege was used.

```text
Unauthorized Cleanup Mechanism: NOT_FOUND_IN_SCOPE
Historical Deletion Origin: UNKNOWN
Historical Paths Read, Moved, or Deleted by This Investigation: 0
Historical Paths Read, Moved, or Deleted by M-Disk.1.2/1.3 Runs: 0 (per their retained records)
```

`NOT_FOUND_IN_SCOPE` means no matching path in the reviewed Khaos code or available records. It is not proof that no external process or system maintenance removed the roots.

The per-revision call-site counts and current-path checks are retained in the owner-only record `m-disk-1-4-20261025/M-DISK-1-4_DELETION_PATH_AUDIT.json`, SHA-256 `597afb3ff29e92abf28c04c3c3cd405b4183a9dcbcce050707785f21d3a752da`.
