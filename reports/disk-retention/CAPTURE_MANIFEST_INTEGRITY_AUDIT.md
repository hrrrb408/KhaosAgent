# M-Disk.1.4 — Capture Manifest Integrity Audit

## Independent byte comparison

The archived JSON is valid canonical JSON. In all three cases, hashing its actual saved bytes disagrees with the `diagnostic_capture.capture_manifest_sha256` value in the corresponding `evidence-index.json`:

| Trial | SHA-256 of saved manifest bytes | Index-declared SHA-256 | Match |
|---|---|---|---|
| `phase32-stage-b-a-1` | `90bbdc0e840b300a217cff6e0e962e7171e86aaac7a30c3148b34a61d1c3cbc1` | `3a9e8999fdebedfd74484bad66c9aea9b3a2b2e60ac0af4848301e2cf7e51966` | No |
| `phase32-stage-b-a-2` | `0822d87f36a222850d9d43686326e29e4cd053033f02f71903e5884e875ba46b` | `0b5f5a72cb5ef5601c72397418213040cd34df991a779781c7afc50d3c5ef86d` | No |
| `phase321-focused-task-a-01` | `bb96354756e8778cd5ad8781b659444107990803a44b7c46b72f67dbf110199d` | `5497f413e0804f2e3fff51e76243e2945f8402715ea7d5b78be785bed8e62d61` | No |

## Defect mechanism and bounded repair

The checked implementation wrote `canonical_json(metadata)` as `capture-manifest.json` through `save_bytes()`. That helper then appended the new file's own `{path, bytes, sha256}` record to the same mutable `copied` list referenced by `metadata`. The return expression subsequently hashed `canonical_json(metadata)` again. It therefore hashed post-write metadata containing a self-entry, while the file on disk contained the pre-self-entry form. Reconstructing that post-write value from each stored manifest reproduces all three declared hashes exactly.

The exact source revision of the retention helper that generated the three historical indexes is not independently recorded. The mismatch mechanism is exactly reproducible from the checked code and stored bytes, but the executed helper revision is not proven. No historical file was edited or rehashed in place.

The future-capture fix takes the digest from the `save_bytes()` record for the final manifest file, reopens the bounded saved file, and verifies its bytes against that digest before returning it. The manifest stays schema `1`, canonical serialization is unchanged, and the manifest does not list itself. A changed or unreadable post-write file raises an error; it is never silently normalized.

Regression coverage verifies deterministic serialized bytes across two captures, byte-for-byte result-hash identity, size/hash for every copied file, schema compatibility, tampered-after-write rejection, and refusal to overwrite existing evidence. The three original indexes and manifests remain unchanged.

```text
Future Capture Manifest Binding: FIXED AND UNIT-TESTED
Historical Capture Manifest Binding: UNRESOLVED (3/3 mismatches remain immutable)
Historical Helper Revision: NOT_BOUND
```
