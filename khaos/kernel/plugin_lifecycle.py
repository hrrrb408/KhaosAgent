"""Small Kernel-owned store for admitted Seed Plugin candidates and slots."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import errno
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time
from collections.abc import Iterator

from .workspace_snapshot import (
    WorkspaceReadScope,
    WorkspaceSnapshotError,
    WorkspaceWriteScope,
)


MAX_MANIFEST_BYTES = 4_096
MAX_AGENT_INTERFACE_BYTES = 2_048
MAX_AGENT_INTERFACE_OPERATIONS = 16
MAX_AGENT_INTERFACE_FIELDS = 16
MAX_AGENT_INTERFACE_SUMMARY_BYTES = 512
MAX_PLUGIN_SOURCE_BYTES = 10_240
ACTIVATION_APPROVAL_SECONDS = 30 * 24 * 60 * 60
_CANDIDATE_DOMAIN = b"Khaos Seed Plugin Candidate v1\0"
_STATE_SCHEMA = 1
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_PLUGIN_ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_AGENT_INTERFACE_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
    os, "O_NOFOLLOW", 0
) | getattr(os, "O_CLOEXEC", 0)
_READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(
    os, "O_NOFOLLOW", 0
) | getattr(os, "O_CLOEXEC", 0)
_STATE_FILENAME = "state.json"
_STATE_TEMP_PREFIX = ".state-"
_STATE_TEMP_SUFFIX = ".tmp"


class PluginLifecycleError(RuntimeError):
    """A stable, path-free rejection from the trusted lifecycle boundary."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class AgentPluginOperation:
    name: str
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AgentPluginInterface:
    summary: str
    operations: tuple[AgentPluginOperation, ...]


@dataclass(frozen=True, slots=True)
class PluginManifest:
    plugin_id: str
    process_exec: bool
    read_scope: tuple[str, ...]
    write_scope: tuple[str, ...]
    agent_interface: AgentPluginInterface | None = None

    @property
    def scope_digest(self) -> str:
        body = _canonical_json(
            {
                "id": self.plugin_id,
                "process_exec": self.process_exec,
                "read": list(self.read_scope),
                "write": list(self.write_scope),
            }
        )
        return hashlib.sha256(b"Khaos Seed capability scope v1\0" + body).hexdigest()


@dataclass(frozen=True, slots=True)
class PluginCandidate:
    candidate_digest: str
    manifest_digest: str
    scope_digest: str
    manifest: PluginManifest
    manifest_bytes: bytes
    source: bytes


@dataclass(frozen=True, slots=True)
class Activation:
    slot: str
    candidate_digest: str
    manifest_digest: str
    scope_digest: str
    approval_id: str
    approved_at: int
    expires_at: int


@contextmanager
def _open_store(root: str | os.PathLike[str]) -> Iterator[tuple[int, int]]:
    """Open only the final Kernel store and candidates directories without following links."""
    path = Path(root)
    if not path.is_absolute() or path.name in ("", ".", ".."):
        raise PluginLifecycleError("store_unavailable")
    try:
        parent = path.parent.resolve(strict=True)
        parent_fd = os.open(parent, _DIRECTORY_FLAGS)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PluginLifecycleError("store_unavailable") from exc

    root_fd = -1
    candidates_fd = -1
    lock_fd = -1
    try:
        root_fd = _open_owned_directory_at(
            parent_fd,
            path.name,
            unavailable_code="store_unavailable",
            corrupt_code="store_unavailable",
        )
        lock_fd = _open_store_lock(
            root_fd,
            "activation.lock",
            unavailable_code="activation_state_unavailable",
            corrupt_code="activation_state_corrupt",
        )
        candidates_fd = _open_owned_directory_at(
            root_fd,
            "candidates",
            unavailable_code="store_unavailable",
            corrupt_code="store_unavailable",
        )
        yield root_fd, candidates_fd
    except PluginLifecycleError:
        raise
    except OSError as exc:
        raise PluginLifecycleError("store_unavailable") from exc
    finally:
        if candidates_fd >= 0:
            os.close(candidates_fd)
        if lock_fd >= 0:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        if root_fd >= 0:
            os.close(root_fd)
        os.close(parent_fd)


