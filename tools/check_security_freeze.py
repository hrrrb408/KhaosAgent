"""Check the reviewed TCB inventory and classify changes against a Git baseline.

This is a development/CI gate, not a runtime authority or a substitute for review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "security/tcb-manifest.json"
UNTRUSTED_SWIFT = {"AgentHost.swift", "AgentHostActionOutput.swift", "AgentHostCandidateSource.swift"}


def protected(path: str) -> bool:
    return (
        path.startswith(("security/", ".github/", "tests/", "khaos/kernel/"))
        or (path.startswith("khaos/macos/") and Path(path).name not in UNTRUSTED_SWIFT)
        or path in {"khaos/__init__.py", "khaos/ipc.py", "khaos/launcher.py",
                    "tools/build_macos_seed.py", "tools/check_security_freeze.py",
                    "reports/security-kernel-finalization/protected_install_experiment.py",
                    "reports/security-kernel-finalization/same_uid_experiment.py",
                    "AGENTS.md", "SECURITY.md", "docs/KERNEL_ABI.md",
                    "docs/Khaos vNext 架构设计文档.md", "docs/SECURITY_FREEZE.md",
                    "docs/SELF_HOSTING.md", "docs/SEED_THREAT_MODEL.md"}
    )


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True)


def verify_manifest(root: Path) -> None:
    manifest_bytes = (root / MANIFEST).read_bytes()
    manifest = json.loads(manifest_bytes)
    baseline = json.loads((root / "security/freeze-baseline.json").read_text())
    if baseline["manifest_sha256"] != hashlib.sha256(manifest_bytes).hexdigest():
        raise ValueError("baseline manifest digest mismatch")
    seen = set()
    for entry in manifest["files"]:
        path = entry["path"]
        if path in seen or Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError("invalid or duplicate manifest path")
        seen.add(path)
        source = root / path
        if source.resolve() != root.resolve() / path or source.is_symlink() or not source.is_file():
            raise ValueError(f"missing or symlinked input: {path}")
        if hashlib.sha256(source.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"freeze digest mismatch: {path}")
        if not entry["boundary"] or not entry["tests"] or entry["role"] not in {
            "runtime-tcb", "build-governance", "development-enforcement"
        }:
            raise ValueError(f"incomplete manifest entry: {path}")
    expected = {p for p in git(root, "ls-files", "-z").split("\0") if protected(p)
                and not p.startswith("security/")}
    if expected != seen:
        raise ValueError(f"inventory differs: {sorted(expected ^ seen)}")


def check_changes(root: Path, base: str) -> list[str]:
    # Read the base inventory as data. Never execute a checker from the proposed tree.
    baseline = json.loads(git(root, "show", f"{base}:{MANIFEST}"))
    frozen = {e["path"] for e in baseline["files"]}
    changed = git(root, "diff", "--name-only", "-z", "--no-renames", base, "--").split("\0")
    sensitive = sorted(p for p in changed if p in frozen or protected(p))
    if not sensitive:
        return []
    note_path = "security/security-change.json"
    if note_path not in changed:
        raise ValueError("trusted change requires a fresh security/security-change.json")
    note = json.loads((root / note_path).read_text())
    if note["base"] != base or sorted(note["files"]) != sensitive:
        raise ValueError("security declaration must bind base and exact sensitive paths")
    for field in ("motivation", "invariants", "authority_delta", "real_os_tests", "trusted_delta", "baseline_decision"):
        if not isinstance(note.get(field), str) or not note[field].strip():
            raise ValueError(f"security declaration missing {field}")
    return sensitive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--base")
    args = parser.parse_args()
    try:
        verify_manifest(args.root)
        changed = check_changes(args.root, args.base) if args.base else []
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"security-freeze: {error}\n")
    print(f"security-freeze: verified; sensitive changes={len(changed)}; independent approval is external")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
