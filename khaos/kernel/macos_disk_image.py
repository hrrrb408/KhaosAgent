"""Create bounded, private APFS work volumes for macOS snapshots."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import plistlib
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator

from .workspace_snapshot import (
    _MAX_SNAPSHOT_STORAGE_BYTES,
    _MIN_SNAPSHOT_STORAGE_BYTES,
    _SNAPSHOT_IMAGE_OPERATION_MARKER as _IMAGE_OPERATION_MARKER,
    WorkspaceSnapshotCancelled,
    WorkspaceSnapshotError,
    _check_snapshot_cancellation,
)


_HDIUTIL = "/usr/bin/hdiutil"
_DISKUTIL = "/usr/sbin/diskutil"
_DEVICE_PATTERN = re.compile(r"/dev/disk[0-9]+(?:s[0-9]+)?\Z")
_WHOLE_DEVICE_PATTERN = re.compile(r"/dev/disk[0-9]+\Z")
_IMAGE_OPERATION_TIMEOUT_SECONDS = 60
_IMAGE_ATTACH_SETTLE_TIMEOUT_SECONDS = 5
_IMAGE_RECONCILIATION_TIMEOUT_SECONDS = 15
_IMAGE_CLEANUP_TOOL_TIMEOUT_SECONDS = 10
_TOOL_CANCELLATION_POLL_SECONDS = 0.02
_IMAGE_INFO_POLL_SECONDS = 0.05
_IMAGE_SECTOR_BYTES = 512


@contextmanager
def mounted_apfs_volume(
    parent: Path,
    *,
    size_bytes: int,
    case_sensitive: bool,
    owner_pid: int | None = None,
    directory_name: str | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> Iterator[Path]:
    """Yield a fixed-capacity APFS image below a private temporary directory.

    ``directory_name`` lets packaged integration tests exercise a Broker-shaped
    lease path while reusing this source-tree-only image backend.
    """
    if sys.platform != "darwin":
        raise WorkspaceSnapshotError("bounded APFS snapshots require macOS")
    if type(size_bytes) is not int or not (
        _MIN_SNAPSHOT_STORAGE_BYTES
        <= size_bytes
        <= _MAX_SNAPSHOT_STORAGE_BYTES
    ):
        raise ValueError("APFS image size is outside the supported range")
    if type(case_sensitive) is not bool:
        raise ValueError("APFS image case sensitivity must be explicit")
    if owner_pid is not None and (type(owner_pid) is not int or owner_pid < 1):
        raise ValueError("APFS image owner PID is invalid")
    _check_snapshot_cancellation(cancel_requested)

    parent = parent.resolve(strict=True)
    prefix = "khaos-snapshot-"
    if owner_pid is not None:
        prefix += f"{owner_pid}-"
    if directory_name is None:
        temporary = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
    else:
        if (
            not isinstance(directory_name, str)
            or not directory_name
            or Path(directory_name).name != directory_name
            or directory_name in {".", ".."}
        ):
            raise ValueError("APFS image directory name is invalid")
        temporary = parent / directory_name
        temporary.mkdir(mode=0o700)
        os.chmod(temporary, 0o700)
    image = temporary / "workspace.sparsebundle"
    mount_point = temporary / "volume"
    operation_marker = temporary / _IMAGE_OPERATION_MARKER
    attached_device: str | None = None
    image_operation_started = False
    operation_may_continue = False
    operation_cancelled = False
    cleanup_error: BaseException | None = None

    try:
        mount_point.mkdir(mode=0o700)
        mount_point = mount_point.resolve(strict=True)
        sectors = size_bytes // _IMAGE_SECTOR_BYTES
        expected_filesystem = "Case-sensitive APFS" if case_sensitive else "APFS"
        expected_visible_name = (
            "APFS (Case-sensitive)" if case_sensitive else "APFS"
        )
        _check_snapshot_cancellation(cancel_requested)
        operation_marker.touch(mode=0o600, exist_ok=False)
        image_operation_started = True
        try:
            _run_tool(
                _HDIUTIL,
                (
                    "create",
                    "-type",
                    "SPARSEBUNDLE",
                    "-sectors",
                    str(sectors),
                    "-layout",
                    "NONE",
                    "-fs",
                    expected_filesystem,
                    "-volname",
                    "KhaosWork",
                    "-nospotlight",
                    str(image),
                ),
                cancel_requested=cancel_requested,
            )
        except BaseException as exc:
            operation_may_continue = _operation_may_continue_after_exit(exc)
            raise

        try:
            entities, attached_device = _attach_image(
                image,
                mount_point=mount_point,
                cancel_requested=cancel_requested,
            )
        except BaseException as exc:
            operation_may_continue = _operation_may_continue_after_exit(exc)
            raise
        _validate_mounted_apfs_volume(
            image,
            mount_point,
            size_bytes=size_bytes,
            case_sensitive=case_sensitive,
            expected_image_device=attached_device,
            attach_entities=entities,
            cancel_requested=cancel_requested,
        )
        _check_snapshot_cancellation(cancel_requested)
        yield mount_point
    except WorkspaceSnapshotCancelled:
        operation_cancelled = True
        raise
    finally:
        if image_operation_started:
            try:
                image_cleaned = _reconcile_pending_image_operation(
                    image,
                    mount_point,
                    may_still_be_running=operation_may_continue,
                )
                if not image_cleaned:
                    cleanup_error = WorkspaceSnapshotError(
                        "APFS image operation may still be active"
                    )
            except BaseException as exc:
                cleanup_error = exc
        if cleanup_error is None:
            try:
                operation_marker.unlink(missing_ok=True)
                shutil.rmtree(temporary, ignore_errors=False)
            except BaseException as exc:
                cleanup_error = exc
        if cleanup_error is not None:
            if operation_cancelled:
                raise WorkspaceSnapshotCancelled(
                    "workspace cancellation left APFS cleanup unresolved"
                ) from cleanup_error
            raise WorkspaceSnapshotError(
                "APFS work image could not be safely removed"
            ) from cleanup_error


def _validate_mounted_apfs_volume(
    image: Path,
    mount_point: Path,
    *,
    size_bytes: int,
    case_sensitive: bool,
    expected_image_device: str | None = None,
    attach_entities: list[dict[str, object]] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> None:
    image_info = _attached_image_info(image, cancel_requested=cancel_requested)
    if image_info is None:
        raise WorkspaceSnapshotError("APFS work image is not attached")
    image_entities = _validated_entities(image_info.get("system-entities"))
    image_device = _whole_image_device(image_entities)
    image_capacity = _image_capacity(image_info)
    expected_capacity = (size_bytes // _IMAGE_SECTOR_BYTES) * _IMAGE_SECTOR_BYTES
    if (
        image_device != expected_image_device
        and expected_image_device is not None
    ) or image_capacity != expected_capacity or image_capacity > size_bytes:
        raise WorkspaceSnapshotError("APFS work image capacity is invalid")

    volumes = attach_entities if attach_entities is not None else image_entities
    matching_volumes = [
        entity for entity in volumes if entity.get("mount-point") == str(mount_point)
    ]
    if len(matching_volumes) != 1:
        raise WorkspaceSnapshotError("APFS work volume did not mount as requested")
    volume = matching_volumes[0]
    volume_device = volume.get("dev-entry")
    if (
        volume.get("volume-kind") != "apfs"
        or not isinstance(volume_device, str)
        or _DEVICE_PATTERN.fullmatch(volume_device) is None
        or not mount_point.is_mount()
    ):
        raise WorkspaceSnapshotError("APFS work volume identity is invalid")

    expected_filesystem = "Case-sensitive APFS" if case_sensitive else "APFS"
    expected_visible_name = "APFS (Case-sensitive)" if case_sensitive else "APFS"
    info = _run_tool(
        _DISKUTIL,
        ("info", "-plist", str(mount_point)),
        cancel_requested=cancel_requested,
    )
    try:
        volume_info = plistlib.loads(info.stdout)
    except plistlib.InvalidFileException as exc:
        raise WorkspaceSnapshotError("APFS work volume info is malformed") from exc
    if (
        not isinstance(volume_info, dict)
        or volume_info.get("MountPoint") != str(mount_point)
        or volume_info.get("FilesystemName") != expected_filesystem
        or volume_info.get("FilesystemUserVisibleName") != expected_visible_name
        or volume_info.get("DeviceIdentifier") != volume_device.removeprefix("/dev/")
        or type(volume_info.get("TotalSize")) is not int
        or not 0 < volume_info["TotalSize"] <= image_capacity
    ):
        raise WorkspaceSnapshotError("APFS work volume capacity is invalid")


def cleanup_abandoned_apfs_volumes(owner_pid: int) -> None:
    """Detach and remove APFS work images left by a dead Kernel worker."""
    if sys.platform != "darwin":
        raise WorkspaceSnapshotError("bounded APFS snapshots require macOS")
    if type(owner_pid) is not int or owner_pid < 1:
        raise ValueError("APFS image owner PID is invalid")

    temporary_parent = Path(tempfile.gettempdir()).resolve(strict=True)
    prefix = f"khaos-snapshot-{owner_pid}-"
    pending_roots: set[Path] = set()
    for temporary in temporary_parent.iterdir():
        if not temporary.name.startswith(prefix):
            continue
        _validate_worker_temporary(temporary, temporary_parent, prefix)
        if not _has_image_operation_marker(temporary):
            continue
        image_cleaned = _reconcile_pending_image_operation(
            temporary / "workspace.sparsebundle",
            temporary / "volume",
            may_still_be_running=True,
        )
        if image_cleaned:
            _remove_worker_temporary(temporary, temporary_parent, prefix)
        else:
            pending_roots.add(temporary)

    attached = _attached_worker_images(
        temporary_parent, prefix, exclude=pending_roots
    )
    for temporary, image, device in attached:
        _run_tool(_HDIUTIL, ("detach", device))
        mount_point = temporary / "volume"
        if _settled_attached_image_info(image, mount_point) is not None:
            raise WorkspaceSnapshotError("abandoned APFS work image remains attached")
        if mount_point.is_mount():
            raise WorkspaceSnapshotError("abandoned APFS work volume remains mounted")
        _remove_worker_temporary(temporary, temporary_parent, prefix)

    attached_roots = {temporary for temporary, _, _ in attached}
    for temporary in temporary_parent.iterdir():
        if (
            temporary in attached_roots
            or temporary in pending_roots
            or not temporary.name.startswith(prefix)
        ):
            continue
        _remove_worker_temporary(temporary, temporary_parent, prefix)


def _attached_worker_images(
    temporary_parent: Path,
    prefix: str,
    *,
    exclude: set[Path] | None = None,
) -> list[tuple[Path, Path, str]]:
    result = _run_tool(_HDIUTIL, ("info", "-plist"))
    try:
        response = plistlib.loads(result.stdout)
    except plistlib.InvalidFileException as exc:
        raise WorkspaceSnapshotError("APFS image inventory is malformed") from exc
    if not isinstance(response, dict) or not isinstance(response.get("images"), list):
        raise WorkspaceSnapshotError("APFS image inventory is invalid")

    attached: list[tuple[Path, Path, str]] = []
    for entry in response["images"]:
        if not isinstance(entry, dict):
            raise WorkspaceSnapshotError("APFS image inventory is invalid")
        image_path = entry.get("image-path")
        if not isinstance(image_path, str) or not image_path.endswith(
            "/workspace.sparsebundle"
        ):
            continue
        image = Path(image_path)
        temporary = image.parent
        try:
            if (
                temporary.parent.resolve(strict=True) != temporary_parent
                or not temporary.name.startswith(prefix)
                or (exclude is not None and temporary in exclude)
                or image.resolve(strict=True) != image
            ):
                continue
        except OSError:
            continue
        mount_point = temporary / "volume"
        settled = _settled_attached_image_info(image, mount_point)
        if settled is None:
            continue
        entities = _validated_entities(settled.get("system-entities"))
        attached.append((temporary, image, _whole_image_device(entities)))
    return attached


def _remove_worker_temporary(
    temporary: Path,
    temporary_parent: Path,
    prefix: str,
) -> None:
    _validate_worker_temporary(temporary, temporary_parent, prefix)
    shutil.rmtree(temporary)


def _validate_worker_temporary(
    temporary: Path,
    temporary_parent: Path,
    prefix: str,
) -> None:
    if (
        temporary.parent.resolve(strict=True) != temporary_parent
        or not temporary.name.startswith(prefix)
        or temporary.is_symlink()
    ):
        raise WorkspaceSnapshotError("abandoned APFS work path is invalid")
    info = temporary.stat(follow_symlinks=False)
    if info.st_uid != os.getuid() or not temporary.is_dir():
        raise WorkspaceSnapshotError("abandoned APFS work path is not private")


def _has_image_operation_marker(temporary: Path) -> bool:
    try:
        info = (temporary / _IMAGE_OPERATION_MARKER).lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise WorkspaceSnapshotError("APFS image operation marker is invalid")
    return True


def _attach_image(
    image: Path,
    *,
    mount_point: Path,
    cancel_requested: Callable[[], bool] | None = None,
) -> tuple[list[dict[str, object]], str]:
    result = _run_tool(
        _HDIUTIL,
        (
            "attach",
            "-plist",
            "-nobrowse",
            "-mountpoint",
            str(mount_point),
            str(image),
        ),
        cancel_requested=cancel_requested,
    )
    try:
        response = plistlib.loads(result.stdout)
    except plistlib.InvalidFileException as exc:
        raise WorkspaceSnapshotError("APFS image attachment info is malformed") from exc
    if not isinstance(response, dict):
        raise WorkspaceSnapshotError("APFS image attachment info is invalid")
    entities = _validated_entities(response.get("system-entities"))
    return entities, _whole_image_device(entities)


def _attached_image_info(
    image: Path,
    *,
    cancel_requested: Callable[[], bool] | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, object] | None:
    """Find one attached image by canonical path in hdiutil's system inventory."""
    result = _run_tool(
        _HDIUTIL,
        ("info", "-plist"),
        cancel_requested=cancel_requested,
        timeout_seconds=timeout_seconds,
    )
    try:
        response = plistlib.loads(result.stdout)
    except plistlib.InvalidFileException as exc:
        raise WorkspaceSnapshotError("APFS image inventory is malformed") from exc
    if not isinstance(response, dict) or not isinstance(response.get("images"), list):
        raise WorkspaceSnapshotError("APFS image inventory is invalid")

    expected_path = image.resolve(strict=False)
    matching: list[dict[str, object]] = []
    for entry in response["images"]:
        if not isinstance(entry, dict):
            raise WorkspaceSnapshotError("APFS image inventory is invalid")
        image_path = entry.get("image-path")
        if not isinstance(image_path, str):
            continue
        try:
            resolved_path = Path(image_path).resolve(strict=False)
        except OSError:
            continue
        if resolved_path == expected_path:
            matching.append(entry)
    if len(matching) > 1:
        raise WorkspaceSnapshotError("APFS work image identity is ambiguous")
    return matching[0] if matching else None


