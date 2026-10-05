"""Create a private, hard-link-free copy of a workspace tree."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
import ctypes
import fcntl
import os
from pathlib import Path
import secrets
import stat
import struct
import sys
import tempfile
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from functools import cache
from types import MappingProxyType

from ..ipc import (
    MAX_WORKSPACE_LIST_ENTRIES,
    MAX_WORKSPACE_LIST_NAME_BYTES,
    MAX_WORKSPACE_READ_BYTES,
    MAX_WORKSPACE_WRITE_BYTES,
)


class WorkspaceSnapshotError(RuntimeError):
    """The source tree could not be copied without crossing its boundary."""


class WorkspacePathIOError(WorkspaceSnapshotError):
    """Path-free I/O stage for a directory ancestry check."""

    def __init__(self, stage: str) -> None:
        if stage not in {
            "directory_mountpoint",
            "directory_resolve",
            "path_mountpoint",
            "path_resolve",
        }:
            raise ValueError("workspace path I/O stage is invalid")
        self.stage = stage
        super().__init__(stage)


class WorkspaceSnapshotCancelled(WorkspaceSnapshotError):
    """The trusted caller cancelled workspace snapshot construction."""


@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    """Metadata captured from one source-tree entry by the snapshot copier."""

    kind: str
    mode: int
    signature: tuple[int, ...]
    size: int = 0
    digest: str | None = None
    target: str | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    """Captured baseline, bound source descriptor, and private tree."""

    source_root: Path
    path: Path
    source_mount_point: str | None
    snapshot_mount_point: str | None
    storage_limit_bytes: int | None
    baseline: Mapping[tuple[str, ...], SnapshotEntry]
    max_entries: int
    max_bytes: int
    max_depth: int
    _source_root_fd: int | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class WorkspaceDirectoryEntry:
    """Safe metadata for one entry in a Kernel-scoped snapshot listing."""

    name: str
    kind: str
    size: int | None


class WorkspaceReadLimitError(WorkspaceSnapshotError):
    """A bounded snapshot read or listing exceeded its response budget."""


_MAX_WORKSPACE_PATH_BYTES = 4096
_MAX_WORKSPACE_READ_SCOPE_PATHS = 128
_MAX_WORKSPACE_READ_SCOPE_BYTES = 4096
_MAX_WORKSPACE_WRITE_SCOPE_PATHS = 128
_MAX_WORKSPACE_WRITE_SCOPE_BYTES = 4096
_DEFAULT_WORKSPACE_MAX_DEPTH = 64
_SNAPSHOT_BROKER_STORAGE_DIRECTORY = "khaos-snapshot-broker"
_SNAPSHOT_IMAGE_OPERATION_MARKER = ".khaos-image-operation-pending"


def read_snapshot_file(
    snapshot: WorkspaceSnapshot, relative_path: str
) -> bytes:
    """Read one bounded regular file without following any path symlink."""
    parts = _snapshot_path_parts(snapshot, relative_path)
    if not parts:
        raise WorkspaceSnapshotError("snapshot root is not a file")

    parent_fd, name, device = _open_snapshot_parent(snapshot, parts)
    try:
        expected = _stat_exact_snapshot_entry(parent_fd, name)
        assert expected is not None
        if not stat.S_ISREG(expected.st_mode) or expected.st_nlink != 1:
            raise WorkspaceSnapshotError(
                "snapshot file must be a single-link regular file"
            )
        if expected.st_size > MAX_WORKSPACE_READ_BYTES:
            raise WorkspaceReadLimitError("snapshot file exceeds the read limit")

        try:
            descriptor = os.open(name, _FILE_READ_FLAGS, dir_fd=parent_fd)
        except OSError as exc:
            raise WorkspaceSnapshotError("snapshot file cannot be opened safely") from exc
        try:
            opened = os.fstat(descriptor)
            _verify_snapshot_file(snapshot, descriptor, expected, opened, device)
            chunks: list[bytes] = []
            total = 0
            while total <= MAX_WORKSPACE_READ_BYTES:
                chunk = os.read(
                    descriptor,
                    min(16 * 1024, MAX_WORKSPACE_READ_BYTES + 1 - total),
                )
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            final = os.fstat(descriptor)
            current = _stat_exact_snapshot_entry(parent_fd, name)
            assert current is not None
            if not _same_entry(opened, final) or not _same_entry(final, current):
                raise WorkspaceSnapshotError("snapshot file changed while reading")
            if total > MAX_WORKSPACE_READ_BYTES:
                raise WorkspaceReadLimitError("snapshot file exceeds the read limit")
            return b"".join(chunks)
        except OSError as exc:
            raise WorkspaceSnapshotError("snapshot file could not be read safely") from exc
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_fd)


def write_snapshot_file(
    snapshot: WorkspaceSnapshot,
    relative_path: str,
    content: bytes,
) -> str:
    """Atomically replace one regular snapshot file without following links."""
    if type(content) is not bytes or len(content) > MAX_WORKSPACE_WRITE_BYTES:
        raise WorkspaceSnapshotError("snapshot write exceeds its limit")
    parts = _snapshot_path_parts(snapshot, relative_path)
    if not parts:
        raise WorkspaceSnapshotError("snapshot root is not a file")

    parent_fd, name, device = _open_snapshot_parent(snapshot, parts)
    temporary_name = f".khaos-write-{secrets.token_hex(16)}"
    temporary_fd = -1
    temporary_identity: tuple[int, int] | None = None
    try:
        existing = _stat_exact_snapshot_entry(
            parent_fd, name, allow_missing=True
        )

        mode = 0o600
        if existing is not None:
            if (
                not stat.S_ISREG(existing.st_mode)
                or existing.st_nlink != 1
                or existing.st_dev != device
            ):
                raise WorkspaceSnapshotError(
                    "snapshot write target must be a single-link regular file"
                )
            mode = stat.S_IMODE(existing.st_mode) & 0o777

        try:
            temporary_fd = os.open(
                temporary_name,
                os.O_WRONLY | _FILE_CREATE_FLAGS,
                mode,
                dir_fd=parent_fd,
            )
        except OSError as exc:
            raise WorkspaceSnapshotError("snapshot write staging failed") from exc

        staged = os.fstat(temporary_fd)
        if (
            not stat.S_ISREG(staged.st_mode)
            or staged.st_nlink != 1
            or staged.st_dev != device
        ):
            raise WorkspaceSnapshotError("snapshot write staging is unsafe")
        temporary_identity = (staged.st_dev, staged.st_ino)
        os.fchmod(temporary_fd, mode)
        view = memoryview(content)
        while view:
            written = os.write(temporary_fd, view)
            if written <= 0:
                raise OSError("snapshot write made no progress")
            view = view[written:]
        os.fsync(temporary_fd)
        completed = os.fstat(temporary_fd)
        if (
            not _same_file_identity(staged, completed)
            or completed.st_size != len(content)
        ):
            raise WorkspaceSnapshotError("snapshot write staging changed")

        if existing is None:
            # link() is atomic and refuses to overwrite a concurrent creator.
            os.link(
                temporary_name,
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
            os.unlink(temporary_name, dir_fd=parent_fd)
            temporary_identity = None
        else:
            current = _stat_exact_snapshot_entry(parent_fd, name)
            assert current is not None
            if not _same_entry(existing, current):
                raise WorkspaceSnapshotError("snapshot write target changed")
            os.replace(
                temporary_name,
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            temporary_identity = None

        installed = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(installed.st_mode)
            or installed.st_nlink != 1
            or installed.st_dev != device
            or installed.st_size != len(content)
            or (installed.st_dev, installed.st_ino) != (completed.st_dev, completed.st_ino)
        ):
            raise WorkspaceSnapshotError("snapshot write result changed")
        _verify_snapshot_mount(snapshot, parent_fd, device)
        return sha256(content).hexdigest()
    except WorkspaceSnapshotError:
        raise
    except OSError as exc:
        raise WorkspaceSnapshotError("snapshot file could not be written safely") from exc
    finally:
        if temporary_fd >= 0:
            os.close(temporary_fd)
        if temporary_identity is not None:
            try:
                temporary = os.stat(
                    temporary_name, dir_fd=parent_fd, follow_symlinks=False
                )
                if (temporary.st_dev, temporary.st_ino) == temporary_identity:
                    os.unlink(temporary_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            except OSError:
                pass
        os.close(parent_fd)


def list_snapshot_directory(
    snapshot: WorkspaceSnapshot, relative_path: str = ""
) -> tuple[WorkspaceDirectoryEntry, ...]:
    """List one bounded directory without following links or crossing mounts."""
    parts = _snapshot_path_parts(snapshot, relative_path, allow_root=True)
    descriptor, device = _open_snapshot_directory(snapshot, parts)
    try:
        before = os.fstat(descriptor)
        entries: list[WorkspaceDirectoryEntry] = []
        name_bytes = 0
        try:
            with os.scandir(descriptor) as iterator:
                for entry in iterator:
                    _validate_component(entry.name)
                    encoded_name = entry.name.encode("utf-8", errors="strict")
                    name_bytes += len(encoded_name)
                    if (
                        len(entries) >= MAX_WORKSPACE_LIST_ENTRIES
                        or name_bytes > MAX_WORKSPACE_LIST_NAME_BYTES
                    ):
                        raise WorkspaceReadLimitError(
                            "snapshot directory exceeds the listing limit"
                        )
                    info = os.stat(
                        entry.name, dir_fd=descriptor, follow_symlinks=False
                    )
                    if stat.S_ISDIR(info.st_mode):
                        child_fd = os.open(
                            entry.name, _DIRECTORY_FLAGS, dir_fd=descriptor
                        )
                        try:
                            opened = os.fstat(child_fd)
                            if not _same_entry(info, opened):
                                raise WorkspaceSnapshotError(
                                    "snapshot directory entry changed while listing"
                                )
                            _verify_snapshot_mount(snapshot, child_fd, device)
                        finally:
                            os.close(child_fd)
                        kind, size = "directory", None
                    elif stat.S_ISREG(info.st_mode):
                        if info.st_dev != device or info.st_nlink != 1:
                            raise WorkspaceSnapshotError(
                                "snapshot file is linked or outside its volume"
                            )
                        kind, size = "file", info.st_size
                    elif stat.S_ISLNK(info.st_mode):
                        kind, size = "symlink", None
                    else:
                        kind, size = "other", None
                    entries.append(
                        WorkspaceDirectoryEntry(entry.name, kind, size)
                    )
        except (OSError, UnicodeEncodeError) as exc:
            raise WorkspaceSnapshotError(
                "snapshot directory could not be listed safely"
            ) from exc

        if not _same_entry(before, os.fstat(descriptor)):
            raise WorkspaceSnapshotError("snapshot directory changed while listing")
        return tuple(sorted(entries, key=lambda item: item.name.encode("utf-8")))
    finally:
        os.close(descriptor)


@dataclass
class _CopyBudget:
    max_entries: int
    max_bytes: int
    max_depth: int
    device: int
    mount_point: str | None
    destination_device: int | None = None
    destination_mount_point: str | None = None
    cancel_requested: Callable[[], bool] | None = None
    entries: int = 0
    bytes: int = 0
    baseline: dict[tuple[str, ...], SnapshotEntry] = field(default_factory=dict)

    def check_cancelled(self) -> None:
        _check_snapshot_cancellation(self.cancel_requested)

    def add_entry(self, amount: int = 0) -> None:
        self.check_cancelled()
        self.entries += 1
        self.bytes += amount
        if self.entries > self.max_entries or self.bytes > self.max_bytes:
            raise WorkspaceSnapshotError("workspace snapshot limit exceeded")


_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_FILE_READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_FILE_CREATE_FLAGS = (
    os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_FILE_WRITE_FLAGS = os.O_WRONLY | _FILE_CREATE_FLAGS
_FILE_READ_WRITE_FLAGS = os.O_RDWR | _FILE_CREATE_FLAGS
_COPY_CHUNK_BYTES = 1024 * 1024
_MAX_SYMLINK_BYTES = 4096
_MAX_MOUNTPOINT_BYTES = 4096
_F_GETPATH_BUFFER_BYTES = 1024
_MIN_SNAPSHOT_STORAGE_BYTES = 128_000_000
_SNAPSHOT_STORAGE_OVERHEAD_BYTES = 256 * 1024 * 1024
_MAX_SNAPSHOT_STORAGE_BYTES = 16 * 1024 * 1024 * 1024


@contextmanager
def _brokered_mounted_apfs_volume(
    mount_point: Path,
    *,
    size_bytes: int,
    case_sensitive: bool,
    cancel_requested: Callable[[], bool] | None = None,
) -> Iterator[Path]:
    """Validate and use the exact APFS lease returned by the trusted Broker."""
    if sys.platform != "darwin":
        raise WorkspaceSnapshotError("bounded APFS snapshots require macOS")
    if type(size_bytes) is not int or not (
        _MIN_SNAPSHOT_STORAGE_BYTES <= size_bytes <= _MAX_SNAPSHOT_STORAGE_BYTES
    ):
        raise ValueError("APFS image size is outside the supported range")
    if type(case_sensitive) is not bool:
        raise ValueError("APFS image case sensitivity must be explicit")
    _check_snapshot_cancellation(cancel_requested)

    temporary_parent = Path(tempfile.gettempdir()).resolve(strict=True)
    mount_point = mount_point.resolve(strict=True)
    lease_root = mount_point.parent
    broker_storage_root = lease_root.parent
    lease_prefix = f"{_SNAPSHOT_BROKER_STORAGE_DIRECTORY}-"
    lease_id = lease_root.name.removeprefix(lease_prefix)
    try:
        uuid.UUID(lease_id)
    except ValueError as exc:
        raise WorkspaceSnapshotError("brokered APFS lease path is invalid") from exc
    try:
        broker_storage_info = broker_storage_root.stat(follow_symlinks=False)
        lease_info = lease_root.stat(follow_symlinks=False)
    except OSError as exc:
        raise WorkspaceSnapshotError("brokered APFS lease identity is invalid") from exc
    if (
        mount_point.name != "volume"
        or broker_storage_root.name != _SNAPSHOT_BROKER_STORAGE_DIRECTORY
        or lease_root != temporary_parent
        or not stat.S_ISDIR(broker_storage_info.st_mode)
        or (broker_storage_info.st_mode & 0o777) != 0o700
        or broker_storage_info.st_uid != os.getuid()
        or not stat.S_ISDIR(lease_info.st_mode)
        or (lease_info.st_mode & 0o777) != 0o700
        or lease_info.st_uid != os.getuid()
        or not mount_point.is_mount()
    ):
        raise WorkspaceSnapshotError("brokered APFS lease identity is invalid")
    marker = lease_root / _SNAPSHOT_IMAGE_OPERATION_MARKER
    try:
        marker_info = marker.lstat()
    except OSError as exc:
        raise WorkspaceSnapshotError("brokered APFS lease marker is missing") from exc
    if (
        not stat.S_ISREG(marker_info.st_mode)
        or marker_info.st_uid != os.getuid()
        or marker_info.st_nlink != 1
    ):
        raise WorkspaceSnapshotError("brokered APFS lease marker is invalid")

    # The authenticated Broker already checked image, device, capacity, and
    # mount identity. Repeating its external-tool checks here would duplicate
    # the authority check; snapshot creation still verifies filesystem identity.
    _check_snapshot_cancellation(cancel_requested)
    yield mount_point


_ATTR_VOL_CAPABILITIES = 0x00020000
_ATTR_VOL_FSTYPENAME = 0x00100000
_ATTR_VOL_MOUNTPOINT = 0x00001000
_ATTR_VOL_INFO = 0x80000000
_VOL_CAP_FMT_CASE_SENSITIVE = 0x00000100


class _DarwinAttrList(ctypes.Structure):
    _fields_ = (
        ("bitmapcount", ctypes.c_uint16),
        ("reserved", ctypes.c_uint16),
        ("commonattr", ctypes.c_uint32),
        ("volattr", ctypes.c_uint32),
        ("dirattr", ctypes.c_uint32),
        ("fileattr", ctypes.c_uint32),
        ("forkattr", ctypes.c_uint32),
    )


@contextmanager
def workspace_snapshot(
    workspace: str | os.PathLike[str],
    *,
    source_root_fd: int | None = None,
    brokered_mount_path: str | os.PathLike[str] | None = None,
    brokered_storage_bytes: int | None = None,
    snapshot_name: str = "workspace",
    max_entries: int = 100_000,
    max_bytes: int = 1024 * 1024 * 1024,
    max_depth: int = _DEFAULT_WORKSPACE_MAX_DEPTH,
    max_storage_bytes: int | None = None,
    owner_pid: int | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> Iterator[WorkspaceSnapshot]:
    """Yield a private copy, rejecting hard links and unstable filesystem entries.

    Files are copied through no-follow file descriptors, so the returned tree
    contains independent file inodes. Symbolic links are copied as links and
    special files, cross-device entries, and files with multiple links fail
    closed. macOS rejects source entries whose mounted-volume root differs
    from the workspace and copies into a separate capacity-bounded APFS volume.
    When a trusted caller supplies ``source_root_fd``, copying is bound to that
    opened directory and fails if the named root no longer identifies it.
    An optional trusted cancellation check is polled between entries and file
    copy chunks; cancellation aborts before the private snapshot is exposed.
    """
    for limit in (max_entries, max_bytes, max_depth):
        if type(limit) is not int or limit < 1:
            raise ValueError("snapshot limits must be positive integers")
    if max_storage_bytes is not None and (
        type(max_storage_bytes) is not int
        or max_storage_bytes < _MIN_SNAPSHOT_STORAGE_BYTES
    ):
        raise ValueError("snapshot storage limit is invalid")
    if (brokered_mount_path is None) != (brokered_storage_bytes is None):
        raise ValueError("brokered APFS mount configuration is incomplete")
    if brokered_storage_bytes is not None and (
        type(brokered_storage_bytes) is not int
        or brokered_storage_bytes < _MIN_SNAPSHOT_STORAGE_BYTES
        or brokered_storage_bytes > _MAX_SNAPSHOT_STORAGE_BYTES
    ):
        raise ValueError("brokered APFS storage limit is invalid")
    if owner_pid is not None and (type(owner_pid) is not int or owner_pid < 1):
        raise ValueError("snapshot storage owner PID is invalid")
    if cancel_requested is not None and not callable(cancel_requested):
        raise ValueError("snapshot cancellation check must be callable")
    _validate_component(snapshot_name)
    _check_snapshot_cancellation(cancel_requested)
    _require_descriptor_relative_filesystem()

    requested_root = Path(workspace).expanduser()
    if source_root_fd is None:
        try:
            root = requested_root.resolve(strict=True)
        except OSError as exc:
            raise WorkspaceSnapshotError("workspace root is unavailable") from exc
    else:
        root = _path_for_directory_descriptor(source_root_fd)
        if requested_root != root:
            raise WorkspaceSnapshotError(
                "workspace path does not match its pinned descriptor"
            )
    if root == Path("/"):
        raise WorkspaceSnapshotError("filesystem root is not a workspace")

    source_fd = -1
    parent_fd = -1
    try:
        source_fd = (
            _open_absolute_directory(root)
            if source_root_fd is None
            else _duplicate_bound_workspace_root(root, source_root_fd)
        )
        root_stat = os.fstat(source_fd)
        root_before = _entry_signature(root_stat)
        if not stat.S_ISDIR(root_stat.st_mode):
            raise WorkspaceSnapshotError("workspace root is not a directory")
        root_mount_point = _volume_mountpoint(source_fd)
        if sys.platform == "darwin" and root_mount_point is None:
            raise WorkspaceSnapshotError(
                "workspace mount identity could not be verified"
            )
        storage_parent = (
            Path(tempfile.gettempdir()).resolve(strict=True)
            if sys.platform == "darwin"
            else root.parent
        )
        if sys.platform == "darwin" and _path_is_within(
            storage_parent,
            root,
            directory_descriptor=source_fd,
        ):
            raise WorkspaceSnapshotError(
                "snapshot backing storage cannot be inside the workspace"
            )
        parent_fd = _open_absolute_directory(storage_parent)
        parent_signature = _entry_signature(os.fstat(parent_fd))

        storage_limit = None
        if sys.platform == "darwin":
            default_storage_limit = (
                2 * max_bytes + _SNAPSHOT_STORAGE_OVERHEAD_BYTES
            )
            if default_storage_limit > _MAX_SNAPSHOT_STORAGE_BYTES:
                raise ValueError("snapshot storage limit exceeds the supported maximum")
            storage_limit = (
                default_storage_limit
                if max_storage_bytes is None
                else max_storage_bytes
            )
            if storage_limit > default_storage_limit:
                raise ValueError("snapshot storage limit exceeds its copy budget")
            if brokered_storage_bytes is not None and brokered_storage_bytes != storage_limit:
                raise WorkspaceSnapshotError(
                    "Kernel snapshot broker capacity does not match the copy budget"
                )
            case_sensitive = _apfs_case_sensitivity(source_fd)
            if brokered_mount_path is None:
                # Source-tree tests use the direct backend. The signed product
                # intentionally omits that module, so a missing Broker lease
                # cannot fall back to mounting an image in KernelProduction.xpc.
                from .macos_disk_image import mounted_apfs_volume

                storage_context = mounted_apfs_volume(
                    storage_parent,
                    size_bytes=storage_limit,
                    case_sensitive=case_sensitive,
                    owner_pid=owner_pid,
                    cancel_requested=cancel_requested,
                )
            else:
                storage_context = _brokered_mounted_apfs_volume(
                    Path(brokered_mount_path),
                    size_bytes=storage_limit,
                    case_sensitive=case_sensitive,
                    cancel_requested=cancel_requested,
                )
        else:
            if max_storage_bytes is not None:
                raise WorkspaceSnapshotError(
                    "bounded APFS snapshots require macOS"
                )
            storage_context = tempfile.TemporaryDirectory(
                prefix="khaos-snapshot-", dir=root.parent
            )

        with storage_context as storage_root_value:
            _check_snapshot_cancellation(cancel_requested)
            storage_root = Path(storage_root_value).resolve(strict=True)
            temporary_root = (
                storage_root.parent if storage_limit is not None else storage_root
            )
            storage_parent_path = (
                temporary_root
                if brokered_mount_path is not None
                else temporary_root.parent
            )
            temporary_parent_fd = _open_absolute_directory(
                storage_parent_path
            )
            try:
                if not _same_directory_identity(
                    parent_signature,
                    _entry_signature(os.fstat(temporary_parent_fd)),
                ):
                    raise WorkspaceSnapshotError(
                        "snapshot parent changed during creation"
                    )
            finally:
                os.close(temporary_parent_fd)
            snapshot = storage_root / snapshot_name
            snapshot.mkdir(mode=0o700)
            snapshot = snapshot.resolve(strict=True)
            destination_fd = _open_absolute_directory(snapshot)
            try:
                destination_root = os.fstat(destination_fd)
                snapshot_mount_point = _volume_mountpoint(destination_fd)
                if sys.platform == "darwin":
                    if (
                        destination_root.st_dev == root_stat.st_dev
                        or snapshot_mount_point in (None, root_mount_point)
                    ):
                        raise WorkspaceSnapshotError(
                            "snapshot did not use a separate APFS work volume"
                        )
                elif (
                    destination_root.st_dev != root_stat.st_dev
                    or snapshot_mount_point != root_mount_point
                ):
                    raise WorkspaceSnapshotError(
                        "snapshot and workspace are on different filesystem mounts"
                    )
                budget = _CopyBudget(
                    max_entries=max_entries,
                    max_bytes=max_bytes,
                    max_depth=max_depth,
                    device=os.fstat(source_fd).st_dev,
                    mount_point=root_mount_point,
                    destination_device=destination_root.st_dev,
                    destination_mount_point=snapshot_mount_point,
                    cancel_requested=cancel_requested,
                )
                budget.baseline[()] = SnapshotEntry(
                    "directory",
                    stat.S_IMODE(root_stat.st_mode) & 0o777,
                    root_before,
                )
                _copy_directory(
                    source_fd, destination_fd, budget, depth=0, relative=()
                )
                budget.check_cancelled()
            except WorkspaceSnapshotError:
                raise
            except OSError as exc:
                raise WorkspaceSnapshotError(
                    "workspace changed or could not be copied safely"
                ) from exc
            finally:
                os.close(destination_fd)

            try:
                current_snapshot_fd = _open_absolute_directory(snapshot)
            except OSError as exc:
                raise WorkspaceSnapshotError(
                    "snapshot root changed during creation"
                ) from exc
            try:
                current_snapshot = os.fstat(current_snapshot_fd)
                if (
                    not _same_directory_identity(
                        _entry_signature(destination_root),
                        _entry_signature(current_snapshot),
                    )
                    or _volume_mountpoint(current_snapshot_fd)
                    != snapshot_mount_point
                ):
                    raise WorkspaceSnapshotError(
                        "snapshot root changed during creation"
                    )
            finally:
                os.close(current_snapshot_fd)

            if _entry_signature(os.fstat(source_fd)) != root_before:
                raise WorkspaceSnapshotError("workspace changed during snapshot")
            if source_root_fd is None:
                current_root_fd = _open_absolute_directory(root)
                try:
                    if _entry_signature(os.fstat(current_root_fd)) != root_before:
                        raise WorkspaceSnapshotError(
                            "workspace root changed during snapshot"
                        )
                finally:
                    os.close(current_root_fd)
            elif (
                _entry_signature(os.fstat(source_fd)) != root_before
                or _path_for_directory_descriptor(source_fd) != root
            ):
                raise WorkspaceSnapshotError("workspace root changed during snapshot")

            yield WorkspaceSnapshot(
                source_root=root,
                path=snapshot,
                source_mount_point=root_mount_point,
                snapshot_mount_point=snapshot_mount_point,
                storage_limit_bytes=storage_limit,
                baseline=MappingProxyType(dict(budget.baseline)),
                max_entries=max_entries,
                max_bytes=max_bytes,
                max_depth=max_depth,
                _source_root_fd=source_fd,
            )
    except WorkspaceSnapshotError:
        raise
    except OSError as exc:
        raise WorkspaceSnapshotError(
            "workspace changed or could not be copied safely"
        ) from exc
    finally:
        if parent_fd >= 0:
            os.close(parent_fd)
        if source_fd >= 0:
            os.close(source_fd)


def _check_snapshot_cancellation(
    cancel_requested: Callable[[], bool] | None,
) -> None:
    if cancel_requested is not None and cancel_requested():
        raise WorkspaceSnapshotCancelled("workspace snapshot was cancelled")


def _duplicate_bound_workspace_root(root: Path, source_root_fd: int) -> int:
    """Use a trusted caller's root and reject a moved or retargeted binding."""
    if type(source_root_fd) is not int or source_root_fd < 0:
        raise WorkspaceSnapshotError("workspace root descriptor is invalid")
    try:
        descriptor = os.dup(source_root_fd)
    except OSError as exc:
        raise WorkspaceSnapshotError(
            "workspace root descriptor is unavailable"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            raise WorkspaceSnapshotError("workspace root is not a directory")
        if _path_for_directory_descriptor(descriptor) != root:
            raise WorkspaceSnapshotError("workspace root changed before snapshot")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _path_for_directory_descriptor(descriptor: int) -> Path:
    """Get macOS's current path for a pinned directory without reopening it."""
    if (
        type(descriptor) is not int
        or descriptor < 0
        or sys.platform != "darwin"
        or not hasattr(fcntl, "F_GETPATH")
    ):
        raise WorkspaceSnapshotError("workspace descriptor path is unsupported")
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode):
            raise WorkspaceSnapshotError("workspace root is not a directory")
        encoded_path = fcntl.fcntl(
            descriptor,
            fcntl.F_GETPATH,
            b"\0" * _F_GETPATH_BUFFER_BYTES,
        )
    except OSError as exc:
        raise WorkspaceSnapshotError(
            "workspace descriptor path is unavailable"
        ) from exc
    if b"\0" not in encoded_path:
        raise WorkspaceSnapshotError("workspace descriptor path is truncated")
    path_bytes = encoded_path.split(b"\0", 1)[0]
    if not path_bytes:
        raise WorkspaceSnapshotError("workspace descriptor path is invalid")
    path = Path(os.fsdecode(path_bytes))
    if not path.is_absolute():
        raise WorkspaceSnapshotError("workspace descriptor path is not absolute")
    return path


