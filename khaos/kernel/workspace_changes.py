"""Validate Runner output and commit a bounded workspace changeset."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from hashlib import sha256
import ctypes
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile

from .workspace_snapshot import (
    SnapshotEntry,
    WorkspaceSnapshot,
    WorkspaceSnapshotError,
    WorkspaceWriteScope,
    _COPY_CHUNK_BYTES,
    _DIRECTORY_FLAGS,
    _FILE_READ_FLAGS,
    _FILE_READ_WRITE_FLAGS,
    _FILE_WRITE_FLAGS,
    _MAX_SYMLINK_BYTES,
    _CopyBudget,
    _entry_signature,
    _open_absolute_directory,
    _path_for_directory_descriptor,
    _require_descriptor_relative_filesystem,
    _same_entry,
    _same_directory_identity,
    _validate_component,
    _verify_directory,
    _verify_mountpoint,
    _verify_named_entry,
    _volume_mountpoint,
)


_COPYFILE_ACL_XATTR = (1 << 0) | (1 << 2)
_XATTR_SHOWCOMPRESSION = 0x0020
_MAX_COMMIT_XATTR_BYTES = 64 * 1024 * 1024
_MAX_XATTR_NAME_LIST_BYTES = 1024 * 1024


class WorkspaceCommitError(WorkspaceSnapshotError):
    """The proposed changeset was unsafe, stale, or could not be applied."""


class WorkspaceCommitOutcomeUncertain(WorkspaceCommitError):
    """Workspace writeback did not finish; live changes may remain."""


@dataclass(frozen=True, slots=True)
class WorkspaceChangeSet:
    """Relative paths changed by one completed commit."""

    added: tuple[tuple[str, ...], ...]
    modified: tuple[tuple[str, ...], ...]
    deleted: tuple[tuple[str, ...], ...]


@dataclass(slots=True)
class _CommitPlan:
    """Validated changes and the exact live paths the committer will write."""

    changes: WorkspaceChangeSet
    changed_files: list[tuple[str, ...]]
    replaced_or_removed: list[tuple[str, ...]]
    new_directories: list[tuple[str, ...]]
    removal_temporary_names: dict[tuple[str, ...], str]
    replacement_temporary_names: dict[tuple[str, ...], str]
    preparation_cleanup_temporary_names: dict[tuple[str, ...], str]
    addition_temporary_names: dict[tuple[str, ...], str]
    addition_cleanup_temporary_names: dict[tuple[str, ...], str]
    file_write_paths: tuple[tuple[str, ...], ...]
    create_unlink_paths: tuple[tuple[str, ...], ...]


@dataclass(slots=True)
class _PreparedFileReplacement:
    """A same-directory replacement prepared before live mutations begin."""

    name: str
    parent_fd: int
    identity: tuple[int, int]
    cleanup_temporary_name: str
    parent_binding_check: Callable[[], bool]
    signature: tuple[int, ...]
    original: SnapshotEntry
    output: SnapshotEntry
    owner: tuple[int, int]
    xattrs: tuple[tuple[bytes, int, bytes], ...]
    preserve_recovery_entry: bool = False


def commit_snapshot(
    snapshot: WorkspaceSnapshot,
    *,
    workspace_write_scope: WorkspaceWriteScope,
    before_live_mutations: Callable[
        [Path, tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]], None
    ]
    | None = None,
) -> WorkspaceChangeSet:
    """Validate and apply Runner output without following its paths.

    Output files are first copied into a private staging directory. Existing
    file replacements are then prepared beside their destinations, including
    trusted baseline metadata, before changeset mutations begin. The source tree
    must still match the exact baseline captured when the snapshot was made.
    Existing files and removed entries are exchanged with same-directory macOS
    atomic swaps; the displaced entry is checked against the baseline, and
    detected entry or parent-binding races are restored where possible before
    the commit is rejected. A non-blocking advisory lock on the source volume's
    mountpoint rejects overlapping Khaos commits, including nested workspace
    scopes that share a mountpoint. Root and parent bindings are re-opened around
    mutations, but arbitrary writers can ignore the advisory lock; this is not
    an exclusive writer authority or a multi-file transaction. Every caller
    must supply the retained exact-path write scope. The broker also supplies a
    callback that applies the live-path OS restriction after validation and
    immediately before mutation.
    """
    if not isinstance(snapshot, WorkspaceSnapshot):
        raise TypeError("commit requires a workspace snapshot value")
    if sys.platform != "darwin":
        raise WorkspaceCommitError("workspace commit is unsupported on this platform")
    import fcntl

    live_mutation_started = False

    def mark_live_mutation() -> None:
        nonlocal live_mutation_started
        live_mutation_started = True

    _require_descriptor_relative_filesystem((os.unlink, os.rmdir))

    source_fd = -1
    source_mount_fd = -1
    snapshot_fd = -1
    try:
        if type(snapshot._source_root_fd) is not int or snapshot._source_root_fd < 0:
            raise WorkspaceCommitError("workspace root descriptor is unavailable")
        source_fd = os.dup(snapshot._source_root_fd)
        if snapshot.source_mount_point is None:
            raise WorkspaceCommitError("workspace filesystem mount changed")
        source_mount_fd = _open_absolute_directory(Path(snapshot.source_mount_point))
        snapshot_fd = _open_absolute_directory(snapshot.path)
        source_root = os.fstat(source_fd)
        source_mount_root = os.fstat(source_mount_fd)
        snapshot_root = os.fstat(snapshot_fd)
        if not stat.S_ISDIR(source_root.st_mode):
            raise WorkspaceCommitError("workspace root is not a directory")
        if not stat.S_ISDIR(source_mount_root.st_mode):
            raise WorkspaceCommitError("workspace mount root is not a directory")
        if not stat.S_ISDIR(snapshot_root.st_mode):
            raise WorkspaceCommitError("snapshot root is not a directory")
        if (
            type(snapshot.storage_limit_bytes) is not int
            or snapshot.storage_limit_bytes < 1
            or snapshot.snapshot_mount_point is None
            or snapshot.source_mount_point == snapshot.snapshot_mount_point
            or source_root.st_dev == snapshot_root.st_dev
            or _volume_mountpoint(source_fd) != snapshot.source_mount_point
            or _volume_mountpoint(source_mount_fd) != snapshot.source_mount_point
            or _volume_mountpoint(snapshot_fd) != snapshot.snapshot_mount_point
        ):
            raise WorkspaceCommitError("workspace filesystem mount changed")
        try:
            fcntl.flock(source_mount_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WorkspaceCommitError(
                "another Khaos workspace commit is active on this mountpoint"
            ) from exc
        except OSError as exc:
            raise WorkspaceCommitError(
                "workspace commit lock is unavailable"
            ) from exc

        staging_parent = Path(tempfile.gettempdir()).resolve(strict=True)
        with tempfile.TemporaryDirectory(
            prefix="khaos-changes-", dir=staging_parent
        ) as value:
            staging_path = Path(value).resolve(strict=True)
            staging_fd = _open_absolute_directory(staging_path)
            try:
                output, staged_files = _scan_tree(
                    snapshot_fd,
                    device=snapshot_root.st_dev,
                    max_entries=snapshot.max_entries,
                    max_bytes=snapshot.max_bytes,
                    max_depth=snapshot.max_depth,
                    mount_point=snapshot.snapshot_mount_point,
                    staging_fd=staging_fd,
                )
                _validate_output(snapshot.baseline, output)

                current_source, _ = _scan_tree(
                    source_fd,
                    device=os.fstat(source_fd).st_dev,
                    max_entries=snapshot.max_entries,
                    max_bytes=snapshot.max_bytes,
                    max_depth=snapshot.max_depth,
                    mount_point=snapshot.source_mount_point,
                )
                if current_source != snapshot.baseline:
                    raise WorkspaceCommitError(
                        "workspace changed since the snapshot was created"
                    )
                _verify_source_root_path(snapshot, source_fd)

                plan = _plan_commit(snapshot.baseline, output)
                scope = WorkspaceWriteScope.from_paths(
                    workspace_write_scope,
                    max_depth=snapshot.max_depth,
                )
                if any(
                    not scope.permits_write(
                        "/".join(path), max_depth=snapshot.max_depth
                    )
                    for path in (
                        *plan.changes.added,
                        *plan.changes.modified,
                        *plan.changes.deleted,
                    )
                ):
                    raise WorkspaceCommitError(
                        "changeset exceeds workspace write scope"
                    )
                if before_live_mutations is not None:
                    before_live_mutations(
                        staging_path,
                        plan.file_write_paths,
                        plan.create_unlink_paths,
                    )
                _apply_changes(
                    source_fd,
                    snapshot.source_root,
                    snapshot.baseline,
                    output,
                    staged_files,
                    staging_fd,
                    snapshot.source_mount_point,
                    plan,
                    on_live_mutation=mark_live_mutation,
                )
                return plan.changes
            finally:
                os.close(staging_fd)
    except WorkspaceCommitOutcomeUncertain:
        raise
    except WorkspaceCommitError as exc:
        if live_mutation_started:
            raise WorkspaceCommitOutcomeUncertain(str(exc)) from exc
        raise
    except WorkspaceSnapshotError as exc:
        if live_mutation_started:
            raise WorkspaceCommitOutcomeUncertain(str(exc)) from exc
        raise WorkspaceCommitError(str(exc)) from exc
    except OSError as exc:
        if live_mutation_started:
            raise WorkspaceCommitOutcomeUncertain(str(exc)) from exc
        raise WorkspaceCommitError(
            "workspace changed or the changeset could not be applied"
        ) from exc
    except Exception as exc:
        if live_mutation_started:
            raise WorkspaceCommitOutcomeUncertain(str(exc)) from exc
        raise
    finally:
        if snapshot_fd >= 0:
            os.close(snapshot_fd)
        if source_mount_fd >= 0:
            os.close(source_mount_fd)
        if source_fd >= 0:
            os.close(source_fd)


def _scan_tree(
    root_fd: int,
    *,
    device: int,
    max_entries: int,
    max_bytes: int,
    max_depth: int,
    mount_point: str,
    staging_fd: int | None = None,
) -> tuple[dict[tuple[str, ...], SnapshotEntry], dict[tuple[str, ...], str]]:
    root_stat = os.fstat(root_fd)
    if not stat.S_ISDIR(root_stat.st_mode):
        raise WorkspaceCommitError("workspace root is not a directory")
    if root_stat.st_dev != device:
        raise WorkspaceCommitError("workspace root changed filesystems")
    _verify_mountpoint(mount_point, root_fd)

    budget = _CopyBudget(
        max_entries=max_entries,
        max_bytes=max_bytes,
        max_depth=max_depth,
        device=device,
        mount_point=mount_point,
    )
    entries = {
        (): SnapshotEntry(
            "directory",
            stat.S_IMODE(root_stat.st_mode) & 0o777,
            _entry_signature(root_stat),
        )
    }
    staged_files: dict[tuple[str, ...], str] = {}
    _scan_directory(
        root_fd,
        relative=(),
        depth=0,
        budget=budget,
        entries=entries,
        staged_files=staged_files,
        staging_fd=staging_fd,
    )
    return entries, staged_files


def _scan_directory(
    directory_fd: int,
    *,
    relative: tuple[str, ...],
    depth: int,
    budget: _CopyBudget,
    entries: dict[tuple[str, ...], SnapshotEntry],
    staged_files: dict[tuple[str, ...], str],
    staging_fd: int | None,
) -> None:
    before_directory = os.fstat(directory_fd)
    with os.scandir(directory_fd) as children:
        for child in children:
            name = child.name
            _validate_component(name)
            path = (*relative, name)
            entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if entry.st_dev != budget.device:
                raise WorkspaceCommitError(
                    "workspace contains an entry on another filesystem"
                )

            if stat.S_ISDIR(entry.st_mode):
                budget.add_entry()
                if depth >= budget.max_depth:
                    raise WorkspaceCommitError("workspace nesting limit exceeded")
                child_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=directory_fd)
                try:
                    if not _same_entry(entry, os.fstat(child_fd)):
                        raise WorkspaceCommitError(
                            "workspace changed while the changeset was scanned"
                        )
                    _verify_mountpoint(budget.mount_point, child_fd)
                    entries[path] = SnapshotEntry(
                        "directory",
                        stat.S_IMODE(entry.st_mode) & 0o777,
                        _entry_signature(entry),
                    )
                    _scan_directory(
                        child_fd,
                        relative=path,
                        depth=depth + 1,
                        budget=budget,
                        entries=entries,
                        staged_files=staged_files,
                        staging_fd=staging_fd,
                    )
                    _verify_named_entry(directory_fd, name, entry)
                    if not _same_entry(entry, os.fstat(child_fd)):
                        raise WorkspaceCommitError(
                            "workspace changed while the changeset was scanned"
                        )
                finally:
                    os.close(child_fd)
            elif stat.S_ISREG(entry.st_mode):
                _scan_regular_file(
                    directory_fd,
                    name,
                    path,
                    entry,
                    budget,
                    entries,
                    staged_files,
                    staging_fd,
                )
            elif stat.S_ISLNK(entry.st_mode):
                target = os.readlink(name, dir_fd=directory_fd)
                target_bytes = os.fsencode(target)
                if len(target_bytes) > _MAX_SYMLINK_BYTES:
                    raise WorkspaceCommitError("workspace symlink target is too long")
                budget.add_entry(len(target_bytes))
                _verify_named_entry(directory_fd, name, entry)
                entries[path] = SnapshotEntry(
                    "symlink",
                    stat.S_IMODE(entry.st_mode) & 0o777,
                    _entry_signature(entry),
                    target=target,
                )
            else:
                raise WorkspaceCommitError(
                    "workspace contains an unsupported filesystem entry"
                )
    _verify_directory(directory_fd, before_directory)


def _scan_regular_file(
    directory_fd: int,
    name: str,
    path: tuple[str, ...],
    entry: os.stat_result,
    budget: _CopyBudget,
    entries: dict[tuple[str, ...], SnapshotEntry],
    staged_files: dict[tuple[str, ...], str],
    staging_fd: int | None,
) -> None:
    if entry.st_nlink != 1:
        raise WorkspaceCommitError("workspace contains a file with multiple hard links")
    budget.add_entry(entry.st_size)
    source_fd = os.open(name, _FILE_READ_FLAGS, dir_fd=directory_fd)
    output_fd = -1
    staged_name: str | None = None
    try:
        if not _same_entry(entry, os.fstat(source_fd)):
            raise WorkspaceCommitError("workspace changed while the changeset was scanned")
        _verify_mountpoint(budget.mount_point, source_fd)
        if staging_fd is not None:
            staged_name = f"{len(staged_files):08x}"
            output_fd = os.open(
                staged_name,
                _FILE_WRITE_FLAGS,
                0o600,
                dir_fd=staging_fd,
            )

        digest = sha256()
        copied = 0
        while True:
            chunk = os.read(source_fd, _COPY_CHUNK_BYTES)
            if not chunk:
                break
            copied += len(chunk)
            if copied > entry.st_size or budget.bytes - entry.st_size + copied > budget.max_bytes:
                raise WorkspaceCommitError("workspace snapshot limit exceeded")
            digest.update(chunk)
            if output_fd >= 0:
                _write_all(output_fd, chunk)
        if copied != entry.st_size or not _same_entry(entry, os.fstat(source_fd)):
            raise WorkspaceCommitError("workspace changed while the changeset was scanned")
        _verify_named_entry(directory_fd, name, entry)
        if output_fd >= 0:
            os.fchmod(output_fd, 0o400)
            os.fsync(output_fd)
        entries[path] = SnapshotEntry(
            "file",
            stat.S_IMODE(entry.st_mode) & 0o777,
            _entry_signature(entry),
            size=copied,
            digest=digest.hexdigest(),
        )
        if staged_name is not None:
            staged_files[path] = staged_name
    finally:
        os.close(source_fd)
        if output_fd >= 0:
            os.close(output_fd)
        if staged_name is not None and path not in staged_files:
            try:
                os.unlink(staged_name, dir_fd=staging_fd)
            except FileNotFoundError:
                pass


def _write_all(descriptor: int, value: bytes) -> None:
    view = memoryview(value)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise WorkspaceCommitError("changeset staging write failed")
        view = view[written:]


def _validate_output(
    baseline: Mapping[tuple[str, ...], SnapshotEntry],
    output: dict[tuple[str, ...], SnapshotEntry],
) -> None:
    for path, entry in output.items():
        original = baseline.get(path)
        if entry.kind == "symlink" and (
            original is None
            or original.kind != "symlink"
            or original.target != entry.target
        ):
            raise WorkspaceCommitError("new or changed symbolic links are not accepted")
        if (
            entry.kind == "file"
            and original is not None
            and original.kind == "file"
            and entry.mode != original.mode
        ):
            raise WorkspaceCommitError("Runner cannot change file permissions")


def _same_value(left: SnapshotEntry, right: SnapshotEntry) -> bool:
    if left.kind != right.kind:
        return False
    if left.kind == "file":
        return (
            left.mode == right.mode
            and left.size == right.size
            and left.digest == right.digest
        )
    if left.kind == "symlink":
        return left.target == right.target
    return True


def _describe_changes(
    baseline: Mapping[tuple[str, ...], SnapshotEntry],
    output: dict[tuple[str, ...], SnapshotEntry],
) -> WorkspaceChangeSet:
    added: list[tuple[str, ...]] = []
    modified: list[tuple[str, ...]] = []
    deleted: list[tuple[str, ...]] = []
    for path, entry in output.items():
        original = baseline.get(path)
        if original is None:
            added.append(path)
        elif not _same_value(original, entry):
            modified.append(path)
    for path in baseline:
        if path not in output:
            deleted.append(path)
    return WorkspaceChangeSet(
        tuple(sorted(added)),
        tuple(sorted(modified)),
        tuple(sorted(deleted)),
    )


def _plan_commit(
    baseline: Mapping[tuple[str, ...], SnapshotEntry],
    output: dict[tuple[str, ...], SnapshotEntry],
) -> _CommitPlan:
    changes = _describe_changes(baseline, output)
    changed_paths = set(changes.added) | set(changes.modified)
    changed_files = sorted(
        path for path in changed_paths if output[path].kind == "file"
    )
    replaced_or_removed = sorted(
        (
            path
            for path, original in baseline.items()
            if path not in output or output[path].kind != original.kind
        ),
        key=lambda value: (-len(value), value),
    )
    new_directories = sorted(
        path
        for path, entry in output.items()
        if entry.kind == "directory"
        and (path not in baseline or baseline[path].kind != "directory")
    )
    removal_temporary_names = {
        path: _new_temporary_name() for path in replaced_or_removed
    }
    preparation_cleanup_temporary_names = {
        path: _new_temporary_name()
        for path in changed_files
        if path in baseline and baseline[path].kind == "file"
    }
    replacement_temporary_names = {
        path: _new_temporary_name()
        for path in changed_files
        if path in baseline and baseline[path].kind == "file"
    }
    addition_temporary_names = {
        path: _new_temporary_name()
        for path in changed_files
        if path not in replacement_temporary_names
    }
    addition_cleanup_temporary_names = {
        path: _new_temporary_name()
        for path in addition_temporary_names
    }

    file_write_paths: set[tuple[str, ...]] = set()
    create_unlink_paths: set[tuple[str, ...]] = set()
    for path in replaced_or_removed:
        create_unlink_paths.update((path, path[:-1]))
    for path in new_directories:
        create_unlink_paths.update((path, path[:-1]))
    create_unlink_paths.update(path[:-1] for path in changed_files)
    file_write_paths.update(
        path
        for path in changed_files
        if path not in baseline or baseline[path].kind != "file"
    )
    create_unlink_paths.update(
        path
        for path in changed_files
        if path in baseline and baseline[path].kind == "file"
    )
    file_write_paths.update(
        (*path[:-1], name)
        for path, name in removal_temporary_names.items()
        if baseline[path].kind != "directory"
    )
    create_unlink_paths.update(
        (*path[:-1], name)
        for path, name in removal_temporary_names.items()
        if baseline[path].kind == "directory"
    )
    for path, name in (
        *replacement_temporary_names.items(),
        *preparation_cleanup_temporary_names.items(),
        *addition_temporary_names.items(),
    ):
        file_write_paths.add((*path[:-1], name))
    create_unlink_paths.update(
        (*path[:-1], name)
        for path, name in addition_cleanup_temporary_names.items()
    )
    return _CommitPlan(
        changes=changes,
        changed_files=changed_files,
        replaced_or_removed=replaced_or_removed,
        new_directories=new_directories,
        removal_temporary_names=removal_temporary_names,
        replacement_temporary_names=replacement_temporary_names,
        preparation_cleanup_temporary_names=preparation_cleanup_temporary_names,
        addition_temporary_names=addition_temporary_names,
        addition_cleanup_temporary_names=addition_cleanup_temporary_names,
        file_write_paths=tuple(
            sorted(file_write_paths, key=lambda value: (len(value), value))
        ),
        create_unlink_paths=tuple(
            sorted(create_unlink_paths, key=lambda value: (len(value), value))
        ),
    )


def _new_temporary_name() -> str:
    return f".khaos-{secrets.token_hex(12)}.tmp"


def _apply_changes(
    root_fd: int,
    source_root: Path,
    baseline: Mapping[tuple[str, ...], SnapshotEntry],
    output: dict[tuple[str, ...], SnapshotEntry],
    staged_files: dict[tuple[str, ...], str],
    staging_fd: int,
    mount_point: str,
    plan: _CommitPlan,
    *,
    on_live_mutation: Callable[[], None],
) -> None:
    active_directories = {
        path: entry.signature
        for path, entry in baseline.items()
        if entry.kind == "directory"
    }
    prepared: dict[tuple[str, ...], _PreparedFileReplacement] = {}
    try:
        _prepare_file_replacements(
            root_fd,
            source_root,
            baseline,
            output,
            plan.changed_files,
            staged_files,
            staging_fd,
            active_directories,
            mount_point,
            plan.replacement_temporary_names,
            plan.preparation_cleanup_temporary_names,
            prepared,
            on_live_mutation,
        )
        _apply_prepared_changes(
            root_fd,
            source_root,
            baseline,
            output,
            plan,
            staged_files,
            staging_fd,
            active_directories,
            mount_point,
            prepared,
            on_live_mutation,
        )
    finally:
        _cleanup_prepared_file_replacements(
            prepared, on_live_mutation=on_live_mutation
        )


def _prepare_file_replacements(
    root_fd: int,
    source_root: Path,
    baseline: Mapping[tuple[str, ...], SnapshotEntry],
    output: Mapping[tuple[str, ...], SnapshotEntry],
    changed_files: list[tuple[str, ...]],
    staged_files: Mapping[tuple[str, ...], str],
    staging_fd: int,
    active_directories: dict[tuple[str, ...], tuple[int, ...]],
    mount_point: str,
    temporary_names: Mapping[tuple[str, ...], str],
    cleanup_temporary_names: Mapping[tuple[str, ...], str],
    prepared: dict[tuple[str, ...], _PreparedFileReplacement],
    on_live_mutation: Callable[[], None],
) -> None:
    remaining_bytes = _MAX_COMMIT_XATTR_BYTES
    for path in changed_files:
        original = baseline.get(path)
        if original is None or original.kind != "file":
            continue

        parent_fd = _open_parent(
            root_fd, path[:-1], active_directories, mount_point
        )
        source_fd = -1
        staged_fd = -1
        destination_fd = -1
        metadata_verify_fd = -1
        retained_parent_fd = -1
        temporary_name = temporary_names[path]
        cleanup_temporary_name = cleanup_temporary_names[path]
        temporary_created = False
        temporary_identity: tuple[int, int] | None = None
        transferred = False

        def parent_binding_is_current() -> bool:
            return _parent_binding_is_current(
                root_fd,
                source_root,
                path[:-1],
                parent_fd,
                active_directories,
                mount_point,
            )

        try:
            if not parent_binding_is_current():
                raise WorkspaceCommitError("workspace directory changed during commit")

            source_fd = os.open(path[-1], _FILE_READ_FLAGS, dir_fd=parent_fd)
            _verify_existing_file(parent_fd, path[-1], source_fd, original)
            source_stat = os.fstat(source_fd)
            if getattr(source_stat, "st_flags", 0):
                raise WorkspaceCommitError(
                    "workspace file flags cannot be preserved during replacement"
                )
            owner = (source_stat.st_uid, source_stat.st_gid)
            xattrs, size = _extended_attribute_fingerprint(
                source_fd, max_bytes=remaining_bytes
            )
            _verify_existing_file(
                parent_fd, path[-1], source_fd, original, owner, xattrs
            )

            staged_fd = os.open(staged_files[path], _FILE_READ_FLAGS, dir_fd=staging_fd)
            staged_stat = os.fstat(staged_fd)
            if not stat.S_ISREG(staged_stat.st_mode) or staged_stat.st_nlink != 1:
                raise WorkspaceCommitError("staged changeset file is invalid")
            expected_output = output[path]
            if expected_output.size is None or expected_output.digest is None:
                raise WorkspaceCommitError("staged changeset file is invalid")

            destination_fd = os.open(
                temporary_name,
                _FILE_WRITE_FLAGS,
                0o600,
                dir_fd=parent_fd,
            )
            temporary_created = True
            created = os.fstat(destination_fd)
            temporary_identity = (created.st_dev, created.st_ino)
            _copy_verified_file(staged_fd, destination_fd, expected_output)

            destination_stat = os.fstat(destination_fd)
            if (destination_stat.st_uid, destination_stat.st_gid) != owner:
                os.fchown(destination_fd, *owner)
            os.fchmod(destination_fd, original.mode)
            _copy_file_acl_and_xattrs(source_fd, destination_fd)
            _verify_existing_file(
                parent_fd, path[-1], source_fd, original, owner, xattrs
            )
            destination_stat = os.fstat(destination_fd)
            if (
                (destination_stat.st_uid, destination_stat.st_gid) != owner
                or stat.S_IMODE(destination_stat.st_mode) & 0o777 != original.mode
            ):
                raise WorkspaceCommitError("workspace metadata could not be preserved")
            os.fsync(destination_fd)
            prepared_stat = os.fstat(destination_fd)
            if not stat.S_ISREG(prepared_stat.st_mode) or prepared_stat.st_nlink != 1:
                raise WorkspaceCommitError("prepared workspace file is invalid")
            os.close(destination_fd)
            destination_fd = -1
            metadata_verify_fd = os.open(
                temporary_name, _FILE_READ_FLAGS, dir_fd=parent_fd
            )
            metadata_stat = os.fstat(metadata_verify_fd)
            prepared_xattrs, _ = _extended_attribute_fingerprint(
                metadata_verify_fd, max_bytes=_MAX_COMMIT_XATTR_BYTES
            )
            if (
                _entry_signature(metadata_stat) != _entry_signature(prepared_stat)
                or prepared_xattrs != xattrs
                or (metadata_stat.st_uid, metadata_stat.st_gid) != owner
                or stat.S_IMODE(metadata_stat.st_mode) & 0o777 != original.mode
            ):
                raise WorkspaceCommitError("workspace metadata could not be preserved")
            os.close(metadata_verify_fd)
            metadata_verify_fd = -1
            os.fsync(parent_fd)

            retained_parent_fd = os.dup(parent_fd)
            replacement = _PreparedFileReplacement(
                name=temporary_name,
                parent_fd=retained_parent_fd,
                identity=(prepared_stat.st_dev, prepared_stat.st_ino),
                cleanup_temporary_name=cleanup_temporary_name,
                parent_binding_check=partial(
                    _parent_binding_is_current,
                    root_fd,
                    source_root,
                    path[:-1],
                    retained_parent_fd,
                    active_directories,
                    mount_point,
                ),
                signature=_entry_signature(prepared_stat),
                original=original,
                output=expected_output,
                owner=owner,
                xattrs=xattrs,
            )
            if not _prepared_file_matches(
                replacement, temporary_name, after_swap=False
            ):
                raise WorkspaceCommitError("prepared workspace file is invalid")
            prepared[path] = replacement
            transferred = True
            retained_parent_fd = -1
            remaining_bytes -= size
        finally:
            if source_fd >= 0:
                os.close(source_fd)
            if staged_fd >= 0:
                os.close(staged_fd)
            if destination_fd >= 0:
                os.close(destination_fd)
            if metadata_verify_fd >= 0:
                os.close(metadata_verify_fd)
            if retained_parent_fd >= 0:
                os.close(retained_parent_fd)
            try:
                if temporary_created and not transferred:
                    try:
                        if temporary_identity is None:
                            raise WorkspaceCommitError(
                                "prepared workspace file identity is unavailable"
                            )
                        _remove_expected_entry(
                            parent_fd,
                            temporary_name,
                            None,
                            expected_identity=temporary_identity,
                            temporary_name=cleanup_temporary_name,
                            parent_binding_check=parent_binding_is_current,
                            on_live_mutation=on_live_mutation,
                            mark_mutation_on_exchange=False,
                        )
                    except (OSError, WorkspaceCommitError):
                        # A failed preflight is not a clean rejection if its
                        # exact inode cannot be safely removed.
                        on_live_mutation()
                        raise
            finally:
                os.close(parent_fd)


def _verify_existing_file(
    parent_fd: int,
    name: str,
    source_fd: int,
    expected: SnapshotEntry,
    owner: tuple[int, int] | None = None,
    xattrs: tuple[tuple[bytes, int, bytes], ...] | None = None,
) -> None:
    source_stat = os.fstat(source_fd)
    if (
        _entry_signature(source_stat) != expected.signature
        or getattr(source_stat, "st_flags", 0)
        or (owner is not None and (source_stat.st_uid, source_stat.st_gid) != owner)
    ):
        raise WorkspaceCommitError("workspace file changed during commit")
    current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if _entry_signature(current) != expected.signature:
        raise WorkspaceCommitError("workspace file changed during commit")
    if xattrs is not None:
        current_xattrs, _ = _extended_attribute_fingerprint(
            source_fd, max_bytes=_MAX_COMMIT_XATTR_BYTES
        )
        if current_xattrs != xattrs:
            raise WorkspaceCommitError("workspace metadata changed during commit")


def _apply_prepared_changes(
    root_fd: int,
    source_root: Path,
    baseline: Mapping[tuple[str, ...], SnapshotEntry],
    output: dict[tuple[str, ...], SnapshotEntry],
    plan: _CommitPlan,
    staged_files: Mapping[tuple[str, ...], str],
    staging_fd: int,
    active_directories: dict[tuple[str, ...], tuple[int, ...]],
    mount_point: str,
    prepared: Mapping[tuple[str, ...], _PreparedFileReplacement],
    on_live_mutation: Callable[[], None],
) -> None:
    for path in plan.replaced_or_removed:
        original = baseline[path]
        parent_fd = _open_parent(
            root_fd, path[:-1], active_directories, mount_point
        )
        try:
            def parent_binding_is_current() -> bool:
                return _parent_binding_is_current(
                    root_fd,
                    source_root,
                    path[:-1],
                    parent_fd,
                    active_directories,
                    mount_point,
                )

            if not parent_binding_is_current():
                raise WorkspaceCommitError("workspace directory changed during commit")
            _remove_expected_entry(
                parent_fd,
                path[-1],
                original,
                temporary_name=plan.removal_temporary_names[path],
                parent_binding_check=parent_binding_is_current,
                on_live_mutation=on_live_mutation,
            )
            if original.kind == "directory":
                active_directories.pop(path, None)
        finally:
            os.close(parent_fd)

    for path in plan.new_directories:
        parent_fd = _open_parent(
            root_fd, path[:-1], active_directories, mount_point
        )
        try:
            if not _parent_binding_is_current(
                root_fd,
                source_root,
                path[:-1],
                parent_fd,
                active_directories,
                mount_point,
            ):
                raise WorkspaceCommitError("workspace directory changed during commit")
            os.mkdir(path[-1], mode=0o700, dir_fd=parent_fd)
            on_live_mutation()
            created = os.stat(path[-1], dir_fd=parent_fd, follow_symlinks=False)
            if not stat.S_ISDIR(created.st_mode):
                raise WorkspaceCommitError("created workspace entry is not a directory")
            if not _parent_binding_is_current(
                root_fd,
                source_root,
                path[:-1],
                parent_fd,
                active_directories,
                mount_point,
            ):
                raise WorkspaceCommitError("workspace directory changed during commit")
            try:
                os.fsync(parent_fd)
            except OSError as exc:
                raise WorkspaceCommitError(
                    "workspace directory could not be synced"
                ) from exc
            active_directories[path] = _entry_signature(created)
        finally:
            os.close(parent_fd)

    for path in plan.changed_files:
        replacement = prepared.get(path)
        if replacement is not None:
            parent_fd = replacement.parent_fd

            def parent_binding_is_current() -> bool:
                return _parent_binding_is_current(
                    root_fd,
                    source_root,
                    path[:-1],
                    parent_fd,
                    active_directories,
                    mount_point,
                )

            if not parent_binding_is_current():
                raise WorkspaceCommitError("workspace directory changed during commit")
            _install_prepared_file_replacement(
                path[-1],
                replacement,
                parent_binding_is_current,
                on_live_mutation,
            )
            continue

        parent_fd = _open_parent(
            root_fd, path[:-1], active_directories, mount_point
        )
        try:
            def parent_binding_is_current() -> bool:
                return _parent_binding_is_current(
                    root_fd,
                    source_root,
                    path[:-1],
                    parent_fd,
                    active_directories,
                    mount_point,
                )

            if not parent_binding_is_current():
                raise WorkspaceCommitError("workspace directory changed during commit")
            _assert_absent(path[-1], parent_fd)
            _install_staged_file(
                path[-1],
                staged_files[path],
                output[path],
                parent_binding_is_current,
                parent_fd,
                staging_fd,
                plan.addition_temporary_names[path],
                plan.addition_cleanup_temporary_names[path],
                on_live_mutation,
            )
        finally:
            os.close(parent_fd)


def _cleanup_prepared_file_replacements(
    prepared: Mapping[tuple[str, ...], _PreparedFileReplacement],
    *,
    on_live_mutation: Callable[[], None],
) -> None:
    cleanup_error: Exception | None = None
    for replacement in prepared.values():
        try:
            if replacement.preserve_recovery_entry:
                continue
            try:
                os.stat(
                    replacement.name,
                    dir_fd=replacement.parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                continue
            try:
                _remove_expected_entry(
                    replacement.parent_fd,
                    replacement.name,
                    None,
                    expected_identity=replacement.identity,
                    temporary_name=replacement.cleanup_temporary_name,
                    parent_binding_check=replacement.parent_binding_check,
                    on_live_mutation=on_live_mutation,
                    mark_mutation_on_exchange=False,
                )
            except FileNotFoundError:
                continue
            except (OSError, WorkspaceCommitError) as exc:
                on_live_mutation()
                cleanup_error = cleanup_error or exc
        except (OSError, WorkspaceCommitError) as exc:
            on_live_mutation()
            cleanup_error = cleanup_error or exc
        finally:
            os.close(replacement.parent_fd)
    if cleanup_error is not None:
        raise WorkspaceCommitError(
            "prepared workspace replacement could not be cleaned up"
        ) from cleanup_error


def _parent_binding_is_current(
    root_fd: int,
    source_root: Path,
    components: tuple[str, ...],
    parent_fd: int,
    active_directories: dict[tuple[str, ...], tuple[int, ...]],
    mount_point: str,
) -> bool:
    """Require an opened parent to remain reachable from the named workspace root."""
    current_fd = -1
    try:
        if _path_for_directory_descriptor(root_fd) != source_root:
            return False
        current_fd = _open_parent(
            root_fd, components, active_directories, mount_point
        )
        return _same_directory_identity(
            _entry_signature(os.fstat(current_fd)),
            _entry_signature(os.fstat(parent_fd)),
        )
    except (OSError, WorkspaceCommitError):
        return False
    finally:
        if current_fd >= 0:
            os.close(current_fd)


def _extended_attribute_fingerprint(
    descriptor: int, *, max_bytes: int
) -> tuple[tuple[tuple[bytes, int, bytes], ...], int]:
    libc = ctypes.CDLL(None, use_errno=True)
    listxattr = libc.flistxattr
    listxattr.argtypes = (ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int)
    listxattr.restype = ctypes.c_ssize_t
    getxattr = libc.fgetxattr
    getxattr.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_int,
    )
    getxattr.restype = ctypes.c_ssize_t

    name_bytes = listxattr(descriptor, None, 0, _XATTR_SHOWCOMPRESSION)
    if name_bytes < 0:
        _raise_metadata_os_error()
    if name_bytes > min(max_bytes, _MAX_XATTR_NAME_LIST_BYTES):
        raise WorkspaceCommitError("workspace extended metadata exceeds commit limit")
    if name_bytes == 0:
        return (), 0

    names_buffer = ctypes.create_string_buffer(name_bytes)
    actual_name_bytes = listxattr(
        descriptor,
        names_buffer,
        name_bytes,
        _XATTR_SHOWCOMPRESSION,
    )
    if actual_name_bytes < 0:
        _raise_metadata_os_error()
    if actual_name_bytes > name_bytes:
        raise WorkspaceCommitError("workspace metadata changed during commit")
    encoded_names = names_buffer.raw[:actual_name_bytes]
    if not encoded_names.endswith(b"\0"):
        raise WorkspaceCommitError("workspace extended metadata is malformed")

    names = encoded_names[:-1].split(b"\0")
    fingerprint: list[tuple[bytes, int, bytes]] = []
    total_bytes = actual_name_bytes
    for name in names:
        if not name or len(name) > 127:
            raise WorkspaceCommitError("workspace extended metadata is malformed")
        value_bytes = getxattr(descriptor, name, None, 0, 0, 0)
        if value_bytes < 0:
            _raise_metadata_os_error()
        total_bytes += value_bytes
        if total_bytes > max_bytes:
            raise WorkspaceCommitError("workspace extended metadata exceeds commit limit")
        value_buffer = ctypes.create_string_buffer(value_bytes) if value_bytes else None
        actual_value_bytes = getxattr(
            descriptor, name, value_buffer, value_bytes, 0, 0
        )
        if actual_value_bytes < 0:
            _raise_metadata_os_error()
        if actual_value_bytes != value_bytes:
            raise WorkspaceCommitError("workspace metadata changed during commit")
        value = value_buffer.raw[:value_bytes] if value_buffer is not None else b""
        fingerprint.append((name, value_bytes, sha256(value).digest()))
    return tuple(fingerprint), total_bytes


def _raise_metadata_os_error() -> None:
    error = ctypes.get_errno()
    raise OSError(error, os.strerror(error))


def _open_parent(
    root_fd: int,
    components: tuple[str, ...],
    active_directories: dict[tuple[str, ...], tuple[int, ...]],
    mount_point: str,
) -> int:
    current_fd = os.dup(root_fd)
    try:
        root_signature = active_directories[()]
        if not _same_directory_identity(
            root_signature, _entry_signature(os.fstat(current_fd))
        ) or _volume_mountpoint(current_fd) != mount_point:
            raise WorkspaceCommitError("workspace root changed during commit")
        path: tuple[str, ...] = ()
        for component in components:
            path = (*path, component)
            expected = active_directories.get(path)
            if expected is None:
                raise WorkspaceCommitError("changeset parent is not a directory")
            next_fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=current_fd)
            if not _same_directory_identity(
                expected, _entry_signature(os.fstat(next_fd))
            ) or _volume_mountpoint(next_fd) != mount_point:
                os.close(next_fd)
                raise WorkspaceCommitError("workspace directory changed during commit")
            os.close(current_fd)
            current_fd = next_fd
        result = current_fd
        current_fd = -1
        return result
    finally:
        if current_fd >= 0:
            os.close(current_fd)


def _verify_source_root_path(snapshot: WorkspaceSnapshot, source_fd: int) -> None:
    expected = snapshot.baseline[()].signature
    if (
        _path_for_directory_descriptor(source_fd) != snapshot.source_root
        or _volume_mountpoint(source_fd) != snapshot.source_mount_point
        or not _same_directory_identity(
            expected, _entry_signature(os.fstat(source_fd))
        )
    ):
        raise WorkspaceCommitError("workspace root changed before commit")


def _assert_absent(name: str, parent_fd: int) -> None:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise WorkspaceCommitError("workspace destination appeared during commit")


def _remove_expected_entry(
    parent_fd: int,
    name: str,
    expected: SnapshotEntry | None,
    *,
    expected_identity: tuple[int, int] | None = None,
    temporary_name: str,
    parent_binding_check: Callable[[], bool],
    on_live_mutation: Callable[[], None],
    mark_mutation_on_exchange: bool = True,
) -> None:
    """Exchange and validate an entry before path-based removal.

    The final unlink or rmdir is not inode-conditional; this does not exclude
    non-cooperating same-UID writers after the identity check.
    """
    if (expected is None) == (expected_identity is None):
        raise WorkspaceCommitError("workspace removal identity is invalid")
    temporary_fd = -1
    sentinel_created = False
    preserve_temporary = False
    sentinel_kind = (
        "directory"
        if expected is not None and expected.kind == "directory"
        else "file"
    )

    try:
        if sentinel_kind == "directory":
            os.mkdir(temporary_name, mode=0o700, dir_fd=parent_fd)
            sentinel_created = True
        else:
            temporary_fd = os.open(
                temporary_name,
                _FILE_WRITE_FLAGS,
                0o600,
                dir_fd=parent_fd,
            )
            sentinel_created = True
            os.fsync(temporary_fd)
            os.close(temporary_fd)
            temporary_fd = -1

        _rename_swap(parent_fd, temporary_name, name)
        if mark_mutation_on_exchange:
            on_live_mutation()
        preserve_temporary = True
        if (
            not (
                _matches_displaced_entry(parent_fd, temporary_name, expected)
                if expected is not None
                else _matches_displaced_file_identity(
                    parent_fd, temporary_name, expected_identity
                )
            )
            or not parent_binding_check()
        ):
            try:
                _rename_swap(parent_fd, temporary_name, name)
            except OSError as exc:
                raise WorkspaceCommitError(
                    "workspace changed during removal; recovery entry retained "
                    f"as {temporary_name}"
                ) from exc
            preserve_temporary = False
            try:
                os.fsync(parent_fd)
            except OSError as exc:
                raise WorkspaceCommitError(
                    "workspace entry was restored but directory sync failed"
                ) from exc
            raise WorkspaceCommitError("workspace entry changed during removal")

        # The identity check above and this pathname removal are not atomic.
        # Runner Seatbelt excludes Plugin writes, but Seed has no global
        # exclusion against other same-UID processes.
        try:
            _remove_entry_at(
                parent_fd,
                temporary_name,
                expected.kind if expected is not None else "file",
            )
        except OSError as exc:
            try:
                _rename_swap(parent_fd, temporary_name, name)
            except OSError as rollback_exc:
                raise WorkspaceCommitError(
                    "workspace removal failed; recovery entry retained "
                    f"as {temporary_name}"
                ) from rollback_exc
            preserve_temporary = False
            try:
                os.fsync(parent_fd)
            except OSError as sync_exc:
                raise WorkspaceCommitError(
                    "workspace entry was restored but directory sync failed"
                ) from sync_exc
            raise WorkspaceCommitError("workspace entry could not be removed") from exc
        preserve_temporary = False
        sentinel_created = False
        try:
            _remove_entry_at(parent_fd, name, sentinel_kind)
            os.fsync(parent_fd)
        except OSError as exc:
            raise WorkspaceCommitError(
                "workspace entry was removed but temporary cleanup failed"
            ) from exc
    finally:
        if temporary_fd >= 0:
            os.close(temporary_fd)
        if sentinel_created and not preserve_temporary:
            try:
                _remove_entry_at(parent_fd, temporary_name, sentinel_kind)
            except FileNotFoundError:
                pass
            except OSError:
                # The sentinel was created in the live workspace; if cleanup
                # fails, the broker cannot report a clean rejection.
                on_live_mutation()
                raise


def _remove_entry_at(directory_fd: int, name: str, kind: str) -> None:
    if kind == "directory":
        os.rmdir(name, dir_fd=directory_fd)
    else:
        os.unlink(name, dir_fd=directory_fd)


def _prepared_file_matches(
    replacement: _PreparedFileReplacement,
    name: str,
    *,
    after_swap: bool,
) -> bool:
    descriptor = -1
    try:
        entry = os.stat(name, dir_fd=replacement.parent_fd, follow_symlinks=False)
        signature = _entry_signature(entry)
        signature_mismatch = (
            signature[:7] != replacement.signature[:7]
            if after_swap
            else signature != replacement.signature
        )
        if (
            not stat.S_ISREG(entry.st_mode)
            or entry.st_nlink != 1
            or (entry.st_dev, entry.st_ino) != replacement.identity
            or signature_mismatch
            or signature[8:] != replacement.signature[8:]
            or (entry.st_uid, entry.st_gid) != replacement.owner
            or stat.S_IMODE(entry.st_mode) & 0o777 != replacement.original.mode
            or entry.st_size != replacement.output.size
        ):
            return False
        descriptor = os.open(name, _FILE_READ_FLAGS, dir_fd=replacement.parent_fd)
        opened = os.fstat(descriptor)
        if _entry_signature(opened) != signature:
            return False
        xattrs, _ = _extended_attribute_fingerprint(
            descriptor, max_bytes=_MAX_COMMIT_XATTR_BYTES
        )
        if xattrs != replacement.xattrs:
            return False
        if (
            not _file_content_matches(
                descriptor,
                replacement.output.size,
                replacement.output.digest,
            )
            or _entry_signature(os.fstat(descriptor)) != signature
        ):
            return False
        _verify_named_entry(replacement.parent_fd, name, entry)
        return True
    except (OSError, WorkspaceSnapshotError):
        return False
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _install_prepared_file_replacement(
    destination_name: str,
    replacement: _PreparedFileReplacement,
    parent_binding_check: Callable[[], bool],
    on_live_mutation: Callable[[], None],
) -> None:
    parent_fd = replacement.parent_fd
    source_fd = -1
    try:
        if not _prepared_file_matches(
            replacement, replacement.name, after_swap=False
        ):
            raise WorkspaceCommitError("prepared workspace file changed during commit")
        source_fd = os.open(destination_name, _FILE_READ_FLAGS, dir_fd=parent_fd)
        _verify_existing_file(
            parent_fd,
            destination_name,
            source_fd,
            replacement.original,
            replacement.owner,
            replacement.xattrs,
        )
        if not parent_binding_check():
            raise WorkspaceCommitError("workspace directory changed during commit")

        _rename_swap(parent_fd, replacement.name, destination_name)
        on_live_mutation()
        valid_output = _prepared_file_matches(
            replacement, destination_name, after_swap=True
        )
        valid_baseline = _matches_displaced_entry(
            parent_fd, replacement.name, replacement.original
        )
        if not valid_output or not valid_baseline or not parent_binding_check():
            try:
                _rename_swap(parent_fd, replacement.name, destination_name)
            except OSError as exc:
                replacement.preserve_recovery_entry = True
                raise WorkspaceCommitError(
                    "workspace changed during commit; recovery entry retained "
                    f"as {replacement.name}"
                ) from exc
            try:
                os.fsync(parent_fd)
            except OSError as exc:
                raise WorkspaceCommitError(
                    "workspace file was restored but directory sync failed"
                ) from exc
            raise WorkspaceCommitError("workspace file changed during commit")

        # The displaced baseline is still a raceable workspace name; remove it
        # with the shared identity-checking exchange before preserving success.
        try:
            _remove_expected_entry(
                parent_fd,
                replacement.name,
                replacement.original,
                temporary_name=replacement.cleanup_temporary_name,
                parent_binding_check=parent_binding_check,
                on_live_mutation=on_live_mutation,
                mark_mutation_on_exchange=False,
            )
        except (OSError, WorkspaceCommitError) as exc:
            replacement.preserve_recovery_entry = True
            raise WorkspaceCommitError(
                "workspace replacement cleanup is uncertain at "
                f"{replacement.name}"
            ) from exc
    finally:
        if source_fd >= 0:
            os.close(source_fd)


def _install_staged_file(
    destination_name: str,
    staged_name: str,
    expected_output: SnapshotEntry,
    parent_binding_check: Callable[[], bool],
    parent_fd: int,
    staging_fd: int,
    temporary_name: str,
    cleanup_temporary_name: str,
    on_live_mutation: Callable[[], None],
) -> None:
    staged_fd = os.open(staged_name, _FILE_READ_FLAGS, dir_fd=staging_fd)
    destination_fd = -1
    installed_fd = -1
    temporary_created = False
    temporary_cleanup_attempted = False
    temporary_identity: tuple[int, int] | None = None

    def remove_temporary_file() -> None:
        nonlocal temporary_cleanup_attempted, temporary_created
        if not temporary_created:
            return
        if temporary_identity is None:
            raise WorkspaceCommitError("temporary workspace file identity is unavailable")
        temporary_cleanup_attempted = True
        try:
            _remove_expected_entry(
                parent_fd,
                temporary_name,
                None,
                expected_identity=temporary_identity,
                temporary_name=cleanup_temporary_name,
                parent_binding_check=parent_binding_check,
                on_live_mutation=on_live_mutation,
                mark_mutation_on_exchange=False,
            )
        except (OSError, WorkspaceCommitError):
            # If cleanup cannot prove the temporary name still identifies our
            # open file, preserve the competing entry and report an uncertain
            # workspace result instead of unlinking by name.
            on_live_mutation()
            raise
        temporary_created = False

    try:
        staged_stat = os.fstat(staged_fd)
        if not stat.S_ISREG(staged_stat.st_mode) or staged_stat.st_nlink != 1:
            raise WorkspaceCommitError("staged changeset file is invalid")
        destination_fd = os.open(
            temporary_name,
            _FILE_READ_WRITE_FLAGS,
            0o600,
            dir_fd=parent_fd,
        )
        temporary_created = True
        temporary_stat = os.fstat(destination_fd)
        if not stat.S_ISREG(temporary_stat.st_mode) or temporary_stat.st_nlink != 1:
            raise WorkspaceCommitError("temporary workspace file is invalid")
        temporary_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
        _copy_verified_file(staged_fd, destination_fd, expected_output)
        os.fchmod(destination_fd, 0o600)
        os.fsync(destination_fd)
        if not parent_binding_check():
            raise WorkspaceCommitError("workspace directory changed during commit")
        source_signature = _entry_signature(os.fstat(destination_fd))
        source_xattrs, _ = _extended_attribute_fingerprint(
            destination_fd, max_bytes=_MAX_COMMIT_XATTR_BYTES
        )

        # Clone from the held descriptor so replacing temporary_name cannot
        # substitute another inode. Compare the source state afterward, while
        # allowing link-count and ctime changes from unlinking its raced name.
        _clone_file_from_descriptor(destination_fd, parent_fd, destination_name)
        on_live_mutation()
        installed_entry = os.stat(
            destination_name, dir_fd=parent_fd, follow_symlinks=False
        )
        current_source_signature = _entry_signature(os.fstat(destination_fd))
        current_source_xattrs, _ = _extended_attribute_fingerprint(
            destination_fd, max_bytes=_MAX_COMMIT_XATTR_BYTES
        )
        if (
            current_source_signature[:4] != source_signature[:4]
            or current_source_signature[5:7] != source_signature[5:7]
            or current_source_signature[8:] != source_signature[8:]
            or current_source_xattrs != source_xattrs
        ):
            raise WorkspaceCommitError("prepared workspace file changed during clone")
        installed_fd = os.open(
            destination_name, _FILE_READ_FLAGS, dir_fd=parent_fd
        )
        installed_stat = os.fstat(installed_fd)
        installed_xattrs, _ = _extended_attribute_fingerprint(
            installed_fd, max_bytes=_MAX_COMMIT_XATTR_BYTES
        )
        if (
            not stat.S_ISREG(installed_stat.st_mode)
            or installed_stat.st_nlink != 1
            or stat.S_IMODE(installed_stat.st_mode) & 0o777 != 0o600
            or installed_stat.st_size != expected_output.size
            or not _same_entry(installed_entry, installed_stat)
            or not _file_content_matches(
                installed_fd,
                expected_output.size,
                expected_output.digest,
            )
            or _entry_signature(os.fstat(installed_fd))
            != _entry_signature(installed_stat)
        ):
            raise WorkspaceCommitError("installed workspace file is invalid")
        _verify_named_entry(parent_fd, destination_name, installed_stat)
        if installed_xattrs != source_xattrs:
            raise WorkspaceCommitError(
                "installed workspace file metadata changed during clone"
            )
        if not parent_binding_check():
            raise WorkspaceCommitError("workspace directory changed during commit")
        remove_temporary_file()
    finally:
        os.close(staged_fd)
        if destination_fd >= 0:
            os.close(destination_fd)
        # The clone is already a live mutation. Never roll it back with a
        # pathname unlink after an inode check: another writer can replace the
        # name between those syscalls, and macOS has no conditional unlink.
        if temporary_created and not temporary_cleanup_attempted:
            remove_temporary_file()
        if installed_fd >= 0:
            os.close(installed_fd)


def _clone_file_from_descriptor(
    source_fd: int,
    destination_directory_fd: int,
    destination_name: str,
) -> None:
    """Atomically create a distinct file from a verified descriptor on APFS."""
    try:
        fclonefileat = ctypes.CDLL(None, use_errno=True).fclonefileat
    except (AttributeError, OSError) as exc:
        raise WorkspaceCommitError(
            "descriptor-based file clone is unavailable"
        ) from exc
    fclonefileat.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint32,
    )
    fclonefileat.restype = ctypes.c_int
    result = fclonefileat(
        source_fd,
        destination_directory_fd,
        os.fsencode(destination_name),
        0,
    )
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _copy_verified_file(
    source_fd: int,
    destination_fd: int,
    expected: SnapshotEntry,
) -> None:
    if expected.kind != "file" or expected.size is None or expected.digest is None:
        raise WorkspaceCommitError("staged changeset file is invalid")

    digest = sha256()
    copied = 0
    while True:
        chunk = os.read(source_fd, _COPY_CHUNK_BYTES)
        if not chunk:
            break
        copied += len(chunk)
        if copied > expected.size:
            raise WorkspaceCommitError("staged changeset file changed")
        digest.update(chunk)
        _write_all(destination_fd, chunk)
    if copied != expected.size or digest.hexdigest() != expected.digest:
        raise WorkspaceCommitError("staged changeset file changed")


def _file_content_matches(
    descriptor: int,
    expected_size: int | None,
    expected_digest: str | None,
) -> bool:
    if expected_size is None or expected_digest is None:
        return False
    digest = sha256()
    size = 0
    while True:
        chunk = os.read(descriptor, _COPY_CHUNK_BYTES)
        if not chunk:
            break
        size += len(chunk)
        if size > expected_size:
            return False
        digest.update(chunk)
    return size == expected_size and digest.hexdigest() == expected_digest


def _copy_file_acl_and_xattrs(source_fd: int, destination_fd: int) -> None:
    fcopyfile = ctypes.CDLL(None, use_errno=True).fcopyfile
    fcopyfile.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    )
    fcopyfile.restype = ctypes.c_int
    if fcopyfile(source_fd, destination_fd, None, _COPYFILE_ACL_XATTR) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _rename_swap(directory_fd: int, source_name: str, destination_name: str) -> None:
    """Atomically exchange two same-directory entries on supported macOS volumes."""
    if sys.platform != "darwin":
        raise WorkspaceCommitError("atomic file replacement is unsupported")
    try:
        renameatx_np = ctypes.CDLL(None, use_errno=True).renameatx_np
    except (AttributeError, OSError) as exc:
        raise WorkspaceCommitError("macOS atomic file replacement is unavailable") from exc
    renameatx_np.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameatx_np.restype = ctypes.c_int
    result = renameatx_np(
        directory_fd,
        os.fsencode(source_name),
        directory_fd,
        os.fsencode(destination_name),
        0x00000002,  # RENAME_SWAP from <sys/stdio.h>.
    )
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _matches_displaced_entry(
    directory_fd: int, name: str, expected: SnapshotEntry
) -> bool:
    """Check an atomically displaced entry against its snapshot baseline."""
    if expected.kind == "file":
        return _matches_displaced_file(directory_fd, name, expected)
    if expected.kind == "symlink":
        try:
            entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if (
                not stat.S_ISLNK(entry.st_mode)
                or _entry_signature(entry)[:7] != expected.signature[:7]
                or _entry_signature(entry)[8:] != expected.signature[8:]
                or os.readlink(name, dir_fd=directory_fd) != expected.target
            ):
                return False
            _verify_named_entry(directory_fd, name, entry)
            return True
        except (OSError, WorkspaceSnapshotError):
            return False
    if expected.kind == "directory":
        descriptor = -1
        try:
            entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if (
                not stat.S_ISDIR(entry.st_mode)
                or not _same_directory_identity(
                    expected.signature, _entry_signature(entry)
                )
            ):
                return False
            descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=directory_fd)
            opened = os.fstat(descriptor)
            if not _same_directory_identity(
                expected.signature, _entry_signature(opened)
            ):
                return False
            with os.scandir(descriptor) as children:
                if next(children, None) is not None:
                    return False
            _verify_named_entry(directory_fd, name, entry)
            return _same_directory_identity(
                expected.signature, _entry_signature(os.fstat(descriptor))
            )
        except (OSError, WorkspaceSnapshotError):
            return False
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    return False


def _matches_displaced_file_identity(
    directory_fd: int, name: str, expected_identity: tuple[int, int] | None
) -> bool:
    if expected_identity is None:
        return False
    try:
        entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(entry.st_mode)
            or entry.st_nlink != 1
            or (entry.st_dev, entry.st_ino) != expected_identity
        ):
            return False
        _verify_named_entry(directory_fd, name, entry)
        return True
    except (OSError, WorkspaceSnapshotError):
        return False


def _matches_displaced_file(
    directory_fd: int, name: str, expected: SnapshotEntry
) -> bool:
    if expected.digest is None:
        return False
    descriptor = -1
    try:
        entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        signature = _entry_signature(entry)
        if (
            not stat.S_ISREG(entry.st_mode)
            or signature[:7] != expected.signature[:7]
            or signature[8:] != expected.signature[8:]
            or entry.st_nlink != 1
            or entry.st_size != expected.size
        ):
            return False
        descriptor = os.open(name, _FILE_READ_FLAGS, dir_fd=directory_fd)
        opened = os.fstat(descriptor)
        if _entry_signature(opened) != signature:
            return False
        if not _file_content_matches(
            descriptor, expected.size, expected.digest
        ):
            return False
        if _entry_signature(os.fstat(descriptor)) != signature:
            return False
        _verify_named_entry(directory_fd, name, entry)
        return True
    except (OSError, WorkspaceSnapshotError):
        return False
    finally:
        if descriptor >= 0:
            os.close(descriptor)