@contextmanager
def _open_plugin_state_directory(
    state_root: str | os.PathLike[str], plugin_id: str
) -> Iterator[int]:
    """Open the Kernel-owned state domain selected by a validated Plugin ID."""
    if type(plugin_id) is not str or _PLUGIN_ID.fullmatch(plugin_id) is None:
        raise PluginLifecycleError("plugin_state_unavailable")
    path = Path(state_root)
    if not path.is_absolute() or path.name in ("", ".", ".."):
        raise PluginLifecycleError("plugin_state_unavailable")
    try:
        parent = path.parent.resolve(strict=True)
        parent_fd = os.open(parent, _DIRECTORY_FLAGS)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PluginLifecycleError("plugin_state_unavailable") from exc

    root_fd = -1
    plugin_fd = -1
    lock_fd = -1
    try:
        root_fd = _open_owned_directory_at(
            parent_fd,
            path.name,
            unavailable_code="plugin_state_unavailable",
            corrupt_code="plugin_state_corrupt",
        )
        plugin_fd = _open_owned_directory_at(
            root_fd,
            plugin_id,
            unavailable_code="plugin_state_unavailable",
            corrupt_code="plugin_state_corrupt",
        )
        lock_fd = _open_store_lock(
            plugin_fd,
            ".lock",
            unavailable_code="plugin_state_unavailable",
            corrupt_code="plugin_state_corrupt",
        )
        _remove_orphaned_state_temps(plugin_fd)
        yield plugin_fd
    except PluginLifecycleError:
        raise
    except OSError as exc:
        raise PluginLifecycleError("plugin_state_unavailable") from exc
    finally:
        if lock_fd >= 0:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        if plugin_fd >= 0:
            os.close(plugin_fd)
        if root_fd >= 0:
            os.close(root_fd)
        os.close(parent_fd)


def read_plugin_state(
    state_root: str | os.PathLike[str], plugin_id: str
) -> bytes | None:
    """Read one opaque, bounded business-state blob for a logical Plugin."""
    from ..ipc import MAX_PLUGIN_STATE_BYTES

    with _open_plugin_state_directory(state_root, plugin_id) as directory_fd:
        try:
            descriptor = os.open(_STATE_FILENAME, _READ_FLAGS, dir_fd=directory_fd)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise PluginLifecycleError("plugin_state_corrupt") from exc
        try:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_uid != os.getuid()
                or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_size > MAX_PLUGIN_STATE_BYTES
            ):
                raise PluginLifecycleError("plugin_state_corrupt")
            data = _read_descriptor(descriptor, MAX_PLUGIN_STATE_BYTES + 1)
            after = os.fstat(descriptor)
            if (
                len(data) != before.st_size
                or len(data) > MAX_PLUGIN_STATE_BYTES
                or before.st_dev != after.st_dev
                or before.st_ino != after.st_ino
                or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ctime_ns != after.st_ctime_ns
                or before.st_nlink != after.st_nlink
            ):
                raise PluginLifecycleError("plugin_state_corrupt")
            return data
        except OSError as exc:
            raise PluginLifecycleError("plugin_state_unavailable") from exc
        finally:
            os.close(descriptor)


def replace_plugin_state(
    state_root: str | os.PathLike[str], plugin_id: str, data: bytes
) -> None:
    """Durably replace one opaque state blob; interruption leaves old or new bytes."""
    from ..ipc import MAX_PLUGIN_STATE_BYTES

    if type(data) is not bytes or len(data) > MAX_PLUGIN_STATE_BYTES:
        raise PluginLifecycleError("plugin_state_too_large")
    with _open_plugin_state_directory(state_root, plugin_id) as directory_fd:
        _atomic_replace_at(
            directory_fd,
            _STATE_FILENAME,
            data,
            temp_prefix=_STATE_TEMP_PREFIX,
            unavailable_code="plugin_state_unavailable",
            uncertain_code="plugin_state_outcome_uncertain",
        )


def _remove_orphaned_state_temps(directory_fd: int) -> None:
    """Bound crash residue without following or removing unrelated entries."""
    for name in os.listdir(directory_fd):
        if not (
            name.startswith(_STATE_TEMP_PREFIX)
            and name.endswith(_STATE_TEMP_SUFFIX)
            and len(name) == len(_STATE_TEMP_PREFIX) + 32 + len(_STATE_TEMP_SUFFIX)
            and all(character in "0123456789abcdef" for character in name[len(_STATE_TEMP_PREFIX):-len(_STATE_TEMP_SUFFIX)])
        ):
            continue
        try:
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if (
                stat.S_ISREG(metadata.st_mode)
                and metadata.st_nlink == 1
                and metadata.st_uid == os.getuid()
            ):
                os.unlink(name, dir_fd=directory_fd)
        except FileNotFoundError:
            continue
    os.fsync(directory_fd)


