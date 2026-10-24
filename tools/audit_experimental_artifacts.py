"""Validate an exact local artifact manifest without changing its candidates."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.experimental_artifact_retention import (
    load_manifest,
    require_private_directory,
    validate_manifest,
    write_private_file,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="read and validate exact manifest entries only (the only supported mode)")
    parser.add_argument("--output", type=Path,
                        help="optional new owner-only JSON result file")
    args = parser.parse_args()
    try:
        manifest, manifest_sha256 = load_manifest(args.manifest.expanduser().absolute())
        results = validate_manifest(manifest)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.exit(2, f"artifact-audit: REFUSE: {error}\n")

    summary = {
        "schema": 1,
        "mode": "DRY_RUN_READ_ONLY",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_sha256": manifest_sha256,
        "candidate_count": len(results),
        "ready_pending_owner_approval": sum(item["status"] == "READY_PENDING_OWNER_APPROVAL" for item in results),
        "refused": sum(item["status"] == "REFUSE" for item in results),
        "estimated_reclaimable_bytes": None,
        "apfs_exclusive_reclaimable_bytes": "UNKNOWN",
        "candidates": results,
        "mutations_performed": 0,
    }
    payload = (json.dumps(summary, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if args.output is not None:
        output = args.output.expanduser().absolute()
        if output.exists() or output.is_symlink():
            parser.error("--output must be a new file")
        try:
            if not output.parent.is_dir():
                raise ValueError("output parent must already exist")
            require_private_directory(output.parent)
        except (OSError, ValueError) as error:
            parser.error(f"--output parent must be owner-only: {error}")
        write_private_file(output, payload)
    sys.stdout.write(payload.decode("utf-8"))
    return 2 if summary["refused"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