def _open_absolute_directory(path: Path) -> int:
    if not path.is_absolute():
        raise WorkspaceSnapshotError("workspace path must be absolute")
    descriptor = os.open("/", _DIRECTORY_FLAGS)
    try:
        for part in path.parts[1:]:
            try:
                next_descriptor = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            except PermissionError:
                # App Sandbox can grant an exact directory while refusing to
                # open an ancestor such as /Users. Verify the kernel's path for
                # the directly opened descriptor before using that grant.
                if sys.platform != "darwin":
                    raise
                direct = os.open(path, _DIRECTORY_FLAGS)
                try:
                    if _path_for_directory_descriptor(direct) != path:
                        raise WorkspaceSnapshotError(
                            "workspace directory resolved outside its path"
                        )
                    os.close(descriptor)
                    return direct
                except BaseException:
                    os.close(direct)
                    raise
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


@cache
def _get_fgetattrlist():
    try:
        function = ctypes.CDLL(None, use_errno=True).fgetattrlist
    except (AttributeError, OSError) as exc:
        raise WorkspaceSnapshotError(
            "filesystem mount identity API is unavailable"
        ) from exc
    function.argtypes = (
        ctypes.c_int,
        ctypes.POINTER(_DarwinAttrList),
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_ulong,
    )
    function.restype = ctypes.c_int
    return function


