"""Run benchmark verification in a read-only, network-denied macOS sandbox."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import selectors
import shutil
import signal
import resource
import subprocess
import sys
import tempfile
import time
from typing import Any

from khaos.kernel.macos_seatbelt import (
    SANDBOX_EXECUTABLE,
    _python_runtime_paths,
    _snapshot_profile,
)


_MAX_OUTPUT_BYTES = 2 * 1024 * 1024
_OUTPUT_TAIL_BYTES = 8192
_MAX_RSS_KIB = 1024 * 1024


def _copy_regular_tree(source: Path, target: Path) -> None:
    """Copy only ordinary, non-linked benchmark files into a fresh tree."""
    target.mkdir(mode=0o700)
    for entry in sorted(source.iterdir(), key=lambda path: path.name):
        destination = target / entry.name
        if entry.is_symlink():
            raise ValueError("benchmark workspace contains a symlink")
        if entry.is_dir():
            _copy_regular_tree(entry, destination)
        elif entry.is_file():
            shutil.copyfile(entry, destination)
        else:
            raise ValueError("benchmark workspace contains a special file")


def run_suite(
    workspace: Path,
    test_path: Path,
    *,
    hidden: bool,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    """Run one frozen test module against a private copy of the trial workspace.

    No model-authored code runs on the evaluator host. The copied workspace is
    read-only under Seatbelt; network and child-process execution stay denied.
    """
    started = time.monotonic()
    timeout = timeout_seconds or (20 if hidden else 15)
    if sys.platform != "darwin" or not SANDBOX_EXECUTABLE.is_file() or not os.access(
        SANDBOX_EXECUTABLE, os.X_OK
    ):
        return {
            "status": "SANDBOX_UNAVAILABLE",
            "returncode": None,
            "elapsed_seconds": round(time.monotonic() - started, 4),
            "output_tail": "macOS Seatbelt evaluator is unavailable",
        }

    source_workspace = workspace.resolve(strict=True)
    source_test = test_path.resolve(strict=True)
    if not source_workspace.is_dir() or not source_test.is_file():
        raise ValueError("benchmark verification input is not a regular file or directory")
    code = (
        "import runpy,sys,types,unittest; sys.path.insert(0, sys.argv[1]); "
        "module=types.SimpleNamespace(**runpy.run_path(sys.argv[2], run_name='frozen_acceptance')); "
        "suite=unittest.defaultTestLoader.loadTestsFromModule(module); "
        "result=unittest.TextTestRunner(verbosity=2).run(suite); "
        "raise SystemExit(not result.wasSuccessful())"
    )
    output = bytearray()
    output_size = 0
    status = "FAIL"
    returncode: int | None = None
    max_rss_kib: int | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="khaos-independent-eval-") as root_value:
            root = Path(root_value).resolve(strict=True)
            copied_workspace = root / "workspace"
            _copy_regular_tree(source_workspace, copied_workspace)
            copied_workspace = copied_workspace.resolve(strict=True)
            if source_test.is_relative_to(source_workspace):
                copied_test = copied_workspace / source_test.relative_to(source_workspace)
            else:
                copied_test = root / "acceptance.py"
                shutil.copyfile(source_test, copied_test)
            copied_test = copied_test.resolve(strict=True)
            profile = _snapshot_profile(
                copied_workspace,
                _python_runtime_paths(),
                executable=Path(sys.executable).resolve(strict=True),
                allow_workspace_write=False,
                readable_paths=(copied_test.resolve(strict=True),) if hidden else (),
            )
            python = str(Path(sys.executable).resolve(strict=True))

            def set_limits() -> None:
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
                resource.setrlimit(resource.RLIMIT_CPU, (timeout + 1, timeout + 1))
                resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))

            process = subprocess.Popen(
                (
                    str(SANDBOX_EXECUTABLE),
                    "-p",
                    profile,
                    python,
                    "-I",
                    "-B",
                    "-c",
                    code,
                    str(copied_workspace),
                    str(copied_test),
                ),
                cwd=copied_workspace,
                env={
                    "HOME": str(root / "empty-home"),
                    "LANG": "C.UTF-8",
                    "PATH": "/usr/bin:/bin",
                    "TMPDIR": str(root),
                },
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                preexec_fn=set_limits,
            )
            assert process.stdout is not None
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + timeout
            timed_out = False
            output_limited = False
            resource_limited = False
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        timed_out = True
                        break
                    events = (
                        selector.select(min(0.1, remaining))
                        if selector.get_map()
                        else ()
                    )
                    for key, _ in events:
                        chunk = os.read(key.fd, 64 * 1024)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        output_size += len(chunk)
                        output.extend(chunk)
                        if len(output) > _OUTPUT_TAIL_BYTES:
                            del output[:-_OUTPUT_TAIL_BYTES]
                        if output_size > _MAX_OUTPUT_BYTES:
                            output_limited = True
                            break
                    if output_limited:
                        break
                    if process.poll() is not None and not selector.get_map():
                        break
                    try:
                        sample = subprocess.run(
                            ("/bin/ps", "-o", "rss=", "-p", str(process.pid)),
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=0.2,
                            env={"PATH": "/usr/bin:/bin", "LANG": "C"},
                        )
                    except subprocess.TimeoutExpired:
                        sample = None
                    try:
                        rss_kib = int(sample.stdout.strip()) if sample else 0
                    except ValueError:
                        rss_kib = 0
                    if rss_kib:
                        max_rss_kib = max(max_rss_kib or 0, rss_kib)
                        if rss_kib > _MAX_RSS_KIB:
                            resource_limited = True
                            break
            finally:
                selector.close()
                process.stdout.close()
            if timed_out or output_limited or resource_limited:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                returncode = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                returncode = process.wait(timeout=5)
            if timed_out:
                status = "TIMEOUT"
            elif output_limited:
                status = "OUTPUT_LIMIT"
            elif resource_limited:
                status = "RSS_LIMIT"
            else:
                status = "PASS" if returncode == 0 else "FAIL"
    except (OSError, RuntimeError, ValueError) as error:
        status = "SANDBOX_UNAVAILABLE"
        output.extend(str(error).encode("utf-8", errors="replace")[-_OUTPUT_TAIL_BYTES:])

    return {
        "status": status,
        "returncode": returncode,
        "elapsed_seconds": round(time.monotonic() - started, 4),
        "output_tail": output.decode("utf-8", errors="replace"),
        "output_sha256": hashlib.sha256(output).hexdigest(),
        "output_bytes_captured": min(output_size, _MAX_OUTPUT_BYTES),
        "max_rss_kib": max_rss_kib if max_rss_kib is not None else "NOT_MEASURED",
        "sandbox": "macos-seatbelt-read-only-no-network-no-child-process",
    }
