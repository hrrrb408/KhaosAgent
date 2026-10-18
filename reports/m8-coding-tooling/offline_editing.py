"""Offline A/B/C editing prototypes for M8.5.1.

This module operates only on an in-memory mapping of fixture paths to bytes. It is
an algorithm comparison, not a filesystem, approval, sandbox, or Kernel model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import unicodedata
from typing import Mapping

MAX_PATCH_BYTES = 4096
MAX_ARGUMENT_BYTES = 4096


@dataclass(frozen=True)
class Outcome:
    status: str
    content: bytes | None = None
    detail: str = ""
    replacements: int = 0


def _text(data: bytes) -> str:
    return data.decode("utf-8", errors="strict")


def shell_replace(state: Mapping[str, bytes], path: str, old_text: str, new_text: str) -> Outcome:
    """Model the prompt's Path.read_text/str.replace/assert/write_text example."""
    if path not in state:
        return Outcome("TARGET_NOT_FOUND")
    try:
        original = _text(state[path])
    except UnicodeDecodeError:
        return Outcome("INVALID_ENCODING")
    if not old_text:
        return Outcome("INVALID_EDIT", detail="oldText must be non-empty")
    count = original.count(old_text)
    if count == 0:
        return Outcome("NO_MATCH")
    updated = original.replace(old_text, new_text)
    if updated == original:
        return Outcome("NO_CHANGE")
    return Outcome("SUCCESS", updated.encode("utf-8"), replacements=count)


def structured_edit(
    state: Mapping[str, bytes], path: str, old_text: str, new_text: str
) -> Outcome:
    """Model a minimal single-file edit that requires one exact unique match."""
    if not path or not old_text:
        return Outcome("INVALID_EDIT", detail="path and oldText must be non-empty")
    if path not in state:
        return Outcome("TARGET_NOT_FOUND")
    try:
        original = _text(state[path])
    except UnicodeDecodeError:
        return Outcome("INVALID_ENCODING")
    count = original.count(old_text)
    if count == 0:
        return Outcome("NO_MATCH")
    if count != 1:
        return Outcome("AMBIGUOUS_MATCH", detail=f"oldText occurs {count} times")
    updated = original.replace(old_text, new_text, 1)
    if updated == original:
        return Outcome("NO_CHANGE")
    return Outcome("SUCCESS", updated.encode("utf-8"), replacements=1)


def minimal_patch(state: Mapping[str, bytes], patch: str) -> Outcome:
    """Model one exact-context update hunk; other patch operations fail closed."""
    if len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
        return Outcome("PATCH_TOO_LARGE")
    lines = patch.splitlines()
    if len(lines) < 3 or lines[0] != "*** Begin Patch" or lines[-1] != "*** End Patch":
        return Outcome("INVALID_PATCH")
    entries = lines[1:-1]
    file_ops = [line for line in entries if line.startswith("*** ")]
    if len(file_ops) != 1 or not file_ops[0].startswith("*** Update File: "):
        return Outcome("UNSUPPORTED_FILE_OPERATION", detail="prototype accepts one update only")
    path = file_ops[0][len("*** Update File: ") :]
    if not path or path not in state:
        return Outcome("TARGET_NOT_FOUND")
    hunks = [i for i, line in enumerate(entries) if line == "@@"]
    if len(hunks) != 1:
        return Outcome("INVALID_PATCH", detail="prototype accepts one @@ hunk")
    body = entries[hunks[0] + 1 :]
    if not body:
        return Outcome("INVALID_PATCH")
    old_lines: list[str] = []
    new_lines: list[str] = []
    saw_change = False
    for line in body:
        if line.startswith("*** "):
            return Outcome("UNSUPPORTED_FILE_OPERATION")
        if not line:
            return Outcome("INVALID_PATCH", detail="patch body lines require a prefix")
        prefix, value = line[0], line[1:]
        if prefix == " ":
            old_lines.append(value)
            new_lines.append(value)
        elif prefix == "-":
            old_lines.append(value)
            saw_change = True
        elif prefix == "+":
            new_lines.append(value)
            saw_change = True
        else:
            return Outcome("INVALID_PATCH", detail=f"invalid body prefix {prefix!r}")
    if not saw_change or not old_lines:
        return Outcome("INVALID_PATCH", detail="update needs context and a change")
    try:
        original = _text(state[path])
    except UnicodeDecodeError:
        return Outcome("INVALID_ENCODING")
    had_trailing_newline = original.endswith("\n")
    original_lines = original.splitlines()
    width = len(old_lines)
    matches = [
        i
        for i in range(len(original_lines) - width + 1)
        if original_lines[i : i + width] == old_lines
    ]
    if not matches:
        return Outcome("NO_MATCH", detail="patch context not found")
    if len(matches) != 1:
        return Outcome("AMBIGUOUS_MATCH", detail=f"patch context occurs {len(matches)} times")
    start = matches[0]
    updated_lines = original_lines[:start] + new_lines + original_lines[start + width :]
    updated = "\n".join(updated_lines) + ("\n" if had_trailing_newline else "")
    if updated == original:
        return Outcome("NO_CHANGE")
    return Outcome("SUCCESS", updated.encode("utf-8"), replacements=1)