@cache
def _get_getattrlist():
    try:
        function = ctypes.CDLL(None, use_errno=True).getattrlist
    except (AttributeError, OSError) as exc:
        raise WorkspaceSnapshotError(
            "filesystem mount identity API is unavailable"
        ) from exc
    function.argtypes = (
        ctypes.c_char_p,
        ctypes.POINTER(_DarwinAttrList),
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_ulong,
    )
    function.restype = ctypes.c_int
    return function


def _mountpoint_attributes() -> _DarwinAttrList:
    return _DarwinAttrList(
        5,
        0,
        0,
        _ATTR_VOL_INFO | _ATTR_VOL_MOUNTPOINT,
        0,
        0,
        0,
    )


def _apfs_case_sensitivity(descriptor: int) -> bool:
    """Read APFS type and case semantics from the already-open source root."""
    if sys.platform != "darwin":
        raise WorkspaceSnapshotError("bounded APFS snapshots require macOS")
    if type(descriptor) is not int or descriptor < 0:
        raise WorkspaceSnapshotError("workspace root descriptor is invalid")

    attributes = _DarwinAttrList(
        5,
        0,
        0,
        _ATTR_VOL_CAPABILITIES | _ATTR_VOL_FSTYPENAME,
        0,
        0,
        0,
    )
    buffer = ctypes.create_string_buffer(_MAX_MOUNTPOINT_BYTES)
    function = _get_fgetattrlist()
    if function(descriptor, ctypes.byref(attributes), buffer, len(buffer), 0) != 0:
        error = ctypes.get_errno()
        raise WorkspaceSnapshotError(
            "workspace APFS capabilities could not be verified"
        ) from OSError(error, os.strerror(error))

    returned_size = struct.unpack_from("=I", buffer.raw)[0]
    capability_offset = struct.calcsize("=I")
    capabilities = struct.unpack_from("=8I", buffer.raw, capability_offset)
    filesystem_offset = capability_offset + struct.calcsize("=8I")
    filesystem = _decode_attribute_reference(
        buffer,
        filesystem_offset,
        returned_size,
    )
    valid_format = capabilities[4]
    if (
        filesystem != b"apfs"
        or not valid_format & _VOL_CAP_FMT_CASE_SENSITIVE
    ):
        raise WorkspaceSnapshotError("workspace must use a supported APFS filesystem")
    return bool(capabilities[0] & _VOL_CAP_FMT_CASE_SENSITIVE)


