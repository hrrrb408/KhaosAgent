# APFS Reclaim Measurement Plan

This is a future measurement procedure only. It does not authorize deletion. The current three historical Scratch roots are missing, and APFS-exclusive reclaim for them is `UNKNOWN`.

## Before any future authorized cleanup

1. Require explicit owner approval for the exact current manifest SHA and exact candidate IDs.
2. Confirm the candidate is present and the read-only audit reports `READY_PENDING_OWNER_APPROVAL`.
3. Recompute the path's canonical location, device, inode, complete metadata-tree fingerprint, logical bytes and `st_blocks`; require exact equality with the approved manifest.
4. Require current `lsof` reference state `CLEAR`; `UNKNOWN`, timeout, tool error or any PID refuses the operation.
5. Reverify the independent evidence archive hashes and required source model presence. Never hash or copy the model merely to perform cleanup.
6. Capture `df -k /System/Volumes/Data` and `diskutil apfs list` immediately before the one candidate. Record both raw outputs with a timestamp and do not add their overlapping capacity values.

## One candidate at a time

The current audit utility is read-only and has no historical delete operation. If exact cleanup is later authorized, implementation and review of a narrowly scoped executor must be a separate step. It must accept only the manifest path and candidate ID, re-run every precondition immediately before mutation, refuse path substitution, and remove only the single exact directory. No wildcard, broad temporary-root cleanup, permission change, forced process termination, model access or fallback path is allowed.

After each authorized operation, record whether the exact root disappeared, list any remaining entries without following links, check for unexpected effects, and take new `df -k` and `diskutil apfs list` samples. Report observed free-space growth as the measured result; do not equate it to logical size or `st_blocks`. APFS clone/shared extents, snapshots and concurrent activity can make the delta smaller or otherwise different. If the target changes or any check fails, stop before the next candidate.

## Current baseline

At the post-regression sample, the Data volume reported 468,112,384 KiB available (479,347,081,216 bytes) and the APFS container reported 479,347,077,120 bytes not allocated. The three historical targets were already absent, so this run performed no historical deletion and cannot measure their reclamation. The ~58 GiB increase from the previous snapshot is not attributable to a specific file or operation.
