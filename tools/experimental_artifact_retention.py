"""Read-only artifact inspection and bounded experimental build preflight."""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import stat
import subprocess
import tempfile
from typing import Callable

GIB = 1024**3
MODEL_MAX_BYTES = 24 * GIB
BUILD_FIXED_RESERVE_BYTES = 2 * GIB
BUILD_PERCENT_RESERVE = 0.10
MAX_TREE_ENTRIES = 100_000
MAX_TREE_DEPTH = 64
MAX_DIAGNOSTIC_FILE_BYTES = 2 * 1024 * 1024
MAX_DIAGNOSTIC_WORKSPACE_BYTES = 32 * 1024 * 1024
MAX_DIAGNOSTIC_WORKSPACE_FILES = 1_000


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def manifest_sidecar(path: Path) -> Path:
    return path.with_suffix(".sha256")


def require_private_directory(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ValueError("evidence directory must be a real directory")
    if path.resolve(strict=True) != path:
        raise ValueError("evidence directory path must be canonical")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("evidence directory must be owner-only")


def write_private_file(path: Path, payload: bytes) -> None:
    """Create a new owner-only file; never overwrite existing evidence."""
    require_private_directory(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def write_manifest(path: Path, manifest: dict[str, object]) -> str:
    payload = canonical_json(manifest)
    digest = sha256_bytes(payload)
    require_private_directory(path.parent)
    write_private_file(path, payload)
    write_private_file(manifest_sidecar(path), f"{digest}  {path.name}\n".encode())
    return digest


def load_manifest(path: Path) -> tuple[dict[str, object], str]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("manifest must be a regular, non-symlink file")
    if path.stat().st_uid != os.getuid() or stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("manifest file must be owner-only")
    require_private_directory(path.parent)
    payload = path.read_bytes()
    sidecar = manifest_sidecar(path)
    if sidecar.is_symlink() or not sidecar.is_file():
        raise ValueError("manifest checksum sidecar is missing or unsafe")
    if sidecar.stat().st_uid != os.getuid() or stat.S_IMODE(sidecar.stat().st_mode) & 0o077:
        raise ValueError("manifest checksum sidecar must be owner-only")
    expected = sidecar.read_text(encoding="ascii").strip().split()
    digest = sha256_bytes(payload)
    if len(expected) != 2 or expected[0] != digest or expected[1] != path.name:
        raise ValueError("manifest checksum mismatch")
    manifest = json.loads(payload)
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise ValueError("unsupported manifest schema")
    if not isinstance(manifest.get("candidates"), list):
        raise ValueError("manifest candidates must be a list")
    return manifest, digest


def _entry(path: Path, relative: str, info: os.stat_result) -> dict[str, object]:
    mode = info.st_mode
    if stat.S_ISDIR(mode):
        kind = "directory"
    elif stat.S_ISREG(mode):
        kind = "file"
    elif stat.S_ISLNK(mode):
        kind = "symlink"
    else:
        kind = "special"
    record = {
        "path": relative,
        "kind": kind,
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": stat.S_IMODE(mode),
        "size_bytes": info.st_size,
        "allocated_bytes": getattr(info, "st_blocks", 0) * 512,
        "mtime_ns": info.st_mtime_ns,
        "link_count": info.st_nlink,
    }
    if kind == "symlink":
        record["link_target"] = os.readlink(path)
    return record


def inventory_path(path: Path) -> dict[str, object]:
    """Inventory metadata only; never opens candidate file contents."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("candidate path must be normalized and absolute")
    if path.is_symlink():
        raise ValueError("candidate root is a symlink")
    root = path.resolve(strict=True)
    if root != path:
        raise ValueError("candidate path is not canonical")
    entries: list[dict[str, object]] = []
    errors: list[str] = []
    logical_bytes = 0
    allocated_bytes = 0
    stack: list[tuple[Path, str, int]] = [(root, ".", 0)]
    while stack:
        current, relative, depth = stack.pop()
        if depth > MAX_TREE_DEPTH:
            raise ValueError("candidate tree exceeds maximum depth")
        info = current.lstat()
        record = _entry(current, relative, info)
        entries.append(record)
        if len(entries) > MAX_TREE_ENTRIES:
            raise ValueError("candidate tree exceeds maximum entry count")
        if record["kind"] == "symlink":
            try:
                target = Path(str(record["link_target"]))
                resolved_target = target if target.is_absolute() else current.parent / target
                if not _is_within(resolved_target.resolve(strict=False), root):
                    errors.append(f"escaping_symlink:{relative}")
            except (OSError, RuntimeError):
                errors.append(f"unresolvable_symlink:{relative}")
            continue
        if record["kind"] == "file" and info.st_nlink != 1:
            errors.append(f"hard_linked_entry:{relative}")
        if record["kind"] == "special":
            errors.append(f"special_file:{relative}")
            continue
        if record["kind"] == "file":
            logical_bytes += info.st_size
            allocated_bytes += getattr(info, "st_blocks", 0) * 512
        elif record["kind"] == "directory":
            try:
                children = sorted(current.iterdir(), key=lambda child: child.name, reverse=True)
            except OSError as error:
                errors.append(f"unreadable_directory:{relative}:{type(error).__name__}")
                continue
            stack.extend(
                (child, child.relative_to(root).as_posix(), depth + 1)
                for child in children
            )
    entries.sort(key=lambda item: str(item["path"]))
    fingerprint = sha256_bytes(canonical_json(entries))
    root_info = root.lstat()
    return {
        "canonical_path": str(root),
        "device": root_info.st_dev,
        "inode": root_info.st_ino,
        "kind": "directory" if stat.S_ISDIR(root_info.st_mode) else "file",
        "logical_bytes": logical_bytes,
        "allocated_bytes": allocated_bytes,
        "entry_count": len(entries),
        "tree_fingerprint_sha256": fingerprint,
        "errors": errors,
    }


def capture_candidate(candidate: dict[str, object]) -> dict[str, object]:
    path = Path(str(candidate["path"]))
    observed = inventory_path(path)
    return {
        **candidate,
        "canonical_path": observed["canonical_path"],
        "expected_device": observed["device"],
        "expected_inode": observed["inode"],
        "expected_size_bytes": observed["logical_bytes"],
        "expected_allocated_bytes": observed["allocated_bytes"],
        "expected_entry_count": observed["entry_count"],
        "expected_tree_fingerprint_sha256": observed["tree_fingerprint_sha256"],
        "inventory_errors": observed["errors"],
        "active_processes": candidate.get("active_processes", []),
        "estimated_reclaimable_bytes": None,
    }


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def lsof_references(path: Path, *, timeout: int = 20) -> tuple[str, list[int]]:
    executable = shutil.which("lsof")
    if executable is None:
        return "UNKNOWN", []
    try:
        result = subprocess.run(
            [executable, "-nP", "+D", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "UNKNOWN", []
    lines = result.stdout.splitlines()
    rows = lines[1:] if lines else []
    if result.stderr.strip() or result.returncode not in (0, 1):
        return "UNKNOWN", []
    if not rows:
        return "CLEAR", []
    pids: set[int] = set()
    for row in rows:
        parts = row.split()
        if len(parts) > 1 and parts[1].isdigit():
            pids.add(int(parts[1]))
    return ("REFERENCED", sorted(pids)) if pids else ("UNKNOWN", [])


def _protected_path(candidate: Path, protected_paths: list[str]) -> bool:
    for raw in protected_paths:
        protected = Path(raw)
        if _is_within(candidate, protected) or _is_within(protected, candidate):
            return True
    return False


def validate_candidate(
    candidate: dict[str, object],
    *,
    allowed_roots: list[str],
    protected_paths: list[str],
    reference_check: Callable[[Path], tuple[str, list[int]]] = lsof_references,
) -> dict[str, object]:
    candidate_id = candidate.get("candidate_id", "unknown")
    raw = Path(str(candidate.get("path", "")))
    reasons: list[str] = []

    def refuse(*items: str) -> dict[str, object]:
        return {"candidate_id": candidate_id, "status": "REFUSE", "reasons": list(items)}

    if not raw.is_absolute() or ".." in raw.parts:
        return refuse("path_not_absolute_or_normalized")
    try:
        if raw.is_symlink():
            raise ValueError("candidate_is_symlink")
        canonical = raw.resolve(strict=True)
        if canonical != raw:
            raise ValueError("path_not_canonical")
        info = raw.lstat()
    except (OSError, ValueError) as error:
        return refuse(str(error))

    if candidate.get("canonical_path") != str(canonical):
        return refuse("canonical_path_mismatch")

    allowed: list[Path] = []
    for root in allowed_roots:
        raw_root = Path(root)
        try:
            if raw_root.is_absolute() and not raw_root.is_symlink() \
                    and raw_root.resolve(strict=True) == raw_root \
                    and stat.S_ISDIR(raw_root.lstat().st_mode):
                allowed.append(raw_root)
        except OSError:
            continue
    if not any(raw.parent == root for root in allowed):
        return refuse("outside_exact_allowed_root")
    if raw == Path.home() or raw == Path("/") or raw.name in {".codex", "evidence"}:
        return refuse("protected_root")
    if _protected_path(raw, protected_paths):
        return refuse("protected_path_overlap")
    if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        return refuse("unsupported_or_symlink_type")
    if stat.S_ISDIR(info.st_mode) and (raw / ".git").exists():
        return refuse("git_repository_root")
    if candidate.get("is_model_source") is True:
        return refuse("unique_model_source_protected")

    if candidate.get("classification") != "SAFE_CANDIDATE":
        reasons.append("candidate_classification_not_safe")
    if candidate.get("evidence_preserved") is not True:
        reasons.append("evidence_dependency_unresolved")
    if candidate.get("rebuild_proven") is not True:
        reasons.append("rebuild_not_proven")
    if candidate.get("consumer_dependencies_resolved") is not True:
        reasons.append("consumer_dependency_unresolved")
    if candidate.get("cleanup_status") not in {"PENDING_OWNER_APPROVAL", "DRY_RUN_ONLY"}:
        reasons.append("candidate_not_pending_owner_approval")
    try:
        observed = inventory_path(raw)
    except (OSError, ValueError) as error:
        observed = None
        reasons.append(f"inventory_failed:{type(error).__name__}")
    reference_state = "NOT_RUN_UNSAFE_OR_UNAVAILABLE_TREE"
    pids: list[int] = []
    if observed is not None:
        if observed["errors"]:
            reasons.append("candidate_tree_contains_unsafe_entry")
        if observed["device"] != candidate.get("expected_device"):
            reasons.append("device_mismatch")
        if observed["inode"] != candidate.get("expected_inode"):
            reasons.append("inode_mismatch")
        if observed["logical_bytes"] != candidate.get("expected_size_bytes"):
            reasons.append("logical_size_mismatch")
        if observed["allocated_bytes"] != candidate.get("expected_allocated_bytes"):
            reasons.append("allocated_size_mismatch")
        if observed["tree_fingerprint_sha256"] != candidate.get("expected_tree_fingerprint_sha256"):
            reasons.append("tree_identity_mismatch")
        if not observed["errors"]:
            reference_state, pids = reference_check(raw)
            if reference_state != "CLEAR":
                reasons.append("active_reference_" + reference_state.lower())
            if pids:
                reasons.append("active_process_reference")
    if reasons:
        status = "REFUSE"
    elif candidate.get("cleanup_status") == "PENDING_OWNER_APPROVAL":
        status = "READY_PENDING_OWNER_APPROVAL"
    else:
        status = "DRY_RUN_ELIGIBLE"
    return {
        "candidate_id": candidate_id,
        "status": status,
        "reasons": reasons,
        "canonical_path": str(canonical),
        "device": observed["device"] if observed else info.st_dev,
        "inode": observed["inode"] if observed else info.st_ino,
        "logical_bytes": observed["logical_bytes"] if observed else None,
        "allocated_bytes": observed["allocated_bytes"] if observed else None,
        "estimated_reclaimable_bytes": None,
        "apfs_shared_extent_uncertainty": "UNKNOWN",
        "active_processes": pids,
        "reference_check": reference_state,
    }


def validate_manifest(
    manifest: dict[str, object],
    *,
    reference_check: Callable[[Path], tuple[str, list[int]]] = lsof_references,
) -> list[dict[str, object]]:
    roots = manifest.get("allowed_roots")
    protected = manifest.get("protected_paths")
    candidates = manifest.get("candidates")
    if not isinstance(roots, list) or not all(isinstance(root, str) for root in roots):
        raise ValueError("allowed_roots must be a list of paths")
    if not isinstance(protected, list) or not all(isinstance(item, str) for item in protected):
        raise ValueError("protected_paths must be a list of paths")
    if not isinstance(candidates, list):
        raise ValueError("candidates must be a list")
    paths: list[Path] = []
    ids: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("candidate entry must be an object")
        candidate_id = candidate.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id or candidate_id in ids:
            raise ValueError("candidate IDs must be unique non-empty strings")
        ids.add(candidate_id)
        path = Path(str(candidate.get("canonical_path", candidate.get("path", ""))))
        if any(_is_within(path, other) or _is_within(other, path) for other in paths):
            raise ValueError("duplicate or nested cleanup candidates are not allowed")
        paths.append(path)
    return [
        validate_candidate(
            candidate,
            allowed_roots=roots,
            protected_paths=protected,
            reference_check=reference_check,
        )
        for candidate in candidates
    ]


def preflight_required_bytes(model_bytes: int) -> int:
    if not isinstance(model_bytes, int) or model_bytes <= 0 or model_bytes > MODEL_MAX_BYTES:
        raise ValueError("local model size is outside the supported bound")
    return model_bytes + BUILD_FIXED_RESERVE_BYTES + math.ceil(model_bytes * BUILD_PERCENT_RESERVE)


def local_model_size(model_path: Path) -> int:
    if model_path.is_symlink():
        raise ValueError("local model must not be a symlink")
    info = model_path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("local model must be a single-link regular file")
    preflight_required_bytes(info.st_size)
    return info.st_size


def _existing_directory(path: Path) -> Path:
    current = path.expanduser().absolute()
    while not current.is_dir():
        if current == current.parent:
            raise ValueError("no existing output-volume ancestor")
        current = current.parent
    return current.resolve(strict=True)


def disk_space_preflight(
    model_bytes: int,
    output_parent: Path,
    *,
    usage: Callable[[str | os.PathLike[str]], shutil._ntuple_diskusage] = shutil.disk_usage,
) -> dict[str, int | str | bool]:
    required = preflight_required_bytes(model_bytes)
    volume_path = _existing_directory(output_parent)
    disk = usage(volume_path)
    result: dict[str, int | str | bool] = {
        "status": "PASS" if disk.free >= required else "INSUFFICIENT_DISK_SPACE",
        "model_bytes": model_bytes,
        "required_free_bytes": required,
        "free_bytes": disk.free,
        "volume_total_bytes": disk.total,
        "volume_used_bytes": disk.used,
        "volume_device": volume_path.stat().st_dev,
    }
    return result


def scratch_cleanup_state(
    scratch: Path,
    expected_device: int,
    expected_inode: int,
    *,
    expected_tree_fingerprint: str | None = None,
    reference_check: Callable[[Path], tuple[str, list[int]]] = lsof_references,
) -> tuple[bool, str]:
    """Check identity and open references before a caller-owned temp cleanup."""
    try:
        if scratch.is_symlink() or scratch.resolve(strict=True) != scratch:
            return False, "scratch_path_changed"
        info = scratch.lstat()
    except OSError:
        return False, "scratch_path_missing"
    if not stat.S_ISDIR(info.st_mode):
        return False, "scratch_not_directory"
    if (info.st_dev, info.st_ino) != (expected_device, expected_inode):
        return False, "scratch_identity_changed"
    if expected_tree_fingerprint is not None:
        try:
            observed = inventory_path(scratch)
        except (OSError, ValueError):
            return False, "scratch_inventory_failed"
        unsafe_errors = [
            item for item in observed["errors"]
            if item.startswith((
                "escaping_symlink:", "unresolvable_symlink:", "hard_linked_entry:",
                "special_file:", "unreadable_directory:",
            ))
        ]
        if unsafe_errors or observed["tree_fingerprint_sha256"] != expected_tree_fingerprint:
            return False, "scratch_contents_changed_after_evidence_capture"
    state, pids = reference_check(scratch)
    if state != "CLEAR" or pids:
        return False, "scratch_open_reference_" + state.lower()
    return True, "scratch_identity_verified_no_open_references"


def cleanup_invocation_scratch(
    scratch: Path,
    expected_device: int,
    expected_inode: int,
    *,
    expected_tree_fingerprint: str,
    reference_check: Callable[[Path], tuple[str, list[int]]] = lsof_references,
) -> tuple[bool, str]:
    """Clean only this invocation's default-temp scratch after an identity-bound rename."""
    if not getattr(shutil.rmtree, "avoids_symlink_attacks", False):
        return False, "safe_recursive_cleanup_unavailable"
    try:
        temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
        parent = scratch.parent.resolve(strict=True)
        parent_info = parent.lstat()
    except OSError:
        return False, "scratch_parent_unavailable"
    if parent != temp_root or scratch.parent != parent:
        return False, "scratch_parent_not_default_temp"
    if not scratch.name.startswith("khaos-dsh-xpc-attack-"):
        return False, "scratch_name_not_invocation_owned"
    if not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != os.getuid() \
            or stat.S_IMODE(parent_info.st_mode) & 0o022:
        return False, "scratch_parent_not_private"
    if not expected_tree_fingerprint:
        return False, "scratch_tree_identity_missing"

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    if not getattr(os, "O_DIRECTORY", 0) or not getattr(os, "O_NOFOLLOW", 0):
        return False, "safe_directory_handles_unavailable"
    try:
        parent_fd = os.open(parent, directory_flags)
    except OSError:
        return False, "scratch_parent_open_failed"

    quarantine_name = f".{scratch.name}.cleanup-{secrets.token_hex(8)}"
    renamed = False
    quarantined = parent / quarantine_name

    def restore_quarantine() -> bool:
        nonlocal renamed
        if not renamed:
            return True
        try:
            os.stat(scratch.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            try:
                os.rename(quarantine_name, scratch.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                renamed = False
                return True
            except OSError:
                return False
        except OSError:
            return False
        return False

    def refuse(reason: str) -> tuple[bool, str]:
        if restore_quarantine():
            return False, reason
        return False, f"{reason}; scratch_preserved_at={quarantined}"

    try:
        opened_parent = os.fstat(parent_fd)
        if (opened_parent.st_dev, opened_parent.st_ino) != (parent_info.st_dev, parent_info.st_ino):
            return False, "scratch_parent_identity_changed"
        ready, reason = scratch_cleanup_state(
            scratch,
            expected_device,
            expected_inode,
            expected_tree_fingerprint=expected_tree_fingerprint,
            reference_check=reference_check,
        )
        if not ready:
            return False, reason
        try:
            source_info = os.stat(scratch.name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError:
            return False, "scratch_path_changed_before_quarantine"
        if not stat.S_ISDIR(source_info.st_mode) \
                or (source_info.st_dev, source_info.st_ino) != (expected_device, expected_inode):
            return False, "scratch_identity_changed_before_quarantine"
        try:
            os.rename(scratch.name, quarantine_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            renamed = True
        except OSError:
            return False, "scratch_quarantine_rename_failed"

        try:
            quarantine_info = os.stat(quarantine_name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError:
            return refuse("scratch_quarantine_identity_unavailable")
        if not stat.S_ISDIR(quarantine_info.st_mode) \
                or (quarantine_info.st_dev, quarantine_info.st_ino) != (expected_device, expected_inode):
            return refuse("scratch_identity_changed_during_quarantine")
        ready, reason = scratch_cleanup_state(
            quarantined,
            expected_device,
            expected_inode,
            expected_tree_fingerprint=expected_tree_fingerprint,
            reference_check=reference_check,
        )
        if not ready:
            return refuse(reason)

        # The unpredictable quarantine name makes the identity check and safe fd-based
        # traversal a single bounded cleanup step; callers never delete the stale
        # original pathname directly.
        try:
            current = os.stat(quarantine_name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError:
            return refuse("scratch_quarantine_identity_unavailable")
        if (current.st_dev, current.st_ino) != (expected_device, expected_inode):
            return refuse("scratch_identity_changed_before_delete")
        try:
            shutil.rmtree(quarantine_name, dir_fd=parent_fd)
        except OSError:
            return refuse("scratch_delete_failed")
        renamed = False
        return True, "scratch_identity_rechecked_and_cleaned"
    finally:
        if renamed:
            restore_quarantine()
        os.close(parent_fd)


def scratch_artifact_record(
    scratch: Path,
    expected_device: int,
    expected_inode: int,
    *,
    inventory: dict[str, object] | None = None,
) -> dict[str, object]:
    """Record a local-only exact identity for a retained invocation scratch."""
    record: dict[str, object] = {
        "path": str(scratch),
        "expected_device": expected_device,
        "expected_inode": expected_inode,
        "inventory_status": "UNKNOWN",
    }
    try:
        observed = inventory if inventory is not None else inventory_path(scratch)
    except (OSError, ValueError) as error:
        record["inventory_error"] = type(error).__name__
        return record
    record.update({
        "canonical_path": observed["canonical_path"],
        "observed_device": observed["device"],
        "observed_inode": observed["inode"],
        "logical_bytes": observed["logical_bytes"],
        "allocated_bytes": observed["allocated_bytes"],
        "tree_fingerprint_sha256": observed["tree_fingerprint_sha256"],
        "inventory_errors": observed["errors"],
        "inventory_status": "MATCH" if (observed["device"], observed["inode"])
        == (expected_device, expected_inode) else "IDENTITY_CHANGED",
    })
    return record


def read_bounded_diagnostic_text(path: Path) -> tuple[str, str | None]:
    """Read a small regular log without following links or allocating unbounded memory."""
    try:
        info = path.lstat()
    except OSError as error:
        return "", type(error).__name__
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        return "", "unsafe_diagnostic_file"
    if info.st_size > MAX_DIAGNOSTIC_FILE_BYTES:
        return "", "diagnostic_file_over_limit"
    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino) \
                or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            os.close(descriptor)
            descriptor = -1
            return "", "diagnostic_file_changed"
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            payload = stream.read(MAX_DIAGNOSTIC_FILE_BYTES + 1)
    except OSError as error:
        return "", type(error).__name__
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(payload) > MAX_DIAGNOSTIC_FILE_BYTES:
        return "", "diagnostic_file_over_limit"
    return payload.decode("utf-8", errors="replace"), None


def capture_failure_bundle(
    scratch: Path,
    destination: Path,
    *,
    api_key: str = "",
    build_record_path: Path | None = None,
) -> dict[str, object]:
    """Save bounded failure evidence without copying the signed App or model."""
    require_private_directory(destination.parent)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("failure evidence destination already exists")
    if not scratch.is_dir() or scratch.is_symlink() or scratch.resolve(strict=True) != scratch:
        raise ValueError("failure source must be a canonical real directory")
    destination.mkdir(parents=True, mode=0o700)
    os.chmod(destination, 0o700)
    copied: list[dict[str, object]] = []
    skipped: list[str] = []

    def save_bytes(relative: str, payload: bytes, *, compress: bool = False) -> None:
        output = destination / relative
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(output.parent, 0o700)
        if api_key:
            payload = payload.replace(api_key.encode("utf-8"), b"[REDACTED_API_KEY]")
        data = gzip.compress(payload, mtime=0) if compress else payload
        write_private_file(output, data)
        copied.append({"path": relative, "bytes": len(data), "sha256": sha256_bytes(data)})

    before_inventory = inventory_path(scratch)

    for filename in ("launcher.stdout", "launcher.stderr", "agent-task.txt"):
        source = scratch / filename
        if not source.exists():
            skipped.append(filename)
            continue
        if source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_DIAGNOSTIC_FILE_BYTES:
            raise ValueError(f"unsafe or oversized diagnostic file: {filename}")
        payload = source.read_bytes()
        if filename.startswith("launcher."):
            save_bytes(filename + ".gz", payload, compress=True)
        else:
            save_bytes(filename, payload)

    build_record = build_record_path or (
        scratch / "Khaos DSH XPC Acceptance.app/Contents/Resources/build-inputs.json"
    )
    if build_record.exists():
        if build_record.is_symlink() or not build_record.is_file() or build_record.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("unsafe or oversized build input record")
        save_bytes("build-inputs.json", build_record.read_bytes())
    else:
        skipped.append("build-inputs.json")

    cancellation_log = scratch / "cancellation-control/kernel-events.jsonl"
    if cancellation_log.exists():
        if cancellation_log.is_symlink() or not cancellation_log.is_file() \
                or cancellation_log.stat().st_size > MAX_DIAGNOSTIC_FILE_BYTES:
            raise ValueError("unsafe or oversized cancellation event log")
        save_bytes("cancellation-control/kernel-events.jsonl", cancellation_log.read_bytes())
    elif (scratch / "cancellation-control").exists():
        skipped.append("cancellation-control/kernel-events.jsonl")

    workspace = scratch / "coding-workspace"
    workspace_bytes = 0
    workspace_count = 0
    if workspace.exists():
        if workspace.is_symlink() or not workspace.is_dir():
            raise ValueError("coding workspace is not a real directory")
        for source in sorted(workspace.rglob("*")):
            info = source.lstat()
            if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise ValueError("workspace contains an unsupported entry")
            if stat.S_ISDIR(info.st_mode):
                continue
            if "canary" in source.name.lower():
                skipped.append("coding-workspace/" + source.relative_to(workspace).as_posix() + ":canary")
                continue
            workspace_count += 1
            workspace_bytes += info.st_size
            if workspace_count > MAX_DIAGNOSTIC_WORKSPACE_FILES or info.st_size > MAX_DIAGNOSTIC_FILE_BYTES \
                    or workspace_bytes > MAX_DIAGNOSTIC_WORKSPACE_BYTES:
                raise ValueError("workspace exceeds bounded failure evidence limits")
            save_bytes(
                "coding-workspace/" + source.relative_to(workspace).as_posix(),
                source.read_bytes(),
            )
    else:
        skipped.append("coding-workspace")

    inventory = inventory_path(scratch)
    source_tree_stable = (
        before_inventory["tree_fingerprint_sha256"] == inventory["tree_fingerprint_sha256"]
    )
    required_files = {
        "launcher.stdout.gz", "launcher.stderr.gz", "agent-task.txt", "build-inputs.json",
    }
    copied_names = {str(item["path"]) for item in copied}
    missing_required = sorted(required_files - copied_names)
    if (scratch / "cancellation-control").is_dir() \
            and "cancellation-control/kernel-events.jsonl" not in copied_names:
        missing_required.append("cancellation-control/kernel-events.jsonl")
    if not source_tree_stable:
        missing_required.append("scratch_changed_during_capture")
    metadata = {
        "schema": 1,
        "source_scratch_identity": {"device": inventory["device"], "inode": inventory["inode"]},
        "source_tree_fingerprint_sha256": inventory["tree_fingerprint_sha256"],
        "source_tree_stable_during_capture": source_tree_stable,
        "source_logical_bytes": inventory["logical_bytes"],
        "source_allocated_bytes": inventory["allocated_bytes"],
        "copied_files": copied,
        "skipped_files": skipped,
        "missing_required_files": missing_required,
        "workspace_files_copied": workspace_count,
        "workspace_bytes_copied": workspace_bytes,
        "large_signed_app_and_model_copied": False,
    }
    save_bytes("capture-manifest.json", canonical_json(metadata))
    return {
        "status": "COMPLETE" if not missing_required and source_tree_stable else "INCOMPLETE",
        "directory": str(destination),
        "capture_manifest_sha256": sha256_bytes(canonical_json(metadata)),
        "copied_file_count": len(copied),
        "copied_bytes": sum(int(item["bytes"]) for item in copied),
        "source_tree_fingerprint_sha256": inventory["tree_fingerprint_sha256"],
        "source_tree_stable_during_capture": source_tree_stable,
        "missing_required_files": missing_required,
        "large_signed_app_and_model_copied": False,
    }