def _volume_mountpoint(descriptor: int) -> str | None:
    """Read this fd's mount root; st_dev alone misses same-device mounts."""
    if sys.platform != "darwin":
        return None
    attributes = _mountpoint_attributes()
    buffer = ctypes.create_string_buffer(_MAX_MOUNTPOINT_BYTES)
    function = _get_fgetattrlist()
    if function(descriptor, ctypes.byref(attributes), buffer, len(buffer), 0) != 0:
        error = ctypes.get_errno()
        raise WorkspaceSnapshotError(
            "filesystem mount identity could not be verified"
        ) from OSError(error, os.strerror(error))

    return _decode_volume_mountpoint(buffer)


def _volume_mountpoint_for_path(path: Path, *, stage: str) -> str:
    """Read mount metadata without opening a sandbox-inaccessible directory."""
    if sys.platform != "darwin":
        raise WorkspaceSnapshotError("path mount identity requires macOS")
    try:
        before = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise WorkspacePathIOError(stage) from exc
    if not stat.S_ISDIR(before.st_mode):
        raise WorkspaceSnapshotError("filesystem mount path is not a directory")

    attributes = _mountpoint_attributes()
    buffer = ctypes.create_string_buffer(_MAX_MOUNTPOINT_BYTES)
    function = _get_getattrlist()
    if function(os.fsencode(path), ctypes.byref(attributes), buffer, len(buffer), 1) != 0:
        error = ctypes.get_errno()
        raise WorkspacePathIOError(stage) from OSError(error, os.strerror(error))
    mount_point = _decode_volume_mountpoint(buffer)
    try:
        after = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise WorkspacePathIOError(stage) from exc
    if not _same_directory_identity(
        _entry_signature(before), _entry_signature(after)
    ):
        raise WorkspaceSnapshotError("filesystem mount path changed during inspection")
    return mount_point


