from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path
import sys

resource_root = Path(__file__).resolve().parent
sys.path.insert(0, str(resource_root))

from khaos.ipc import receive_frame
from khaos.launcher import KernelLaunchError, run_workspace_command


workspace = Path(sys.argv[1])
workspace_root_fd = int(sys.argv[2])
cancel_descriptor = int(sys.argv[3])
cancelled = False
input_value = (workspace / "input.txt").read_text(encoding="utf-8")
request = receive_frame(0, timeout_seconds=5)
if (
    set(request) != {"version", "request_id", "operation", "payload"}
    or type(request.get("version")) is not int
    or request["version"] != 10
    or request.get("operation") != "workspace.run"
    or type(request.get("request_id")) is not str
    or len(request["request_id"]) != 32
    or not isinstance(request.get("payload"), dict)
    or set(request["payload"])
    != {
        "timeout_seconds",
        "runner_source",
        "runner_source_sha256",
        "workspace_read_scope",
        "workspace_write_scope",
    }
):
    raise SystemExit("invalid workspace request frame")
payload = request["payload"]
if (
    type(payload.get("timeout_seconds")) not in (int, float)
    or type(payload.get("runner_source")) is not str
    or type(payload.get("runner_source_sha256")) is not str
    or payload["runner_source_sha256"]
    != hashlib.sha256(payload["runner_source"].encode("utf-8")).hexdigest()
    or type(payload.get("workspace_read_scope")) is not list
    or any(type(value) is not str for value in payload["workspace_read_scope"])
    or type(payload.get("workspace_write_scope")) is not list
    or any(type(value) is not str for value in payload["workspace_write_scope"])
):
    raise SystemExit("invalid workspace request payload")


def cancellation_requested() -> bool:
    global cancelled
    if cancelled:
        return True
    try:
        value = os.read(cancel_descriptor, 1)
    except BlockingIOError:
        return False
    if value:
        cancelled = True
    return cancelled

python_executable = str(Path(sys.executable).resolve(strict=True))

try:
    result = run_workspace_command(
        workspace,
        runner_source=payload["runner_source"],
        workspace_read_scope=payload["workspace_read_scope"],
        workspace_write_scope=payload["workspace_write_scope"],
        timeout_seconds=payload["timeout_seconds"],
        cancel_requested=cancellation_requested,
        workspace_root_fd=workspace_root_fd,
    )
except KernelLaunchError as error:
    if str(error) == "process_cancelled":
        print("xpc-kernel-operation=process_cancelled")
        raise SystemExit(0)
    raise
except ValueError as error:
    cause = error
    while cause is not None:
        if isinstance(cause, OSError) and cause.errno in (errno.EPERM, errno.EACCES):
            print(f"xpc-kernel-workspace-root=denied:{cause.errno}")
            raise SystemExit(0)
        cause = cause.__cause__
    raise
expected_output = (
    "xpc-kernel-live-write=denied\n"
    f"xpc-kernel-input={input_value}\n"
    "xpc-kernel-snapshot-write=done\n"
)
if (
    result.returncode != 0
    or result.stdout != expected_output
):
    raise SystemExit(
        f"unexpected sandbox command result: {result.returncode}, "
        f"{result.stdout!r}, {result.stderr!r}"
    )
if (result.added, result.modified, result.deleted) != (1, 0, 0):
    raise SystemExit("unexpected trusted commit summary")
print("xpc-kernel-runner=returncode:0")
print("xpc-kernel-fs-scope=verified")
print(
    "xpc-kernel-commit="
    f"added:{result.added},modified:{result.modified},deleted:{result.deleted}"
)

outside_canary = workspace.parent / "sibling-secret.txt"


def reject_unsafe_changeset(
    kind: str,
    command: str,
    expected_stdout: str,
    candidate_paths: tuple[str, ...],
) -> None:
    argv = [python_executable, "-I", "-S", "-c", command]
    runner_source = f'''\
from khaos.runner_sdk import process_exec, workspace_commit

def run():
    result = process_exec({argv!r})
    if (result["returncode"], result["stdout"], result["stderr"]) != (
        0, {expected_stdout!r}, ""
    ):
        raise SystemExit(61)
    workspace_commit()
'''
    try:
        run_workspace_command(
            workspace,
            runner_source=runner_source,
            workspace_write_scope=candidate_paths,
            timeout_seconds=10,
            workspace_root_fd=workspace_root_fd,
        )
    except KernelLaunchError as error:
        if str(error) != "commit_rejected":
            raise
    else:
        raise SystemExit(f"Kernel committed an unsafe XPC {kind} changeset")

    if any(os.path.lexists(workspace / path) for path in candidate_paths):
        raise SystemExit(f"Kernel partially committed an unsafe XPC {kind} changeset")
    if (workspace / "output.txt").read_text(encoding="utf-8") != "committed:xpc-input":
        raise SystemExit(f"rejected XPC {kind} changeset changed the prior output")
    if outside_canary.read_text(encoding="utf-8") != "sibling-secret":
        raise SystemExit(f"unsafe XPC {kind} changeset changed the outside canary")
    print(f"xpc-kernel-unsafe-{kind}=commit_rejected")


reject_unsafe_changeset(
    "symlink",
    """\
from pathlib import Path
Path('safe-companion.txt').write_text('candidate', encoding='utf-8')
Path('escape-link').symlink_to('../sibling-secret.txt')
print('symlink-ready')
""",
    "symlink-ready\n",
    ("safe-companion.txt", "escape-link"),
)
reject_unsafe_changeset(
    "hardlink",
    """\
import os
from pathlib import Path
Path('safe-companion.txt').write_text('candidate', encoding='utf-8')
Path('hardlink-source.txt').write_text('candidate', encoding='utf-8')
os.link('hardlink-source.txt', 'hardlink-alias.txt')
print('hardlink-ready')
""",
    "hardlink-ready\n",
    ("safe-companion.txt", "hardlink-source.txt", "hardlink-alias.txt"),
)
reject_unsafe_changeset(
    "special",
    """\
import os
from pathlib import Path
Path('safe-companion.txt').write_text('candidate', encoding='utf-8')
os.mkfifo('injected-pipe')
print('special-ready')
""",
    "special-ready\n",
    ("safe-companion.txt", "injected-pipe"),
)
print("xpc-kernel-unsafe-commit=commit_rejected")
print("xpc-kernel-unsafe-output=absent")
print("xpc-kernel-prior-output=preserved")
print("xpc-kernel-outside-canary=unchanged")
