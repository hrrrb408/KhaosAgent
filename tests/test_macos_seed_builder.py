from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.build_macos_seed import BuildError, _query_model_runtime_version


class MacOSSeedBuilderTests(unittest.TestCase):
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
