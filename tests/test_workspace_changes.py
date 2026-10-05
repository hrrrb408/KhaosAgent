from __future__ import annotations

import errno
import os
from pathlib import Path
import plistlib
import select
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from khaos.kernel import workspace_changes
from khaos.kernel.macos_disk_image import mounted_apfs_volume
from khaos.kernel.workspace_changes import (
    WorkspaceCommitError,
    WorkspaceCommitOutcomeUncertain,
    commit_snapshot as _commit_snapshot,
)
from khaos.kernel.workspace_snapshot import (
    WorkspaceSnapshot,
    WorkspaceWriteScope,
    _volume_mountpoint,
    workspace_snapshot,
)
from workspace_test_support import fixture_workspace_write_scope


def _commit_fixture_snapshot(snapshot: WorkspaceSnapshot, **kwargs):
    kwargs.setdefault(
        "workspace_write_scope", fixture_workspace_write_scope(snapshot)
    )
    return _commit_snapshot(snapshot, **kwargs)


class WorkspaceChangesTests(unittest.TestCase):
    def _assert_cross_process_writer_is_rejected(
        self,
        snapshot: WorkspaceSnapshot,
        *,
        writer_script: str,
        writer_arguments: tuple[str, ...],
        acknowledgement: str,
    ) -> None:
        writer = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-S",
                "-c",
                writer_script,
                *writer_arguments,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            close_fds=True,
        )
        real_swap = workspace_changes._rename_swap
        raced = False

        try:
            def trigger_writer_before_swap(
                directory_fd, source_name, destination_name
            ):
                nonlocal raced
                if destination_name == "payload.txt" and not raced:
                    self.assertIsNotNone(writer.stdin)
                    self.assertIsNotNone(writer.stdout)
                    writer.stdin.write("race\n")
                    writer.stdin.flush()
                    ready, _, _ = select.select([writer.stdout], [], [], 5)
                    self.assertTrue(ready, "concurrent writer did not run")
                    self.assertEqual(
                        writer.stdout.readline().strip(), acknowledgement
                    )
                    raced = True
                return real_swap(directory_fd, source_name, destination_name)

            with patch(
                "khaos.kernel.workspace_changes._rename_swap",
                side_effect=trigger_writer_before_swap,
            ):
                with self.assertRaisesRegex(WorkspaceCommitError, "changed"):
                    _commit_fixture_snapshot(snapshot)
            self.assertEqual(writer.wait(timeout=5), 0)
        finally:
            if writer.poll() is None:
                writer.kill()
                writer.wait(timeout=5)
            for stream in (writer.stdin, writer.stdout, writer.stderr):
                if stream is not None:
                    stream.close()

        self.assertTrue(raced)

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS file metadata")
    def test_modified_file_preserves_baseline_acl_and_xattrs(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            target = source / "payload.txt"
            target.write_text("baseline", encoding="utf-8")
            subprocess.run(
                ["/usr/bin/xattr", "-w", "com.khaos.audit", "trusted", str(target)],
                check=True,
            )
            subprocess.run(
                ["/bin/chmod", "+a", "everyone deny execute", str(target)],
                check=True,
            )
            acl_before = _acl_entries(target)
            self.assertTrue(acl_before)

            with workspace_snapshot(source) as snapshot:
                output = snapshot.path / "payload.txt"
                output.write_text("Runner data", encoding="utf-8")
                subprocess.run(
                    [
                        "/usr/bin/xattr",
                        "-w",
                        "com.khaos.audit",
                        "untrusted",
                        str(output),
                    ],
                    check=True,
                )
                subprocess.run(
                    [
                        "/usr/bin/xattr",
                        "-w",
                        "com.khaos.runner",
                        "injected",
                        str(output),
                    ],
                    check=True,
                )
                _commit_fixture_snapshot(snapshot)

            self.assertEqual(target.read_text(encoding="utf-8"), "Runner data")
            self.assertEqual(
                subprocess.run(
                    ["/usr/bin/xattr", "-p", "com.khaos.audit", str(target)],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip(),
                "trusted",
            )
            runner_xattrs = subprocess.run(
                ["/usr/bin/xattr", str(target)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            self.assertNotIn("com.khaos.runner", runner_xattrs)
            self.assertEqual(_acl_entries(target), acl_before)

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS file metadata")
    def test_new_file_discards_runner_acl_and_xattrs(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            target = source / "added.txt"

            with workspace_snapshot(source) as snapshot:
                output = snapshot.path / target.name
                output.write_text("Runner data", encoding="utf-8")
                subprocess.run(
                    [
                        "/usr/bin/xattr",
                        "-w",
                        "com.khaos.runner",
                        "injected",
                        str(output),
                    ],
                    check=True,
                )
                subprocess.run(
                    ["/bin/chmod", "+a", "everyone deny execute", str(output)],
                    check=True,
                )
                output_xattrs = subprocess.run(
                    ["/usr/bin/xattr", str(output)],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.splitlines()
                self.assertIn("com.khaos.runner", output_xattrs)
                self.assertTrue(_acl_entries(output))

                _commit_fixture_snapshot(snapshot)

            self.assertEqual(target.read_text(encoding="utf-8"), "Runner data")
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            target_xattrs = subprocess.run(
                ["/usr/bin/xattr", str(target)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            self.assertNotIn("com.khaos.runner", target_xattrs)
            self.assertEqual(_acl_entries(target), ())

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS file metadata")
    def test_new_directory_discards_runner_mode_acl_and_xattrs(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            target = source / "created"

            with workspace_snapshot(source) as snapshot:
                output = snapshot.path / target.name
                output.mkdir()
                (output / "added.txt").write_text("Runner data", encoding="utf-8")
                os.chmod(output, 0o777)
                subprocess.run(
                    [
                        "/usr/bin/xattr",
                        "-w",
                        "com.khaos.runner",
                        "injected",
                        str(output),
                    ],
                    check=True,
                )
                subprocess.run(
                    ["/bin/chmod", "+a", "everyone deny writeattr", str(output)],
                    check=True,
                )
                output_xattrs = subprocess.run(
                    ["/usr/bin/xattr", str(output)],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.splitlines()
                self.assertIn("com.khaos.runner", output_xattrs)
                self.assertTrue(_acl_entries(output))

                _commit_fixture_snapshot(snapshot)

            self.assertEqual(
                (target / "added.txt").read_text(encoding="utf-8"), "Runner data"
            )
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            self.assertEqual((target / "added.txt").stat().st_mode & 0o777, 0o600)
            target_xattrs = subprocess.run(
                ["/usr/bin/xattr", str(target)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            self.assertNotIn("com.khaos.runner", target_xattrs)
            self.assertEqual(_acl_entries(target), ())

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS ACL inheritance")
    def test_new_entries_inherit_parent_acl_not_runner_acl(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir(mode=0o700)
            subprocess.run(
                [
                    "/bin/chmod",
                    "+a",
                    "everyone allow read,write,execute,file_inherit,directory_inherit",
                    str(source),
                ],
                check=True,
            )
            source_acl = _acl_entries(source)
            self.assertEqual(
                source_acl,
                (
                    "0: group:everyone allow list,add_file,search,"
                    "file_inherit,directory_inherit",
                ),
            )

            target_directory = source / "created"
            target_file = target_directory / "added.txt"
            with workspace_snapshot(source) as snapshot:
                output_directory = snapshot.path / target_directory.name
                output_directory.mkdir()
                output_file = output_directory / target_file.name
                output_file.write_text("Runner data", encoding="utf-8")
                subprocess.run(
                    [
                        "/bin/chmod",
                        "+a",
                        "everyone deny writeattr",
                        str(output_directory),
                    ],
                    check=True,
                )
                subprocess.run(
                    ["/bin/chmod", "+a", "everyone deny execute", str(output_file)],
                    check=True,
                )
                self.assertTrue(_acl_entries(output_directory))
                self.assertTrue(_acl_entries(output_file))

                _commit_fixture_snapshot(snapshot)

            self.assertEqual(target_directory.stat().st_mode & 0o777, 0o700)
            self.assertEqual(target_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(_acl_entries(source), source_acl)
            self.assertEqual(
                _acl_entries(target_directory),
                (
                    "0: group:everyone inherited allow list,add_file,search,"
                    "file_inherit,directory_inherit",
                ),
            )
            self.assertEqual(
                _acl_entries(target_file),
                ("0: group:everyone inherited allow read,write,execute",),
            )

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS extended attributes")
    def test_extended_metadata_budget_fails_before_workspace_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            target = source / "payload.txt"
            target.write_text("baseline", encoding="utf-8")
            subprocess.run(
                ["/usr/bin/xattr", "-w", "com.khaos.audit", "trusted", str(target)],
                check=True,
            )

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "payload.txt").write_text(
                    "Runner data", encoding="utf-8"
                )
                with patch(
                    "khaos.kernel.workspace_changes._MAX_COMMIT_XATTR_BYTES", 1
                ):
                    with self.assertRaisesRegex(
                        WorkspaceCommitError, "extended metadata exceeds commit limit"
                    ):
                        _commit_fixture_snapshot(snapshot)

            self.assertEqual(target.read_text(encoding="utf-8"), "baseline")
            self.assertEqual([path.name for path in source.iterdir()], ["payload.txt"])

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS file metadata")
    def test_metadata_copy_failure_precedes_live_file_replacements(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            targets = {name: source / name for name in ("a.txt", "b.txt")}
            for name, target in targets.items():
                target.write_text(f"baseline {name}", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                for name in targets:
                    (snapshot.path / name).write_text(
                        f"candidate {name}", encoding="utf-8"
                    )

                real_copy = workspace_changes._copy_file_acl_and_xattrs
                copy_calls = 0

                def fail_second_metadata_copy(source_fd, destination_fd):
                    nonlocal copy_calls
                    copy_calls += 1
                    if copy_calls == 2:
                        raise OSError(errno.EIO, "injected metadata-copy failure")
                    return real_copy(source_fd, destination_fd)

                with patch(
                    "khaos.kernel.workspace_changes._copy_file_acl_and_xattrs",
                    side_effect=fail_second_metadata_copy,
                ):
                    with self.assertRaises(WorkspaceCommitError):
                        _commit_fixture_snapshot(snapshot)

            self.assertEqual(copy_calls, 2)
            for name, target in targets.items():
                self.assertEqual(
                    target.read_text(encoding="utf-8"), f"baseline {name}"
                )
            self.assertEqual({path.name for path in source.iterdir()}, set(targets))

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS workspace commit")
    def test_added_file_stage_drift_is_rejected_before_install(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            target = source / "added.txt"

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / target.name).write_text("trusted", encoding="utf-8")
                real_apply = workspace_changes._apply_changes

                def corrupt_staged_file(
                    root_fd,
                    source_root,
                    baseline,
                    output,
                    staged_files,
                    staging_fd,
                    mount_point,
                    plan,
                    *,
                    on_live_mutation,
                ):
                    staged_name = staged_files[(target.name,)]
                    os.chmod(staged_name, 0o600, dir_fd=staging_fd)
                    descriptor = os.open(
                        staged_name,
                        os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=staging_fd,
                    )
                    try:
                        os.write(descriptor, b"changed")
                    finally:
                        os.close(descriptor)
                    return real_apply(
                        root_fd,
                        source_root,
                        baseline,
                        output,
                        staged_files,
                        staging_fd,
                        mount_point,
                        plan,
                        on_live_mutation=on_live_mutation,
                    )

                with patch(
                    "khaos.kernel.workspace_changes._apply_changes",
                    side_effect=corrupt_staged_file,
                ):
                    with self.assertRaisesRegex(
                        WorkspaceCommitError, "staged changeset file changed"
                    ):
                        _commit_fixture_snapshot(snapshot)

            self.assertFalse(target.exists())
            self.assertEqual(list(source.iterdir()), [])

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS workspace commit")
    def test_snapshot_symlink_replacement_after_scan_does_not_redirect_commit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            target = source / "added.txt"
            canary = root / "canary.txt"
            canary.write_text("outside baseline", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                snapshot_target = snapshot.path / target.name
                snapshot_target.write_text("captured output", encoding="utf-8")

                def replace_snapshot_entry(
                    _staging_path: Path,
                    _file_write_paths,
                    _create_unlink_paths,
                ) -> None:
                    snapshot_target.unlink()
                    snapshot_target.symlink_to(canary)

                with self.assertRaises(TypeError):
                    _commit_snapshot(
                        snapshot,
                        before_live_mutations=replace_snapshot_entry,
                    )

                changes = _commit_fixture_snapshot(
                    snapshot,
                    workspace_write_scope=WorkspaceWriteScope.from_paths(
                        (target.name,)
                    ),
                    before_live_mutations=replace_snapshot_entry,
                )

            target_info = target.lstat()
            self.assertTrue(stat.S_ISREG(target_info.st_mode))
            self.assertEqual(target_info.st_nlink, 1)
            self.assertEqual(target.read_text(encoding="utf-8"), "captured output")
            self.assertEqual(canary.read_text(encoding="utf-8"), "outside baseline")
            self.assertEqual(changes.added, ((target.name,),))

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS directory rename")
    def test_commit_rejects_parent_detached_after_open(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            nested = source / "inner"
            nested.mkdir()
            target = nested / "payload.txt"
            target.write_text("baseline", encoding="utf-8")
            escaped = root / "escaped"
            real_open_parent = workspace_changes._open_parent
            inner_open_count = 0
            detached = False

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "inner" / "payload.txt").write_text(
                    "Runner output", encoding="utf-8"
                )

                def detach_after_open(
                    root_fd, components, active_directories, mount_point
                ):
                    nonlocal detached, inner_open_count
                    parent_fd = real_open_parent(
                        root_fd, components, active_directories, mount_point
                    )
                    if components == ("inner",):
                        inner_open_count += 1
                        if inner_open_count == 2:
                            os.rename(nested, escaped)
                            nested.mkdir()
                            detached = True
                    return parent_fd

                with patch(
                    "khaos.kernel.workspace_changes._open_parent",
                    side_effect=detach_after_open,
                ):
                    with self.assertRaisesRegex(
                        WorkspaceCommitOutcomeUncertain,
                        "prepared workspace replacement could not be cleaned up",
                    ):
                        _commit_fixture_snapshot(snapshot)

            self.assertTrue(detached)
            self.assertEqual(
                (escaped / "payload.txt").read_text(encoding="utf-8"), "baseline"
            )
            self.assertFalse((nested / "payload.txt").exists())
            self.assertEqual(list(nested.iterdir()), [])
            prepared = [
                path for path in escaped.iterdir() if path.name.startswith(".khaos-")
            ]
            self.assertEqual(len(prepared), 1)
            self.assertEqual(prepared[0].read_text(encoding="utf-8"), "Runner output")

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS directory rename")
    def test_commit_restores_file_if_parent_detaches_during_swap(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            nested = source / "inner"
            nested.mkdir()
            target = nested / "payload.txt"
            target.write_text("baseline", encoding="utf-8")
            escaped = root / "escaped"
            real_swap = workspace_changes._rename_swap
            detached = False

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "inner" / "payload.txt").write_text(
                    "Runner output", encoding="utf-8"
                )

                def detach_during_swap(
                    directory_fd, source_name, destination_name
                ):
                    nonlocal detached
                    if destination_name == "payload.txt" and not detached:
                        os.rename(nested, escaped)
                        nested.mkdir()
                        detached = True
                    return real_swap(directory_fd, source_name, destination_name)

                with patch(
                    "khaos.kernel.workspace_changes._rename_swap",
                    side_effect=detach_during_swap,
                ):
                    with self.assertRaisesRegex(
                        WorkspaceCommitOutcomeUncertain,
                        "prepared workspace replacement could not be cleaned up",
                    ):
                        _commit_fixture_snapshot(snapshot)

            self.assertTrue(detached)
            self.assertEqual(
                (escaped / "payload.txt").read_text(encoding="utf-8"), "baseline"
            )
            self.assertFalse((nested / "payload.txt").exists())
            self.assertEqual(list(nested.iterdir()), [])
            prepared = [
                path for path in escaped.iterdir() if path.name.startswith(".khaos-")
            ]
            self.assertEqual(len(prepared), 1)
            self.assertEqual(prepared[0].read_text(encoding="utf-8"), "Runner output")

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS workspace rename")
    def test_commit_restores_file_if_workspace_root_moves_during_swap(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            nested = source / "inner"
            nested.mkdir()
            target = nested / "payload.txt"
            target.write_text("baseline", encoding="utf-8")
            moved_workspace = root / "moved-workspace"
            real_swap = workspace_changes._rename_swap
            moved = False

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "inner" / "payload.txt").write_text(
                    "Runner output", encoding="utf-8"
                )

                def move_root_during_swap(
                    directory_fd, source_name, destination_name
                ):
                    nonlocal moved
                    if destination_name == "payload.txt" and not moved:
                        os.rename(source, moved_workspace)
                        source.mkdir()
                        moved = True
                    return real_swap(directory_fd, source_name, destination_name)

                with patch(
                    "khaos.kernel.workspace_changes._rename_swap",
                    side_effect=move_root_during_swap,
                ):
                    with self.assertRaisesRegex(
                        WorkspaceCommitOutcomeUncertain,
                        "prepared workspace replacement could not be cleaned up",
                    ):
                        _commit_fixture_snapshot(snapshot)

            self.assertTrue(moved)
            self.assertEqual(
                (moved_workspace / "inner" / "payload.txt").read_text(
                    encoding="utf-8"
                ),
                "baseline",
            )
            self.assertEqual(list(source.iterdir()), [])
            prepared = [
                path
                for path in (moved_workspace / "inner").iterdir()
                if path.name.startswith(".khaos-")
            ]
            self.assertEqual(len(prepared), 1)
            self.assertEqual(prepared[0].read_text(encoding="utf-8"), "Runner output")

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS directory rename")
    def test_delete_restores_entry_if_parent_detaches_during_swap(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            nested = source / "inner"
            nested.mkdir()
            target = nested / "payload.txt"
            target.write_text("baseline", encoding="utf-8")
            escaped = root / "escaped"
            real_swap = workspace_changes._rename_swap
            detached = False

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "inner" / "payload.txt").unlink()

                def detach_during_swap(
                    directory_fd, source_name, destination_name
                ):
                    nonlocal detached
                    if destination_name == "payload.txt" and not detached:
                        os.rename(nested, escaped)
                        nested.mkdir()
                        detached = True
                    return real_swap(directory_fd, source_name, destination_name)

                with patch(
                    "khaos.kernel.workspace_changes._rename_swap",
                    side_effect=detach_during_swap,
                ):
                    with self.assertRaisesRegex(
                        WorkspaceCommitError, "entry changed during removal"
                    ):
                        _commit_fixture_snapshot(snapshot)

            self.assertTrue(detached)
            self.assertEqual(
                (escaped / "payload.txt").read_text(encoding="utf-8"), "baseline"
            )
            self.assertFalse((nested / "payload.txt").exists())
            self.assertEqual(list(nested.iterdir()), [])

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS directory rename")
    def test_new_file_temp_is_preserved_if_parent_detaches_after_clone(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            nested = source / "inner"
            nested.mkdir()
            escaped = root / "escaped"
            real_check = workspace_changes._parent_binding_is_current
            check_count = 0
            detached = False

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "inner" / "new.txt").write_text(
                    "Runner output", encoding="utf-8"
                )

                def detach_after_clone(
                    root_fd,
                    source_root,
                    components,
                    parent_fd,
                    active_directories,
                    mount_point,
                ):
                    nonlocal check_count, detached
                    if components == ("inner",):
                        check_count += 1
                        if check_count == 3:
                            os.rename(nested, escaped)
                            nested.mkdir()
                            detached = True
                    return real_check(
                        root_fd,
                        source_root,
                        components,
                        parent_fd,
                        active_directories,
                        mount_point,
                    )

                with patch(
                    "khaos.kernel.workspace_changes._parent_binding_is_current",
                    side_effect=detach_after_clone,
                ):
                    with self.assertRaisesRegex(
                        WorkspaceCommitOutcomeUncertain,
                        "workspace entry changed during removal",
                    ):
                        _commit_fixture_snapshot(snapshot)

            self.assertTrue(detached)
            self.assertEqual(
                (escaped / "new.txt").read_text(encoding="utf-8"),
                "Runner output",
            )
            escaped_temporary_entries = list(escaped.glob(".khaos-*.tmp"))
            self.assertEqual(len(escaped_temporary_entries), 1)
            self.assertEqual(
                escaped_temporary_entries[0].read_text(encoding="utf-8"),
                "Runner output",
            )
            self.assertEqual(
                sorted(path.name for path in escaped.iterdir()),
                sorted(("new.txt", escaped_temporary_entries[0].name)),
            )
            self.assertEqual(list(nested.iterdir()), [])

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS directory rename")
    def test_new_directory_is_preserved_if_parent_detaches_after_mkdir(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            nested = source / "inner"
            nested.mkdir()
            escaped = root / "escaped"
            real_check = workspace_changes._parent_binding_is_current
            check_count = 0
            detached = False

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "inner" / "new-directory").mkdir()

                def detach_after_mkdir(
                    root_fd,
                    source_root,
                    components,
                    parent_fd,
                    active_directories,
                    mount_point,
                ):
                    nonlocal check_count, detached
                    if components == ("inner",):
                        check_count += 1
                        if check_count == 2:
                            os.rename(nested, escaped)
                            nested.mkdir()
                            detached = True
                    return real_check(
                        root_fd,
                        source_root,
                        components,
                        parent_fd,
                        active_directories,
                        mount_point,
                    )

                with patch(
                    "khaos.kernel.workspace_changes._parent_binding_is_current",
                    side_effect=detach_after_mkdir,
                ):
                    with self.assertRaisesRegex(
                        WorkspaceCommitOutcomeUncertain, "directory changed"
                    ):
                        _commit_fixture_snapshot(snapshot)

            self.assertTrue(detached)
            self.assertEqual(list(escaped.iterdir()), [escaped / "new-directory"])
            self.assertEqual(list((escaped / "new-directory").iterdir()), [])
            self.assertEqual(list(nested.iterdir()), [])

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS workspace commit")
    def test_new_directory_is_preserved_if_parent_sync_fails(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            created = source / "created"
            real_fsync = os.fsync
            failed_directory_sync = False

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "created").mkdir()

                def fail_first_directory_sync(descriptor: int) -> None:
                    nonlocal failed_directory_sync
                    if (
                        stat.S_ISDIR(os.fstat(descriptor).st_mode)
                        and not failed_directory_sync
                    ):
                        failed_directory_sync = True
                        raise OSError(errno.EIO, "injected directory sync failure")
                    real_fsync(descriptor)

                with patch(
                    "khaos.kernel.workspace_changes.os.fsync",
                    side_effect=fail_first_directory_sync,
                ):
                    with self.assertRaisesRegex(
                        WorkspaceCommitOutcomeUncertain,
                        "directory could not be synced",
                    ):
                        _commit_fixture_snapshot(snapshot)

            self.assertTrue(failed_directory_sync)
            self.assertTrue(created.is_dir())
            self.assertEqual(list(created.iterdir()), [])
            self.assertEqual(list(source.iterdir()), [created])

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS workspace commit")
    def test_new_directory_sync_failure_preserves_racing_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            replacement = root / "replacement"
            replacement.mkdir()
            (replacement / "marker.txt").write_text("racer", encoding="utf-8")
            created = source / "created"
            displaced = root / "displaced-created-directory"
            real_fsync = os.fsync
            replaced = False

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "created").mkdir()

                def replace_before_sync_failure(descriptor: int) -> None:
                    nonlocal replaced
                    if stat.S_ISDIR(os.fstat(descriptor).st_mode) and not replaced:
                        os.rename(created, displaced)
                        os.rename(replacement, created)
                        replaced = True
                        raise OSError(errno.EIO, "injected directory sync failure")
                    real_fsync(descriptor)

                with patch(
                    "khaos.kernel.workspace_changes.os.fsync",
                    side_effect=replace_before_sync_failure,
                ):
                    with self.assertRaisesRegex(
                        WorkspaceCommitOutcomeUncertain,
                        "directory could not be synced",
                    ):
                        _commit_fixture_snapshot(snapshot)

            self.assertTrue(replaced)
            self.assertEqual(
                (created / "marker.txt").read_text(encoding="utf-8"), "racer"
            )
            self.assertTrue(displaced.is_dir())
            self.assertEqual(list(displaced.iterdir()), [])

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS mount metadata")
    def test_commit_rejects_reported_nested_mountpoint_in_runner_output(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            with workspace_snapshot(source) as snapshot:
                nested = snapshot.path / "nested"
                nested.mkdir()
                nested_stat = nested.stat()
                self.assertEqual(nested_stat.st_dev, snapshot.path.stat().st_dev)
                read_mountpoint = workspace_changes._volume_mountpoint

                def report_nested_mount(descriptor: int) -> str | None:
                    entry = os.fstat(descriptor)
                    if (entry.st_dev, entry.st_ino) == (
                        nested_stat.st_dev,
                        nested_stat.st_ino,
                    ):
                        return "/different/mount"
                    return read_mountpoint(descriptor)

                with (
                    patch(
                        "khaos.kernel.workspace_changes._volume_mountpoint",
                        side_effect=report_nested_mount,
                    ),
                    patch(
                        "khaos.kernel.workspace_snapshot._volume_mountpoint",
                        side_effect=report_nested_mount,
                    ),
                ):
                    with self.assertRaisesRegex(
                        WorkspaceCommitError, "another filesystem mount"
                    ):
                        _commit_fixture_snapshot(snapshot)

            self.assertFalse((source / "nested").exists())

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS APFS mounts")
    def test_commit_rejects_real_nested_apfs_mount_added_after_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            (source / "baseline.txt").write_text("trusted", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "candidate.txt").write_text(
                    "Runner output", encoding="utf-8"
                )
                with mounted_apfs_volume(
                    source,
                    size_bytes=256_000_000,
                    case_sensitive=False,
                ) as nested_volume:
                    (nested_volume / "mounted-data.txt").write_text(
                        "untrusted mounted data", encoding="utf-8"
                    )
                    with self.assertRaises(WorkspaceCommitError) as raised:
                        _commit_fixture_snapshot(snapshot)
                    self.assertRegex(
                        str(raised.exception),
                        "another filesystem|workspace changed while the changeset was scanned",
                    )

            self.assertEqual(
                (source / "baseline.txt").read_text(encoding="utf-8"), "trusted"
            )
            self.assertFalse((source / "candidate.txt").exists())
            self.assertFalse((source / "mounted-data.txt").exists())

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS APFS mounts")
    def test_same_volume_nested_mount_cannot_escape_trusted_commit(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            with mounted_apfs_volume(
                Path(value), size_bytes=256_000_000, case_sensitive=False
            ) as volume:
                source = volume / "workspace"
                source.mkdir()
                nested = source / "nested"
                nested.mkdir()
                outside = volume / "outside-secret.txt"
                outside.write_text("outside canary", encoding="utf-8")

                volume_info = plistlib.loads(
                    subprocess.run(
                        ["/usr/sbin/diskutil", "info", "-plist", str(volume)],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=30,
                        check=True,
                    ).stdout
                )
                device = volume_info.get("DeviceIdentifier")
                self.assertIsInstance(device, str, volume_info)
                self.assertTrue((Path("/dev") / device).exists(), volume_info)

                def mount_root(path: Path) -> str | None:
                    # st_dev and Path.is_mount() can miss a same-device mount.
                    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        return _volume_mountpoint(descriptor)
                    finally:
                        os.close(descriptor)

                source_mount = mount_root(source)
                self.assertEqual(mount_root(nested), source_mount)
                self.assertIsNotNone(source_mount)

                nested_mount_created = False
                with workspace_snapshot(source) as snapshot:
                    (snapshot.path / "candidate.txt").write_text(
                        "Runner output", encoding="utf-8"
                    )
                    mount_result: subprocess.CompletedProcess[bytes] | None = None
                    try:
                        mount_result = subprocess.run(
                            [
                                "/sbin/mount_apfs",
                                "-o",
                                "rdonly",
                                f"/dev/{device}",
                                str(nested),
                            ],
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            timeout=30,
                            check=False,
                        )
                        nested_mount = mount_root(nested)
                        nested_mount_created = nested_mount != source_mount
                        if nested_mount_created:
                            self.assertEqual(
                                mount_result.returncode,
                                0,
                                mount_result.stderr.decode(
                                    "utf-8", errors="replace"
                                ),
                            )
                            self.assertEqual(
                                (nested / outside.name).read_text(encoding="utf-8"),
                                "outside canary",
                            )
                            with self.assertRaisesRegex(
                                WorkspaceCommitError, "another filesystem"
                            ):
                                _commit_fixture_snapshot(snapshot)
                        else:
                            self.assertNotEqual(
                                mount_result.returncode,
                                0,
                                mount_result.stderr.decode(
                                    "utf-8", errors="replace"
                                ),
                            )
                            self.assertEqual(nested_mount, source_mount)
                            _commit_fixture_snapshot(snapshot)
                    finally:
                        current_nested_mount = mount_root(nested)
                        if (
                            current_nested_mount != source_mount
                            or (
                                mount_result is not None
                                and mount_result.returncode == 0
                            )
                        ):
                            cleanup = subprocess.run(
                                ["/sbin/umount", str(nested)],
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                timeout=30,
                                check=False,
                            )
                            self.assertEqual(
                                cleanup.returncode,
                                0,
                                cleanup.stderr.decode("utf-8", errors="replace"),
                            )

                self.assertEqual(
                    outside.read_text(encoding="utf-8"), "outside canary"
                )
                self.assertEqual(
                    (source / "candidate.txt").exists(), not nested_mount_created
                )

    def test_commits_bounded_file_and_directory_changes(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            (source / "edit.txt").write_text("before", encoding="utf-8")
            (source / "remove.txt").write_text("remove", encoding="utf-8")
            (source / "nested").mkdir()
            (source / "nested" / "old.txt").write_text("old", encoding="utf-8")
            (source / "kept-link").symlink_to("edit.txt")

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "edit.txt").write_text("after", encoding="utf-8")
                (snapshot.path / "remove.txt").unlink()
                (snapshot.path / "nested" / "old.txt").unlink()
                (snapshot.path / "new-dir").mkdir()
                (snapshot.path / "new-dir" / "added.txt").write_text(
                    "new", encoding="utf-8"
                )

                changes = _commit_fixture_snapshot(snapshot)
                with self.assertRaisesRegex(WorkspaceCommitError, "since the snapshot"):
                    _commit_fixture_snapshot(snapshot)

            self.assertEqual((source / "edit.txt").read_text(), "after")
            self.assertFalse((source / "remove.txt").exists())
            self.assertFalse((source / "nested" / "old.txt").exists())
            self.assertEqual((source / "new-dir" / "added.txt").read_text(), "new")
            self.assertEqual((source / "new-dir").stat().st_mode & 0o777, 0o700)
            self.assertEqual((source / "new-dir" / "added.txt").stat().st_mode & 0o777, 0o600)
            self.assertTrue((source / "kept-link").is_symlink())
            self.assertEqual(
                changes.added,
                (("new-dir",), ("new-dir", "added.txt")),
            )
            self.assertEqual(changes.modified, (("edit.txt",),))
            self.assertEqual(
                changes.deleted,
                (("nested", "old.txt"), ("remove.txt",)),
            )

    def test_rejects_new_symlink_without_touching_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            outside = root / "outside.txt"
            outside.write_text("protected", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "escape").symlink_to(outside)
                with self.assertRaisesRegex(WorkspaceCommitError, "symbolic links"):
                    _commit_fixture_snapshot(snapshot)

            self.assertEqual(outside.read_text(encoding="utf-8"), "protected")
            self.assertFalse((source / "escape").exists())

    def test_rejects_retargeted_existing_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")
            (source / "link").symlink_to(first)

            with workspace_snapshot(source) as snapshot:
                link = snapshot.path / "link"
                link.unlink()
                link.symlink_to(second)
                with self.assertRaisesRegex(WorkspaceCommitError, "symbolic links"):
                    _commit_fixture_snapshot(snapshot)

            self.assertEqual(os.readlink(source / "link"), str(first))
            self.assertEqual(first.read_text(encoding="utf-8"), "first")
            self.assertEqual(second.read_text(encoding="utf-8"), "second")

    def test_rejects_hardlink_in_runner_output(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            protected = source / "protected.txt"
            protected.write_text("protected", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                os.link(snapshot.path / "protected.txt", snapshot.path / "linked")
                with self.assertRaisesRegex(WorkspaceCommitError, "hard links"):
                    _commit_fixture_snapshot(snapshot)

            self.assertEqual(protected.read_text(encoding="utf-8"), "protected")
            self.assertFalse((source / "linked").exists())

    def test_rejects_special_file_in_runner_output(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFO creation is unavailable")
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            with workspace_snapshot(source) as snapshot:
                os.mkfifo(snapshot.path / "pipe")
                with self.assertRaisesRegex(WorkspaceCommitError, "unsupported"):
                    _commit_fixture_snapshot(snapshot)
            self.assertFalse((source / "pipe").exists())

    def test_rejects_unix_socket_output_before_partial_writeback(self) -> None:
        if not hasattr(socket, "AF_UNIX"):
            self.skipTest("Unix domain sockets are unavailable")
        with tempfile.TemporaryDirectory(dir="/tmp") as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            existing = source / "existing.txt"
            existing.write_text("before", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "existing.txt").write_text(
                    "runner replacement", encoding="utf-8"
                )
                (snapshot.path / "safe-addition.txt").write_text(
                    "runner addition", encoding="utf-8"
                )
                socket_alias = root / "snapshot"
                socket_alias.symlink_to(snapshot.path, target_is_directory=True)
                socket_path = socket_alias / "output.sock"

                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as endpoint:
                    endpoint.bind(str(socket_path))
                    with self.assertRaisesRegex(
                        WorkspaceCommitError, "unsupported filesystem entry"
                    ):
                        _commit_fixture_snapshot(snapshot)

            self.assertEqual(existing.read_text(encoding="utf-8"), "before")
            self.assertFalse((source / "safe-addition.txt").exists())

    def test_rejects_runner_file_permission_change(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            target = source / "script"
            target.write_text("safe", encoding="utf-8")
            original_mode = target.stat().st_mode & 0o777

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "script").chmod(0o755)
                with self.assertRaisesRegex(WorkspaceCommitError, "permissions"):
                    _commit_fixture_snapshot(snapshot)

            self.assertEqual(target.stat().st_mode & 0o777, original_mode)
            self.assertEqual(target.read_text(encoding="utf-8"), "safe")

    def test_rejects_stale_source_without_applying_snapshot_output(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            target = source / "current.txt"
            target.write_text("before", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "current.txt").write_text("runner", encoding="utf-8")
                (snapshot.path / "new.txt").write_text("runner", encoding="utf-8")
                target.write_text("user edit", encoding="utf-8")
                with self.assertRaisesRegex(WorkspaceCommitError, "since the snapshot"):
                    _commit_fixture_snapshot(snapshot)

            self.assertEqual(target.read_text(encoding="utf-8"), "user edit")
            self.assertFalse((source / "new.txt").exists())

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS workspace commit")
    def test_rejects_workspace_root_replaced_after_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            moved = root / "moved-workspace"

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "candidate.txt").write_text(
                    "candidate", encoding="utf-8"
                )
                os.rename(source, moved)
                source.mkdir()

                with self.assertRaisesRegex(
                    WorkspaceCommitError, "workspace changed since the snapshot"
                ):
                    _commit_fixture_snapshot(snapshot)

            self.assertEqual(list(moved.iterdir()), [])
            self.assertEqual(list(source.iterdir()), [])

    def test_commit_requires_snapshot_root_descriptor_lifetime(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            target = source / "existing.txt"
            target.write_text("before", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "existing.txt").write_text(
                    "candidate", encoding="utf-8"
                )

            with self.assertRaises(WorkspaceCommitError):
                _commit_fixture_snapshot(snapshot)

            self.assertEqual(target.read_text(encoding="utf-8"), "before")

    def test_rejects_runner_file_replaced_between_stat_and_open(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            replacement = root / "replacement"
            replacement.write_text("after", encoding="utf-8")
            real_open = os.open
            raced = False

            with workspace_snapshot(source) as snapshot:
                target = snapshot.path / "payload"
                target.write_text("before", encoding="utf-8")

                def replace_before_open(path, flags, mode=0o777, *, dir_fd=None):
                    nonlocal raced
                    if path == "payload" and not raced and not flags & os.O_WRONLY:
                        raced = True
                        os.replace(target, root / "moved")
                        os.replace(replacement, target)
                    if mode == 0o777:
                        return real_open(path, flags, dir_fd=dir_fd)
                    return real_open(path, flags, mode, dir_fd=dir_fd)

                with patch(
                    "khaos.kernel.workspace_changes.os.open",
                    side_effect=replace_before_open,
                ) as patched_open:
                    supported = set(os.supports_dir_fd)
                    supported.add(patched_open)
                    with patch(
                        "khaos.kernel.workspace_changes.os.supports_dir_fd",
                        supported,
                    ):
                        with self.assertRaisesRegex(WorkspaceCommitError, "changed"):
                            _commit_fixture_snapshot(snapshot)

            self.assertTrue(raced)
            self.assertFalse((source / "payload").exists())

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS descriptor clone")
    def test_new_file_commit_does_not_overwrite_a_cross_process_racing_destination(
        self,
    ) -> None:
        racer_script = """\
import os
import sys

parent, outside, kind = sys.argv[1:]
sys.stdin.readline()
directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    if kind == "symlink":
        os.symlink(outside, "racing.txt", dir_fd=directory_fd)
    elif kind == "file":
        descriptor = os.open(
            "racing.txt",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=directory_fd,
        )
        try:
            os.write(descriptor, b"concurrent")
        finally:
            os.close(descriptor)
    else:
        raise SystemExit("unsupported destination kind")
finally:
    os.close(directory_fd)
print("installed", flush=True)
"""
        real_clone = workspace_changes._clone_file_from_descriptor

        for kind in ("file", "symlink"):
            with self.subTest(destination_kind=kind):
                with tempfile.TemporaryDirectory() as value:
                    root = Path(value)
                    source = root / "workspace"
                    source.mkdir()
                    outside = root / "outside.txt"
                    outside.write_text("outside canary", encoding="utf-8")
                    racer: subprocess.Popen[str] | None = None
                    raced = False

                    with workspace_snapshot(source) as snapshot:
                        (snapshot.path / "racing.txt").write_text(
                            "runner", encoding="utf-8"
                        )
                        racer = subprocess.Popen(
                            [
                                sys.executable,
                                "-I",
                                "-S",
                                "-c",
                                racer_script,
                                str(source),
                                str(outside),
                                kind,
                            ],
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            close_fds=True,
                        )

                        def create_destination_then_clone(
                            source_fd,
                            destination_directory_fd,
                            destination_name,
                        ):
                            nonlocal raced
                            if destination_name == "racing.txt":
                                assert racer is not None
                                self.assertIsNotNone(racer.stdin)
                                self.assertIsNotNone(racer.stdout)
                                racer.stdin.write("race\n")
                                racer.stdin.flush()
                                ready, _, _ = select.select(
                                    [racer.stdout], [], [], 5
                                )
                                self.assertTrue(
                                    ready, "concurrent writer did not run"
                                )
                                self.assertEqual(
                                    racer.stdout.readline().strip(), "installed"
                                )
                                raced = True
                            return real_clone(
                                source_fd,
                                destination_directory_fd,
                                destination_name,
                            )

                        try:
                            with patch(
                                "khaos.kernel.workspace_changes._clone_file_from_descriptor",
                                side_effect=create_destination_then_clone,
                            ):
                                with self.assertRaises(WorkspaceCommitError):
                                    _commit_fixture_snapshot(snapshot)
                            self.assertEqual(racer.wait(timeout=5), 0)
                        finally:
                            if racer.poll() is None:
                                racer.kill()
                                racer.wait(timeout=5)
                            for stream in (racer.stdin, racer.stdout, racer.stderr):
                                if stream is not None:
                                    stream.close()

                    target = source / "racing.txt"
                    self.assertTrue(raced)
                    if kind == "symlink":
                        self.assertTrue(target.is_symlink())
                        self.assertEqual(os.readlink(target), str(outside))
                    else:
                        self.assertTrue(stat.S_ISREG(target.lstat().st_mode))
                        self.assertEqual(
                            target.read_text(encoding="utf-8"), "concurrent"
                        )
                    self.assertEqual(
                        sorted(path.name for path in source.iterdir()),
                        ["racing.txt"],
                    )
                    self.assertEqual(
                        outside.read_text(encoding="utf-8"), "outside canary"
                    )

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS descriptor clone")
    def test_new_file_commit_rejects_a_racing_temp_name_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            outside = root / "outside.txt"
            outside.write_text("outside canary", encoding="utf-8")
            racer_script = """\
import os
import sys

parent, outside = sys.argv[1:]
sys.stdin.readline()
directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    temporary = [
        name for name in os.listdir(directory_fd)
        if name.startswith(".khaos-") and name.endswith(".tmp")
    ]
    if len(temporary) != 1:
        raise SystemExit("expected one commit temporary file")
    os.unlink(temporary[0], dir_fd=directory_fd)
    os.link(outside, temporary[0], dst_dir_fd=directory_fd, follow_symlinks=False)
finally:
    os.close(directory_fd)
print("replaced", flush=True)
"""
            real_clone = workspace_changes._clone_file_from_descriptor
            racer: subprocess.Popen[str] | None = None
            raced = False

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "payload.txt").write_text(
                    "Runner output", encoding="utf-8"
                )
                racer = subprocess.Popen(
                    [
                        sys.executable,
                        "-I",
                        "-S",
                        "-c",
                        racer_script,
                        str(source),
                        str(outside),
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    close_fds=True,
                )

                def replace_temp_name_before_clone(
                    source_fd,
                    destination_directory_fd,
                    destination_name,
                ):
                    nonlocal raced
                    if destination_name == "payload.txt":
                        assert racer is not None
                        self.assertIsNotNone(racer.stdin)
                        self.assertIsNotNone(racer.stdout)
                        racer.stdin.write("race\n")
                        racer.stdin.flush()
                        ready, _, _ = select.select([racer.stdout], [], [], 5)
                        self.assertTrue(ready, "concurrent writer did not run")
                        self.assertEqual(racer.stdout.readline().strip(), "replaced")
                        raced = True
                    return real_clone(
                        source_fd,
                        destination_directory_fd,
                        destination_name,
                    )

                try:
                    with patch(
                        "khaos.kernel.workspace_changes._clone_file_from_descriptor",
                        side_effect=replace_temp_name_before_clone,
                    ):
                        with self.assertRaises(WorkspaceCommitOutcomeUncertain):
                            _commit_fixture_snapshot(snapshot)
                finally:
                    if racer.poll() is None:
                        racer.kill()
                        racer.wait(timeout=5)
                    for stream in (racer.stdin, racer.stdout, racer.stderr):
                        if stream is not None:
                            stream.close()

            target = source / "payload.txt"
            self.assertTrue(raced)
            self.assertEqual(racer.returncode, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "Runner output")
            temporary_entries = list(source.glob(".khaos-*.tmp"))
            self.assertEqual(len(temporary_entries), 1)
            self.assertTrue(os.path.samefile(temporary_entries[0], outside))
            self.assertEqual(
                temporary_entries[0].read_text(encoding="utf-8"), "outside canary"
            )
            self.assertEqual(outside.read_text(encoding="utf-8"), "outside canary")
            self.assertEqual(outside.stat().st_nlink, 2)

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS descriptor clone")
    def test_new_file_commit_rejects_a_racing_temp_metadata_change(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            racer_script = """\
import os
import subprocess
import sys

parent = sys.argv[1]
directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    temporary = [
        name for name in os.listdir(directory_fd)
        if name.startswith(".khaos-") and name.endswith(".tmp")
    ]
    if len(temporary) != 1:
        raise SystemExit("expected one commit temporary file")
    temporary_path = os.path.join(parent, temporary[0])
    if sys.stdin.readline() != "race\\n":
        raise SystemExit("missing race signal")
    subprocess.run(
        [
            "/usr/bin/xattr",
            "-w",
            "com.khaos.race",
            "injected",
            temporary_path,
        ],
        check=True,
    )
    print("metadata-updated", flush=True)
    if sys.stdin.readline() != "restore\\n":
        raise SystemExit("missing restore signal")
    subprocess.run(
        [
            "/usr/bin/xattr",
            "-w",
            "com.khaos.race",
            "baseline",
            temporary_path,
        ],
        check=True,
    )
finally:
    os.close(directory_fd)
print("metadata-restored", flush=True)
"""
            real_clone = workspace_changes._clone_file_from_descriptor
            real_copy = workspace_changes._copy_verified_file
            racer: subprocess.Popen[str] | None = None
            raced = False

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "payload.txt").write_text(
                    "Runner output", encoding="utf-8"
                )
                racer = subprocess.Popen(
                    [
                        sys.executable,
                        "-I",
                        "-S",
                        "-c",
                        racer_script,
                        str(source),
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    close_fds=True,
                )

                def seed_temp_metadata(staged_fd, destination_fd, expected):
                    real_copy(staged_fd, destination_fd, expected)
                    temporary = tuple(source.glob(".khaos-*.tmp"))
                    self.assertEqual(len(temporary), 1)
                    subprocess.run(
                        [
                            "/usr/bin/xattr",
                            "-w",
                            "com.khaos.race",
                            "baseline",
                            str(temporary[0]),
                        ],
                        check=True,
                    )

                def change_temp_metadata_before_clone(
                    source_fd,
                    destination_directory_fd,
                    destination_name,
                ):
                    nonlocal raced
                    if destination_name == "payload.txt":
                        assert racer is not None
                        self.assertIsNotNone(racer.stdin)
                        self.assertIsNotNone(racer.stdout)
                        racer.stdin.write("race\n")
                        racer.stdin.flush()
                        ready, _, _ = select.select([racer.stdout], [], [], 5)
                        self.assertTrue(ready, "concurrent writer did not run")
                        acknowledgement = racer.stdout.readline().strip()
                        self.assertEqual(
                            acknowledgement,
                            "metadata-updated",
                            racer.stderr.read() if not acknowledgement else "",
                        )
                        cloned = real_clone(
                            source_fd,
                            destination_directory_fd,
                            destination_name,
                        )
                        racer.stdin.write("restore\n")
                        racer.stdin.flush()
                        ready, _, _ = select.select([racer.stdout], [], [], 5)
                        self.assertTrue(
                            ready, "concurrent writer did not restore metadata"
                        )
                        self.assertEqual(
                            racer.stdout.readline().strip(), "metadata-restored"
                        )
                        raced = True
                        return cloned
                    return real_clone(
                        source_fd,
                        destination_directory_fd,
                        destination_name,
                    )

                real_fingerprint = workspace_changes._extended_attribute_fingerprint
                fingerprints = []

                def record_fingerprint(descriptor, *, max_bytes):
                    result = real_fingerprint(descriptor, max_bytes=max_bytes)
                    fingerprints.append(result[0])
                    return result

                try:
                    with patch(
                        "khaos.kernel.workspace_changes._copy_verified_file",
                        side_effect=seed_temp_metadata,
                    ):
                        with patch(
                            "khaos.kernel.workspace_changes._extended_attribute_fingerprint",
                            side_effect=record_fingerprint,
                        ):
                            with patch(
                                "khaos.kernel.workspace_changes._clone_file_from_descriptor",
                                side_effect=change_temp_metadata_before_clone,
                            ):
                                with self.assertRaisesRegex(
                                    WorkspaceCommitOutcomeUncertain,
                                    "installed workspace file metadata changed",
                                ):
                                    _commit_fixture_snapshot(snapshot)
                    self.assertEqual(racer.wait(timeout=5), 0)
                finally:
                    if racer.poll() is None:
                        racer.kill()
                        racer.wait(timeout=5)
                    for stream in (racer.stdin, racer.stdout, racer.stderr):
                        if stream is not None:
                            stream.close()

            self.assertTrue(raced)
            self.assertEqual(fingerprints[0], fingerprints[1])
            self.assertNotEqual(fingerprints[0], fingerprints[2])
            target = source / "payload.txt"
            self.assertEqual(target.read_text(encoding="utf-8"), "Runner output")
            self.assertEqual(
                subprocess.run(
                    ["/usr/bin/xattr", "-p", "com.khaos.race", str(target)],
                    check=True,
                    capture_output=True,
                ).stdout.strip(),
                b"injected",
            )
            self.assertEqual(tuple(source.iterdir()), (target,))

    def test_existing_file_commit_restores_a_racing_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            target = source / "payload.txt"
            target.write_text("baseline", encoding="utf-8")
            concurrent = root / "concurrent.txt"
            concurrent.write_text("concurrent", encoding="utf-8")
            real_swap = workspace_changes._rename_swap
            raced = False

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "payload.txt").write_text("runner", encoding="utf-8")

                def replace_before_swap(directory_fd, source_name, destination_name):
                    nonlocal raced
                    if destination_name == "payload.txt" and not raced:
                        os.replace(concurrent, target)
                        raced = True
                    return real_swap(directory_fd, source_name, destination_name)

                with patch(
                    "khaos.kernel.workspace_changes._rename_swap",
                    side_effect=replace_before_swap,
                ):
                    with self.assertRaisesRegex(WorkspaceCommitError, "changed"):
                        _commit_fixture_snapshot(snapshot)

            self.assertTrue(raced)
            self.assertEqual(target.read_text(encoding="utf-8"), "concurrent")
            self.assertEqual([path.name for path in source.iterdir()], ["payload.txt"])

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS atomic rename")
    def test_existing_file_commit_restores_a_cross_process_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            target = source / "payload.txt"
            target.write_text("baseline", encoding="utf-8")
            concurrent = root / "concurrent.txt"
            concurrent.write_text("concurrent", encoding="utf-8")
            racer_script = """\
import os
import sys

sys.stdin.readline()
os.replace(sys.argv[1], sys.argv[2])
print("replaced", flush=True)
"""

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "payload.txt").write_text("runner", encoding="utf-8")
                self._assert_cross_process_writer_is_rejected(
                    snapshot,
                    writer_script=racer_script,
                    writer_arguments=(str(concurrent), str(target)),
                    acknowledgement="replaced",
                )

            self.assertEqual(target.read_text(encoding="utf-8"), "concurrent")
            self.assertEqual([path.name for path in source.iterdir()], ["payload.txt"])

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS atomic rename")
    def test_existing_file_commit_restores_a_cross_process_in_place_edit(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            target = source / "payload.txt"
            target.write_text("baseline", encoding="utf-8")
            original_inode = target.stat().st_ino
            writer_script = """\
import os
import sys

sys.stdin.readline()
fd = os.open(sys.argv[1], os.O_WRONLY)
os.pwrite(fd, b"parallel", 0)
os.fsync(fd)
os.close(fd)
print("edited", flush=True)
"""

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "payload.txt").write_text("runner", encoding="utf-8")
                self._assert_cross_process_writer_is_rejected(
                    snapshot,
                    writer_script=writer_script,
                    writer_arguments=(str(target),),
                    acknowledgement="edited",
                )

            self.assertEqual(target.stat().st_ino, original_inode)
            self.assertEqual(target.read_text(encoding="utf-8"), "parallel")
            self.assertEqual([path.name for path in source.iterdir()], ["payload.txt"])

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS workspace locking")
    def test_commit_rejects_another_kernel_writer_on_same_mountpoint(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            nested = source / "nested"
            nested.mkdir()
            target = nested / "payload.txt"
            target.write_text("baseline", encoding="utf-8")
            holder_script = (
                "import fcntl, os, sys\n"
                "fd = os.open(sys.argv[1], os.O_RDONLY)\n"
                "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
                "sys.stdout.write('locked\\n'); sys.stdout.flush()\n"
                "sys.stdin.buffer.read(1)\n"
            )
            with workspace_snapshot(nested) as snapshot:
                self.assertIsNotNone(snapshot.source_mount_point)
                (snapshot.path / "payload.txt").write_text(
                    "Runner output", encoding="utf-8"
                )
                holder = subprocess.Popen(
                    [
                        sys.executable,
                        "-I",
                        "-S",
                        "-c",
                        holder_script,
                        str(snapshot.source_mount_point),
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    close_fds=True,
                )

                try:
                    self.assertIsNotNone(holder.stdout)
                    ready, _, _ = select.select([holder.stdout], [], [], 5)
                    self.assertTrue(ready, "lock holder did not become ready")
                    self.assertEqual(holder.stdout.readline().strip(), "locked")
                    with self.assertRaisesRegex(
                        WorkspaceCommitError, "another Khaos workspace commit"
                    ):
                        _commit_fixture_snapshot(snapshot)
                    self.assertEqual(target.read_text(encoding="utf-8"), "baseline")
                    self.assertIsNotNone(holder.stdin)
                    holder.stdin.write("x")
                    holder.stdin.flush()
                    self.assertEqual(holder.wait(timeout=5), 0)
                    _commit_fixture_snapshot(snapshot)
                finally:
                    if holder.poll() is None:
                        if holder.stdin is not None:
                            holder.stdin.write("x")
                            holder.stdin.flush()
                        holder.wait(timeout=5)
                    for stream in (holder.stdin, holder.stdout, holder.stderr):
                        if stream is not None:
                            stream.close()

                self.assertEqual(target.read_text(encoding="utf-8"), "Runner output")

    def test_deleted_file_commit_restores_a_racing_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            target = source / "payload.txt"
            target.write_text("baseline", encoding="utf-8")
            concurrent = root / "concurrent.txt"
            concurrent.write_text("concurrent", encoding="utf-8")
            real_swap = workspace_changes._rename_swap
            raced = False

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "payload.txt").unlink()

                def replace_before_swap(directory_fd, source_name, destination_name):
                    nonlocal raced
                    if destination_name == "payload.txt" and not raced:
                        os.replace(concurrent, target)
                        raced = True
                    return real_swap(directory_fd, source_name, destination_name)

                with patch(
                    "khaos.kernel.workspace_changes._rename_swap",
                    side_effect=replace_before_swap,
                ):
                    with self.assertRaisesRegex(WorkspaceCommitError, "changed"):
                        _commit_fixture_snapshot(snapshot)

            self.assertTrue(raced)
            self.assertEqual(target.read_text(encoding="utf-8"), "concurrent")
            self.assertEqual([path.name for path in source.iterdir()], ["payload.txt"])

    def test_deleted_symlink_commit_restores_a_racing_retarget(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")
            target = source / "link"
            target.symlink_to(first)
            replacement = root / "replacement-link"
            replacement.symlink_to(second)
            real_swap = workspace_changes._rename_swap
            raced = False

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "link").unlink()

                def retarget_before_swap(directory_fd, source_name, destination_name):
                    nonlocal raced
                    if destination_name == "link" and not raced:
                        os.replace(replacement, target)
                        raced = True
                    return real_swap(directory_fd, source_name, destination_name)

                with patch(
                    "khaos.kernel.workspace_changes._rename_swap",
                    side_effect=retarget_before_swap,
                ):
                    with self.assertRaisesRegex(WorkspaceCommitError, "changed"):
                        _commit_fixture_snapshot(snapshot)

            self.assertTrue(raced)
            self.assertEqual(os.readlink(target), str(second))
            self.assertEqual(first.read_text(encoding="utf-8"), "first")
            self.assertEqual(second.read_text(encoding="utf-8"), "second")
            self.assertEqual([path.name for path in source.iterdir()], ["link"])

    def test_deleted_directory_commit_restores_a_racing_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / "workspace"
            source.mkdir()
            target = source / "empty"
            target.mkdir()
            concurrent = root / "concurrent"
            concurrent.mkdir()
            (concurrent / "marker.txt").write_text("preserved", encoding="utf-8")
            real_swap = workspace_changes._rename_swap
            raced = False

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "empty").rmdir()

                def replace_before_swap(directory_fd, source_name, destination_name):
                    nonlocal raced
                    if destination_name == "empty" and not raced:
                        os.replace(concurrent, target)
                        raced = True
                    return real_swap(directory_fd, source_name, destination_name)

                with patch(
                    "khaos.kernel.workspace_changes._rename_swap",
                    side_effect=replace_before_swap,
                ):
                    with self.assertRaisesRegex(WorkspaceCommitError, "changed"):
                        _commit_fixture_snapshot(snapshot)

            self.assertTrue(raced)
            self.assertEqual(
                (target / "marker.txt").read_text(encoding="utf-8"), "preserved"
            )
            self.assertEqual(
                sorted(path.name for path in source.iterdir()), ["empty"]
            )

    def test_atomic_swap_failure_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            target = source / "payload.txt"
            target.write_text("baseline", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "payload.txt").write_text("runner", encoding="utf-8")
                with patch(
                    "khaos.kernel.workspace_changes._rename_swap",
                    side_effect=OSError(errno.ENOTSUP, "swap unsupported"),
                ):
                    with self.assertRaises(WorkspaceCommitOutcomeUncertain):
                        _commit_fixture_snapshot(snapshot)

            self.assertEqual(target.read_text(encoding="utf-8"), "baseline")
            entries = list(source.iterdir())
            prepared = [path for path in entries if path.name.startswith(".khaos-")]
            self.assertEqual(len(entries), 2)
            self.assertEqual(len(prepared), 1)
            self.assertEqual(prepared[0].read_text(encoding="utf-8"), "runner")

    def test_unsupported_platform_commit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            source = Path(value) / "workspace"
            source.mkdir()
            target = source / "payload.txt"
            target.write_text("baseline", encoding="utf-8")

            with workspace_snapshot(source) as snapshot:
                (snapshot.path / "payload.txt").write_text("runner", encoding="utf-8")
                with patch.object(workspace_changes.sys, "platform", "linux"):
                    with self.assertRaisesRegex(
                        WorkspaceCommitError, "unsupported on this platform"
                    ):
                        _commit_fixture_snapshot(snapshot)

            self.assertEqual(target.read_text(encoding="utf-8"), "baseline")
            self.assertEqual([path.name for path in source.iterdir()], ["payload.txt"])


def _acl_entries(path: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ["/bin/ls", "-lde", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(
        line.strip()
        for line in result.stdout.splitlines()
        if line.lstrip().split(":", 1)[0].isdigit()
    )


if __name__ == "__main__":
    unittest.main()
