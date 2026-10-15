from __future__ import annotations

import subprocess
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.build_macos_seed import BuildError, _query_model_runtime_version, _require_signing_identity


class MacOSSeedBuilderTests(unittest.TestCase):
    def test_self_signed_local_identity_does_not_require_global_trust(self) -> None:
        fingerprint = "A" * 40
        output = f'  1) {fingerprint} "Local Seed" (CSSMERR_TP_NOT_TRUSTED)\n'
        with patch("tools.build_macos_seed._run", return_value=output):
            self.assertEqual(_require_signing_identity(fingerprint, None), fingerprint)
            self.assertEqual(_require_signing_identity("Local Seed", None), fingerprint)
        with patch("tools.build_macos_seed._run", return_value=output.replace("NOT_TRUSTED", "CERT_EXPIRED")):
            with self.assertRaises(BuildError):
                _require_signing_identity(fingerprint, None)
        with patch("tools.build_macos_seed._run", return_value=output + output.replace(fingerprint, "B" * 40)):
            with self.assertRaises(BuildError):
                _require_signing_identity("Local Seed", None)

    def test_test_signer_saves_search_list_before_keychain_creation(self) -> None:
        import test_macos_xpc_sandbox as product_tests
        created = False
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            def run(command, **kwargs):
                nonlocal created
                output = ""
                if command[:2] == ["security", "create-keychain"]:
                    created = True
                if command == ["security", "list-keychains", "-d", "user"]:
                    output = '"/initial/login.keychain"\n'
                    if created:
                        output += f'"{directory / "xpc-test.keychain"}"\n'
                if command[:2] == ["openssl", "x509"]:
                    output = "SHA1 Fingerprint=" + ":".join(["AA"] * 20)
                return subprocess.CompletedProcess(command, 0, output, "")
            with patch.object(product_tests.subprocess, "run", side_effect=run):
                identity, keychain = product_tests.MacOSXPCSandboxTests._create_signing_identity(directory)
            self.assertEqual(identity, "A" * 40)
            self.assertEqual(keychain, directory / "xpc-test.keychain")
            prior = json.loads((directory / "original-keychain-search-list.json").read_text())
            self.assertEqual(prior, ["/initial/login.keychain"])

    def test_runtime_version_probe_allows_cold_signed_bundle_validation(self) -> None:
        completed = subprocess.CompletedProcess(
            ["llama-cli", "--version"], 0, "llama.cpp test build\n", ""
        )
        with patch("tools.build_macos_seed.subprocess.run", return_value=completed) as run:
            self.assertEqual(_query_model_runtime_version(Path("llama-cli")), "llama.cpp test build")

        self.assertEqual(run.call_args.kwargs["timeout"], 60)

    def test_runtime_version_probe_fails_closed_after_timeout(self) -> None:
        with patch(
            "tools.build_macos_seed.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["llama-cli", "--version"], 60),
        ):
            with self.assertRaisesRegex(BuildError, "could not query bundled llama.cpp version"):
                _query_model_runtime_version(Path("llama-cli"))


if __name__ == "__main__":
    unittest.main()