def _decode_volume_mountpoint(buffer: ctypes.Array[ctypes.c_char]) -> str:
    returned_size = struct.unpack_from("=I", buffer.raw)[0]
    reference_offset = struct.calcsize("=I")
    value = _decode_attribute_reference(buffer, reference_offset, returned_size)
    try:
        mount_point = value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkspaceSnapshotError(
            "filesystem mount identity is not UTF-8"
        ) from exc
    if not mount_point.startswith("/"):
        raise WorkspaceSnapshotError("filesystem mount identity is not absolute")
    return mount_point


def _decode_attribute_reference(
    buffer: ctypes.Array[ctypes.c_char],
    reference_offset: int,
    returned_size: int,
) -> bytes:
    reference_size = struct.calcsize("=iI")
    if (
        returned_size < reference_offset + reference_size
        or returned_size > len(buffer)
    ):
        raise WorkspaceSnapshotError("filesystem volume attribute is malformed")
    data_offset, data_length = struct.unpack_from("=iI", buffer.raw, reference_offset)
    data_start = reference_offset + data_offset
    data_end = data_start + data_length
    if (
        data_offset < reference_size
        or data_length < 2
        or data_end > returned_size
    ):
        raise WorkspaceSnapshotError("filesystem volume attribute is malformed")
    value = buffer.raw[data_start:data_end]
    if not value.endswith(b"\0") or b"\0" in value[:-1]:
        raise WorkspaceSnapshotError("filesystem volume attribute is malformed")
    return value[:-1]


