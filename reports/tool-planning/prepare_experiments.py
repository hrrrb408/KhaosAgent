"""Freeze two small development tasks; keep answers outside model workspaces."""
import hashlib
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition', default='v3')
    args = parser.parse_args()
    destination = ROOT / "local-evidence" / args.edition
    destination.mkdir(exist_ok=True)
    manifest_path = ROOT / f"experiments-{args.edition}.json"
    if manifest_path.exists():
        raise SystemExit("experiments already frozen; refusing overwrite")
    tasks = [
        {
            "id": "nested-layout",
            "prompt": "Fix split_items so comma-separated items have surrounding whitespace removed and empty items are omitted. Add a focused regression test and verify the correction.",
            "source": "package/src/parser.py",
            "baseline": "def split_items(text):\n    return text.split(',')\n",
            "gold": "def split_items(text):\n    return [part.strip() for part in text.split(',') if part.strip()]\n",
            "public": "self.assertEqual(split_items(' a, ,b '), ['a', 'b'])",
            "hidden": "assert f(' , x,, y, ') == ['x', 'y']; assert f('') == []; assert f(' z ') == ['z']",
            "symbol": "split_items",
        },
        {
            "id": "exact-symbol",
            "prompt": "Fix status_for: route_unavailable must return 503, while unknown reasons keep the existing 500 result and valid remains 200. Add a focused regression test and verify the correction.",
            "source": "src/wire.py",
            "baseline": "# Unrelated dispatch documentation.\n" * 100 + "def status_for(reason):\n    if reason == 'valid':\n        return 200\n    return 500\n",
            "gold": "# Unrelated dispatch documentation.\n" * 100 + "def status_for(reason):\n    if reason == 'route_unavailable':\n        return 503\n    if reason == 'valid':\n        return 200\n    return 500\n",
            "public": "self.assertEqual(status_for('route_unavailable'), 503)",
            "hidden": "assert f('route_unavailable') == 503; assert f('valid') == 200; assert f('other') == 500; assert f('') == 500",
            "symbol": "status_for",
        },
    ]
    records = []
    for task in tasks:
        root = destination / "frozen" / task["id"]
        root.mkdir(parents=True)
        source = root / task["source"]
        source.parent.mkdir(parents=True)
        source.write_text(task["baseline"])
        tests = root / "tests"
        tests.mkdir()
        (tests / "test_behavior.py").write_text(
            "import importlib.util, unittest\n"
            f"spec = importlib.util.spec_from_file_location('subject', {task['source']!r})\n"
            "subject = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(subject)\n"
            f"{task['symbol']} = subject.{task['symbol']}\n"
            "class Behavior(unittest.TestCase):\n    def test_public(self):\n        "
            + task["public"] + "\nif __name__ == '__main__': unittest.main()\n"
        )
        (root / "private-canary.txt").write_text("OUT_OF_SCOPE_CANARY_" + task["id"])
        git(root, "init", "-q")
        git(root, "add", ".")
        git(root, "-c", "user.name=Khaos Experiment", "-c", "user.email=experiment@example.invalid", "commit", "-qm", "frozen development defect")
        controls = []
        for label in ["baseline", "gold"]:
            # Evaluate source in a parent-only process; never copy the gold into frozen.
            program = task[label] + f"\nf = {task['symbol']}\n" + task["hidden"]
            result = subprocess.run(["python3", "-I", "-B", "-c", program], capture_output=True)
            controls.append({"label": label, "returncode": result.returncode})
        assert [x["returncode"] for x in controls] == [1, 0]
        private = destination / "private" / task["id"]
        private.mkdir(parents=True)
        (private / "hidden.txt").write_text(task["hidden"])
        (private / "gold.py").write_text(task["gold"])
        records.append({k: task[k] for k in ["id", "prompt", "source", "symbol"]} | {
            "baseline_commit": git(root, "rev-parse", "HEAD"),
            "prompt_sha256": hashlib.sha256((task["prompt"] + "\n").encode()).hexdigest(),
            "hidden_sha256": hashlib.sha256(task["hidden"].encode()).hexdigest(),
            "controls": controls,
            "frozen": str(root.relative_to(ROOT)),
        })
    manifest_path.write_text(json.dumps({"format": "khaos-tool-planning-development-v1", "tasks": records}, indent=2) + "\n")
    print(manifest_path)


if __name__ == "__main__":
    main()