def admit_candidate(
    store_root: str | os.PathLike[str],
    manifest_bytes: bytes,
    source_bytes: bytes,
    *,
    expected_active_candidate_digest: str | None = None,
    expected_generation: int | None = None,
) -> PluginCandidate:
    """Validate and store a Candidate, optionally bound to the active evolution target."""
    manifest = _parse_manifest(manifest_bytes)
    source = _validate_source(source_bytes)
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    candidate_digest = _candidate_digest(manifest_bytes, source_bytes)
    candidate = PluginCandidate(
        candidate_digest=candidate_digest,
        manifest_digest=manifest_digest,
        scope_digest=manifest.scope_digest,
        manifest=manifest,
        manifest_bytes=manifest_bytes,
        source=source,
    )

    if (expected_active_candidate_digest is None) != (expected_generation is None):
        raise PluginLifecycleError("invalid_request")

    with _open_store(store_root) as (root_fd, candidates_fd):
        if expected_active_candidate_digest is not None:
            baseline = _active_evolution_baseline(
                root_fd,
                candidates_fd,
                expected_active_candidate_digest,
                expected_generation,
            )
            _validate_evolution_candidate(candidate, baseline)
        try:
            existing = _read_candidate(candidates_fd, candidate_digest)
        except PluginLifecycleError as exc:
            if exc.code != "candidate_missing":
                raise
        else:
            _require_same_candidate(existing, candidate)
            return existing

        _install_candidate(candidates_fd, candidate, manifest_bytes)
        return _read_candidate(candidates_fd, candidate_digest)


def evolution_source(
    store_root: str | os.PathLike[str],
    *,
    candidate_digest: str,
    manifest_digest: str,
    scope_digest: str,
    expected_generation: int,
) -> PluginCandidate:
    """Return source only for the exact currently active evolution target."""
    with _open_store(store_root) as (root_fd, candidates_fd):
        candidate = _active_evolution_baseline(
            root_fd,
            candidates_fd,
            candidate_digest,
            expected_generation,
        )
        if (
            candidate.manifest_digest != manifest_digest
            or candidate.scope_digest != scope_digest
        ):
            raise PluginLifecycleError("approval_binding_mismatch")
        return candidate


def evaluation_candidate(
    store_root: str | os.PathLike[str],
    *,
    baseline_candidate_digest: str,
    candidate_digest: str,
    manifest_digest: str,
    scope_digest: str,
    expected_generation: int,
) -> PluginCandidate:
    """Resolve a Memory Candidate for isolated evaluation against the active baseline."""
    with _open_store(store_root) as (root_fd, candidates_fd):
        baseline = _active_evolution_baseline(
            root_fd,
            candidates_fd,
            baseline_candidate_digest,
            expected_generation,
        )
        candidate = _read_candidate(candidates_fd, candidate_digest)
        if (
            candidate.manifest_digest != manifest_digest
            or candidate.scope_digest != scope_digest
        ):
            raise PluginLifecycleError("approval_binding_mismatch")
        _validate_evolution_candidate(candidate, baseline)
        return candidate


def _active_evolution_baseline(
    root_fd: int,
    candidates_fd: int,
    candidate_digest: str,
    expected_generation: int,
) -> PluginCandidate:
    state, _ = _read_state(root_fd)
    if (
        type(expected_generation) is not int
        or expected_generation != state["generation"]
        or state["active"] is None
        or state["active"]["candidate_digest"] != candidate_digest
    ):
        raise PluginLifecycleError("stale_approval")
    _validate_state_candidates(candidates_fd, state)
    baseline = _read_candidate(candidates_fd, candidate_digest)
    if (
        baseline.manifest.plugin_id != "memory"
        or baseline.manifest.process_exec
        or baseline.manifest.read_scope
        or baseline.manifest.write_scope
    ):
        raise PluginLifecycleError("capability_denied")
    return baseline


def _validate_evolution_candidate(
    candidate: PluginCandidate,
    baseline: PluginCandidate,
) -> None:
    """Keep Seed Memory evolution inside the baseline identity and capability ceiling."""
    if candidate.manifest.plugin_id != baseline.manifest.plugin_id:
        raise PluginLifecycleError("manifest_rejected")
    if (
        candidate.manifest.process_exec and not baseline.manifest.process_exec
        or not set(candidate.manifest.read_scope).issubset(baseline.manifest.read_scope)
        or not set(candidate.manifest.write_scope).issubset(baseline.manifest.write_scope)
    ):
        raise PluginLifecycleError("capability_denied")
    if candidate.manifest.agent_interface != baseline.manifest.agent_interface:
        raise PluginLifecycleError("manifest_rejected")


def activate_candidate(
    store_root: str | os.PathLike[str],
    candidate_digest: str,
    manifest_digest: str,
    scope_digest: str,
    expected_generation: int,
    *,
    now: int | None = None,
) -> Activation:
    """Activate only the reviewed Candidate at the slot generation shown to the user."""
    timestamp = _timestamp(now)
    with _open_store(store_root) as (root_fd, candidates_fd):
        state, key = _read_state(root_fd)
        if (
            type(expected_generation) is not int
            or expected_generation != state["generation"]
        ):
            raise PluginLifecycleError("stale_approval")
        candidate = _read_candidate(candidates_fd, candidate_digest)
        if (
            candidate.manifest_digest != manifest_digest
            or candidate.scope_digest != scope_digest
        ):
            raise PluginLifecycleError("approval_binding_mismatch")
        _validate_state_candidates(candidates_fd, state)
        if not key:
            key = _read_key(root_fd, create=True)
        activation = Activation(
            slot="primary",
            candidate_digest=candidate.candidate_digest,
            manifest_digest=candidate.manifest_digest,
            scope_digest=candidate.scope_digest,
            approval_id=secrets.token_hex(16),
            approved_at=timestamp,
            expires_at=timestamp + ACTIVATION_APPROVAL_SECONDS,
        )
        updated = {
            "schema": _STATE_SCHEMA,
            "generation": state["generation"] + 1,
            "active": _activation_object(activation),
            "previous": state["active"],
        }
        _write_state(root_fd, key, updated)
        return activation


