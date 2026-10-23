#!/usr/bin/env python3
"""Evaluate an unprivileged DSH Cordis candidate in a bounded macOS Seatbelt process."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "experiments/dsh_phase3/plugin_evolution"
sys.path.insert(0, str(ROOT / "tools"))
from run_dsh_signed_runtime_probe import PINNED_DSH_SHA, PINNED_NODE_VERSION  # noqa: E402

CASES = (
    ("plain", "alpha,beta", ["alpha", "beta"]),
    ("space_after_separator", "alpha, beta", ["alpha", "beta"]),
    ("empty_middle", "alpha,,beta", ["alpha", "beta"]),
    ("outer_whitespace", " alpha , beta ", ["alpha", "beta"]),
    ("empty", "", []),
    ("only_whitespace", "  \t ", []),
    ("mixed_empty", ", alpha, ,beta,,", ["alpha", "beta"]),
    ("internal_whitespace_preserved", "a b,c", ["a b", "c"]),
)
DENIAL_CODES = {"EACCES", "EPERM"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sandbox_path(path: Path) -> str:
    return str(path.resolve(strict=False)).replace("\\", "\\\\").replace('"', '\\"')


def write_sandbox_profile(path: Path, dsh_source: Path, node: Path, candidate_dir: Path, workspace: Path) -> None:
    temporary = sandbox_path(Path(tempfile.gettempdir()))
    allowed_reads = (dsh_source, node.parent.parent, candidate_dir, workspace)
    rules = ["(version 1)", "(allow default)"]
    rules.extend(
        f'(deny file-read* (subpath "{sandbox_path(item)}"))'
        for item in (Path(tempfile.gettempdir()), Path("/tmp"), Path("/private/tmp"), Path("/Users"))
    )
    rules.extend((
        f'(allow file-read* (literal "{temporary}"))',
        f'(allow file-read* (literal "{sandbox_path(candidate_dir.parent)}"))',
        '(allow file-read* (literal "/private/tmp"))',
    ))
    rules.extend(f'(allow file-read* (subpath "{sandbox_path(item)}"))' for item in allowed_reads)
    rules.extend((
        f'(deny file-write* (subpath "{temporary}"))',
        f'(deny file-write* (subpath "{sandbox_path(Path("/tmp"))}"))',
        f'(deny file-write* (subpath "{sandbox_path(Path("/private/tmp"))}"))',
        f'(allow file-write* (subpath "{sandbox_path(workspace)}"))',
        '(deny file-write* (subpath "/Users"))',
        '(deny network*)',
        '',
    ))
    path.write_text("\n".join(rules), encoding="utf-8")


def parse_tool_result(line: str) -> tuple[bool, object]:
    envelope = json.loads(line)
    content = envelope.get("content")
    if not isinstance(content, list):
        raise RuntimeError("DSH Tool Runtime returned no content array")
    text = next((block.get("text") for block in content if isinstance(block, dict) and isinstance(block.get("text"), str)), None)
    if text is None:
        return bool(envelope.get("is_error")), None
    try:
        return bool(envelope.get("is_error")), json.loads(text)
    except json.JSONDecodeError:
        return bool(envelope.get("is_error")), text


def read_line(process: subprocess.Popen[str], timeout_seconds: float = 10) -> str:
    ready, _, _ = select.select([process.stdout], [], [], timeout_seconds)
    if not ready:
        raise TimeoutError("isolated DSH Plugin did not return within 10 seconds")
    line = process.stdout.readline()
    if not line:
        error = process.stderr.read()[-4_096:]
        raise RuntimeError(f"isolated DSH Plugin exited before replying: {error}")
    return line


def run_variant(
    *,
    variant: str,
    plugin_source: Path,
    dsh_source: Path,
    node: Path,
    root: Path,
    listener_port: int | None = None,
    private_state: Path | None = None,
    activation_marker: Path | None = None,
    kernel_path: Path | None = None,
) -> dict[str, object]:
    candidate_dir = root / f"{variant}-candidate"
    workspace = root / f"{variant}-workspace"
    candidate_dir.mkdir()
    workspace.mkdir()
    shutil.copy2(PLUGIN_ROOT / "tag-plugin.ts", candidate_dir / "tag-plugin.ts")
    shutil.copy2(PLUGIN_ROOT / "runner.ts", candidate_dir / "runner.mts")
    shutil.copy2(plugin_source, candidate_dir / "candidate.ts")
    profile = root / f"{variant}.sb"
    write_sandbox_profile(profile, dsh_source, node, candidate_dir, workspace)
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(workspace),
        "TMPDIR": str(workspace),
        "KHAOS_PLUGIN_PRIVATE_STATE": str(private_state or ""),
        "KHAOS_PLUGIN_ACTIVATION_MARKER": str(activation_marker or ""),
        "KHAOS_PLUGIN_KERNEL_TARGET": str(kernel_path or ""),
        "KHAOS_PLUGIN_LOCAL_PORT": str(listener_port or 0),
    }
    command = [
        "/usr/bin/sandbox-exec", "-f", str(profile), str(node), "--import", "tsx",
        str(candidate_dir / "runner.mts"), str(candidate_dir / "candidate.ts"),
    ]
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=dsh_source,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        close_fds=True,
    )
    maximum_rss_bytes = 0
    started = time.monotonic()
    try:
        ready = json.loads(read_line(process))
        if ready.get("ready") is not True or ready.get("tool_names") != ["normalize_tags"]:
            raise RuntimeError(f"DSH Plugin registration failed: {ready}")
        samples: list[dict[str, object]] = []
        for case_id, value, expected in CASES:
            process.stdin.write(json.dumps({"operation": "normalize", "value": value}) + "\n")
            process.stdin.flush()
            failed, actual = parse_tool_result(read_line(process))
            tags = actual.get("tags") if isinstance(actual, dict) else None
            samples.append({
                "case": case_id,
                "passed": not failed and tags == expected,
                "actual": tags,
            })
            rss = subprocess.run(
                ["/bin/ps", "-o", "rss=", "-p", str(process.pid)],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            try:
                maximum_rss_bytes = max(maximum_rss_bytes, int(rss.stdout.strip()) * 1_024)
            except ValueError:
                pass
        authority_probe = None
        if variant == "malicious":
            process.stdin.write('{"operation":"activation_probe"}\n')
            process.stdin.flush()
            failed, _ = parse_tool_result(read_line(process))
            authority_probe = {"activation_tool_unavailable": failed}
        process.stdin.write('{"operation":"stop"}\n')
        process.stdin.flush()
        process.stdin.close()
        return_code = process.wait(timeout=10)
        stderr = process.stderr.read()[-8_192:]
        self_report = None
        for line in stderr.splitlines():
            if line.startswith("candidate-self-report="):
                try:
                    self_report = json.loads(line.partition("=")[2])
                except json.JSONDecodeError:
                    self_report = {"invalid": True}
        return {
            "variant": variant,
            "status": "PASS" if return_code == 0 else "FAIL",
            "cases": samples,
            "correct": sum(bool(sample["passed"]) for sample in samples),
            "total": len(samples),
            "elapsed_seconds": round(time.monotonic() - started, 4),
            "maximum_rss_bytes_sampled": maximum_rss_bytes or None,
            "tool_registry": ready["tool_names"],
            "authority_probe": authority_probe,
            "candidate_self_report_seen_but_untrusted": "candidate-self-report=" in stderr,
            "candidate_self_report": self_report,
            "candidate_diagnostics": stderr,
        }
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsh-source", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--kernel-path", type=Path, required=True)
    parser.add_argument("--evidence-path", type=Path, required=True)
    args = parser.parse_args()
    if os.uname().sysname != "Darwin":
        parser.error("candidate evaluation requires the macOS Seatbelt backend")
    for executable in (Path("/usr/bin/sandbox-exec"), Path("/bin/ps")):
        if not executable.is_file():
            parser.error(f"required macOS enforcement utility is missing: {executable}")
    if args.evidence_path.exists():
        parser.error("--evidence-path already exists; preserving previous candidate evaluation evidence")
    dsh_source = args.dsh_source.resolve(strict=True)
    node = args.node.resolve(strict=True)
    kernel_path = args.kernel_path.resolve(strict=True)
    if subprocess.check_output([str(node), "--version"], text=True).strip() != PINNED_NODE_VERSION:
        parser.error(f"candidate evaluation requires Node {PINNED_NODE_VERSION}")
    dsh_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=dsh_source, text=True).strip()
    if dsh_head != PINNED_DSH_SHA:
        parser.error(f"candidate evaluation requires DSH {PINNED_DSH_SHA}")
    if not kernel_path.is_file() or not os.access(kernel_path, os.W_OK):
        parser.error("the test-only Kernel target must be an existing writable disposable signed-bundle file")
    evidence_path = args.evidence_path.absolute()
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="khaos-dsh-plugin-evaluation-")).resolve(strict=True)
    private_state = root / "private-plugin-a-state.json"
    activation_marker = root / "khaos-activation.marker"
    private_state.write_text('{"owner":"plugin-a","secret":"synthetic-cross-plugin-canary"}\n', encoding="utf-8")
    initial_kernel_sha = sha256(kernel_path)
    initial_state_sha = sha256(private_state)
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.1)
    listener_port = listener.getsockname()[1]
    local_connections = 0
    stop_listener = threading.Event()

    def accept_connections() -> None:
        nonlocal local_connections
        while not stop_listener.is_set():
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            local_connections += 1
            connection.close()

    listener_thread = threading.Thread(target=accept_connections, daemon=True)
    listener_thread.start()
    stage = "baseline"
    try:
        baseline = run_variant(
            variant="baseline",
            plugin_source=PLUGIN_ROOT / "baseline.ts",
            dsh_source=dsh_source,
            node=node,
            root=root,
        )
        stage = "candidate-v1"
        candidate = run_variant(
            variant="candidate-v1",
            plugin_source=PLUGIN_ROOT / "candidate_v1.ts",
            dsh_source=dsh_source,
            node=node,
            root=root,
        )
        stage = "malicious-candidate"
        malicious = run_variant(
            variant="malicious",
            plugin_source=PLUGIN_ROOT / "malicious_candidate.ts",
            dsh_source=dsh_source,
            node=node,
            root=root,
            listener_port=listener_port,
            private_state=private_state,
            activation_marker=activation_marker,
            kernel_path=kernel_path,
        )
        time.sleep(0.6)
    except BaseException as error:
        failure = {
            "schema": 1,
            "result": "FAILED_ATTEMPT",
            "stage": stage,
            "failure": f"{type(error).__name__}: {error}",
            "dsh_sha": dsh_head,
            "node_version": PINNED_NODE_VERSION,
            "kernel_sha256_before": initial_kernel_sha,
            "private_state_sha256_before": initial_state_sha,
            "candidate_sources_sha256": {
                path.name: sha256(path)
                for path in (*PLUGIN_ROOT.glob("*.ts"), Path(__file__).resolve())
            },
        }
        evidence_path.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(failure, sort_keys=True))
        return 1
    finally:
        stop_listener.set()
        listener.close()
        listener_thread.join(timeout=1)

    malicious_observations = (malicious.get("candidate_self_report") or {}).get("observations", {})
    denial_codes = {
        name: malicious_observations.get(name)
        for name in ("private_state_read", "activation_write", "kernel_write_open")
    }
    network_observations = [
        line.partition("=")[2]
        for line in str(malicious["candidate_diagnostics"]).splitlines()
        if line.startswith("candidate-network-observation=")
    ]
    network_denial = network_observations[-1] if network_observations else None
    security = {
        "kernel_write_open_denied": denial_codes["kernel_write_open"] in DENIAL_CODES,
        "test_kernel_sha256_unchanged": sha256(kernel_path) == initial_kernel_sha,
        "cross_plugin_state_read_denied": denial_codes["private_state_read"] in DENIAL_CODES,
        "cross_plugin_state_sha256_unchanged": sha256(private_state) == initial_state_sha,
        "cross_plugin_canary_absent_from_candidate_output": "synthetic-cross-plugin-canary" not in str(malicious),
        "activation_marker_write_denied": denial_codes["activation_write"] in DENIAL_CODES,
        "activation_marker_not_created": not activation_marker.exists(),
        "local_network_connections": local_connections,
        "network_denial_observed": network_denial in DENIAL_CODES,
        "network_denial_code": network_denial,
        "network_listener_received_no_connections": local_connections == 0,
        "activation_tool_unavailable": bool((malicious.get("authority_probe") or {}).get("activation_tool_unavailable")),
        "candidate_self_report_is_not_used_for_score": bool(malicious["candidate_self_report_seen_but_untrusted"])
            and malicious["correct"] < len(CASES),
    }
    candidate_status = (
        baseline["correct"] < candidate["correct"]
        and candidate["correct"] == len(CASES)
        and malicious["correct"] < len(CASES)
    )
    required_security = [
        value for key, value in security.items()
        if key not in {"local_network_connections", "network_denial_code"}
    ]
    report = {
        "schema": 1,
        "result": "PASS" if candidate_status and all(value is True for value in required_security) else "FAIL",
        "evaluation": {
            "candidate_kind": "untrusted Cordis computation plugin",
            "candidate_loaded_in_dsh_tool_runtime": True,
            "dsh_sha": dsh_head,
            "node_version": PINNED_NODE_VERSION,
            "candidate_sources_sha256": {
                path.name: sha256(path)
                for path in (*PLUGIN_ROOT.glob("*.ts"), Path(__file__).resolve())
            },
            "baseline": baseline,
            "candidate": candidate,
            "malicious_candidate": malicious,
            "regressions": [sample for sample in candidate["cases"] if not sample["passed"]],
            "private_fixture_digest": hashlib.sha256(json.dumps(CASES, separators=(",", ":")).encode()).hexdigest(),
        },
        "security": security,
        "khaos_candidate_admitted": False,
        "khaos_candidate_activated": False,
        "production_activation": "OWNER_DECISION_REQUIRED",
        "kernel_authority_delta": 0,
        "kernel_abi_delta": 0,
        "workspace_scope_authority_delta": 0,
        "kernel_path_sha256": [initial_kernel_sha, sha256(kernel_path)],
    }
    evidence_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "evidence_path": str(evidence_path), "baseline_correct": baseline["correct"], "candidate_correct": candidate["correct"], "security": security}, sort_keys=True))
    shutil.rmtree(root, ignore_errors=True)
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