def _reconcile_pending_image_operation(
    image: Path,
    mount_point: Path,
    *,
    may_still_be_running: bool,
) -> bool:
    """Reconcile one pending image operation against the OS inventory."""
    deadline = time.monotonic() + _IMAGE_RECONCILIATION_TIMEOUT_SECONDS
    detached_device = False
    while True:
        image_info = _attached_image_info(
            image, timeout_seconds=_IMAGE_CLEANUP_TOOL_TIMEOUT_SECONDS
        )
        if image_info is None:
            if mount_point.is_mount():
                raise WorkspaceSnapshotError(
                    "APFS work volume is mounted without an image record"
                )
            if detached_device or not may_still_be_running:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(_IMAGE_INFO_POLL_SECONDS, remaining))
            continue

        entities = image_info.get("system-entities")
        if entities == []:
            if mount_point.is_mount():
                raise WorkspaceSnapshotError(
                    "APFS work volume is mounted without a device identity"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(_IMAGE_INFO_POLL_SECONDS, remaining))
            continue

        entities = _validated_entities(entities)
        for entity in entities:
            entity_mount = entity.get("mount-point")
            if entity_mount is not None and entity_mount != str(mount_point):
                raise WorkspaceSnapshotError(
                    "APFS work image has an unexpected mount point"
                )
        if mount_point.is_mount() and not any(
            entity.get("mount-point") == str(mount_point) for entity in entities
        ):
            raise WorkspaceSnapshotError(
                "APFS work volume mount identity is invalid"
            )

        device = _whole_image_device(entities)
        try:
            _run_tool(
                _HDIUTIL,
                ("detach", device),
                timeout_seconds=_IMAGE_CLEANUP_TOOL_TIMEOUT_SECONDS,
            )
        except WorkspaceSnapshotError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(_IMAGE_INFO_POLL_SECONDS, remaining))
            continue
        detached_device = True
        while True:
            image_info = _attached_image_info(
                image, timeout_seconds=_IMAGE_CLEANUP_TOOL_TIMEOUT_SECONDS
            )
            if image_info is None and not mount_point.is_mount():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(_IMAGE_INFO_POLL_SECONDS, remaining))