def active_candidate(
    store_root: str | os.PathLike[str],
    *,
    now: int | None = None,
    candidate_digest: str | None = None,
    manifest_digest: str | None = None,
    scope_digest: str | None = None,
    expected_generation: int | None = None,
) -> tuple[PluginCandidate, Activation]:
    """Resolve the active Candidate, optionally binding a reviewed run to its slot."""
    timestamp = _timestamp(now)
    with _open_store(store_root) as (root_fd, candidates_fd):
        state, _ = _read_state(root_fd)
        binding = (candidate_digest, manifest_digest, scope_digest)
        has_binding = expected_generation is not None or any(
            value is not None for value in binding
        )
        if has_binding:
            if type(expected_generation) is not int or any(
                type(value) is not str for value in binding
            ):
                raise PluginLifecycleError("invalid_request")
            if expected_generation != state["generation"]:
                raise PluginLifecycleError("stale_approval")
        reference = state["active"]
        if reference is None:
            raise PluginLifecycleError("no_active_candidate")
        activation = _activation_from_object(reference)
        if timestamp >= activation.expires_at:
            raise PluginLifecycleError("approval_expired")
        candidate = _read_candidate(candidates_fd, activation.candidate_digest)
        _require_activation_matches_candidate(activation, candidate)
        if has_binding and (
            candidate.candidate_digest != candidate_digest
            or candidate.manifest_digest != manifest_digest
            or candidate.scope_digest != scope_digest
        ):
            raise PluginLifecycleError("approval_binding_mismatch")
        return candidate, activation


def rollback(
    store_root: str | os.PathLike[str],
    *,
    expected_generation: int,
    candidate_digest: str,
    manifest_digest: str,
    scope_digest: str,
    now: int | None = None,
) -> Activation:
    """Atomically route to the reviewed previous Candidate at the reviewed generation."""
    timestamp = _timestamp(now)
    with _open_store(store_root) as (root_fd, candidates_fd):
        state, key = _read_state(root_fd)
        if (
            type(expected_generation) is not int
            or expected_generation != state["generation"]
        ):
            raise PluginLifecycleError("stale_approval")
        previous = state["previous"]
        current = state["active"]
        if previous is None or current is None:
            raise PluginLifecycleError("invalid_rollback_target")
        target = _activation_from_object(previous)
        if timestamp >= target.expires_at:
            raise PluginLifecycleError("approval_expired")
        target_candidate = _read_candidate(candidates_fd, target.candidate_digest)
        current_activation = _activation_from_object(current)
        current_candidate = _read_candidate(candidates_fd, current_activation.candidate_digest)
        _require_activation_matches_candidate(target, target_candidate)
        if (
            candidate_digest != target.candidate_digest
            or manifest_digest != target.manifest_digest
            or scope_digest != target.scope_digest
        ):
            raise PluginLifecycleError("approval_binding_mismatch")
        _require_activation_matches_candidate(current_activation, current_candidate)
        updated = {
            "schema": _STATE_SCHEMA,
            "generation": state["generation"] + 1,
            "active": previous,
            "previous": current,
        }
        _write_state(root_fd, key, updated)
        return target


def activation_state(
    store_root: str | os.PathLike[str],
) -> tuple[Activation | None, Activation | None, int]:
    """Return verified slot metadata without exposing stored Plugin source."""
    active, previous, generation = activation_details(store_root)
    return (
        active[1] if active is not None else None,
        previous[1] if previous is not None else None,
        generation,
    )


def activation_details(
    store_root: str | os.PathLike[str],
) -> tuple[
    tuple[PluginCandidate, Activation] | None,
    tuple[PluginCandidate, Activation] | None,
    int,
]:
    """Resolve and verify slot metadata for the trusted Launcher review UI."""
    with _open_store(store_root) as (root_fd, candidates_fd):
        state, _ = _read_state(root_fd)

        def resolve(reference: object) -> tuple[PluginCandidate, Activation] | None:
            if reference is None:
                return None
            activation = _activation_from_object(reference)
            candidate = _read_candidate(candidates_fd, activation.candidate_digest)
            _require_activation_matches_candidate(activation, candidate)
            return candidate, activation

        return resolve(state["active"]), resolve(state["previous"]), state["generation"]