def _path_is_within(
    path: Path,
    directory: Path,
    *,
    directory_descriptor: int | None = None,
    path_descriptor: int | None = None,
) -> bool:
    """Compare directory ancestry after resolving macOS firmlink path aliases."""
    if sys.platform != "darwin":
        if directory_descriptor is not None or path_descriptor is not None:
            raise WorkspaceSnapshotError(
                "descriptor ancestry requires macOS enforcement"
            )
        path = path.resolve(strict=True)
        directory = directory.resolve(strict=True)
        return path.is_relative_to(directory)

    if path_descriptor is None:
        try:
            path = path.resolve(strict=True)
        except OSError as exc:
            raise WorkspacePathIOError("path_resolve") from exc
    elif _path_for_directory_descriptor(path_descriptor) != path:
        raise WorkspaceSnapshotError("workspace root changed during ancestry check")
    if directory_descriptor is None:
        try:
            directory = directory.resolve(strict=True)
        except OSError as exc:
            raise WorkspacePathIOError("directory_resolve") from exc
    elif _path_for_directory_descriptor(directory_descriptor) != directory:
        raise WorkspaceSnapshotError("workspace root changed during ancestry check")
    path_mount = (
        _volume_mountpoint(path_descriptor)
        if path_descriptor is not None
        else _volume_mountpoint_for_path(path, stage="path_mountpoint")
    )
    directory_mount = (
        _volume_mountpoint(directory_descriptor)
        if directory_descriptor is not None
        else _volume_mountpoint_for_path(directory, stage="directory_mountpoint")
    )
    if path_mount is None or directory_mount is None:
        raise WorkspaceSnapshotError(
            "filesystem mount identity could not be verified"
        )
    path_on_mount = _path_on_mount(path, path_mount)
    directory_on_mount = _path_on_mount(directory, directory_mount)
    return path_on_mount.is_relative_to(directory_on_mount)


def _path_on_mount(path: Path, mount_point: str) -> Path:
    """Translate a firmlink alias to its equivalent path below its mount root."""
    mount_root = Path(mount_point).resolve(strict=True)
    if path.is_relative_to(mount_root):
        return path
    mount_path = mount_root / path.relative_to("/")
    try:
        if not os.path.samefile(path, mount_path):
            raise WorkspaceSnapshotError(
                "filesystem path alias could not be verified"
            )
    except OSError as exc:
        raise WorkspaceSnapshotError(
            "filesystem path alias could not be verified"
        ) from exc
    return mount_path


def _copy_directory(
    source_fd: int,
    destination_fd: int,
    budget: _CopyBudget,
    *,
    depth: int,
    relative: tuple[str, ...],
) -> None:
    before_directory = os.fstat(source_fd)
    _verify_mountpoint(budget.mount_point, source_fd)
    _verify_copy_target(destination_fd, budget)
    with os.scandir(source_fd) as entries:
        for item in entries:
            name = item.name
            _validate_component(name)
            child_path = (*relative, name)
            entry = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
            if entry.st_dev != budget.device:
                raise WorkspaceSnapshotError(
                    "workspace contains an entry on another filesystem"
                )

            if stat.S_ISDIR(entry.st_mode):
                budget.add_entry()
                if depth >= budget.max_depth:
                    raise WorkspaceSnapshotError(
                        "workspace nesting limit exceeded"
                    )
                source_child_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=source_fd)
                try:
                    if not _same_entry(entry, os.fstat(source_child_fd)):
                        raise WorkspaceSnapshotError(
                            "workspace changed during snapshot"
                        )
                    _verify_mountpoint(budget.mount_point, source_child_fd)
                    budget.baseline[child_path] = SnapshotEntry(
                        "directory",
                        stat.S_IMODE(entry.st_mode) & 0o777,
                        _entry_signature(entry),
                    )
                    os.mkdir(name, mode=0o700, dir_fd=destination_fd)
                    destination_child_fd = os.open(
                        name, _DIRECTORY_FLAGS, dir_fd=destination_fd
                    )
                    try:
                        _verify_copy_target(destination_child_fd, budget)
                        _copy_directory(
                            source_child_fd,
                            destination_child_fd,
                            budget,
                            depth=depth + 1,
                            relative=child_path,
                        )
                    finally:
                        os.close(destination_child_fd)
                    _verify_named_entry(source_fd, name, entry)
                    if not _same_entry(entry, os.fstat(source_child_fd)):
                        raise WorkspaceSnapshotError(
                            "workspace changed during snapshot"
                        )
                finally:
                    os.close(source_child_fd)
            elif stat.S_ISREG(entry.st_mode):
                _copy_regular_file(
                    source_fd, destination_fd, name, entry, budget, child_path
                )
            elif stat.S_ISLNK(entry.st_mode):
                _copy_symlink(
                    source_fd, destination_fd, name, entry, budget, child_path
                )
            else:
                raise WorkspaceSnapshotError(
                    "workspace contains an unsupported filesystem entry"
                )

    _verify_directory(source_fd, before_directory)
    _verify_copy_target(destination_fd, budget)


def _copy_regular_file(
    source_directory_fd: int,
    destination_directory_fd: int,
    name: str,
    entry: os.stat_result,
    budget: _CopyBudget,
    relative: tuple[str, ...],
) -> None:
    budget.add_entry(entry.st_size)
    if entry.st_nlink != 1:
        raise WorkspaceSnapshotError(
            "workspace contains a file with multiple hard links"
        )

    source_fd = os.open(name, _FILE_READ_FLAGS, dir_fd=source_directory_fd)
    destination_fd = -1
    try:
        if not _same_entry(entry, os.fstat(source_fd)):
            raise WorkspaceSnapshotError("workspace changed during snapshot")
        _verify_mountpoint(budget.mount_point, source_fd)
        destination_fd = os.open(
            name,
            _FILE_WRITE_FLAGS,
            0o600,
            dir_fd=destination_directory_fd,
        )
        _verify_copy_target(destination_fd, budget)
        copied = 0
        digest = sha256()
        while True:
            budget.check_cancelled()
            chunk = os.read(source_fd, _COPY_CHUNK_BYTES)
            if not chunk:
                break
            copied += len(chunk)
            digest.update(chunk)
            if copied + budget.bytes - entry.st_size > budget.max_bytes:
                raise WorkspaceSnapshotError("workspace snapshot limit exceeded")
            view = memoryview(chunk)
            while view:
                written = os.write(destination_fd, view)
                if written == 0:
                    raise WorkspaceSnapshotError("workspace snapshot write failed")
                view = view[written:]
        if copied != entry.st_size:
            raise WorkspaceSnapshotError("workspace changed during snapshot")
        os.fchmod(destination_fd, stat.S_IMODE(entry.st_mode) & 0o777)
        if not _same_entry(entry, os.fstat(source_fd)):
            raise WorkspaceSnapshotError("workspace changed during snapshot")
        _verify_named_entry(source_directory_fd, name, entry)
        budget.baseline[relative] = SnapshotEntry(
            "file",
            stat.S_IMODE(entry.st_mode) & 0o777,
            _entry_signature(entry),
            size=copied,
            digest=digest.hexdigest(),
        )
    finally:
        os.close(source_fd)
        if destination_fd >= 0:
            os.close(destination_fd)


