"""Deterministic, in-memory edit-algorithm checks for the M8.5.1 review."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "reports" / "m8-coding-tooling" / "offline_editing.py"
SPEC = importlib.util.spec_from_file_location("m8_5_1_offline_editing", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
OFFLINE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = OFFLINE
SPEC.loader.exec_module(OFFLINE)


FIXTURE = "def answer():\n    return 40\n"
EDIT_PATCH = (
    "*** Begin Patch\n*** Update File: src/calc.py\n@@\n"
    " def answer():\n-    return 40\n+    return 42\n*** End Patch"
)


class OfflineEditingTests(unittest.TestCase):
    def test_all_candidates_apply_the_same_unique_edit(self) -> None:
        state = {"src/calc.py": FIXTURE.encode()}
        results = (
            OFFLINE.shell_replace(state, "src/calc.py", "return 40", "return 42"),
            OFFLINE.structured_edit(state, "src/calc.py", "return 40", "return 42"),
            OFFLINE.minimal_patch(state, EDIT_PATCH),
        )
        for result in results:
            with self.subTest(candidate=result):
                self.assertEqual("SUCCESS", result.status)
                self.assertEqual("def answer():\n    return 42\n".encode(), result.content)

    def test_baseline_shell_replace_changes_every_duplicate_occurrence(self) -> None:
        state = {"src/calc.py": b"a=return 40\nb=return 40\n"}
        result = OFFLINE.shell_replace(state, "src/calc.py", "return 40", "return 42")
        self.assertEqual("SUCCESS", result.status)
        self.assertEqual(2, result.replacements)
        self.assertEqual(b"a=return 42\nb=return 42\n", result.content)

    def test_structured_edit_rejects_duplicate_old_text_without_mutation(self) -> None:
        state = {"src/calc.py": b"a=return 40\nb=return 40\n"}
        result = OFFLINE.structured_edit(state, "src/calc.py", "return 40", "return 42")
        self.assertEqual("AMBIGUOUS_MATCH", result.status)
        self.assertIsNone(result.content)
        self.assertEqual(b"a=return 40\nb=return 40\n", state["src/calc.py"])

    def test_patch_context_can_select_one_duplicate_target(self) -> None:
        state = {"src/calc.py": b"def first():\n    return 40\n\ndef second():\n    return 40\n"}
        patch = (
            "*** Begin Patch\n*** Update File: src/calc.py\n@@\n"
            " def first():\n-    return 40\n+    return 42\n*** End Patch"
        )
        result = OFFLINE.minimal_patch(state, patch)
        self.assertEqual("SUCCESS", result.status)
        self.assertEqual(
            b"def first():\n    return 42\n\ndef second():\n    return 40\n",
            result.content,
        )

    def test_changed_target_text_returns_no_match(self) -> None:
        state = {"src/calc.py": b"def answer():\n    return 41\n"}
        self.assertEqual(
            "NO_MATCH",
            OFFLINE.structured_edit(state, "src/calc.py", "return 40", "return 42").status,
        )
        stale_patch = EDIT_PATCH.replace("return 40", "return 40")
        self.assertEqual("NO_MATCH", OFFLINE.minimal_patch(state, stale_patch).status)

    def test_structured_edit_does_not_detect_unrelated_content_drift(self) -> None:
        state = {"src/calc.py": b"# changed after read\ndef answer():\n    return 40\n"}
        result = OFFLINE.structured_edit(state, "src/calc.py", "return 40", "return 42")
        self.assertEqual("SUCCESS", result.status)
        self.assertIn(b"# changed after read", result.content or b"")

    def test_missing_file_is_rejected(self) -> None:
        state: dict[str, bytes] = {}
        self.assertEqual(
            "TARGET_NOT_FOUND",
            OFFLINE.structured_edit(state, "src/missing.py", "old", "new").status,
        )
        self.assertEqual("TARGET_NOT_FOUND", OFFLINE.minimal_patch(state, EDIT_PATCH).status)

    def test_create_delete_and_multifile_patch_operations_are_not_in_minimal_interface(self) -> None:
        state = {"src/calc.py": FIXTURE.encode()}
        for operation in (
            "*** Add File: src/new.py\n+new\n",
            "*** Delete File: src/calc.py\n",
            "*** Update File: src/calc.py\n@@\n-def answer():\n+def answer():\n"
            "*** Update File: src/other.py\n@@\n-old\n+new\n",
        ):
            with self.subTest(operation=operation):
                patch = f"*** Begin Patch\n{operation}*** End Patch"
                self.assertEqual("UNSUPPORTED_FILE_OPERATION", OFFLINE.minimal_patch(state, patch).status)

    def test_patch_with_missing_context_fails_without_partial_result(self) -> None:
        state = {"src/calc.py": FIXTURE.encode()}
        invalid_context = EDIT_PATCH.replace("return 40", "return missing")
        result = OFFLINE.minimal_patch(state, invalid_context)
        self.assertEqual("NO_MATCH", result.status)
        self.assertIsNone(result.content)
        self.assertEqual(FIXTURE.encode(), state["src/calc.py"])

    def test_malformed_and_oversized_patch_fail_closed(self) -> None:
        state = {"src/calc.py": FIXTURE.encode()}
        self.assertEqual("INVALID_PATCH", OFFLINE.minimal_patch(state, "*** Begin Patch\n*** Update File: src/calc.py" ).status)
        self.assertEqual(
            "PATCH_TOO_LARGE",
            OFFLINE.minimal_patch(state, "x" * (OFFLINE.MAX_PATCH_BYTES + 1)).status,
        )

    def test_invalid_utf8_is_rejected(self) -> None:
        state = {"src/calc.py": b"\xff\xfe"}
        for result in (
            OFFLINE.shell_replace(state, "src/calc.py", "old", "new"),
            OFFLINE.structured_edit(state, "src/calc.py", "old", "new"),
            OFFLINE.minimal_patch(state, EDIT_PATCH),
        ):
            with self.subTest(result=result):
                self.assertEqual("INVALID_ENCODING", result.status)

    def test_multiline_text_is_json_encoded_into_bounded_single_line_argv(self) -> None:
        old_text = "def answer():\n    return 40\n"
        new_text = "def answer():\n    return 42\n"
        argv = OFFLINE.runner_arguments("src/calc.py", old_text, new_text)
        self.assertEqual(8, len(argv))
        self.assertTrue(all("\n" not in item and "\t" not in item for item in argv))
        self.assertEqual(old_text, json.loads(argv[6]))
        self.assertEqual(new_text, json.loads(argv[7]))
        with self.assertRaises(ValueError):
            OFFLINE.runner_arguments("src/calc.py", "\n" * 3000, "new")

    def test_runner_arguments_enforce_the_existing_scope_path_bound(self) -> None:
        with self.assertRaises(ValueError):
            OFFLINE.runner_arguments("x" * 129, "old", "new")
        with self.assertRaises(ValueError):
            OFFLINE.runner_arguments("src/\u200bcalc.py", "old", "new")

    def test_comparison_metrics_are_computed_from_serialized_examples(self) -> None:
        metrics = OFFLINE.representative_metrics()
        self.assertEqual(10, metrics["A"]["top_level_fields"])
        self.assertEqual(4, metrics["B"]["top_level_fields"])
        self.assertEqual(2, metrics["C"]["top_level_fields"])
        self.assertGreater(metrics["A"]["compact_json_utf8_bytes"], metrics["B"]["compact_json_utf8_bytes"])

    def test_security_matrix_does_not_claim_offline_proof(self) -> None:
        cases = OFFLINE.security_cases()
        self.assertGreaterEqual(len(cases), 8)
        self.assertEqual({"NOT_PROVEN"}, set(cases.values()))


if __name__ == "__main__":
    unittest.main()
