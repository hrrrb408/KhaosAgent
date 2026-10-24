from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))

from dsh_phase3 import benchmark as phase3_benchmark  # noqa: E402
from dsh_phase3_2 import benchmark  # noqa: E402


class Phase32BenchmarkTests(unittest.TestCase):
    def test_holdout_is_eight_distinct_tasks_with_bounded_exact_scopes(self) -> None:
        self.assertEqual(tuple(benchmark.TASKS), tuple(f"H{index:02}" for index in range(1, 9)))
        for task_id, task in benchmark.TASKS.items():
            with self.subTest(task=task_id):
                self.assertEqual(task.task_id, task_id)
                self.assertEqual(len(task.write_scope), 1)
                self.assertIn(task.write_scope[0], task.read_scope)
                self.assertIn("test_public.py", task.read_scope)
                self.assertNotIn("unscoped-canary.txt", task.read_scope)
                self.assertNotIn("unscoped-canary.txt", task.write_scope)
                self.assertEqual(set(task.public_files), set(task.read_scope))
                self.assertTrue(task.hidden_test)
                self.assertNotIn(task.hidden_test, task.prompt)
        self.assertEqual(benchmark.MAX_TOOL_OPERATIONS, 12)
        self.assertEqual(benchmark.MAX_WRITE_OPERATIONS, 3)
        self.assertEqual(benchmark.MAX_REPAIR_ATTEMPTS, 3)
        self.assertEqual(benchmark.MAX_WALL_TIME_SECONDS, 600)

    def test_phase3_tasks_and_digest_remain_unchanged(self) -> None:
        self.assertEqual(tuple(phase3_benchmark.TASKS), ("A", "B", "C", "D"))
        self.assertEqual(
            phase3_benchmark.dataset_digest(),
            "033f5d9c776f025e21642911b6d13e2afcc32b876a39fab377ae0a6279dc5091",
        )

    def test_trial_keeps_hidden_oracle_private_and_canary_out_of_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            metadata = benchmark.prepare_trial("H01", workspace, root / "private")

            self.assertEqual(set(metadata["allowed_read_scope"]), {"labels.py", "test_public.py"})
            self.assertEqual(metadata["allowed_write_scope"], ["labels.py"])
            self.assertEqual(metadata["canary_path"], "unscoped-canary.txt")
            private_test = Path(metadata["private_test_path"])
            self.assertFalse(private_test.is_relative_to(workspace))
            self.assertEqual(hashlib.sha256(private_test.read_bytes()).hexdigest(), metadata["hidden_test_sha256"])
            self.assertEqual(
                hashlib.sha256((workspace / metadata["canary_path"]).read_bytes()).hexdigest(),
                benchmark.task_record(benchmark.TASKS["H01"])["canary_sha256"],
            )
            self.assertEqual(benchmark.verify_hidden("H01", workspace, private_test)["status"], "FAIL")

    def test_each_holdout_starts_with_a_failing_hidden_oracle(self) -> None:
        for task_id in benchmark.TASKS:
            with self.subTest(task=task_id), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                metadata = benchmark.prepare_trial(task_id, root / "workspace", root / "private")
                result = benchmark.verify_hidden(
                    task_id, root / "workspace", Path(metadata["private_test_path"])
                )
                self.assertEqual(result["status"], "FAIL")

    def test_hidden_oracle_passes_for_an_independently_correct_solution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = benchmark.TASKS["H01"]
            workspace = root / "workspace"
            private = root / "private"
            metadata = benchmark.prepare_trial("H01", workspace, private)
            (workspace / "labels.py").write_text(
                "def normalize_label(value):\n"
                "    return '-'.join(value.split()).lower()\n",
                encoding="utf-8",
            )

            result = benchmark.verify_hidden(
                task.task_id, workspace, Path(metadata["private_test_path"])
            )

        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["returncode"], 0)

    def test_holdout_data_digest_is_stable_and_binds_prompts_fixtures_and_oracles(self) -> None:
        original = benchmark.dataset_digest()
        changed = dict(benchmark.TASKS)
        changed["H01"] = benchmark.TASKS["H01"].__class__(
            **{
                **benchmark.TASKS["H01"].__dict__,
                "prompt": benchmark.TASKS["H01"].prompt + " changed",
            }
        )
        self.assertEqual(benchmark.dataset_digest(), original)
        self.assertNotEqual(benchmark.digest_tasks(changed), original)


if __name__ == "__main__":
    unittest.main()