def _copy_symlink(
    source_directory_fd: int,
    destination_directory_fd: int,
    name: str,
    entry: os.stat_result,
    budget: _CopyBudget,
    relative: tuple[str, ...],
) -> None:
    _verify_copy_target(destination_directory_fd, budget)
    target = os.readlink(name, dir_fd=source_directory_fd)
    target_bytes = os.fsencode(target)
    if len(target_bytes) > _MAX_SYMLINK_BYTES:
        raise WorkspaceSnapshotError("workspace symlink target is too long")
    budget.add_entry(len(target_bytes))
    _verify_named_entry(source_directory_fd, name, entry)
    os.symlink(target, name, dir_fd=destination_directory_fd)
    _verify_copy_target(destination_directory_fd, budget)
    _verify_named_entry(source_directory_fd, name, entry)
    budget.baseline[relative] = SnapshotEntry(
        "symlink",
        stat.S_IMODE(entry.st_mode) & 0o777,
        _entry_signature(entry),
        target=target,
    )


def _validate_component(name: str) -> None:
    if (
        not isinstance(name, str)
        or name in ("", ".", "..")
        or "/" in name
        or "\x00" in name
    ):
        raise WorkspaceSnapshotError("workspace contains an invalid path component")
    try:
        name.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise WorkspaceSnapshotError(
            "workspace contains a non-UTF-8 path component"
        ) from exc


def _verify_mountpoint(expected: str | None, descriptor: int) -> None:
    if _volume_mountpoint(descriptor) != expected:
        raise WorkspaceSnapshotError(
            "workspace contains an entry on another filesystem mount"
        )


def _verify_copy_target(descriptor: int, budget: _CopyBudget) -> None:
    if budget.destination_device is None:
        return
    if os.fstat(descriptor).st_dev != budget.destination_device:
        raise WorkspaceSnapshotError("snapshot destination changed filesystems")
    _verify_mountpoint(budget.destination_mount_point, descriptor)


def _verify_named_entry(
    directory_fd: int, name: str, expected: os.stat_result
) -> None:
    current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    if not _same_entry(expected, current):
        raise WorkspaceSnapshotError("workspace changed during snapshot")


def _verify_directory(directory_fd: int, expected: os.stat_result) -> None:
    if not _same_entry(expected, os.fstat(directory_fd)):
        raise WorkspaceSnapshotError("workspace changed during snapshot")


def _same_entry(left: os.stat_result, right: os.stat_result) -> bool:
    return _entry_signature(left) == _entry_signature(right)


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
        and stat.S_IFMT(left.st_mode) == stat.S_IFMT(right.st_mode)
        and left.st_nlink == right.st_nlink
    )


def _same_directory_identity(
    left: tuple[int, ...], right: tuple[int, ...]
) -> bool:
    return left[:4] == right[:4]


def _entry_signature(entry: os.stat_result) -> tuple[int, ...]:
    return (
        entry.st_dev,
        entry.st_ino,
        stat.S_IFMT(entry.st_mode),
        stat.S_IMODE(entry.st_mode),
        entry.st_nlink,
        entry.st_size,
        entry.st_mtime_ns,
        entry.st_ctime_ns,
        entry.st_uid,
        entry.st_gid,
        getattr(entry, "st_flags", 0),
    )


def _require_descriptor_relative_filesystem(
    additional_functions: tuple[object, ...] = (),
) -> None:
    required_functions = (
        os.open,
        os.stat,
        os.readlink,
        os.mkdir,
        os.symlink,
        *additional_functions,
    )
    if (
        not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "O_DIRECTORY")
        or os.scandir not in os.supports_fd
        or any(function not in os.supports_dir_fd for function in required_functions)
    ):
        raise WorkspaceSnapshotError(
            "descriptor-relative no-follow filesystem APIs are unavailable"
        )


def _snapshot_path_parts(
    snapshot: WorkspaceSnapshot,
    relative_path: object,
    *,
    allow_root: bool = False,
) -> tuple[str, ...]:
    return _relative_path_parts(
        relative_path,
        max_depth=snapshot.max_depth,
        allow_root=allow_root,
    )


def _relative_path_parts(
    relative_path: object,
    *,
    max_depth: int,
    allow_root: bool = False,
) -> tuple[str, ...]:
    if type(relative_path) is not str:
        raise WorkspaceSnapshotError("snapshot path must be a string")
    try:
        encoded_path = relative_path.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise WorkspaceSnapshotError("snapshot path is not valid UTF-8") from exc
    if (
        len(encoded_path) > _MAX_WORKSPACE_PATH_BYTES
        or relative_path.startswith("/")
        or type(max_depth) is not int
        or max_depth < 1
    ):
        raise WorkspaceSnapshotError("snapshot path is invalid")
    if relative_path == "" and allow_root:
        return ()

    parts = tuple(relative_path.split("/"))
    if len(parts) > max_depth:
        raise WorkspaceSnapshotError("snapshot path exceeds the depth limit")
    for part in parts:
        _validate_component(part)
    return parts


def _parse_scope_paths(
    paths: object,
    *,
    scope_name: str,
    max_depth: int,
    max_paths: int,
    max_bytes: int,
) -> tuple[tuple[str, ...], ...]:
    if (
        isinstance(paths, (str, bytes))
        or not isinstance(paths, Sequence)
        or len(paths) > max_paths
        or type(max_depth) is not int
        or max_depth < 1
    ):
        raise WorkspaceSnapshotError(f"{scope_name} is invalid")

    parsed: list[tuple[str, ...]] = []
    total_bytes = 0
    for path in paths:
        try:
            parts = _relative_path_parts(path, max_depth=max_depth)
        except WorkspaceSnapshotError as exc:
            raise WorkspaceSnapshotError(f"{scope_name} path is invalid") from exc
        total_bytes += len(path.encode("utf-8")) + 1
        if total_bytes > max_bytes:
            raise WorkspaceSnapshotError(f"{scope_name} is too large")
        if parts in parsed:
            raise WorkspaceSnapshotError(f"{scope_name} has duplicates")
        parsed.append(parts)
    return tuple(
        sorted(parsed, key=lambda parts: "/".join(parts).encode("utf-8"))
    )


