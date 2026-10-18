# Candidate B Alias Security Report

## Case and Unicode aliases

The tests ran on the real APFS-backed test fixture. Both alias conditions were constructed on this volume rather than skipped:

- Case alias: `tags.py` and `TAGS.py` satisfied `os.path.samefile`.
- Unicode normalization alias: the test used the source literals `canonical = "tag\u00e9s.py"` and `normalized_alias = "tage\u0301s.py"`; `os.path.samefile` returned true on this volume.

The fixed edit used only the explicitly declared path and scopes for each fixture. The permitted outcomes were a safe one-file replacement, or a fail-closed Kernel/Runner result with original bytes preserved. In either case the synthetic canary stayed unchanged and no extra entry remained. Both tests passed on this volume; neither was skipped for an environment limitation.

## Hardlinks

- An internal `tags.py`/`unscoped-canary.txt` hardlink was proven by equal inode numbers. Snapshot creation rejected it with `workspace_rejected_snapshot`; both names retained the original bytes and inode.
- The external-hardlink fixture used an outside synthetic file linked as `tags.py`. The test accepts only a fail-closed snapshot rejection or a replacement of the scoped workspace name while the outside file retains its original bytes. The full L3 group passed.

## Conclusion

Case, Unicode and hardlink alias attacks have L3 results for the exercised fixture and host volume. The matrix keeps the original signed Gate A rows NOT_PROVEN because the corresponding L4 adversarial operations have not been authorized or run. No conclusion is made about other filesystems or normalization rules.