def _operation_may_continue_after_exit(error: BaseException) -> bool:
    if isinstance(error, WorkspaceSnapshotCancelled):
        return True
    cause = error.__cause__
    while cause is not None:
        if isinstance(cause, subprocess.TimeoutExpired):
            return True
        cause = cause.__cause__
    return False


def _settled_attached_image_info(
    image: Path,
    mount_point: Path,
) -> dict[str, object] | None:
    """Wait for an attach or detach to finish changing the OS device inventory."""
    deadline = time.monotonic() + _IMAGE_ATTACH_SETTLE_TIMEOUT_SECONDS
    while True:
        image_info = _attached_image_info(image)
        if image_info is None:
            if mount_point.is_mount():
                raise WorkspaceSnapshotError(
                    "APFS work volume is mounted without an image record"
                )
            return None
        entities = image_info.get("system-entities")
        if entities == []:
            has_mountpoint = False
        else:
            entities = _validated_entities(entities)
            has_mountpoint = any(
                entity.get("mount-point") == str(mount_point)
                for entity in entities
            )
        if not has_mountpoint:
            if mount_point.is_mount():
                raise WorkspaceSnapshotError(
                    "APFS work volume mount identity is invalid"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WorkspaceSnapshotError(
                    "APFS image attachment did not settle"
                )
            time.sleep(min(_IMAGE_INFO_POLL_SECONDS, remaining))
            continue
        return image_info


def _image_capacity(image_info: dict[str, object]) -> int:
    """Return the image's OS-reported virtual capacity in bytes."""
    sectors = image_info.get("blockcount")
    sector_bytes = image_info.get("blocksize")
    if (
        image_info.get("image-type") != "sparse bundle disk image"
        or image_info.get("writeable") is not True
        or type(sectors) is not int
        or sectors < 1
        or type(sector_bytes) is not int
        or sector_bytes != _IMAGE_SECTOR_BYTES
    ):
        raise WorkspaceSnapshotError("APFS work image capacity metadata is invalid")
    return sectors * sector_bytes


def _validated_entities(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value or any(
        not isinstance(entity, dict) for entity in value
    ):
        raise WorkspaceSnapshotError("APFS image attachment info is invalid")
    return value


def _whole_image_device(entities: list[dict[str, object]]) -> str:
    devices = {
        device
        for entity in entities
        if entity.get("content-hint") in (None, "")
        and isinstance((device := entity.get("dev-entry")), str)
        and _WHOLE_DEVICE_PATTERN.fullmatch(device) is not None
    }
    if len(devices) != 1:
        raise WorkspaceSnapshotError("APFS image device identity is invalid")
    return next(iter(devices))


def _run_tool(
    executable: str,
    arguments: tuple[str, ...],
    *,
    cancel_requested: Callable[[], bool] | None = None,
    timeout_seconds: float | None = None,
) -> subprocess.CompletedProcess[bytes]:
    command = (executable, *arguments)
    operation_timeout = (
        _IMAGE_OPERATION_TIMEOUT_SECONDS
        if timeout_seconds is None
        else timeout_seconds
    )
    process: subprocess.Popen[bytes] | None = None
    try:
        _check_snapshot_cancellation(cancel_requested)
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "LC_ALL": "C",
            },
            close_fds=True,
            start_new_session=True,
        )
        deadline = time.monotonic() + operation_timeout
        while True:
            _check_snapshot_cancellation(cancel_requested)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(
                    command, operation_timeout
                )
            poll_seconds = (
                min(_TOOL_CANCELLATION_POLL_SECONDS, remaining)
                if cancel_requested is not None
                else remaining
            )
            try:
                stdout, stderr = process.communicate(timeout=poll_seconds)
                break
            except subprocess.TimeoutExpired:
                if cancel_requested is None:
                    raise
        result = subprocess.CompletedProcess(
            command, process.returncode, stdout, stderr
        )
    except (OSError, subprocess.SubprocessError) as exc:
        if process is not None:
            _stop_tool_process_group(process)
        raise WorkspaceSnapshotError(
            "APFS image operation is unavailable"
        ) from exc
    except BaseException:
        if process is not None:
            _stop_tool_process_group(process)
        raise
    if result.returncode != 0:
        operation = arguments[0] if arguments else "unknown"
        raise WorkspaceSnapshotError(
            f"APFS image operation failed: {Path(executable).name} "
            f"{operation} exited {result.returncode}"
        )
    return result


def _stop_tool_process_group(process: subprocess.Popen[bytes]) -> None:
    """Stop the fixed OS tool and reap descendants holding its pipes."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError as exc:
        try:
            process.kill()
            process.communicate(timeout=5)
        except (OSError, subprocess.SubprocessError) as cleanup_exc:
            raise WorkspaceSnapshotError(
                "APFS image tool process could not be stopped"
            ) from cleanup_exc
        raise WorkspaceSnapshotError(
            "APFS image tool process group could not be stopped"
        ) from exc
    try:
        process.communicate(timeout=1)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as exc:
        try:
            process.kill()
            process.communicate(timeout=5)
        except (OSError, subprocess.SubprocessError) as cleanup_exc:
            raise WorkspaceSnapshotError(
                "APFS image tool process could not be stopped"
            ) from cleanup_exc
        raise WorkspaceSnapshotError(
            "APFS image tool process group could not be stopped"
        ) from exc
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired as exc:
        raise WorkspaceSnapshotError(
            "APFS image tool process group did not exit"
        ) from exc
