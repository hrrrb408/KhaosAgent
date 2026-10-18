# B14 — Read-Allowed, Write-Denied Isolation

## Fixture and authorization

The real macOS Seatbelt Runner test uses the fixed Candidate B Staged Replacement script in an isolated workspace containing synthetic other.py, tags.py, and unscoped-canary.txt. The proposal is scoped to readScope=[other.py] and writeScope=[tags.py], while the fixed script targets other.py. The test does not widen either scope or change production code.

## Observed result

The test observed all of these Runner stages: other.py was read, oldText matched uniquely, a same-directory temporary file was created in the private snapshot, and os.replace completed there. The snapshot observer then saw other.py contain the replacement. The actual Kernel result was commit_rejected because the complete changeset contained a modified path outside writeScope. The API did not surface a WorkspaceCommandResult or process return code for this rejection; the report therefore does not infer one.

| File | Initial SHA-256 | Final live SHA-256 | Result |
|---|---|---|---|
| other.py | 21ac4b67b5cd63e3cdd0f774e4778d63945a75d6f3a1a1993d656e80bf581dad | 21ac4b67b5cd63e3cdd0f774e4778d63945a75d6f3a1a1993d656e80bf581dad | unchanged |
| tags.py | 07db47957ef8d4c58b0be6aae3947101275a3cd43749736fe61a9471fe56b1e3 | 07db47957ef8d4c58b0be6aae3947101275a3cd43749736fe61a9471fe56b1e3 | unchanged |
| unscoped-canary.txt | 0b6ba3c1ade1071adfd0088da2fd0fb0ab3bb522405ddb593d70c192d04836cd | 0b6ba3c1ade1071adfd0088da2fd0fb0ab3bb522405ddb593d70c192d04836cd | unchanged |

The final live directory contains only those three fixture files. No .khaos-edit-* temporary entry was committed. The result is Result B: the private Snapshot changed and the Kernel rejected the complete changeset before live writeback. This is stronger and more specific than an OS denial during file access.

## Gate status

B14 L3: PASS. This proves that read permission does not imply commit permission for this fixed script and exact scope pair. The inherited matrix separately retains its L4 end-to-end requirement. No signed adversarial B14 operation was included in the one authorized positive replay, so B14 L4 remains NOT_PROVEN and is not promoted by this L3 result.