@dataclass(frozen=True, slots=True)
class WorkspaceReadScope:
    """Kernel-retained relative roots for Runner and command workspace reads."""

    paths: tuple[tuple[str, ...], ...]

    @classmethod
    def from_paths(
        cls,
        paths: object = (),
        *,
        max_depth: int = _DEFAULT_WORKSPACE_MAX_DEPTH,
    ) -> WorkspaceReadScope:
        if isinstance(paths, cls):
            paths = paths.as_paths()
        ordered = _parse_scope_paths(
            paths,
            scope_name="workspace read scope",
            max_depth=max_depth,
            max_paths=_MAX_WORKSPACE_READ_SCOPE_PATHS,
            max_bytes=_MAX_WORKSPACE_READ_SCOPE_BYTES,
        )
        minimal: list[tuple[str, ...]] = []
        for parts in ordered:
            if not any(_path_is_prefix(root, parts) for root in minimal):
                minimal.append(parts)
        return cls(tuple(minimal))

    def as_paths(self) -> tuple[str, ...]:
        return tuple("/".join(parts) for parts in self.paths)

    def permits_read(self, relative_path: object, *, max_depth: int) -> bool:
        try:
            requested = _relative_path_parts(
                relative_path,
                max_depth=max_depth,
            )
        except WorkspaceSnapshotError:
            return False
        return any(_path_is_prefix(root, requested) for root in self.paths)

    def permits_list(self, relative_path: object, *, max_depth: int) -> bool:
        try:
            requested = _relative_path_parts(
                relative_path,
                max_depth=max_depth,
                allow_root=True,
            )
        except WorkspaceSnapshotError:
            return False
        return any(_path_scopes_overlap(root, requested) for root in self.paths)

    def visible_entries(
        self,
        relative_path: object,
        entries: tuple[WorkspaceDirectoryEntry, ...],
        *,
        max_depth: int,
    ) -> tuple[WorkspaceDirectoryEntry, ...]:
        directory = _relative_path_parts(
            relative_path,
            max_depth=max_depth,
            allow_root=True,
        )
        return tuple(
            entry
            for entry in entries
            if any(
                _path_scopes_overlap(root, directory + (entry.name,))
                for root in self.paths
            )
        )


@dataclass(frozen=True, slots=True)
class WorkspaceWriteScope:
    """Kernel-retained exact paths that Runner may change in the snapshot."""

    paths: tuple[tuple[str, ...], ...]

    @classmethod
    def from_paths(
        cls,
        paths: object = (),
        *,
        max_depth: int = _DEFAULT_WORKSPACE_MAX_DEPTH,
    ) -> WorkspaceWriteScope:
        if isinstance(paths, cls):
            paths = paths.as_paths()
        return cls(
            _parse_scope_paths(
                paths,
                scope_name="workspace write scope",
                max_depth=max_depth,
                max_paths=_MAX_WORKSPACE_WRITE_SCOPE_PATHS,
                max_bytes=_MAX_WORKSPACE_WRITE_SCOPE_BYTES,
            )
        )

    def as_paths(self) -> tuple[str, ...]:
        return tuple("/".join(parts) for parts in self.paths)

    def permits_write(self, relative_path: object, *, max_depth: int) -> bool:
        try:
            requested = _relative_path_parts(
                relative_path,
                max_depth=max_depth,
            )
        except WorkspaceSnapshotError:
            return False
        return requested in self.paths


def _path_is_prefix(prefix: tuple[str, ...], path: tuple[str, ...]) -> bool:
    return len(prefix) <= len(path) and path[: len(prefix)] == prefix


def _path_scopes_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    return _path_is_prefix(left, right) or _path_is_prefix(right, left)


def _open_snapshot_directory(
    snapshot: WorkspaceSnapshot, parts: tuple[str, ...]
) -> tuple[int, int]:
    descriptor = -1
    try:
        descriptor = _open_absolute_directory(snapshot.path)
        root_device = os.fstat(descriptor).st_dev
        _verify_snapshot_mount(snapshot, descriptor, root_device)
        for part in parts:
            expected = _stat_exact_snapshot_entry(descriptor, part)
            assert expected is not None
            if not stat.S_ISDIR(expected.st_mode):
                raise WorkspaceSnapshotError(
                    "snapshot path component is not a directory"
                )
            next_descriptor = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            try:
                opened = os.fstat(next_descriptor)
                current = _stat_exact_snapshot_entry(descriptor, part)
                assert current is not None
                if not _same_entry(expected, opened) or not _same_entry(
                    opened, current
                ):
                    raise WorkspaceSnapshotError(
                        "snapshot directory changed while opening"
                    )
                _verify_snapshot_mount(snapshot, next_descriptor, root_device)
            except BaseException:
                os.close(next_descriptor)
                raise
            previous_descriptor = descriptor
            descriptor = next_descriptor
            os.close(previous_descriptor)
        result = descriptor
        descriptor = -1
        return result, root_device
    except WorkspaceSnapshotError:
        raise
    except OSError as exc:
        raise WorkspaceSnapshotError("snapshot directory cannot be opened safely") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _stat_exact_snapshot_entry(
    directory_fd: int,
    name: str,
    *,
    allow_missing: bool = False,
) -> os.stat_result | None:
    """Resolve a stored directory-entry spelling without OS alias expansion."""
    try:
        with os.scandir(directory_fd) as entries:
            for entry in entries:
                if entry.name == name:
                    return entry.stat(follow_symlinks=False)
    except OSError as exc:
        raise WorkspaceSnapshotError(
            "snapshot entry could not be checked safely"
        ) from exc

    if allow_missing:
        try:
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise WorkspaceSnapshotError(
                "snapshot entry could not be checked safely"
            ) from exc
    raise WorkspaceSnapshotError("snapshot path spelling is not exact")


def _open_snapshot_parent(
    snapshot: WorkspaceSnapshot, parts: tuple[str, ...]
) -> tuple[int, str, int]:
    descriptor, root_device = _open_snapshot_directory(snapshot, parts[:-1])
    return descriptor, parts[-1], root_device


def _verify_snapshot_mount(
    snapshot: WorkspaceSnapshot, descriptor: int, expected_device: int
) -> None:
    if os.fstat(descriptor).st_dev != expected_device:
        raise WorkspaceSnapshotError("snapshot path crossed a filesystem volume")
    if sys.platform == "darwin" and snapshot.snapshot_mount_point is None:
        raise WorkspaceSnapshotError("snapshot mount identity is unavailable")
    if snapshot.snapshot_mount_point is not None:
        _verify_mountpoint(snapshot.snapshot_mount_point, descriptor)


def _verify_snapshot_file(
    snapshot: WorkspaceSnapshot,
    descriptor: int,
    expected: os.stat_result,
    opened: os.stat_result,
    expected_device: int,
) -> None:
    if (
        not stat.S_ISREG(opened.st_mode)
        or opened.st_nlink != 1
        or not _same_entry(expected, opened)
    ):
        raise WorkspaceSnapshotError("snapshot file changed while opening")
    _verify_snapshot_mount(snapshot, descriptor, expected_device)