def _parse_manifest(data: bytes) -> PluginManifest:
    if type(data) is not bytes or not 0 < len(data) <= MAX_MANIFEST_BYTES:
        raise PluginLifecycleError("manifest_rejected")
    try:
        value = json.loads(data.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object)
        canonical = _canonical_json(value)
    except (
        UnicodeError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
        RecursionError,
    ) as exc:
        raise PluginLifecycleError("manifest_rejected") from exc
    if data not in (canonical, canonical + b"\n"):
        raise PluginLifecycleError("manifest_rejected")
    required_keys = {"abi_version", "id", "process_exec", "read", "write"}
    if type(value) is not dict or set(value) not in (
        required_keys,
        required_keys | {"agent_interface"},
    ):
        raise PluginLifecycleError("manifest_rejected")
    plugin_id = value["id"]
    read_paths = value["read"]
    write_paths = value["write"]
    if (
        type(value["abi_version"]) is not int
        or value["abi_version"] != 6
        or type(plugin_id) is not str
        or _PLUGIN_ID.fullmatch(plugin_id) is None
        or type(value["process_exec"]) is not bool
        or type(read_paths) is not list
        or type(write_paths) is not list
        or any(type(path) is not str for path in read_paths + write_paths)
        or len(read_paths) + len(write_paths) > 8
    ):
        raise PluginLifecycleError("manifest_rejected")
    try:
        read_scope = WorkspaceReadScope.from_paths(read_paths).as_paths()
        write_scope = WorkspaceWriteScope.from_paths(write_paths).as_paths()
    except WorkspaceSnapshotError as exc:
        raise PluginLifecycleError("manifest_rejected") from exc
    agent_interface = (
        _parse_agent_interface(value["agent_interface"])
        if "agent_interface" in value
        else None
    )
    if agent_interface is not None and (
        value["process_exec"] or read_scope or write_scope
    ):
        # The current product Runner accepts business input only for state-only calls.
        raise PluginLifecycleError("manifest_rejected")
    return PluginManifest(
        plugin_id=plugin_id,
        process_exec=value["process_exec"],
        read_scope=tuple(read_scope),
        write_scope=tuple(write_scope),
        agent_interface=agent_interface,
    )


def _parse_agent_interface(value: object) -> AgentPluginInterface:
    """Bound informational Agent metadata without interpreting Plugin business input."""
    if type(value) is not dict or set(value) != {"summary", "operations"}:
        raise PluginLifecycleError("manifest_rejected")
    summary = value["summary"]
    operations = value["operations"]
    if (
        type(summary) is not str
        or not summary
        or _utf8_size(summary) > MAX_AGENT_INTERFACE_SUMMARY_BYTES
        or type(operations) is not list
        or not 1 <= len(operations) <= MAX_AGENT_INTERFACE_OPERATIONS
    ):
        raise PluginLifecycleError("manifest_rejected")
    if len(_canonical_json(value)) > MAX_AGENT_INTERFACE_BYTES:
        raise PluginLifecycleError("manifest_rejected")

    parsed_operations: list[AgentPluginOperation] = []
    operation_names: set[str] = set()
    for operation in operations:
        if type(operation) is not dict or set(operation) != {"name", "fields"}:
            raise PluginLifecycleError("manifest_rejected")
        name = operation["name"]
        fields = operation["fields"]
        if (
            type(name) is not str
            or _AGENT_INTERFACE_NAME.fullmatch(name) is None
            or name in operation_names
            or type(fields) is not list
            or len(fields) > MAX_AGENT_INTERFACE_FIELDS
            or any(
                type(field) is not str
                or _AGENT_INTERFACE_NAME.fullmatch(field) is None
                or field == "operation"
                for field in fields
            )
            or len(set(fields)) != len(fields)
        ):
            raise PluginLifecycleError("manifest_rejected")
        operation_names.add(name)
        parsed_operations.append(AgentPluginOperation(name, tuple(fields)))

    return AgentPluginInterface(summary, tuple(parsed_operations))


def _utf8_size(value: str) -> int:
    try:
        return len(value.encode("utf-8", errors="strict"))
    except UnicodeError as exc:
        raise PluginLifecycleError("manifest_rejected") from exc


def _validate_source(data: bytes) -> bytes:
    if type(data) is not bytes or not 0 < len(data) <= MAX_PLUGIN_SOURCE_BYTES:
        raise PluginLifecycleError("plugin_source_rejected")
    try:
        source = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PluginLifecycleError("plugin_source_rejected") from exc
    from ..ipc import IPCProtocolError, validate_runner_source

    try:
        validate_runner_source(source)
    except IPCProtocolError as exc:
        raise PluginLifecycleError("plugin_source_rejected") from exc
    return data


