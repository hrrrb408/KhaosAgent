# Experimental Artifact Retention Policy

This policy applies only to the experimental DSH acceptance runner and builder. It introduces no Kernel task state, trusted process, IPC operation, or production permission.

## Artifact classes

| Class | Examples | Policy |
|---|---|---|
| Evidence | trial JSON, request/result correlations, bounded logs, build inputs, fixture state | Preserve in a restricted evidence directory before considering scratch cleanup. Never rewrite an existing evidence file. |
| Build artifact | signed experimental App, Node/DSH bundle, Swift intermediates | Record exact source and dependency digests. Rebuildability must be established before an old App can become a cleanup candidate. |
| Model source | unique or designated GGUF source | Retain. Do not move into a global path or grant AgentHost additional filesystem access. |
| Invocation scratch | directory created by the current runner invocation | Clean only after evidence writes complete, the original directory identity and metadata tree still match, and `lsof` reports no open reference. Otherwise retain. |

## Runner lifecycle

Successful runs continue to write the result report and bounded compressed raw logs before cleaning the runner-owned temporary directory. `--preserve-scratch` is an explicit keep request.

On failure, the runner now:

1. Detaches the Python temporary-directory finalizer first, so an exception during evidence handling cannot silently erase the scratch.
2. Stops only the Node processes already associated with this exact App, recording a cleanup error and retaining scratch if that step fails.
3. Writes an owner-only `.failed-artifacts` directory beside the requested evidence. It contains compressed stdout/stderr capped at 2 MiB each, the task text, a build-input record, and bounded non-canary synthetic workspace files (at most 32 MiB and 1,000 files). Exact API-key bytes are redacted from every copied payload.
4. Excludes the signed App and model. It records the scratch tree fingerprint and copied-file digests; no model bytes are rehashed.
5. Writes the `.failed.json` and retention status as new owner-only files. It does not overwrite an existing result.
6. Records the exact scratch path, Device/Inode, logical and allocated size, and metadata-tree fingerprint in the owner-only retention record so any retained scratch can be reviewed and added to a later exact manifest.
7. Calls `TemporaryDirectory.cleanup()` only when required evidence is complete, the original scratch Device/Inode and tree fingerprint still match, and an `lsof` check reports no references. Missing evidence, an identity change, a hard link, an external symlink, an open file, unavailable `lsof`, or process-cleanup failure retains scratch.

The evidence directory is mode `0700`; files are mode `0600`. Failure bundles are deliberately bounded. If a build record or required logs are absent, the capture is marked incomplete and scratch is retained for review.

## Exact cleanup manifest

`tools/audit_experimental_artifacts.py` accepts only an exact owner-only manifest with a matching SHA-256 sidecar. It verifies canonical absolute paths, direct-child membership under enumerated roots, Device/Inode, file type, logical and allocated bytes, per-entry metadata fingerprint, Git-root exclusion, protected model/evidence paths, duplicate/nested candidates, and live references. It reports `REFUSE` on an unknown process state or unresolved dependency. It has no delete, move, truncate, or overwrite operation.

The manifest fingerprint covers path names and filesystem metadata, not file contents. It detects replacement and ordinary modifications but is not a cryptographic content archive. Model SHA values are sourced from prior signed build records; large GGUFs are not reread. APFS exclusive extents remain unmeasured.

`SAFE_CANDIDATE` and `PENDING_OWNER_APPROVAL` are distinct gates. This PR provides no execution path for deleting historical candidates. Any future cleanup needs a fresh manifest and exact owner authorization, then a separate implementation/review.

## Retention windows and disk preflight

This phase does not introduce automatic age-based deletion. Evidence retention must remain reviewable until the owning experiment and any open defect investigation are closed. Unknown provenance remains retained.

Before hashing a local model App or copying its GGUF, the experimental builder stats the model and checks free bytes on the output volume. Required free space is:

```text
model bytes + 2 GiB staging allowance + 10% model-size safety margin
```

For the audited 18,556,689,568-byte model this is 22,559,842,173 bytes. The output volume's current free-space measure already reflects all existing scratch and App occupancy. The check is a preflight, not a quota and not a guarantee against later concurrent use. Insufficient space exits with `INSUFFICIENT_DISK_SPACE` before code-signature verification or model hashing.

The existing explicit prebuilt-App route remains available, but it is not a complete build-cache key: the runner currently verifies the deep App signature, Khaos source SHA, provider, workspace identity when applicable, and local-model ID. It does not compare every DSH, Node, model, signing-identity, and entitlement input against a requested build as one exact reuse decision. This change adds no cache and does not recommend blind App reuse. Future reuse should require an explicit full-field comparison of the signed build-input record; a similar filename is never sufficient.
