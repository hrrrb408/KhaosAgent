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


if __name__ == "__main__":
    unittest.main()
