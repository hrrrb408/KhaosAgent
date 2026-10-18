# Candidate B Path Security Report

## Fixture and evidence level

All cases use the deterministic fixed Staged Replacement and disposable synthetic files through the real macOS Seatbelt Runner and Kernel snapshot/changeset path (L3). The normal scope is exactly `readScope=["tags.py"]`, `writeScope=["tags.py"]`. The ancestor-symlink and parent-rename cases use their exact `src/tags.py` fixture path and are identified separately below. No scope is widened to make a test pass.

Fixture bytes include:

- Original `tags.py`: SHA-256 `476ac287f5ed529f016a1ba705a336abb57f38156da8a097a2a0ddbed2e5f164`.
- Expected replacement: SHA-256 `8db3b1d5a79058bc0db32f9904c38162c6384ff813d41ab45b9db2348a264a63`.
- `synthetic canary\n`: SHA-256 `0b6ba3c1ade1071adfd0088da2fd0fb0ab3bb522405ddb593d70c192d04836cd`.

## Results

| Attack | Observed result | Final state |
|---|---|---|
| `../outside.py`, `src/../../outside.py` | Nonzero Runner result under exact `tags.py` scope | No changeset; original target and external canary unchanged; no temp. |
| Absolute external target | Rejected under exact `tags.py` scope | No changeset; external target and workspace unchanged. |
| Empty target | Rejected by the fixed script's regular-file check | No target, canary, changeset or temp change. |
| `./tags.py` | Accepted as a spelling of the scoped path | Exactly one modified path; expected bytes; canary unchanged; temp absent. |
| `./target.py`, `src//target.py` | No access to an unscoped file | Either a scoped-read denial or Kernel `commit_rejected`; both target and canary bytes unchanged. |
| Missing target, absent/duplicate old text, no-op replacement | Fixed script returned nonzero | No file creation or mutation; changeset 0/0/0; no temp. |
| Symlink leaf `tags.py` → canary | Runner could not perform the fixed edit through the link | Link target and canary unchanged; no changeset. |
| Symlink ancestor `src` → external directory | Exact `src/tags.py` fixture failed closed | External target and canary unchanged. |
| Target swapped to a canary symlink before read | Scoped read was denied | Original live target restored/unchanged; external canary unchanged. |
| Target swapped to a canary symlink after unique-text read | Atomic replacement replaced the symlink entry itself | Only scoped `tags.py` changed to the expected bytes; canary unchanged; no temp. |
| Parent `src` renamed and replaced with an external symlink after read | Runner/Kernel failed closed | Live `src/tags.py`, workspace canary and external target unchanged. |

The case and Unicode aliases are reported separately in `ALIAS_SECURITY_REPORT.md`. A target that is in scope may be replaced atomically; the evidence shows that the replacement did not follow the raced symlink to the canary.

## Limit

These are L3 test-fixture results. Rows whose original Gate A criterion requires signed-product evidence remain NOT_PROVEN until a separately approved L4 action exists. The tests do not establish arbitrary same-UID host tampering resistance.