def runner_arguments(path: str, old_text: str, new_text: str) -> list[str]:
    """Encode multiline text as bounded single-line argv JSON strings."""
    script = (
        "import json,sys; from pathlib import Path; "
        "p=Path(sys.argv[1]); old=json.loads(sys.argv[2]); new=json.loads(sys.argv[3]); "
        "data=p.read_bytes(); text=data.decode('utf-8'); count=text.count(old); "
        "assert count == 1; p.write_bytes(text.replace(old,new,1).encode('utf-8'))"
    )
    arguments = [
        "python3", "-I", "-B", "-c", script, path,
        json.dumps(old_text, ensure_ascii=True, separators=(",", ":")),
        json.dumps(new_text, ensure_ascii=True, separators=(",", ":")),
    ]
    try:
        path_bytes = path.encode("utf-8", errors="strict")
        old_text.encode("utf-8", errors="strict")
        new_text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError("path and edit text must be valid UTF-8") from error
    if not path or len(path_bytes) > 128:
        raise ValueError("path must fit the existing 128-byte scope bound")
    if any(unicodedata.category(char) in {"Cc", "Cf"} for char in path):
        raise ValueError("path must be a single-line argv value")
    if any(len(item.encode("utf-8")) > MAX_ARGUMENT_BYTES for item in arguments):
        raise ValueError("encoded argv item exceeds the existing argument bound")
    return arguments


def representative_actions() -> dict[str, dict[str, object]]:
    """Return one bounded representative proposal for the same edit."""
    path = "src/calc.py"
    old_text = "return 40"
    new_text = "return 42"
    script = (
        "from pathlib import Path; p=Path('src/calc.py'); "
        "old='return 40'; new='return 42'; text=p.read_text(); "
        "updated=text.replace(old,new); assert updated != text; p.write_text(updated)"
    )
    patch = (
        "*** Begin Patch\n*** Update File: src/calc.py\n@@\n"
        " def answer():\n-    return 40\n+    return 42\n*** End Patch"
    )
    return {
        "A": {
            "type": "shell",
            "text": "",
            "argv": ["python3", "-I", "-B", "-c", script],
            "readScope": [path],
            "writeScope": [path],
            "pluginID": "",
            "candidateDigest": "",
            "generation": 0,
            "pluginInput": "",
            "evolutionGoal": "",
        },
        "B": {"type": "edit", "path": path, "oldText": old_text, "newText": new_text},
        "C": {"type": "patch", "patch": patch},
    }


def representative_metrics() -> dict[str, dict[str, int]]:
    actions = representative_actions()
    return {
        name: {
            "top_level_fields": len(action),
            "nonempty_values_including_type": sum(value not in ("", [], 0) for value in action.values()),
            "compact_json_utf8_bytes": len(
                json.dumps(action, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            ),
        }
        for name, action in actions.items()
    }


def security_cases() -> dict[str, str]:
    """Security is intentionally not simulated by these pure edit algorithms."""
    return {
        "path_traversal": "NOT_PROVEN",
        "symlink_escape": "NOT_PROVEN",
        "hardlink_or_alias": "NOT_PROVEN",
        "rename_or_toctou_race": "NOT_PROVEN",
        "write_scope_enforcement": "NOT_PROVEN",
        "approval_denial": "NOT_PROVEN",
        "sandbox_rejection": "NOT_PROVEN",
        "snapshot_changeset_validation": "NOT_PROVEN",
    }


def outcome_dict(outcome: Outcome) -> dict[str, object]:
    result = asdict(outcome)
    if result["content"] is not None:
        result["content"] = result["content"].decode("utf-8", errors="replace")
    return result
