from __future__ import annotations

import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch


class MemoryPluginTests(unittest.TestCase):
    def test_remember_recall_forget_use_the_canonical_v1_blob(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "memory"
            / "plugin.py"
        )
        stored: list[bytes | None] = [None]
        with (
            patch("khaos.runner_sdk.state_read", side_effect=lambda: stored[0]),
            patch(
                "khaos.runner_sdk.state_replace",
                side_effect=lambda data: stored.__setitem__(0, data),
            ),
        ):
            run = runpy.run_path(str(source))["run"]
            self.assertEqual(
                run({
                    "operation": "remember",
                    "key": "project_codename",
                    "value": "Project K",
                }),
                {
                    "operation": "remember",
                    "key": "project_codename",
                    "remembered": True,
                },
            )
            self.assertEqual(
                stored[0],
                b'{"format":"khaos-memory-v1","items":{"project_codename":"Project K"}}',
            )
            self.assertEqual(
                run({"operation": "recall", "key": "project_codename"}),
                {
                    "operation": "recall",
                    "key": "project_codename",
                    "found": True,
                    "value": "Project K",
                },
            )
            self.assertEqual(
                run({"operation": "forget", "key": "project_codename"}),
                {
                    "operation": "forget",
                    "key": "project_codename",
                    "forgotten": True,
                },
            )
            self.assertEqual(
                json.loads(stored[0]),
                {"format": "khaos-memory-v1", "items": {}},
            )
            self.assertFalse(
                run({"operation": "recall", "key": "project_codename"})["found"]
            )

    def test_candidate_b_uses_exact_then_unique_nfkc_casefold_fallback(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "memory-candidate-b"
            / "plugin.py"
        )
        stored = [
            b'{"format":"khaos-memory-v1","items":{"Name":"Alice","name":"Bob",'
            b'"project_codename":"Project K"}}'
        ]
        with patch("khaos.runner_sdk.state_read", side_effect=lambda: stored[0]):
            run = runpy.run_path(str(source))["run"]
            self.assertEqual(
                run({"operation": "recall", "key": "Name"})["value"],
                "Alice",
            )
            self.assertEqual(
                run({"operation": "recall", "key": "PROJECT_CODENAME"})["value"],
                "Project K",
            )
            self.assertEqual(
                run({
                    "operation": "recall",
                    "key": "ＰＲＯＪＥＣＴ＿ＣＯＤＥＮＡＭＥ",
                })["value"],
                "Project K",
            )
            self.assertFalse(run({"operation": "recall", "key": "NAME"})["found"])
            self.assertFalse(
                run({"operation": "recall", "key": " project_codename"})["found"]
            )
            self.assertEqual(stored[0], (
                b'{"format":"khaos-memory-v1","items":{"Name":"Alice","name":"Bob",'
                b'"project_codename":"Project K"}}'
            ))

    def test_candidate_b_fails_closed_on_incompatible_state_without_replacing_it(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "memory-candidate-b"
            / "plugin.py"
        )
        stored = [b'{"format":"khaos-memory-v0","items":{"key":"old"}}']
        with patch("khaos.runner_sdk.state_read", side_effect=lambda: stored[0]):
            run = runpy.run_path(str(source))["run"]
            with self.assertRaisesRegex(ValueError, "canonical khaos-memory-v1"):
                run({"operation": "recall", "key": "key"})
        self.assertEqual(stored[0], b'{"format":"khaos-memory-v0","items":{"key":"old"}}')


if __name__ == "__main__":
    unittest.main()
