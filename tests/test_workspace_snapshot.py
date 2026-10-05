from __future__ import annotations

import os
import hashlib
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import khaos.kernel.workspace_snapshot as workspace_snapshot_module
from khaos.kernel.macos_disk_image import (
    _HDIUTIL,
    _IMAGE_OPERATION_MARKER,
    _attach_image,
    _attached_image_info,
    _reconcile_pending_image_operation,
    _run_tool,
    cleanup_abandoned_apfs_volumes,
    mounted_apfs_volume,
)
from khaos.kernel.workspace_snapshot import (
    MAX_WORKSPACE_READ_BYTES,
    WorkspaceReadLimitError,
    WorkspaceReadScope,
    WorkspacePathIOError,
    WorkspaceSnapshotCancelled,
    WorkspaceSnapshotError,
    WorkspaceWriteScope,
    _apfs_case_sensitivity,
    _path_is_within,
    _validate_component,
    list_snapshot_directory,
    read_snapshot_file,
    write_snapshot_file,
    workspace_snapshot,
)


class WorkspaceSnapshotTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "darwin", "requires macOS descriptor paths")
    def test_exact_directory_grant_survives_denied_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            path = Path(value).resolve(strict=True)
            real_open = os.open
            denied_ancestor = path.parts[1]

            def deny_ancestor(name, flags, *, dir_fd=None):
                if name == denied_ancestor and dir_fd is not None:
                    raise PermissionError(1, "App Sandbox denied ancestor")
                if dir_fd is None:
                    return real_open(name, flags)
                return real_open(name, flags, dir_fd=dir_fd)

            with patch("khaos.kernel.workspace_snapshot.os.open", side_effect=deny_ancestor):
                descriptor = workspace_snapshot_module._open_absolute_directory(path)
            try:
                self.assertEqual(
                    workspace_snapshot_module._path_for_directory_descriptor(descriptor),
                    path,
                )
            finally:
                os.close(descriptor)

            with (
                patch("khaos.kernel.workspace_snapshot.os.open", side_effect=deny_ancestor),
                patch(
                    "khaos.kernel.workspace_snapshot._path_for_directory_descriptor",
                    return_value=Path("/different"),
                ),
                self.assertRaisesRegex(
                    WorkspaceSnapshotError, "resolved outside its path"
                ),
            ):
                workspace_snapshot_module._open_absolute_directory(path)

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS path diagnostics")
    def test_path_ancestry_io_error_has_only_a_fixed_stage(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            path = Path(value).resolve(strict=True)
            with patch(
                "khaos.kernel.workspace_snapshot._get_getattrlist",
                return_value=lambda *_arguments: -1,
            ):
                with self.assertRaises(WorkspacePathIOError) as raised:
                    _path_is_within(path, path.parent)

        self.assertEqual(raised.exception.stage, "path_mountpoint")

    def test_path_component_rejects_non_utf8_filesystem_names(self) -> None:
        component = os.fsdecode(b"invalid-\xff")
        with self.assertRaisesRegex(
            WorkspaceSnapshotError, "non-UTF-8 path component"
        ):
            _validate_component(component)

    def test_snapshot_name_is_one_valid_directory_component(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "source"
            source.mkdir()
            (source / "input.txt").write_text("content", encoding="utf-8")

            with workspace_snapshot(source, snapshot_name="seatbelt-probe") as snapshot:
                self.assertEqual(snapshot.path.name, "seatbelt-probe")
                self.assertEqual(
                    (snapshot.path / "input.txt").read_text(encoding="utf-8"),
                    "content",
                )

            for invalid_name in ("", ".", "..", "nested/path", "unsafe\x00name"):
                with self.subTest(name=invalid_name):
                    with self.assertRaises(WorkspaceSnapshotError):
                        with workspace_snapshot(source, snapshot_name=invalid_name):
                            self.fail("invalid snapshot names must be rejected")

    def test_workspace_read_scope_is_bounded_and_rejects_root_or_escape(self) -> None:
        scope = WorkspaceReadScope.from_paths(("src/main.py", "src"))
        self.assertEqual(scope.as_paths(), ("src",))
        self.assertTrue(scope.permits_read("src/main.py", max_depth=64))
        self.assertTrue(scope.permits_read("src/nested/file.py", max_depth=64))
        self.assertFalse(scope.permits_read("docs/secret.md", max_depth=64))

        invalid_scopes = (
            ("",),
            ("../secret",),
            ("/etc/passwd",),
            ("src//main.py",),
            ("src", "src"),
            tuple(f"file-{index}" for index in range(129)),
            ("x" * 4096,),
        )
        for invalid_scope in invalid_scopes:
            with self.subTest(scope=invalid_scope[:2]):
                with self.assertRaises(WorkspaceSnapshotError):
                    WorkspaceReadScope.from_paths(invalid_scope)

    def test_workspace_write_scope_is_exact_and_rejects_invalid_paths(self) -> None:
        scope = WorkspaceWriteScope.from_paths(("src/main.py", "src/other.py"))
        self.assertFalse(
            WorkspaceWriteScope.from_paths().permits_write(
                "src/main.py", max_depth=64
            )
        )
        self.assertEqual(scope.as_paths(), ("src/main.py", "src/other.py"))
        self.assertTrue(scope.permits_write("src/main.py", max_depth=64))
        self.assertFalse(scope.permits_write("src/new.py", max_depth=64))
        self.assertFalse(scope.permits_write("src", max_depth=64))
        self.assertFalse(scope.permits_write("../outside", max_depth=64))

        for invalid_scope in (
            ("",),
            ("../secret",),
            ("/etc/passwd",),
            ("src//main.py",),
            ("src/main.py", "src/main.py"),
            tuple(f"file-{index}" for index in range(129)),
            ("x" * 4096,),
        ):
            with self.subTest(scope=invalid_scope[:2]):
                with self.assertRaises(WorkspaceSnapshotError):
                    WorkspaceWriteScope.from_paths(invalid_scope)

    def test_snapshot_write_replaces_only_safe_regular_files(self) -> None:
        from khaos.ipc import MAX_WORKSPACE_WRITE_BYTES

        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            (source / "nested").mkdir(parents=True)
            existing = source / "nested" / "existing.txt"
            existing.write_bytes(b"before")
            existing.chmod(0o640)
            outside = root / "outside.txt"
            outside.write_bytes(b"outside-canary")
            (source / "link.txt").symlink_to(outside)

            with workspace_snapshot(source) as snapshot:
                content = b"replacement"
                digest = write_snapshot_file(snapshot, "nested/existing.txt", content)
                self.assertEqual(digest, hashlib.sha256(content).hexdigest())
                self.assertEqual(
                    (snapshot.path / "nested" / "existing.txt").read_bytes(), content
                )
                self.assertEqual(
                    (snapshot.path / "nested" / "existing.txt").stat().st_mode & 0o777,
                    0o640,
                )

                new_content = b"new file"
                write_snapshot_file(snapshot, "nested/new.txt", new_content)
                new_file = snapshot.path / "nested" / "new.txt"
                self.assertEqual(new_file.read_bytes(), new_content)
                self.assertEqual(new_file.stat().st_mode & 0o777, 0o600)

                os.link(new_file, snapshot.path / "hardlink.txt")
                for unsafe_path in ("../outside.txt", "link.txt", "hardlink.txt"):
                    with self.subTest(path=unsafe_path):
                        with self.assertRaises(WorkspaceSnapshotError):
                            write_snapshot_file(snapshot, unsafe_path, b"blocked")
                with self.assertRaises(WorkspaceSnapshotError):
                    write_snapshot_file(
                        snapshot,
                        "nested/large.txt",
                        b"x" * (MAX_WORKSPACE_WRITE_BYTES + 1),
                    )
                self.assertEqual(outside.read_bytes(), b"outside-canary")

    def test_snapshot_read_and_list_are_bounded_and_do_not_follow_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            outside = root / "outside"
            outside.mkdir()
            (outside / "secret.txt").write_text("outside", encoding="utf-8")
            (source / "payload.bin").write_bytes(b"payload")
            (source / "large.bin").write_bytes(b"x" * (MAX_WORKSPACE_READ_BYTES + 1))
            (source / "link.txt").symlink_to(outside / "secret.txt")
            (source / "escape").symlink_to(outside, target_is_directory=True)
            many = source / "many"
            many.mkdir()
            for index in range(129):
                (many / f"entry-{index:03}.txt").write_text("x", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                self.assertEqual(read_snapshot_file(snapshot, "payload.bin"), b"payload")
                root_entries = list_snapshot_directory(snapshot)
                by_name = {entry.name: entry for entry in root_entries}
                self.assertEqual(by_name["payload.bin"].kind, "file")
                self.assertEqual(by_name["link.txt"].kind, "symlink")
                self.assertIsNone(by_name["link.txt"].size)

                for unsafe_path in (
                    "../outside/secret.txt",
                    str(outside / "secret.txt"),
                    "link.txt",
                    "escape/secret.txt",
                ):
                    with self.subTest(path=unsafe_path):
                        with self.assertRaises(WorkspaceSnapshotError):
                            read_snapshot_file(snapshot, unsafe_path)

                with self.assertRaises(WorkspaceReadLimitError):
                    read_snapshot_file(snapshot, "large.bin")
                with self.assertRaises(WorkspaceReadLimitError):
                    list_snapshot_directory(snapshot, "many")
                with self.assertRaises(WorkspaceSnapshotError):
                    list_snapshot_directory(snapshot, "escape")

                os.link(snapshot.path / "payload.bin", snapshot.path / "hardlink.bin")
                with self.assertRaises(WorkspaceSnapshotError):
                    read_snapshot_file(snapshot, "hardlink.bin")

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS mount metadata")
    def test_rejects_snapshot_backing_directory_inside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            backing_parent = source / "temporary"
            backing_parent.mkdir()

            with patch(
                "khaos.kernel.workspace_snapshot.tempfile.gettempdir",
                return_value=str(backing_parent),
            ):
                with self.assertRaisesRegex(
                    WorkspaceSnapshotError, "inside the workspace"
                ):
                    with workspace_snapshot(source):
                        self.fail("snapshot backing storage entered the workspace")

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS firmlinks")
    def test_resolves_firmlink_aliases_when_checking_workspace_ancestry(self) -> None:
        workspace_root = Path("/System/Volumes/Data")
        system_temporary = Path(tempfile.gettempdir()).resolve(strict=True)
        temporary_alias = workspace_root / system_temporary.relative_to("/")
        self.assertTrue(workspace_root.is_dir())
        self.assertTrue(os.path.samefile(system_temporary, temporary_alias))
        self.assertTrue(_path_is_within(Path.cwd(), workspace_root))
        self.assertTrue(_path_is_within(system_temporary, workspace_root))
        self.assertTrue(_path_is_within(system_temporary, temporary_alias))

    @unittest.skipUnless(sys.platform == "darwin", "requires APFS images")
    def test_case_sensitive_source_keeps_case_sensitive_snapshot_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            with mounted_apfs_volume(
                Path(value), size_bytes=256_000_000, case_sensitive=True
            ) as source_volume:
                source = source_volume / "workspace"
                source.mkdir()
                (source / "CaseName").write_text("upper", encoding="utf-8")
                (source / "casename").write_text("lower", encoding="utf-8")

                with workspace_snapshot(
                    source, max_storage_bytes=128_000_000
                ) as snapshot:
                    self.assertEqual(
                        (snapshot.path / "CaseName").read_text(encoding="utf-8"),
                        "upper",
                    )
                    self.assertEqual(
                        (snapshot.path / "casename").read_text(encoding="utf-8"),
                        "lower",
                    )
                    self.assertNotEqual(
                        snapshot.source_mount_point,
                        snapshot.snapshot_mount_point,
                    )

    @unittest.skipUnless(
        sys.platform == "darwin" and Path(_HDIUTIL).is_file(),
        "requires the real macOS APFS image tools",
    )
    def test_apfs_descriptor_reports_case_sensitivity_from_volume_capabilities(self) -> None:
        for case_sensitive in (False, True):
            with self.subTest(case_sensitive=case_sensitive):
                with tempfile.TemporaryDirectory() as value:
                    root = Path(value).resolve(strict=True)
                    with mounted_apfs_volume(
                        root,
                        size_bytes=128_000_000,
                        case_sensitive=case_sensitive,
                    ) as mount_point:
                        descriptor = os.open(
                            mount_point,
                            os.O_RDONLY | os.O_DIRECTORY,
                        )
                        try:
                            self.assertEqual(
                                _apfs_case_sensitivity(descriptor),
                                case_sensitive,
                            )
                        finally:
                            os.close(descriptor)

    @unittest.skipUnless(
        sys.platform == "darwin" and Path(_HDIUTIL).is_file(),
        "requires a real macOS HFS+ image",
    )
    def test_hfs_volume_is_rejected_by_apfs_descriptor_check(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve(strict=True)
            image = root / "non-apfs.dmg"
            mount_point = root / "volume"
            mount_point.mkdir(mode=0o700)
            image_created = False
            try:
                _run_tool(
                    _HDIUTIL,
                    (
                        "create",
                        "-size",
                        "128m",
                        "-layout",
                        "NONE",
                        "-fs",
                        "HFS+",
                        "-volname",
                        "KhaosHFSProbe",
                        str(image),
                    ),
                )
                image_created = True
                _attach_image(image, mount_point=mount_point)
                self.assertTrue(mount_point.is_mount())
                descriptor = os.open(
                    mount_point,
                    os.O_RDONLY | os.O_DIRECTORY,
                )
                try:
                    with self.assertRaises(WorkspaceSnapshotError):
                        _apfs_case_sensitivity(descriptor)
                finally:
                    os.close(descriptor)
            finally:
                if image_created:
                    self.assertTrue(
                        _reconcile_pending_image_operation(
                            image,
                            mount_point,
                            may_still_be_running=False,
                        ),
                        "HFS+ probe image must be detached before cleanup",
                    )

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS mount metadata")
    def test_snapshot_captures_distinct_source_and_snapshot_mountpoints(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            (source / "file.txt").write_text("content", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                source_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY)
                snapshot_fd = os.open(snapshot.path, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    self.assertIsNotNone(snapshot.source_mount_point)
                    self.assertIsNotNone(snapshot.snapshot_mount_point)
                    self.assertNotEqual(
                        snapshot.source_mount_point,
                        snapshot.snapshot_mount_point,
                    )
                    self.assertIsNotNone(snapshot.storage_limit_bytes)
                    self.assertNotEqual(
                        os.fstat(source_fd).st_dev,
                        os.fstat(snapshot_fd).st_dev,
                    )
                    self.assertEqual(
                        workspace_snapshot_module._volume_mountpoint(source_fd),
                        snapshot.source_mount_point,
                    )
                    self.assertEqual(
                        workspace_snapshot_module._volume_mountpoint(snapshot_fd),
                        snapshot.snapshot_mount_point,
                    )
                finally:
                    os.close(snapshot_fd)
                    os.close(source_fd)

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS mount metadata")
    def test_rejects_reported_nested_mountpoint_with_same_device(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            nested = source / "nested"
            nested.mkdir()
            nested_stat = nested.stat()
            root_device = source.stat().st_dev
            self.assertEqual(nested_stat.st_dev, root_device)
            read_mountpoint = workspace_snapshot_module._volume_mountpoint

            def report_nested_mount(descriptor: int) -> str | None:
                entry = os.fstat(descriptor)
                if (entry.st_dev, entry.st_ino) == (
                    nested_stat.st_dev,
                    nested_stat.st_ino,
                ):
                    return "/different/mount"
                return read_mountpoint(descriptor)

            with patch(
                "khaos.kernel.workspace_snapshot._volume_mountpoint",
                side_effect=report_nested_mount,
            ):
                with self.assertRaisesRegex(
                    WorkspaceSnapshotError, "another filesystem mount"
                ):
                    with workspace_snapshot(source):
                        self.fail("a nested filesystem mount was copied")

    def test_copy_breaks_inode_identity_and_preserves_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            (source / "file.txt").write_text("workspace data", encoding="utf-8")
            (source / "nested").mkdir()
            (source / "nested" / "tool").write_text("tool", encoding="utf-8")
            (source / "link").symlink_to("nested/tool")

            with workspace_snapshot(source) as workspace_snapshot_value:
                snapshot = workspace_snapshot_value.path
                original = (source / "file.txt").stat()
                copied = (snapshot / "file.txt").stat()
                self.assertEqual((snapshot / "file.txt").read_text(), "workspace data")
                self.assertNotEqual(
                    (original.st_dev, original.st_ino),
                    (copied.st_dev, copied.st_ino),
                )
                self.assertEqual(copied.st_nlink, 1)
                self.assertTrue((snapshot / "link").is_symlink())
                self.assertEqual(os.readlink(snapshot / "link"), "nested/tool")

    def test_rejects_hardlink_to_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            outside = root / "secret.txt"
            outside.write_text("outside secret", encoding="utf-8")
            os.link(outside, source / "linked-secret.txt")

            with self.assertRaisesRegex(WorkspaceSnapshotError, "hard links"):
                with workspace_snapshot(source):
                    self.fail("a hardlinked workspace was exposed")
            self.assertEqual(outside.read_text(encoding="utf-8"), "outside secret")

    def test_rejects_non_regular_special_files(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFO creation is unavailable")
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            os.mkfifo(source / "pipe")
            with self.assertRaisesRegex(WorkspaceSnapshotError, "unsupported"):
                with workspace_snapshot(source):
                    self.fail("a special file was exposed")

    def test_enforces_copy_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            (source / "large.txt").write_text("four", encoding="utf-8")
            with self.assertRaisesRegex(WorkspaceSnapshotError, "limit"):
                with workspace_snapshot(source, max_bytes=3):
                    self.fail("an over-limit workspace was exposed")

    def test_enforces_copy_entry_count_limit(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            (source / "first.txt").write_text("first", encoding="utf-8")
            (source / "second.txt").write_text("second", encoding="utf-8")

            with self.assertRaisesRegex(WorkspaceSnapshotError, "limit"):
                with workspace_snapshot(source, max_entries=1):
                    self.fail("an over-limit workspace was exposed")

            self.assertEqual(
                sorted(path.name for path in source.iterdir()),
                ["first.txt", "second.txt"],
            )

    def test_cancellation_during_file_copy_discards_private_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            original = b"snapshot-input" * (256 * 1024)
            (source / "large.bin").write_bytes(original)
            storage_parent = (
                Path(tempfile.gettempdir()).resolve()
                if sys.platform == "darwin"
                else root
            )
            existing_snapshots = set(storage_parent.glob("khaos-snapshot-*"))
            source_stat = (source / "large.bin").stat()
            source_identity = source_stat.st_dev, source_stat.st_ino
            copied_source_chunk = False
            original_read = os.read

            def read_and_record_source_chunk(
                descriptor: int, byte_count: int
            ) -> bytes:
                nonlocal copied_source_chunk
                data = original_read(descriptor, byte_count)
                source_descriptor = os.fstat(descriptor)
                if data and (
                    source_descriptor.st_dev,
                    source_descriptor.st_ino,
                ) == source_identity:
                    copied_source_chunk = True
                return data

            def cancel_after_first_copy_chunk() -> bool:
                return copied_source_chunk

            with patch(
                "khaos.kernel.workspace_snapshot.os.read",
                side_effect=read_and_record_source_chunk,
            ):
                with self.assertRaisesRegex(
                    WorkspaceSnapshotCancelled, "workspace snapshot was cancelled"
                ):
                    with workspace_snapshot(
                        source,
                        max_bytes=4 * 1024 * 1024,
                        cancel_requested=cancel_after_first_copy_chunk,
                    ):
                        self.fail("a cancelled snapshot was exposed to its caller")

            self.assertTrue(copied_source_chunk)
            self.assertEqual((source / "large.bin").read_bytes(), original)
            self.assertEqual(
                set(storage_parent.glob("khaos-snapshot-*")), existing_snapshots
            )

    def test_run_tool_cancellation_kills_and_reaps_the_tool_process(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            process_id_path = root / "tool.pid"
            ready_path = root / "tool-ready"
            script = """\
import os
import sys
import time
from pathlib import Path

Path(sys.argv[1]).write_text(str(os.getpid()))
Path(sys.argv[2]).write_text("ready")
while True:
    time.sleep(1)
"""
            cancellation_observed = False

            def cancel_when_tool_is_running() -> bool:
                nonlocal cancellation_observed
                cancellation_observed = ready_path.exists()
                return cancellation_observed

            with self.assertRaises(WorkspaceSnapshotCancelled):
                _run_tool(
                    sys.executable,
                    ("-I", "-S", "-c", script, str(process_id_path), str(ready_path)),
                    cancel_requested=cancel_when_tool_is_running,
                )

            self.assertTrue(cancellation_observed)
            with self.assertRaises(ProcessLookupError):
                os.kill(int(process_id_path.read_text(encoding="utf-8")), 0)

    @unittest.skipUnless(
        sys.platform == "darwin" and Path(_HDIUTIL).is_file(),
        "requires the real macOS APFS image tools",
    )
    def test_cancellation_during_apfs_attach_reconciles_or_preserves_image(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value).resolve(strict=True)
            attach_observed = False

            def cancel_when_attach_is_running() -> bool:
                nonlocal attach_observed
                if attach_observed:
                    return True
                result = subprocess.run(
                    ["/bin/ps", "-axo", "command="],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                attach_observed = any(
                    f"{_HDIUTIL} attach " in line and str(root) in line
                    for line in result.stdout.splitlines()
                )
                return attach_observed

            with self.assertRaises(WorkspaceSnapshotCancelled):
                with mounted_apfs_volume(
                    root,
                    size_bytes=256_000_000,
                    case_sensitive=False,
                    cancel_requested=cancel_when_attach_is_running,
                ):
                    self.fail("a cancelled APFS mount was exposed")

            self.assertTrue(attach_observed)
            remaining = list(root.iterdir())
            if remaining:
                self.assertEqual(len(remaining), 1)
                self.assertTrue(
                    (remaining[0] / _IMAGE_OPERATION_MARKER).is_file(),
                    "unresolved APFS cleanup did not retain its pending marker",
                )
                self.assertFalse((remaining[0] / "volume").is_mount())
            inventory = plistlib.loads(
                _run_tool(_HDIUTIL, ("info", "-plist")).stdout
            )
            images = inventory.get("images")
            self.assertIsInstance(images, list)
            self.assertFalse(
                any(
                    isinstance(image, dict)
                    and isinstance(image.get("image-path"), str)
                    and str(root) in image["image-path"]
                    for image in images
                ),
                "cancelled APFS image remained attached",
            )

    @unittest.skipUnless(
        sys.platform == "darwin" and Path(_HDIUTIL).is_file(),
        "requires the real macOS APFS image tools",
    )
    def test_failed_create_cleanup_detaches_exact_unmounted_image(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            temporary = Path(value).resolve(strict=True) / "khaos-snapshot-probe"
            temporary.mkdir(mode=0o700)
            image = temporary / "workspace.sparsebundle"
            mount_point = temporary / "volume"
            mount_point.mkdir(mode=0o700)
            _run_tool(
                _HDIUTIL,
                (
                    "create",
                    "-type",
                    "SPARSEBUNDLE",
                    "-sectors",
                    "500000",
                    "-layout",
                    "NONE",
                    "-fs",
                    "APFS",
                    "-volname",
                    "KhaosCreateCleanupProbe",
                    "-nospotlight",
                    str(image),
                ),
            )
            _run_tool(
                _HDIUTIL,
                ("attach", "-nomount", "-plist", "-nobrowse", str(image)),
            )

            image_info = _attached_image_info(image)
            self.assertIsNotNone(image_info)
            self.assertTrue(image_info["system-entities"])
            self.assertFalse(mount_point.is_mount())

            self.assertTrue(
                _reconcile_pending_image_operation(
                    image, mount_point, may_still_be_running=True
                )
            )

            self.assertIsNone(_attached_image_info(image))
            self.assertFalse(mount_point.is_mount())

    @unittest.skipUnless(
        sys.platform == "darwin" and Path(_HDIUTIL).is_file(),
        "requires the real macOS APFS image tools",
    )
    def test_abandoned_pending_image_is_preserved_without_os_identity(self) -> None:
        owner_pid = os.getpid()
        temporary_parent = Path(tempfile.gettempdir()).resolve(strict=True)
        prefix = f"khaos-snapshot-{owner_pid}-"
        temporary = Path(tempfile.mkdtemp(prefix=prefix, dir=temporary_parent))
        (temporary / "volume").mkdir(mode=0o700)
        (temporary / _IMAGE_OPERATION_MARKER).touch(mode=0o600)
        try:
            with patch(
                "khaos.kernel.macos_disk_image._IMAGE_RECONCILIATION_TIMEOUT_SECONDS",
                0.01,
            ):
                cleanup_abandoned_apfs_volumes(owner_pid)

            self.assertTrue(temporary.exists())
            self.assertTrue((temporary / _IMAGE_OPERATION_MARKER).is_file())
        finally:
            (temporary / _IMAGE_OPERATION_MARKER).unlink(missing_ok=True)
            (temporary / "volume").rmdir()
            temporary.rmdir()

    @unittest.skipUnless(
        sys.platform == "darwin" and Path(_HDIUTIL).is_file(),
        "requires the real macOS APFS image tools",
    )
    def test_abandoned_worker_cleanup_detaches_its_private_apfs_image(self) -> None:
        owner_pid = os.getpid()
        temporary_parent = Path(tempfile.gettempdir()).resolve(strict=True)
        prefix = f"khaos-snapshot-{owner_pid}-"
        temporary = Path(
            tempfile.mkdtemp(prefix=prefix, dir=temporary_parent)
        )
        image = temporary / "workspace.sparsebundle"
        mount_point = temporary / "volume"
        mount_point.mkdir(mode=0o700)
        _run_tool(
            _HDIUTIL,
            (
                "create",
                "-type",
                "SPARSEBUNDLE",
                "-sectors",
                "500000",
                "-layout",
                "NONE",
                "-fs",
                "APFS",
                "-volname",
                "KhaosCleanupProbe",
                "-nospotlight",
                str(image),
            ),
        )
        _attach_image(image, mount_point=mount_point)
        self.assertTrue(mount_point.is_mount())

        cleanup_abandoned_apfs_volumes(owner_pid)

        self.assertFalse(temporary.exists())
        inventory = plistlib.loads(_run_tool(_HDIUTIL, ("info", "-plist")).stdout)
        self.assertFalse(
            any(
                isinstance(entry, dict) and entry.get("image-path") == str(image)
                for entry in inventory.get("images", [])
            ),
            "abandoned APFS image remained in hdiutil inventory",
        )

    def test_rejects_file_replaced_between_stat_and_open(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            target = source / "item"
            target.write_text("before", encoding="utf-8")
            replacement = root / "replacement"
            replacement.write_text("after!", encoding="utf-8")
            real_open = os.open
            raced = False

            def replace_before_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal raced
                if path == "item" and not raced and not flags & os.O_WRONLY:
                    raced = True
                    os.replace(target, root / "moved")
                    os.replace(replacement, target)
                if mode == 0o777:
                    return real_open(path, flags, dir_fd=dir_fd)
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with patch(
                "khaos.kernel.workspace_snapshot.os.open",
                side_effect=replace_before_open,
            ) as patched_open:
                supported = set(os.supports_dir_fd)
                supported.add(patched_open)
                with patch(
                    "khaos.kernel.workspace_snapshot.os.supports_dir_fd",
                    supported,
                ):
                    with self.assertRaisesRegex(WorkspaceSnapshotError, "changed"):
                        with workspace_snapshot(source):
                            self.fail("a raced workspace entry was exposed")
            self.assertTrue(raced)

    def test_rejects_invalid_limits(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            with self.assertRaises(ValueError):
                with workspace_snapshot(source, max_entries=True):
                    self.fail("boolean accepted as an entry limit")

    def test_fails_closed_without_descriptor_relative_apis(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            with patch("khaos.kernel.workspace_snapshot.os.supports_dir_fd", set()):
                with self.assertRaisesRegex(WorkspaceSnapshotError, "APIs"):
                    with workspace_snapshot(source):
                        self.fail("path-based fallback was used")


if __name__ == "__main__":
    unittest.main()
