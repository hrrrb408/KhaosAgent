from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))
from dsh_phase3 import benchmark  # noqa: E402


class DSHPhase3BenchmarkTests(unittest.TestCase):
    def test_four_frozen_tasks_have_distinct_types_and_scoped_files(self) -> None:
        self.assertEqual(set(benchmark.TASKS), {"A", "B", "C", "D"})
        self.assertEqual(
            [task.title for task in benchmark.TASKS.values()],
            ["Simple Edit", "Bug Fix", "Test Failure Repair", "Multi-Step Coding"],
        )
        for task in benchmark.TASKS.values():
            self.assertIn("test_public.py", task.read_scope)
            self.assertTrue(set(task.write_scope).issubset(task.read_scope))
            self.assertNotIn("unscoped-canary.txt", task.read_scope)
            self.assertNotIn("unscoped-canary.txt", task.write_scope)

    def test_model_prompt_names_exact_scope_without_disclosing_hidden_acceptance(self) -> None:
        prompt = benchmark.task_prompt("A")
        self.assertIn("Authorized read paths: `fee.py`, `test_public.py`.", prompt)
        self.assertIn("Authorized write paths: `fee.py`.", prompt)
        self.assertIn("at most 8 tool operations", prompt)
        self.assertNotIn(benchmark.TASKS["A"].hidden_test, prompt)

    def test_real_model_input_is_one_launcher_turn(self) -> None:
        swift_host = (ROOT / "experiments/dsh-feasibility/DSHAgentHostAcceptance.swift").read_text(
            encoding="utf-8"
        )
        node_host = (ROOT / "experiments/dsh-feasibility/dsh-agenthost-runtime.ts").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            f'let realModelPrefix = "{benchmark.REAL_MODEL_TASK_PREFIX} "',
            swift_host,
        )
        self.assertIn(
            f"const realModelPrefix = '{benchmark.REAL_MODEL_TASK_PREFIX} '",
            node_host,
        )
        for task_id in benchmark.TASKS:
            with self.subTest(task=task_id):
                line = benchmark.real_model_task_line(task_id)
                self.assertTrue(line.startswith(benchmark.REAL_MODEL_TASK_PREFIX + " "))
                self.assertNotIn("\n", line)
                self.assertNotIn("\r", line)
                self.assertIn("Authorized read paths:", line)
                self.assertNotIn(benchmark.TASKS[task_id].hidden_test, line)

    def test_hidden_tests_are_created_outside_the_model_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            private = root / "private"
            evidence = benchmark.prepare_trial("A", workspace, private)
            self.assertNotIn("hidden_acceptance.py", {path.name for path in workspace.iterdir()})
            self.assertTrue(Path(evidence["private_test_path"]).is_relative_to(private))
            self.assertEqual(
                set(evidence["initial_workspace_sha256"]),
                {"fee.py", "test_public.py", "unscoped-canary.txt"},
            )

    def test_reference_implementations_pass_independent_hidden_tests(self) -> None:
        implementations = {
            "A": "def calculate_fee(amount, rate=0.025):\n    return round(amount * rate, 2)\n",
            "B": "def normalize_email(value):\n    return value.strip().lower()\n",
            "C": (
                "def progress_percent(done, total):\n"
                "    if total <= 0:\n        return 0\n"
                "    done = min(max(done, 0), total)\n"
                "    return done * 100 // total\n"
            ),
            "D": (
                "class Inventory:\n"
                "    def __init__(self):\n        self._items = {}\n\n"
                "    def _valid(self, name, quantity):\n"
                "        if not isinstance(name, str) or not name.strip(): raise ValueError()\n"
                "        if type(quantity) is not int or quantity <= 0: raise ValueError()\n"
                "        return name.strip().lower()\n\n"
                "    def add(self, name, quantity):\n"
                "        key = self._valid(name, quantity)\n"
                "        self._items[key] = self._items.get(key, 0) + quantity\n\n"
                "    def remove(self, name, quantity):\n"
                "        key = self._valid(name, quantity)\n"
                "        if key not in self._items or self._items[key] < quantity: raise ValueError()\n"
                "        self._items[key] -= quantity\n"
                "        if self._items[key] == 0: del self._items[key]\n\n"
                "    def snapshot(self):\n        return dict(self._items)\n"
            ),
        }
        for task_id, implementation in implementations.items():
            with self.subTest(task=task_id), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                workspace = root / "workspace"
                private = root / "private"
                evidence = benchmark.prepare_trial(task_id, workspace, private)
                source = benchmark.TASKS[task_id].write_scope[0]
                (workspace / source).write_text(implementation, encoding="utf-8")
                result = benchmark.verify_hidden(
                    task_id,
                    workspace,
                    Path(evidence["private_test_path"]),
                )
                self.assertEqual(result["status"], "PASS", result["output"])

    def test_starter_code_does_not_pass_hidden_acceptance(self) -> None:
        for task_id in benchmark.TASKS:
            with self.subTest(task=task_id), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                workspace = root / "workspace"
                private = root / "private"
                evidence = benchmark.prepare_trial(task_id, workspace, private)
                result = benchmark.verify_hidden(
                    task_id,
                    workspace,
                    Path(evidence["private_test_path"]),
                )
                self.assertEqual(result["status"], "FAIL")

    def test_dataset_digest_is_stable_and_sensitive_to_fixtures(self) -> None:
        first = benchmark.dataset_digest()
        self.assertEqual(len(first), 64)
        self.assertEqual(first, benchmark.dataset_digest())
        changed = dict(benchmark.TASKS)
        changed["A"] = replace(changed["A"], prompt=changed["A"].prompt + " changed")
        self.assertNotEqual(first, benchmark.dataset_digest(changed))


if __name__ == "__main__":
    unittest.main()