def _candidate_digest(manifest: bytes, source: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(_CANDIDATE_DOMAIN)
    digest.update(len(manifest).to_bytes(8, "big"))
    digest.update(manifest)
    digest.update(len(source).to_bytes(8, "big"))
    digest.update(source)
    return digest.hexdigest()


def _install_candidate(
    candidates_fd: int, candidate: PluginCandidate, manifest_bytes: bytes
) -> None:
    staging_name = f".staging-{secrets.token_hex(16)}"
    try:
        os.mkdir(staging_name, 0o700, dir_fd=candidates_fd)
        staging_fd = os.open(staging_name, _DIRECTORY_FLAGS, dir_fd=candidates_fd)
    except OSError as exc:
        raise PluginLifecycleError("candidate_store_failed") from exc
    try:
        _write_candidate_file(staging_fd, "manifest.json", manifest_bytes)
        _write_candidate_file(staging_fd, "plugin.py", candidate.source)
        os.fchmod(staging_fd, 0o500)
        os.fsync(staging_fd)
        try:
            os.rename(
                staging_name,
                candidate.candidate_digest,
                src_dir_fd=candidates_fd,
                dst_dir_fd=candidates_fd,
            )
        except OSError as exc:
            if exc.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                raise
            existing = _read_candidate(candidates_fd, candidate.candidate_digest)
            _require_same_candidate(existing, candidate)
        os.fsync(candidates_fd)
    except PluginLifecycleError:
        raise
    except OSError as exc:
        raise PluginLifecycleError("candidate_store_failed") from exc
    finally:
        os.close(staging_fd)
        _remove_staging(candidates_fd, staging_name)


def _write_candidate_file(directory_fd: int, name: str, data: bytes) -> None:
    try:
        descriptor = os.open(name, _WRITE_FLAGS, 0o400, dir_fd=directory_fd)
    except OSError as exc:
        raise PluginLifecycleError("candidate_store_failed") from exc
    try:
        os.fchmod(descriptor, 0o400)
        _write_all(descriptor, data)
        os.fsync(descriptor)
    except OSError as exc:
        raise PluginLifecycleError("candidate_store_failed") from exc
    finally:
        os.close(descriptor)


def _remove_staging(candidates_fd: int, name: str) -> None:
    try:
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=candidates_fd)
    except OSError:
        return
    try:
        os.fchmod(descriptor, 0o700)
        for entry in os.listdir(descriptor):
            try:
                os.unlink(entry, dir_fd=descriptor)
            except OSError:
                return
    finally:
        os.close(descriptor)
    try:
        os.rmdir(name, dir_fd=candidates_fd)
    except OSError:
        return


def _read_candidate(candidates_fd: int, digest: str) -> PluginCandidate:
    if type(digest) is not str or _HEX_DIGEST.fullmatch(digest) is None:
        raise PluginLifecycleError("candidate_missing")
    try:
        directory_fd = os.open(digest, _DIRECTORY_FLAGS, dir_fd=candidates_fd)
    except FileNotFoundError as exc:
        raise PluginLifecycleError("candidate_missing") from exc
    except OSError as exc:
        raise PluginLifecycleError("candidate_corrupt") from exc
    try:
        _check_directory(directory_fd, 0o500)
        try:
            if set(os.listdir(directory_fd)) != {"manifest.json", "plugin.py"}:
                raise PluginLifecycleError("candidate_corrupt")
        except OSError as exc:
            raise PluginLifecycleError("candidate_corrupt") from exc
        manifest_bytes = _read_regular_file(
            directory_fd, "manifest.json", MAX_MANIFEST_BYTES, 0o400
        )
        source_bytes = _read_regular_file(
            directory_fd, "plugin.py", MAX_PLUGIN_SOURCE_BYTES, 0o400
        )
        manifest = _parse_manifest(manifest_bytes)
        source = _validate_source(source_bytes)
        actual_digest = _candidate_digest(manifest_bytes, source_bytes)
        if actual_digest != digest:
            raise PluginLifecycleError("candidate_corrupt")
        return PluginCandidate(
            candidate_digest=actual_digest,
            manifest_digest=hashlib.sha256(manifest_bytes).hexdigest(),
            scope_digest=manifest.scope_digest,
            manifest=manifest,
            manifest_bytes=manifest_bytes,
            source=source,
        )
    except PluginLifecycleError as exc:
        if exc.code in ("manifest_rejected", "plugin_source_rejected"):
            raise PluginLifecycleError("candidate_corrupt") from exc
        raise
    finally:
        os.close(directory_fd)


