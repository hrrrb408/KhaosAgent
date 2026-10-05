from __future__ import annotations

from khaos.kernel.workspace_snapshot import WorkspaceSnapshot, WorkspaceWriteScope


def fixture_workspace_write_scope(
    snapshot: WorkspaceSnapshot,
) -> WorkspaceWriteScope:
    """Scope fixture commits to paths present in the snapshot fixture."""
    paths = set()
    for parts in snapshot.baseline:
        path = "/".join(parts)
        if path:
            try:
                path.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                continue
            paths.add(path)
    for entry in snapshot.path.rglob("*"):
        path = entry.relative_to(snapshot.path).as_posix()
        try:
            path.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            continue
        paths.add(path)
    return WorkspaceWriteScope.from_paths(
        tuple(sorted(paths)),
        max_depth=snapshot.max_depth,
    )
