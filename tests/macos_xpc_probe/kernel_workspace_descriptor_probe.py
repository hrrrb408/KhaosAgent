from __future__ import annotations

import errno
import os
from pathlib import Path
import stat
import sys

from khaos.kernel.macos_disk_image import mounted_apfs_volume
from khaos.kernel.workspace_snapshot import (
    WorkspaceSnapshotError,
    _apfs_case_sensitivity,
    _volume_mountpoint,
)

workspace_root_fd = int(sys.argv[2])


def read_relative(relative_path: str) -> str:
    descriptor = os.open(relative_path, os.O_RDONLY, dir_fd=workspace_root_fd)
    try:
        return os.read(descriptor, 4096).decode("utf-8")
    finally:
        os.close(descriptor)


if not stat.S_ISDIR(os.fstat(workspace_root_fd).st_mode):
    raise SystemExit("inherited workspace descriptor is not a directory")
if read_relative("input.txt") != "xpc-input":
    raise SystemExit("inherited workspace descriptor read the wrong bytes")
marker = os.open(
    "descriptor-probe-started.txt",
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
    0o600,
    dir_fd=workspace_root_fd,
)
try:
    os.write(marker, b"started")
finally:
    os.close(marker)
print("xpc-kernel-inherited-root=read:xpc-input")

for relative_path, label in (
    ("../sibling-secret.txt", "xpc-kernel-parent-escape"),
    ("sibling-link", "xpc-kernel-symlink-escape"),
    ("sibling-hardlink", "xpc-kernel-hardlink-alias"),
):
    try:
        value = read_relative(relative_path)
    except OSError as error:
        if error.errno not in (errno.EPERM, errno.EACCES, errno.ENOENT):
            raise
        print(f"{label}=denied:{error.errno}")
    else:
        print(f"{label}=allowed:{value}")

if _volume_mountpoint(workspace_root_fd) is None:
    raise SystemExit("xpc-kernel source mount could not be verified")
try:
    case_sensitive = _apfs_case_sensitivity(workspace_root_fd)
except WorkspaceSnapshotError as error:
    print(f"xpc-kernel-source-volume=unavailable:{error}")
else:
    print(f"xpc-kernel-source-volume=inspected:{case_sensitive}")
    try:
        with mounted_apfs_volume(
            Path(os.environ["TMPDIR"]),
            size_bytes=128_000_000,
            case_sensitive=case_sensitive,
        ) as snapshot_mount:
            (snapshot_mount / "probe.txt").write_text("snapshot", encoding="utf-8")
            print("xpc-kernel-apfs-snapshot=mounted")
    except WorkspaceSnapshotError as error:
        print(f"xpc-kernel-apfs-snapshot=unavailable:{error}")