def _read_regular_file(
    directory_fd: int, name: str, maximum_bytes: int, expected_mode: int
) -> bytes:
    try:
        descriptor = os.open(name, _READ_FLAGS, dir_fd=directory_fd)
    except OSError as exc:
        raise PluginLifecycleError("candidate_corrupt") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != expected_mode
            or before.st_size <= 0
            or before.st_size > maximum_bytes
        ):
            raise PluginLifecycleError("candidate_corrupt")
        content = bytearray()
        while len(content) <= maximum_bytes:
            chunk = os.read(descriptor, min(64 * 1024, maximum_bytes + 1 - len(content)))
            if not chunk:
                break
            content.extend(chunk)
        after = os.fstat(descriptor)
        if (
            len(content) != before.st_size
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or before.st_nlink != after.st_nlink
        ):
            raise PluginLifecycleError("candidate_corrupt")
        return bytes(content)
    except OSError as exc:
        raise PluginLifecycleError("candidate_corrupt") from exc
    finally:
        os.close(descriptor)


def _read_state(root_fd: int) -> tuple[dict[str, object], bytes]:
    try:
        descriptor = os.open("activation.json", _READ_FLAGS, dir_fd=root_fd)
    except FileNotFoundError:
        return _empty_state(), b""
    except OSError as exc:
        raise PluginLifecycleError("activation_state_corrupt") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size <= 0
            or before.st_size > 4_096
        ):
            raise PluginLifecycleError("activation_state_corrupt")
        data = _read_descriptor(descriptor, before.st_size)
        after = os.fstat(descriptor)
        if (
            len(data) != before.st_size
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
        ):
            raise PluginLifecycleError("activation_state_corrupt")
    finally:
        os.close(descriptor)

    try:
        envelope = json.loads(data.decode("ascii"), object_pairs_hook=_unique_object)
        if type(envelope) is not dict or set(envelope) != {"mac", "state"}:
            raise ValueError
        if _canonical_json(envelope) != data:
            raise ValueError
        state = _validate_state(envelope["state"])
        mac = envelope["mac"]
        if type(mac) is not str or re.fullmatch(r"[0-9a-f]{64}", mac) is None:
            raise ValueError
        key = _read_key(root_fd, create=False)
        expected = hmac.new(key, _canonical_json(state), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, expected):
            raise ValueError
        return state, key
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, PluginLifecycleError):
            raise
        raise PluginLifecycleError("activation_state_corrupt") from exc


def _read_key(root_fd: int, *, create: bool) -> bytes:
    if create:
        try:
            descriptor = os.open("activation.key", _WRITE_FLAGS, 0o400, dir_fd=root_fd)
        except FileExistsError:
            descriptor = -1
        except OSError as exc:
            raise PluginLifecycleError("activation_state_unavailable") from exc
        if descriptor >= 0:
            key = secrets.token_bytes(32)
            try:
                _write_all(descriptor, key)
                os.fchmod(descriptor, 0o400)
                os.fsync(descriptor)
            except OSError as exc:
                raise PluginLifecycleError("activation_state_unavailable") from exc
            finally:
                os.close(descriptor)
            os.fsync(root_fd)
            return key
    try:
        descriptor = os.open("activation.key", _READ_FLAGS, dir_fd=root_fd)
    except OSError as exc:
        raise PluginLifecycleError("activation_state_corrupt") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o400
            or metadata.st_size != 32
        ):
            raise PluginLifecycleError("activation_state_corrupt")
        key = _read_descriptor(descriptor, 32)
        if len(key) != 32:
            raise PluginLifecycleError("activation_state_corrupt")
        return key
    except OSError as exc:
        raise PluginLifecycleError("activation_state_corrupt") from exc
    finally:
        os.close(descriptor)


def _write_state(root_fd: int, key: bytes, state: dict[str, object]) -> None:
    envelope = {
        "mac": hmac.new(key, _canonical_json(state), hashlib.sha256).hexdigest(),
        "state": state,
    }
    data = _canonical_json(envelope)
    _atomic_replace_at(
        root_fd,
        "activation.json",
        data,
        temp_prefix=".activation-",
        unavailable_code="activation_state_unavailable",
        uncertain_code="activation_outcome_uncertain",
    )


