from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.check_security_freeze import check_changes, protected
from tools.build_macos_seed import BuildError, _publish_app, _snapshot_sources


class SecurityFreezeTests(unittest.TestCase):
    def test_authority_paths_and_new_kernel_files_are_sensitive(self):
        for path in ('khaos/kernel/new.py', 'khaos/macos/NewAuthority.swift',
                     '.github/workflows/new.yml', 'security/tcb-manifest.json',
                     'tests/test_security_freeze.py', 'khaos/__init__.py'):
            self.assertTrue(protected(path), path)
        for path in ('khaos/macos/AgentHost.swift', 'khaos/runner.py', 'examples/memory/plugin.py'):
            self.assertFalse(protected(path), path)

    def test_base_inventory_cannot_be_removed_to_hide_trusted_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()
            git('init', '-q')
            (root / 'security').mkdir()
            (root / 'security/tcb-manifest.json').write_text(json.dumps({'files': [{'path':'old.py'}]}))
            (root / 'old.py').write_text('trusted')
            contract = root / 'docs/Khaos vNext 架构设计文档.md'
            contract.parent.mkdir()
            contract.write_text('contract')
            git('add', '.')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-qm', 'baseline')
            base = git('rev-parse', 'HEAD')
            (root / 'old.py').write_text('changed')
            (root / 'security/tcb-manifest.json').write_text('{"files":[]}')
            with self.assertRaisesRegex(ValueError, 'fresh security'):
                check_changes(root, base)
            (root / 'old.py').write_text('trusted')
            (root / 'security/tcb-manifest.json').write_text(json.dumps({'files': [{'path':'old.py'}]}))
            contract.write_text('modified contract')
            with self.assertRaisesRegex(ValueError, 'fresh security'):
                check_changes(root, base)

    def test_source_snapshot_is_separate_and_expected_map_is_exact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hashes = _snapshot_sources(root / 'snapshot', None)
            for path, digest in hashes.items():
                self.assertEqual(hashlib.sha256((root / 'snapshot' / path).read_bytes()).hexdigest(), digest)
            expected = root / 'expected.json'
            expected.write_text(json.dumps(hashes))
            self.assertEqual(_snapshot_sources(root / 'verified', expected), hashes)
            hashes.pop(next(iter(hashes)))
            expected.write_text(json.dumps(hashes))
            with self.assertRaisesRegex(BuildError, 'reviewed SHA-256'):
                _snapshot_sources(root / 'rejected', expected)

    @unittest.skipUnless(__import__('sys').platform == 'darwin', 'macOS same-UID audit')
    def test_documented_same_uid_key_and_readonly_bundle_counterexamples(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [__import__('sys').executable, '-c',
             "import runpy; runpy.run_path('reports/security-kernel-finalization/same_uid_experiment.py', run_name='__main__')"],
            cwd=root, capture_output=True, text=True, check=True,
        )
        evidence = json.loads(result.stdout)
        self.assertTrue(evidence['co_replaced_key_state_accepted'])
        self.assertTrue(evidence['readonly_owned_bundle_replaced'])
        self.assertTrue(evidence['temporary_artifacts_removed'])

    @unittest.skipUnless(__import__('sys').platform == 'darwin', 'macOS exclusive rename')
    def test_publish_never_replaces_existing_output_or_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'staged.app'
            source.mkdir()
            output = root / 'output.app'
            output.mkdir()
            with self.assertRaises(OSError):
                _publish_app(source, output)
            output.rmdir()
            output.symlink_to(root / 'absent')
            with self.assertRaises(OSError):
                _publish_app(source, output)
            output.unlink()
            _publish_app(source, output)
            self.assertTrue(output.is_dir())
