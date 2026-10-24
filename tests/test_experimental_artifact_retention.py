from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from tools import audit_experimental_artifacts, experimental_artifact_retention
from tools.build_dsh_xpc_acceptance_app import preflight_local_model_build
from tools.experimental_artifact_retention import (
    GIB,
    capture_candidate,
    capture_failure_bundle,
    disk_space_preflight,
    inventory_path,
    load_manifest,
    preflight_required_bytes,
    read_bounded_diagnostic_text,
    scratch_artifact_record,
    scratch_cleanup_state,
    validate_manifest,
    write_manifest,
    write_private_file,
)


def clear_references(_path: Path) -> tuple[str, list[int]]:
    return "CLEAR", []


class ExperimentalArtifactRetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def candidate(self, path: Path, **overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "candidate_id": "candidate-1",
            "path": str(path),
            "artifact_type": "synthetic_fixture",
            "classification": "SAFE_CANDIDATE",
            "trial_id": "trial-test",
            "evidence_preserved": True,
            "rebuild_proven": True,
            "consumer_dependencies_resolved": True,
            "cleanup_status": "PENDING_OWNER_APPROVAL",
            "is_model_source": False,
            "active_processes": [],
        }
        values.update(overrides)
        return capture_candidate(values)

    def manifest(self, candidates: list[dict[str, object]], *, allowed: Path | None = None,
                 protected: list[str] | None = None) -> dict[str, object]:
        return {
            "schema": 1,
            "allowed_roots": [str(allowed or self.root)],
            "protected_paths": protected or [],
            "candidates": candidates,
        }

    def test_exact_manifest_candidate_is_only_reported_as_pending_owner_approval(self) -> None:
        path = self.root / "scratch"
        path.mkdir()
        content = path / "fixture.py"
        content.write_text("answer = 42\n", encoding="utf-8")
        before = hashlib.sha256(content.read_bytes()).hexdigest()
        report = validate_manifest(
            self.manifest([self.candidate(path)]), reference_check=clear_references
        )
        self.assertEqual(report[0]["status"], "READY_PENDING_OWNER_APPROVAL")
        self.assertIsNone(report[0]["estimated_reclaimable_bytes"])
        self.assertEqual(hashlib.sha256(content.read_bytes()).hexdigest(), before)

    def test_symlink_candidate_root_is_refused(self) -> None:
        target = self.root / "target"
        target.mkdir()
        link = self.root / "candidate-link"
        link.symlink_to(target, target_is_directory=True)
        candidate = {
            "candidate_id": "link",
            "path": str(link),
            "classification": "SAFE_CANDIDATE",
            "evidence_preserved": True,
            "rebuild_proven": True,
            "consumer_dependencies_resolved": True,
            "cleanup_status": "PENDING_OWNER_APPROVAL",
        }
        report = validate_manifest(
            self.manifest([candidate]), reference_check=clear_references
        )
        self.assertEqual(report[0]["status"], "REFUSE")
        self.assertIn("candidate_is_symlink", report[0]["reasons"])

    def test_symlink_ancestor_is_refused_as_outside_exact_root(self) -> None:
        real = self.root / "real"
        real.mkdir()
        candidate = real / "scratch"
        candidate.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(real, target_is_directory=True)
        report = validate_manifest(
            self.manifest([self.candidate(candidate)], allowed=alias),
            reference_check=clear_references,
        )
        self.assertEqual(report[0]["status"], "REFUSE")
        self.assertIn("outside_exact_allowed_root", report[0]["reasons"])

    def test_external_symlink_inside_candidate_is_refused(self) -> None:
        allowed = self.root / "candidates"
        allowed.mkdir()
        path = allowed / "scratch"
        path.mkdir()
        outside = self.root / "elsewhere" / "outside-fixture"
        outside.parent.mkdir()
        outside.write_text("x", encoding="utf-8")
        try:
            (path / "escape").symlink_to(outside)
            report = validate_manifest(
                self.manifest([self.candidate(path)], allowed=allowed),
                reference_check=clear_references,
            )
        finally:
            outside.unlink(missing_ok=True)
        self.assertEqual(report[0]["status"], "REFUSE")
        self.assertIn("candidate_tree_contains_unsafe_entry", report[0]["reasons"])
        self.assertEqual(report[0]["reference_check"], "NOT_RUN_UNSAFE_OR_UNAVAILABLE_TREE")

    def test_hard_linked_file_inside_candidate_is_refused(self) -> None:
        allowed = self.root / "candidates"
        allowed.mkdir()
        path = allowed / "scratch"
        path.mkdir()
        external = self.root / "external-data"
        external.write_text("shared", encoding="utf-8")
        os.link(external, path / "shared")
        report = validate_manifest(
            self.manifest([self.candidate(path)], allowed=allowed),
            reference_check=clear_references,
        )
        self.assertEqual(report[0]["status"], "REFUSE")
        self.assertIn("candidate_tree_contains_unsafe_entry", report[0]["reasons"])

    def test_same_path_replaced_by_a_different_inode_is_refused(self) -> None:
        path = self.root / "scratch"
        path.mkdir()
        (path / "one").write_text("one", encoding="utf-8")
        candidate = self.candidate(path)
        path.rename(self.root / "old-scratch")
        path.mkdir()
        (path / "one").write_text("one", encoding="utf-8")
        report = validate_manifest(
            self.manifest([candidate]), reference_check=clear_references
        )
        self.assertEqual(report[0]["status"], "REFUSE")
        self.assertTrue({"inode_mismatch", "tree_identity_mismatch"}.intersection(report[0]["reasons"]))

    def test_candidate_size_or_metadata_change_is_refused(self) -> None:
        path = self.root / "scratch"
        path.mkdir()
        content = path / "one"
        content.write_text("one", encoding="utf-8")
        candidate = self.candidate(path)
        content.write_text("two longer", encoding="utf-8")
        report = validate_manifest(
            self.manifest([candidate]), reference_check=clear_references
        )
        self.assertEqual(report[0]["status"], "REFUSE")
        self.assertIn("logical_size_mismatch", report[0]["reasons"])

    def test_equal_size_content_change_is_caught_by_mtime_tree_identity(self) -> None:
        path = self.root / "scratch"
        path.mkdir()
        content = path / "one"
        content.write_text("one", encoding="utf-8")
        candidate = self.candidate(path)
        content.write_text("two", encoding="utf-8")
        report = validate_manifest(
            self.manifest([candidate]), reference_check=clear_references
        )
        self.assertEqual(report[0]["status"], "REFUSE")
        self.assertIn("tree_identity_mismatch", report[0]["reasons"])

    def test_tampered_manifest_is_rejected_by_sidecar(self) -> None:
        path = self.root / "scratch"
        path.mkdir()
        manifest_path = self.root / "manifest.json"
        digest = write_manifest(manifest_path, self.manifest([self.candidate(path)]))
        manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            load_manifest(manifest_path)
        self.assertEqual(len(digest), 64)

    def test_private_evidence_writer_never_overwrites_an_existing_file(self) -> None:
        path = self.root / "evidence.json"
        path.write_bytes(b"original evidence")
        with self.assertRaises(FileExistsError):
            write_private_file(path, b"replacement")
        self.assertEqual(path.read_bytes(), b"original evidence")

    def test_manifest_canonical_path_must_match_the_exact_candidate(self) -> None:
        path = self.root / "scratch"
        path.mkdir()
        candidate = {**self.candidate(path), "canonical_path": str(self.root / "other")}
        report = validate_manifest(
            self.manifest([candidate]), reference_check=clear_references
        )
        self.assertEqual(report[0]["status"], "REFUSE")
        self.assertIn("canonical_path_mismatch", report[0]["reasons"])

    def test_active_process_reference_is_refused(self) -> None:
        path = self.root / "scratch"
        path.mkdir()
        report = validate_manifest(
            self.manifest([self.candidate(path)]),
            reference_check=lambda _path: ("REFERENCED", [123]),
        )
        self.assertEqual(report[0]["status"], "REFUSE")
        self.assertIn("active_process_reference", report[0]["reasons"])
        self.assertEqual(report[0]["active_processes"], [123])

    def test_unavailable_process_check_is_fail_closed(self) -> None:
        path = self.root / "scratch"
        path.mkdir()
        report = validate_manifest(
            self.manifest([self.candidate(path)]),
            reference_check=lambda _path: ("UNKNOWN", []),
        )
        self.assertEqual(report[0]["status"], "REFUSE")
        self.assertIn("active_reference_unknown", report[0]["reasons"])

    def test_missing_evidence_and_unproven_rebuild_are_refused(self) -> None:
        path = self.root / "scratch"
        path.mkdir()
        candidate = self.candidate(path, evidence_preserved=False, rebuild_proven=False)
        report = validate_manifest(
            self.manifest([candidate]), reference_check=clear_references
        )
        self.assertEqual(report[0]["status"], "REFUSE")
        self.assertIn("evidence_dependency_unresolved", report[0]["reasons"])
        self.assertIn("rebuild_not_proven", report[0]["reasons"])

    def test_unique_model_source_and_protected_evidence_are_refused(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"model")
        model_candidate = self.candidate(model, is_model_source=True)
        model_report = validate_manifest(
            self.manifest([model_candidate]), reference_check=clear_references
        )
        self.assertIn("unique_model_source_protected", model_report[0]["reasons"])

        evidence = self.root / "protected-artifacts"
        evidence.mkdir()
        candidate = self.candidate(evidence)
        protected_report = validate_manifest(
            self.manifest([candidate], protected=[str(evidence)]),
            reference_check=clear_references,
        )
        self.assertIn("protected_path_overlap", protected_report[0]["reasons"])

    def test_path_outside_allowed_root_is_refused(self) -> None:
        allowed = self.root / "allowed"
        allowed.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        candidate = self.candidate(outside)
        calls = {"inventory": 0, "reference": 0}

        def forbidden_inventory(_path: Path) -> dict[str, object]:
            calls["inventory"] += 1
            raise AssertionError("out-of-scope paths must not be scanned")

        def forbidden_reference(_path: Path) -> tuple[str, list[int]]:
            calls["reference"] += 1
            raise AssertionError("out-of-scope paths must not be process-scanned")

        with patch.object(experimental_artifact_retention, "inventory_path", forbidden_inventory):
            report = validate_manifest(
                self.manifest([candidate], allowed=allowed),
                reference_check=forbidden_reference,
            )
        self.assertIn("outside_exact_allowed_root", report[0]["reasons"])
        self.assertEqual(calls, {"inventory": 0, "reference": 0})

    def test_duplicate_and_nested_candidates_are_rejected_before_inventory(self) -> None:
        parent = self.root / "parent"
        child = parent / "child"
        child.mkdir(parents=True)
        first = self.candidate(parent, candidate_id="parent")
        second = self.candidate(child, candidate_id="child")
        with self.assertRaisesRegex(ValueError, "duplicate or nested"):
            validate_manifest(
                self.manifest([first, second]), reference_check=clear_references
            )
        with self.assertRaisesRegex(ValueError, "duplicate or nested"):
            validate_manifest(
                self.manifest([first, {**first, "candidate_id": "duplicate"}]),
                reference_check=clear_references,
            )

    def test_git_repository_root_is_refused(self) -> None:
        path = self.root / "repo"
        path.mkdir()
        (path / ".git").mkdir()
        report = validate_manifest(
            self.manifest([self.candidate(path)]), reference_check=clear_references
        )
        self.assertIn("git_repository_root", report[0]["reasons"])

    def test_preflight_accounts_for_model_copy_staging_and_safety_margin(self) -> None:
        model_bytes = 10 * GIB
        required = preflight_required_bytes(model_bytes)
        self.assertEqual(required, model_bytes + 2 * GIB + model_bytes // 10)
        output = self.root / "not-created" / "output.app"
        fake_usage = shutil._ntuple_diskusage(100 * GIB, 50 * GIB, required - 1)
        report = disk_space_preflight(model_bytes, output.parent, usage=lambda _path: fake_usage)
        self.assertEqual(report["status"], "INSUFFICIENT_DISK_SPACE")
        self.assertEqual(report["required_free_bytes"], required)
        enough = shutil._ntuple_diskusage(100 * GIB, 50 * GIB, required)
        report = disk_space_preflight(model_bytes, output.parent, usage=lambda _path: enough)
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(output.parent.exists())

    def test_builder_preflight_uses_model_metadata_without_reading_model_bytes(self) -> None:
        model_app = self.root / "Khaos Model.app"
        model = model_app / "Contents/XPCServices/KhaosAgentHost.xpc/Contents/Resources/agent-model.gguf"
        model.parent.mkdir(parents=True)
        model.write_bytes(b"fixture-model")
        output_parent = self.root / "output"
        output_parent.mkdir()
        report = {
            "status": "PASS",
            "required_free_bytes": 100,
            "free_bytes": 200,
            "volume_total_bytes": 300,
            "volume_used_bytes": 100,
            "volume_device": output_parent.stat().st_dev,
        }
        with patch("tools.build_dsh_xpc_acceptance_app.disk_space_preflight", return_value=report):
            with patch.object(Path, "open", side_effect=AssertionError("model bytes were read")):
                self.assertEqual(preflight_local_model_build(model_app, output_parent), report)

    def test_builder_preflight_stops_when_volume_space_is_insufficient(self) -> None:
        model_app = self.root / "Khaos Model.app"
        model = model_app / "Contents/XPCServices/KhaosAgentHost.xpc/Contents/Resources/agent-model.gguf"
        model.parent.mkdir(parents=True)
        model.write_bytes(b"fixture-model")
        output_parent = self.root / "output"
        output_parent.mkdir()
        report = {
            "status": "INSUFFICIENT_DISK_SPACE",
            "required_free_bytes": 200,
            "free_bytes": 199,
            "volume_total_bytes": 300,
            "volume_used_bytes": 101,
            "volume_device": output_parent.stat().st_dev,
        }
        with patch("tools.build_dsh_xpc_acceptance_app.disk_space_preflight", return_value=report):
            with self.assertRaisesRegex(RuntimeError, "INSUFFICIENT_DISK_SPACE"):
                preflight_local_model_build(model_app, output_parent)

    def test_scratch_cleanup_requires_same_identity_and_no_open_reference(self) -> None:
        path = self.root / "scratch"
        path.mkdir()
        identity = path.stat()
        fingerprint = str(inventory_path(path)["tree_fingerprint_sha256"])
        allowed, _ = scratch_cleanup_state(
            path, identity.st_dev, identity.st_ino,
            expected_tree_fingerprint=fingerprint,
            reference_check=clear_references,
        )
        self.assertTrue(allowed)
        active, reason = scratch_cleanup_state(
            path, identity.st_dev, identity.st_ino,
            expected_tree_fingerprint=fingerprint,
            reference_check=lambda _path: ("REFERENCED", [456]),
        )
        self.assertFalse(active)
        self.assertEqual(reason, "scratch_open_reference_referenced")
        changed, reason = scratch_cleanup_state(
            path, identity.st_dev + 1, identity.st_ino,
            reference_check=clear_references,
        )
        self.assertFalse(changed)
        self.assertEqual(reason, "scratch_identity_changed")

    def test_retention_record_binds_exact_invocation_scratch_identity(self) -> None:
        path = self.root / "scratch"
        path.mkdir()
        (path / "fixture.txt").write_text("small synthetic fixture", encoding="utf-8")
        identity = path.stat()
        record = scratch_artifact_record(path, identity.st_dev, identity.st_ino)
        self.assertEqual(record["path"], str(path))
        self.assertEqual(record["expected_device"], identity.st_dev)
        self.assertEqual(record["expected_inode"], identity.st_ino)
        self.assertEqual(record["inventory_status"], "MATCH")
        self.assertEqual(record["logical_bytes"], len("small synthetic fixture"))

    def test_detached_temporary_directory_can_be_cleaned_after_evidence(self) -> None:
        temporary = tempfile.TemporaryDirectory(dir=self.root)
        path = Path(temporary.name)
        (path / "synthetic.bin").write_bytes(b"fixture")
        temporary._finalizer.detach()
        temporary.cleanup()
        self.assertFalse(path.exists())

    def test_failure_bundle_is_bounded_owner_only_and_excludes_signed_app_model(self) -> None:
        scratch = self.root / "scratch"
        scratch.mkdir()
        (scratch / "launcher.stdout").write_text("model output\n", encoding="utf-8")
        (scratch / "launcher.stderr").write_text("API=" + "secret-value" + "\n", encoding="utf-8")
        (scratch / "agent-task.txt").write_text("synthetic task\n", encoding="utf-8")
        app = scratch / "Khaos DSH XPC Acceptance.app/Contents/Resources"
        app.mkdir(parents=True)
        (app / "build-inputs.json").write_text('{"source":"abc"}\n', encoding="utf-8")
        (app / "agent-model.gguf").write_bytes(b"do not copy")
        workspace = scratch / "coding-workspace"
        workspace.mkdir()
        (workspace / "fixture.py").write_text("value = 1\n", encoding="utf-8")
        (workspace / "secret-canary.txt").write_text("canary\n", encoding="utf-8")
        cancellation = scratch / "cancellation-control"
        cancellation.mkdir()
        (cancellation / "kernel-events.jsonl").write_text('{"stage":"KERNEL_RESULT"}\n', encoding="utf-8")

        destination = self.root / "diagnostics"
        result = capture_failure_bundle(scratch, destination, api_key="secret-value")
        self.assertEqual(result["status"], "COMPLETE")
        self.assertFalse((destination / "agent-model.gguf").exists())
        self.assertFalse(list(destination.rglob("*.app")))
        compressed = gzip.decompress((destination / "launcher.stderr.gz").read_bytes())
        self.assertNotIn(b"secret-value", compressed)
        self.assertIn(b"[REDACTED_API_KEY]", compressed)
        self.assertTrue((destination / "coding-workspace/fixture.py").is_file())
        self.assertTrue((destination / "cancellation-control/kernel-events.jsonl").is_file())
        self.assertFalse((destination / "coding-workspace/secret-canary.txt").exists())
        self.assertEqual(destination.stat().st_mode & 0o777, 0o700)
        for path in destination.rglob("*"):
            if path.is_file():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_incomplete_failure_bundle_cannot_become_cleanup_evidence(self) -> None:
        scratch = self.root / "scratch"
        scratch.mkdir()
        (scratch / "launcher.stdout").write_bytes(b"")
        (scratch / "launcher.stderr").write_bytes(b"")
        (scratch / "agent-task.txt").write_text("task", encoding="utf-8")
        destination = self.root / "diagnostics"
        result = capture_failure_bundle(scratch, destination)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertIn("build-inputs.json", result["missing_required_files"])

    def test_failure_bundle_refuses_cleanup_if_source_changes_during_capture(self) -> None:
        scratch = self.root / "scratch"
        scratch.mkdir()
        (scratch / "launcher.stdout").write_text("stdout", encoding="utf-8")
        (scratch / "launcher.stderr").write_text("stderr", encoding="utf-8")
        (scratch / "agent-task.txt").write_text("task", encoding="utf-8")
        (scratch / "build-inputs.json").write_text('{"source":"fixture"}\n', encoding="utf-8")
        original_inventory = experimental_artifact_retention.inventory_path
        inventory_calls = 0

        def change_source_before_final_inventory(path: Path) -> dict[str, object]:
            nonlocal inventory_calls
            inventory_calls += 1
            if inventory_calls == 2:
                (scratch / "agent-task.txt").write_text("changed task", encoding="utf-8")
            return original_inventory(path)

        with patch.object(
            experimental_artifact_retention,
            "inventory_path",
            side_effect=change_source_before_final_inventory,
        ):
            result = capture_failure_bundle(scratch, self.root / "diagnostics")
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertIn("scratch_changed_during_capture", result["missing_required_files"])
        self.assertFalse(result["source_tree_stable_during_capture"])

    def test_bounded_diagnostic_reader_refuses_links_and_oversized_files(self) -> None:
        source = self.root / "diagnostic.log"
        source.write_text("bounded log", encoding="utf-8")
        content, error = read_bounded_diagnostic_text(source)
        self.assertEqual(content, "bounded log")
        self.assertIsNone(error)

        linked = self.root / "linked.log"
        linked.symlink_to(source)
        content, error = read_bounded_diagnostic_text(linked)
        self.assertEqual(content, "")
        self.assertEqual(error, "unsafe_diagnostic_file")

        source.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
        content, error = read_bounded_diagnostic_text(source)
        self.assertEqual(content, "")
        self.assertEqual(error, "diagnostic_file_over_limit")

    def test_cli_dry_run_reports_without_mutating_candidate_tree(self) -> None:
        candidate_path = self.root / "candidate"
        candidate_path.mkdir()
        data = candidate_path / "fixture.py"
        data.write_text("value = 1\n", encoding="utf-8")
        candidate = self.candidate(candidate_path)
        before = inventory_path(candidate_path)["tree_fingerprint_sha256"]
        manifest_path = self.root / "manifest.json"
        write_manifest(manifest_path, self.manifest([candidate]))
        output_path = self.root / "dry-run.json"
        output = io.StringIO()
        with patch.object(sys, "argv", [
            "audit_experimental_artifacts.py", "--manifest", str(manifest_path),
            "--output", str(output_path),
        ]), redirect_stdout(output):
            result = audit_experimental_artifacts.main()
        report = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertIn(result, (0, 2))
        self.assertEqual(report["mode"], "DRY_RUN_READ_ONLY")
        self.assertEqual(report["mutations_performed"], 0)
        self.assertEqual(before, inventory_path(candidate_path)["tree_fingerprint_sha256"])
        self.assertEqual(data.read_text(encoding="utf-8"), "value = 1\n")


if __name__ == "__main__":
    unittest.main()