def _validate_state(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != {
        "schema", "generation", "active", "previous"
    }:
        raise ValueError("state schema")
    if (
        type(value["schema"]) is not int
        or value["schema"] != _STATE_SCHEMA
        or type(value["generation"]) is not int
        or value["generation"] < 1
    ):
        raise ValueError("state version")
    for key in ("active", "previous"):
        if value[key] is not None:
            _activation_from_object(value[key])
    if value["active"] is None or value["previous"] is not None and value["generation"] < 2:
        raise ValueError("state slots")
    return value


def _validate_state_candidates(candidates_fd: int, state: dict[str, object]) -> None:
    for item in (state["active"], state["previous"]):
        if item is None:
            continue
        activation = _activation_from_object(item)
        candidate = _read_candidate(candidates_fd, activation.candidate_digest)
        _require_activation_matches_candidate(activation, candidate)


def _activation_from_object(value: object) -> Activation:
    if type(value) is not dict or set(value) != {
        "slot", "candidate_digest", "manifest_digest", "scope_digest",
        "approval_id", "approved_at", "expires_at",
    }:
        raise PluginLifecycleError("activation_state_corrupt")
    if (
        value["slot"] != "primary"
        or any(
            type(value[field]) is not str or _HEX_DIGEST.fullmatch(value[field]) is None
            for field in ("candidate_digest", "manifest_digest", "scope_digest")
        )
        or type(value["approval_id"]) is not str
        or re.fullmatch(r"[0-9a-f]{32}", value["approval_id"]) is None
        or type(value["approved_at"]) is not int
        or type(value["expires_at"]) is not int
        or value["approved_at"] < 0
        or value["expires_at"] <= value["approved_at"]
        or value["expires_at"] - value["approved_at"] != ACTIVATION_APPROVAL_SECONDS
    ):
        raise PluginLifecycleError("activation_state_corrupt")
    return Activation(
        slot=value["slot"],
        candidate_digest=value["candidate_digest"],
        manifest_digest=value["manifest_digest"],
        scope_digest=value["scope_digest"],
        approval_id=value["approval_id"],
        approved_at=value["approved_at"],
        expires_at=value["expires_at"],
    )


def _activation_object(value: Activation) -> dict[str, object]:
    return {
        "slot": value.slot,
        "candidate_digest": value.candidate_digest,
        "manifest_digest": value.manifest_digest,
        "scope_digest": value.scope_digest,
        "approval_id": value.approval_id,
        "approved_at": value.approved_at,
        "expires_at": value.expires_at,
    }


def _require_activation_matches_candidate(
    activation: Activation, candidate: PluginCandidate
) -> None:
    if (
        activation.candidate_digest != candidate.candidate_digest
        or activation.manifest_digest != candidate.manifest_digest
        or activation.scope_digest != candidate.scope_digest
    ):
        raise PluginLifecycleError("activation_state_corrupt")


def _require_same_candidate(left: PluginCandidate, right: PluginCandidate) -> None:
    if (
        left.candidate_digest != right.candidate_digest
        or left.manifest_digest != right.manifest_digest
        or left.scope_digest != right.scope_digest
    ):
        raise PluginLifecycleError("candidate_corrupt")


def _check_directory(
    descriptor: int,
    expected_mode: int,
    *,
    corrupt_code: str = "store_unavailable",
) -> None:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != expected_mode
    ):
        raise PluginLifecycleError(corrupt_code)


def _open_owned_directory_at(
    parent_fd: int,
    name: str,
    *,
    unavailable_code: str,
    corrupt_code: str,
) -> int:
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except FileExistsError:
        pass
    except OSError as exc:
        raise PluginLifecycleError(unavailable_code) from exc
    try:
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        raise PluginLifecycleError(unavailable_code) from exc
    try:
        _check_directory(descriptor, 0o700, corrupt_code=corrupt_code)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_store_lock(
    directory_fd: int,
    name: str,
    *,
    unavailable_code: str,
    corrupt_code: str,
) -> int:
    try:
        descriptor = os.open(
            name,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_fd,
        )
    except OSError as exc:
        raise PluginLifecycleError(unavailable_code) from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size != 0
        ):
            raise PluginLifecycleError(corrupt_code)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        return descriptor
    except PluginLifecycleError:
        os.close(descriptor)
        raise
    except OSError as exc:
        os.close(descriptor)
        raise PluginLifecycleError(unavailable_code) from exc


def _atomic_replace_at(
    directory_fd: int,
    target_name: str,
    data: bytes,
    *,
    temp_prefix: str,
    unavailable_code: str,
    uncertain_code: str,
) -> None:
    name = f"{temp_prefix}{secrets.token_hex(16)}.tmp"
    try:
        descriptor = os.open(name, _WRITE_FLAGS, 0o600, dir_fd=directory_fd)
    except OSError as exc:
        raise PluginLifecycleError(unavailable_code) from exc
    replaced = False
    try:
        _write_all(descriptor, data)
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(
            name,
            target_name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        replaced = True
        os.fsync(directory_fd)
    except OSError as exc:
        raise PluginLifecycleError(
            uncertain_code if replaced else unavailable_code
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not replaced:
            try:
                os.unlink(name, dir_fd=directory_fd)
            except OSError:
                pass


def _empty_state() -> dict[str, object]:
    return {"schema": _STATE_SCHEMA, "generation": 0, "active": None, "previous": None}


def _timestamp(value: int | None) -> int:
    result = int(time.time()) if value is None else value
    if type(result) is not int or result < 0:
        raise PluginLifecycleError("invalid_time")
    return result


def _read_descriptor(descriptor: int, maximum_bytes: int) -> bytes:
    data = bytearray()
    while len(data) <= maximum_bytes:
        chunk = os.read(descriptor, min(64 * 1024, maximum_bytes + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result
