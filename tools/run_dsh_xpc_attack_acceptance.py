#!/usr/bin/env python3
"""Run a real signed AgentHost XPC attack probe with the pinned DSH runtime."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "tools/build_dsh_xpc_acceptance_app.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, timeout: int = 30) -> str:
    result = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command exited {result.returncode}: {result.stdout[-16_000:]}"
        )
    return result.stdout.strip()


def stop_test_launcher(app: Path) -> None:
    expected = str(app / "Contents/MacOS/KhaosSeed")
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,command="],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    for line in result.stdout.splitlines():
        fields = line.strip().split(maxsplit=1)
        if len(fields) != 2 or not (fields[1] == expected or fields[1].startswith(expected + " ")):
            continue
        try:
            os.kill(int(fields[0]), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, ValueError):
            pass


def group_members(group_id: int) -> list[int]:
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,pgid=,command="],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    members: list[int] = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(maxsplit=2)
        if len(fields) != 3:
            continue
        try:
            process_id, process_group = int(fields[0]), int(fields[1])
        except ValueError:
            continue
        if process_group == group_id:
            members.append(process_id)
    return members


def wait_for_group_exit(group_id: int, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not group_members(group_id):
            return True
        time.sleep(0.1)
    return not group_members(group_id)


def running_nodes_for_app(app: Path) -> list[tuple[int, int]]:
    expected_node = str(app / "Contents/Resources/node")
    expected_script = str(app / "Contents/Resources/dsh/agenthost-runtime.mjs")
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,pgid=,command="],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    processes: list[tuple[int, int]] = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(maxsplit=2)
        if len(fields) != 3 or expected_node not in fields[2] or expected_script not in fields[2]:
            continue
        try:
            processes.append((int(fields[0]), int(fields[1])))
        except ValueError:
            continue
    return processes


def stop_nodes_for_app(app: Path) -> None:
    for _, group_id in running_nodes_for_app(app):
        try:
            os.killpg(group_id, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if not running_nodes_for_app(app):
            return
        time.sleep(0.05)
    for _, group_id in running_nodes_for_app(app):
        try:
            os.killpg(group_id, signal.SIGKILL)
        except ProcessLookupError:
            pass


def team_identifier(path: Path) -> str:
    details = run(["/usr/bin/codesign", "--display", "--verbose=4", str(path)])
    match = re.search(r"^TeamIdentifier=(.+)$", details, re.MULTILINE)
    if match is None or match.group(1) == "-":
        raise RuntimeError(f"signed bundle has no Team ID: {path}")
    return match.group(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsh-source", type=Path, required=True)
    parser.add_argument("--node-archive", type=Path, required=True)
    parser.add_argument("--signing-identity", required=True)
    parser.add_argument("--pnpm", default="pnpm")
    parser.add_argument("--keychain", type=Path)
    parser.add_argument("--python-executable", type=Path, default=Path(sys.executable))
    parser.add_argument(
        "--mode",
        choices=("attack", "coding", "fake-result", "cancellation", "node-crash", "plugin-lifecycle", "xpc-crash"),
        default="attack",
    )
    parser.add_argument("--cancellation-case", choices=("b32", "pre-commit", "post-commit"))
    parser.add_argument("--evidence-path", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args()

    if platform.system() != "Darwin":
        parser.error("the signed AgentHost XPC attack acceptance requires macOS")
    if args.timeout_seconds < 30 or args.timeout_seconds > 600:
        parser.error("--timeout-seconds must be between 30 and 600")
    if (args.mode == "cancellation") != (args.cancellation_case is not None):
        parser.error("--cancellation-case is required only with --mode cancellation")

    evidence_path = args.evidence_path.expanduser().absolute()
    if evidence_path.exists():
        parser.error("--evidence-path already exists; use a fresh path to preserve prior acceptance evidence")
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix="khaos-dsh-xpc-attack-")
    scratch = Path(temporary.name).resolve(strict=True)
    try:
        read_canary = scratch / "workspace-read-canary.txt"
        write_canary = scratch / "workspace-write-canary.txt"
        credential_canary = scratch / "credential-canary.txt"
        task_path = scratch / "agent-task.txt"
        workspace = scratch / "coding-workspace"
        cancellation_control = scratch / "cancellation-control"
        stdout_path = scratch / "launcher.stdout"
        stderr_path = scratch / "launcher.stderr"
        app = scratch / "Khaos DSH XPC Acceptance.app"

        read_canary.write_text("workspace read canary; do not disclose\n", encoding="utf-8")
        write_canary.write_text("workspace write canary; must remain unchanged\n", encoding="utf-8")
        credential_canary.write_text("DUMMY_SECRET_CANARY_DO_NOT_USE\n", encoding="utf-8")
        source_sha = run(["git", "-C", str(ROOT), "rev-parse", "HEAD"])
        if args.mode in {"coding", "fake-result", "cancellation", "node-crash", "xpc-crash"}:
            workspace.mkdir()
            if args.mode == "coding":
                (workspace / "example.py").write_text(
                    "def answer():\n    return 100\n",
                    encoding="utf-8",
                )
                (workspace / "test_example.py").write_text(
                    "import unittest\n\nfrom example import answer\n\n"
                    "class ExampleTest(unittest.TestCase):\n"
                    "    def test_answer(self):\n"
                    "        self.assertEqual(answer(), 200)\n\n"
                    "if __name__ == '__main__':\n    unittest.main()\n",
                    encoding="utf-8",
                )
                (workspace / "unscoped-canary.txt").write_text(
                    "sibling file outside every approved scope\n",
                    encoding="utf-8",
                )
                task_path.write_text("KHAOS_DSH_CODING_LOOP\n", encoding="utf-8")
            elif args.mode == "cancellation":
                (workspace / "tags.py").write_text(
                    'def parse_tags(value):\n    return value.split(",")\n',
                    encoding="utf-8",
                )
                (workspace / "unscoped-canary.txt").write_text(
                    "cancellation sibling canary\n",
                    encoding="utf-8",
                )
                cancellation_control.mkdir()
                (cancellation_control / "kernel-events.jsonl").touch(mode=0o600)
                task_path.write_text(
                    f"KHAOS_DSH_CANCELLATION_{args.cancellation_case.upper().replace('-', '_')}\n",
                    encoding="utf-8",
                )
            elif args.mode == "node-crash":
                (workspace / "fixture.txt").write_text("fresh task after intentional Node crash\n", encoding="utf-8")
                (workspace / "unscoped-canary.txt").write_text(
                    "node crash sibling canary\n",
                    encoding="utf-8",
                )
                task_path.write_text(
                    "KHAOS_DSH_NODE_CRASH_ON_RESULT\nKHAOS_DSH_RECOVERY_NEW_TASK\n",
                    encoding="utf-8",
                )
            elif args.mode == "xpc-crash":
                (workspace / "tags.py").write_text(
                    'def parse_tags(value):\n    return value.split(",")\n',
                    encoding="utf-8",
                )
                (workspace / "unscoped-canary.txt").write_text(
                    "AgentHost XPC crash sibling canary\n",
                    encoding="utf-8",
                )
                task_path.write_text(
                    "KHAOS_DSH_AGENTHOST_CRASH_ON_TOOL_RESULT\n"
                    "KHAOS_DSH_XPC_RECOVERY_NEW_TASK\n",
                    encoding="utf-8",
                )
            else:
                task_path.write_text("KHAOS_DSH_FAKE_RESULT\n", encoding="utf-8")
        elif args.mode == "plugin-lifecycle":
            task_path.write_text("KHAOS_DSH_PLUGIN_LIFECYCLE\n", encoding="utf-8")
        else:
            task_path.write_text("KHAOS_DSH_XPC_ATTACK\n", encoding="utf-8")
        initial_hashes = {
            "workspace_read": sha256(read_canary),
            "workspace_write": sha256(write_canary),
            "credential": sha256(credential_canary),
        }
        workspace_initial_hashes = {
            path.name: sha256(path) for path in workspace.iterdir() if path.is_file()
        } if args.mode in {"coding", "cancellation", "node-crash", "xpc-crash"} else {}

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        local_port = listener.getsockname()[1]
        local_connections = 0

        build_command = [
            sys.executable,
            str(BUILDER),
            "--dsh-source", str(args.dsh_source.resolve(strict=True)),
            "--node-archive", str(args.node_archive.resolve(strict=True)),
            "--signing-identity", args.signing_identity,
            "--output-app", str(app),
            "--probe-workspace-read-path", str(read_canary),
            "--probe-workspace-write-path", str(write_canary),
            "--probe-credential-path", str(credential_canary),
            "--probe-local-port", str(local_port),
            "--pnpm", args.pnpm,
            "--python-executable", str(args.python_executable.resolve(strict=True)),
        ]
        if args.keychain is not None:
            build_command.extend(("--keychain", str(args.keychain.expanduser().resolve(strict=True))))
        if args.mode == "cancellation":
            build_command.extend((
                "--cancellation-case", args.cancellation_case,
                "--cancellation-control-path", str(cancellation_control),
            ))
        print(run(build_command, timeout=600))
        if args.mode in {"coding", "fake-result"}:
            print(f"Select this disposable workspace in the signed app Picker: {workspace}", flush=True)
            if args.mode == "coding":
                print("Approve each of the three displayed read, edit, and test operations in the signed Launcher.", flush=True)
            else:
                print("Approve the one displayed command that prints fake test success text and exits with status 1.", flush=True)
        elif args.mode == "cancellation":
            print(f"Select this disposable workspace in the signed app Picker: {workspace}", flush=True)
            print("Review the Candidate B preview and its exact tags.py read/write scopes, then choose Run Once.", flush=True)
            print("At the named acceptance barrier, click Cancel task in that same signed Task Progress window.", flush=True)
        elif args.mode == "node-crash":
            print(f"Select this disposable workspace in the signed app Picker: {workspace}", flush=True)
            print("Approve the first fixture read; DSH Node exits while receiving that real result.", flush=True)
            print("Then approve the second fixture read for the new task after the XPC Host reconnects.", flush=True)
        elif args.mode == "xpc-crash":
            print(f"Select this disposable workspace in the signed app Picker: {workspace}", flush=True)
            print("Approve the scoped tags.py edit; the test Host XPC will terminate after receiving the committed Kernel result.", flush=True)
            print("Then approve the second task's tags.py read after the Launcher reconnects to a fresh AgentHost XPC.", flush=True)

        kernel = app / "Contents/XPCServices/KernelProduction.xpc/Contents/MacOS/KernelProduction"
        kernel_hash = sha256(kernel)
        build_record_path = app / "Contents/Resources/build-inputs.json"
        build_record = json.loads(build_record_path.read_text(encoding="utf-8"))
        if build_record.get("khaos_source_sha") != source_sha:
            raise RuntimeError("signed app build record does not bind to the current exact source SHA")

        stdout_path.touch()
        stderr_path.touch()
        launch = subprocess.Popen(
            [
                "/usr/bin/open", "-n", "-W", "-a", str(app),
                "--stdin", str(task_path),
                "--stdout", str(stdout_path),
                "--stderr", str(stderr_path),
                "--args", "--agent",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + args.timeout_seconds
        cancellation_barrier_seen = False
        cancellation_ack_seen = False
        cancellation_released = False

        def cancellation_events() -> list[dict[str, object]]:
            event_path = cancellation_control / "kernel-events.jsonl"
            if not event_path.exists():
                return []
            events: list[dict[str, object]] = []
            for line in event_path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    events.append(event)
            return events

        def release_cancellation_barrier() -> None:
            nonlocal cancellation_released
            if not cancellation_released:
                (cancellation_control / "release").touch(mode=0o600, exist_ok=False)
                cancellation_released = True

        try:
            while launch.poll() is None and time.monotonic() < deadline:
                while True:
                    try:
                        connection, _ = listener.accept()
                    except BlockingIOError:
                        break
                    else:
                        local_connections += 1
                        connection.close()
                if args.mode == "cancellation":
                    stderr_snapshot = stderr_path.read_text(encoding="utf-8", errors="replace")
                    events = cancellation_events()
                    if args.cancellation_case == "b32":
                        barrier_reached = "acceptance-barrier=POST_APPROVAL_PRE_SUBMIT" in stderr_snapshot
                    else:
                        expected_stage = (
                            "KERNEL_READY_PRE_ACCEPT" if args.cancellation_case == "pre-commit"
                            else "KERNEL_POST_COMMIT_PRE_REPLY"
                        )
                        barrier_reached = any(event.get("stage") == expected_stage for event in events)
                    if barrier_reached and not cancellation_barrier_seen:
                        cancellation_barrier_seen = True
                        print(
                            f"USER ACTION REQUIRED: {args.cancellation_case} reached its signed barrier. "
                            "Click Cancel task in the original Task Progress window now.",
                            flush=True,
                        )
                    if "acceptance-cancellation-ack=" in stderr_snapshot:
                        cancellation_ack_seen = True
                    if cancellation_ack_seen and args.cancellation_case in {"b32", "post-commit"}:
                        release_cancellation_barrier()
                    if cancellation_ack_seen and args.cancellation_case == "pre-commit":
                        submissions = [event for event in events if event.get("stage") == "WORKSPACE_RUN_SUBMISSION"]
                        bridges = [event for event in events if event.get("stage") == "WORKSPACE_REQUEST_BRIDGE"]
                        forwarded = [event for event in events if event.get("stage") == "WORKSPACE_CANCEL_FORWARDED"]
                        if len(submissions) == len(bridges) == len(forwarded) == 1:
                            request_id = submissions[0].get("request_id")
                            workspace_request_id = bridges[0].get("workspace_request_id")
                            if forwarded[0].get("xpc_request_id") == request_id \
                                    and forwarded[0].get("workspace_request_id") == workspace_request_id:
                                release_cancellation_barrier()
                time.sleep(0.1)
            if launch.poll() is None:
                stop_test_launcher(app)
                launch.terminate()
                try:
                    launch.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    launch.kill()
                    launch.wait(timeout=5)
                raise RuntimeError("signed AgentHost XPC attack task did not exit before timeout")
            if launch.returncode != 0:
                raise RuntimeError(f"Launch Services returned exit {launch.returncode}")
            if args.mode == "cancellation" and not (cancellation_barrier_seen and cancellation_ack_seen):
                raise RuntimeError("signed cancellation run omitted the required barrier or actual user cancellation")
        finally:
            listener.close()

        stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
        attack = None
        lifecycle = None
        xpc_recovery = None
        node_pid = None
        descendant_pid = None
        descendant_group_clean = None
        if args.mode == "attack":
            marker = "Khaos: KHAOS_DSH_XPC_ATTACK_RESULT "
            result_lines = [line.partition(marker)[2] for line in stdout.splitlines() if marker in line]
            if len(result_lines) != 1:
                raise RuntimeError(
                    "signed AgentHost XPC did not return one hostile-plugin result; "
                    f"launcher stderr tail={stderr[-3000:]!r}"
                )
            attack = json.loads(result_lines[0])
            if attack.get("status") != "PASS" or attack.get("oversizedScopeBlocked") is not True:
                raise RuntimeError(f"signed AgentHost XPC hostile-plugin checks failed: {attack}")
            node_pid = attack.get("nodePid")
            descendant_pid = attack.get("descendantPid")
            if not isinstance(node_pid, int) or not isinstance(descendant_pid, int) or node_pid <= 0 or descendant_pid <= 0:
                raise RuntimeError("hostile Cordis Plugin omitted the Node and descendant process identities")
            descendant_group_clean = wait_for_group_exit(node_pid, 15)
            if not descendant_group_clean:
                members = group_members(node_pid)
                _ = os.killpg(node_pid, signal.SIGKILL)
                raise RuntimeError(f"AgentHost XPC teardown left Node process-group members running: {members}")
        elif args.mode == "plugin-lifecycle":
            marker = "Khaos: KHAOS_DSH_PLUGIN_LIFECYCLE_RESULT "
            result_lines = [line.partition(marker)[2] for line in stdout.splitlines() if marker in line]
            if len(result_lines) != 1:
                raise RuntimeError("signed AgentHost XPC omitted its Cordis Plugin lifecycle result")
            lifecycle = json.loads(result_lines[0])
            expected_checks = (
                "registeredOnce",
                "duplicateRegistrationRejected",
                "duplicateDidNotAddTool",
                "unloadRemovedTool",
                "inFlightLateResultRejected",
                "postUnloadCallRejected",
                "terminalTaskCallRejected",
            )
            if lifecycle.get("status") != "PASS" \
                    or any(lifecycle.get(check) is not True for check in expected_checks) \
                    or lifecycle.get("probePortCalls") != 2:
                raise RuntimeError(f"signed AgentHost XPC Cordis lifecycle checks failed: {lifecycle}")
            node_pid = lifecycle.get("nodePid")
            if not isinstance(node_pid, int) or node_pid <= 0:
                raise RuntimeError("Cordis lifecycle result omitted the signed XPC Node process identity")
            descendant_group_clean = wait_for_group_exit(node_pid, 15)
            if not descendant_group_clean:
                members = group_members(node_pid)
                _ = os.killpg(node_pid, signal.SIGKILL)
                raise RuntimeError(f"Cordis lifecycle Node process group survived XPC teardown: {members}")
        elif args.mode == "xpc-crash":
            failure_marker = "Agent Host failed while receiving a tool result (xpc_transport_failure)"
            if stdout.count(failure_marker) != 1:
                raise RuntimeError("the Launcher did not surface exactly one AgentHost XPC transport failure")
            if "Khaos: KHAOS_DSH_XPC_RECOVERY_TASK_RESULT" not in stdout:
                raise RuntimeError("a fresh AgentHost XPC did not complete the later independent task")
            if stderr.count("agent-session=tool=approval-presented") != 2 \
                    or stderr.count("agent-session=tool=approved kind=ordinary") != 2:
                raise RuntimeError("the XPC failure workflow did not receive two independent Runner approvals")
            records = [
                json.loads(line.partition("Launcher task record: ")[2])
                for line in stdout.splitlines()
                if "Launcher task record: " in line
            ]
            if len(records) != 2:
                raise RuntimeError("the XPC failure workflow did not preserve two separate task records")
            task_ids = [record.get("task_id") for record in records]
            if not all(isinstance(task_id, str) for task_id in task_ids) or len(set(task_ids)) != 2:
                raise RuntimeError("the later task reused the failed XPC task identity")
            requests = [request for record in records for request in record.get("workspace_requests", [])]
            request_ids = [request.get("request_id") for request in requests]
            if len(requests) != 2 or len(set(request_ids)) != 2:
                raise RuntimeError("the XPC failure caused an operation retry or reused its request identity")
            first_request, second_request = requests
            if first_request.get("kernel_result") != "output" \
                    or first_request.get("commit_outcome") != "committed" \
                    or first_request.get("runner_return_code") != 0:
                raise RuntimeError("the first task lost the committed original Kernel result")
            if second_request.get("kernel_result") != "output" \
                    or second_request.get("commit_outcome") != "committed" \
                    or second_request.get("runner_return_code") != 0:
                raise RuntimeError("the recovered task did not retain its own successful Kernel result")
            expected_tags = (
                'def parse_tags(value):\n'
                '    return [part.strip() for part in value.split(",") if part.strip()]\n'
            )
            if (workspace / "tags.py").read_text(encoding="utf-8") != expected_tags:
                raise RuntimeError("the first committed edit was lost during AgentHost XPC recovery")
            if sha256(workspace / "unscoped-canary.txt") != workspace_initial_hashes["unscoped-canary.txt"] \
                    or {path.name for path in workspace.iterdir()} != set(workspace_initial_hashes):
                raise RuntimeError("AgentHost XPC recovery changed an unscoped path or left a temporary file")
            if "Agent Host failed while receiving a tool result" not in records[0].get("stop_reason", ""):
                raise RuntimeError("the first task did not preserve its XPC failure stop reason")
            node_paths = running_nodes_for_app(app)
            if node_paths:
                stop_nodes_for_app(app)
                raise RuntimeError(f"AgentHost XPC teardown left Node process(es) running: {node_paths}")
            descendant_group_clean = True
            xpc_recovery = {
                "transport_failures": 1,
                "task_ids_unique": True,
                "request_ids_unique": True,
                "first_kernel_result": first_request.get("kernel_result"),
                "first_commit_outcome": first_request.get("commit_outcome"),
                "second_kernel_result": second_request.get("kernel_result"),
                "second_commit_outcome": second_request.get("commit_outcome"),
                "unscoped_canary_unchanged": True,
                "node_processes_after_xpc_teardown": 0,
            }
        elif args.mode == "coding":
            expected = "Khaos: DSH consumed the actual passing test result:"
            if expected not in stdout:
                raise RuntimeError(
                    "the signed deterministic DSH coding loop did not consume the actual passing test result; "
                    f"launcher stderr tail={stderr[-3000:]!r}"
                )
            if stderr.count("agent-session=tool=approval-presented") != 3 \
                    or stderr.count("agent-session=tool=approved kind=ordinary") != 3:
                raise RuntimeError("the signed DSH coding loop did not receive three owner-approved operations")
            expected_example = "def answer():\n    return 200\n"
            if (workspace / "example.py").read_text(encoding="utf-8") != expected_example:
                raise RuntimeError("the signed DSH coding loop did not commit the scoped edit")
            for name in ("test_example.py", "unscoped-canary.txt"):
                if sha256(workspace / name) != workspace_initial_hashes[name]:
                    raise RuntimeError(f"the signed DSH coding loop changed unapproved path {name}")
            record_lines = [
                line.partition("Launcher task record: ")[2]
                for line in stdout.splitlines()
                if "Launcher task record: " in line
            ]
            if len(record_lines) != 1:
                raise RuntimeError("the signed DSH coding loop did not emit one Launcher task record")
            task_record = json.loads(record_lines[0])
            if task_record.get("executed_command_return_codes") != [0, 0, 0]:
                raise RuntimeError("the signed DSH coding loop did not complete three successful Runner calls")
            if not isinstance(task_record.get("workspace_requests"), list) \
                    or len(task_record["workspace_requests"]) != 3:
                raise RuntimeError("the signed DSH coding loop did not record all three Kernel workspace requests")
        elif args.mode == "cancellation":
            event_path = cancellation_control / "kernel-events.jsonl"
            events = []
            for line in event_path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    events.append(event)
            record_lines = [
                line.partition("Launcher task record: ")[2]
                for line in stdout.splitlines()
                if "Launcher task record: " in line
            ]
            if len(record_lines) != 1:
                raise RuntimeError("the signed DSH cancellation run did not emit one Launcher task record")
            task_record = json.loads(record_lines[0])
            if task_record.get("cancellation_requested") is not True \
                    or task_record.get("terminal_result_delivery") != "delivered":
                raise RuntimeError("the Launcher did not record and deliver the cancelled task's terminal result")
            requests = task_record.get("workspace_requests")
            if not isinstance(requests, list) or len(requests) != 1:
                raise RuntimeError("the signed DSH cancellation task did not retain exactly one operation")
            request = requests[0]
            if request.get("approval") != "approved_candidate_b_preview" \
                    or request.get("cancellation_requested") is not True:
                raise RuntimeError("the cancellation record lost the actual Candidate B approval binding")
            if stderr.count("agent-session=tool=approval-presented") != 1 \
                    or stderr.count("agent-session=tool=approved kind=candidate_b_preview") != 1:
                raise RuntimeError("the signed DSH cancellation run did not record one owner-approved Candidate B action")

            sent_values = [
                line.partition("acceptance-terminal-sent=")[2]
                for line in stderr.splitlines()
                if "acceptance-terminal-sent=" in line
            ]
            receipt_lines = [
                line.partition("acceptance-host-receipt=")[2]
                for line in stderr.splitlines()
                if "acceptance-host-receipt=" in line
            ]
            if len(sent_values) != 1 or len(receipt_lines) != 1 \
                    or not receipt_lines[0].startswith("CANCELLATION_RECEIPT_BASE64 "):
                raise RuntimeError("DSH did not return an explicit cancellation terminal receipt")
            received_value = receipt_lines[0].partition("CANCELLATION_RECEIPT_BASE64 ")[2]
            try:
                sent_terminal = base64.b64decode(sent_values[0], validate=True)
                received_terminal = base64.b64decode(received_value, validate=True)
            except (ValueError, base64.binascii.Error) as error:
                raise RuntimeError("DSH cancellation terminal receipt was not valid Base64") from error
            if not received_terminal.startswith(sent_terminal):
                raise RuntimeError("DSH's terminal receipt did not preserve the original Launcher result")

            submissions = [event for event in events if event.get("stage") == "WORKSPACE_RUN_SUBMISSION"]
            runners = [event for event in events if event.get("stage") == "RUNNER_EXECUTION"]
            bridges = [event for event in events if event.get("stage") == "WORKSPACE_REQUEST_BRIDGE"]
            kernel_replies = [event for event in events if event.get("stage") == "ORIGINAL_KERNEL_REPLY"]
            private_changes = [event for event in events if event.get("stage") == "PRIVATE_SNAPSHOT_CHANGED"]
            if args.cancellation_case == "b32":
                if submissions or runners or bridges or kernel_replies:
                    raise RuntimeError("B32 cancellation started a Kernel request or Runner")
                if request.get("kernel_result", "").startswith("not_submitted:") is False \
                        or request.get("commit_outcome") != "not_committed":
                    raise RuntimeError("B32 cancellation did not remain not-submitted")
            else:
                if not (len(submissions) == len(bridges) == len(runners) == len(kernel_replies) == 1):
                    raise RuntimeError("cancellation did not preserve one original Kernel request and Runner")
                submission, bridge, reply = submissions[0], bridges[0], kernel_replies[0]
                if submission.get("request_id") != request.get("request_id") \
                        or bridge.get("xpc_request_id") != request.get("request_id") \
                        or bridge.get("workspace_request_id") != runners[0].get("workspace_request_id") \
                        or reply.get("request_id") != request.get("request_id"):
                    raise RuntimeError("Kernel request, Runner, and original reply identities did not match")
                try:
                    kernel_reply = json.loads(base64.b64decode(reply["response_base64"], validate=True))
                except (KeyError, ValueError, base64.binascii.Error) as error:
                    raise RuntimeError("could not decode the original Kernel XPC result") from error
                if args.cancellation_case == "pre-commit":
                    forwarded = [event for event in events if event.get("stage") == "WORKSPACE_CANCEL_FORWARDED"]
                    if len(forwarded) != 1 \
                            or forwarded[0].get("xpc_request_id") != request.get("request_id") \
                            or forwarded[0].get("workspace_request_id") != bridge.get("workspace_request_id"):
                        raise RuntimeError("pre-commit cancellation was not forwarded on the original XPC request")
                    if kernel_reply.get("error", {}).get("code") != "process_cancelled" \
                            or request.get("kernel_result") != "error:process_cancelled" \
                            or request.get("commit_outcome") != "not_committed":
                        raise RuntimeError("pre-commit cancellation did not preserve the Kernel's cancelled result")
                else:
                    if kernel_reply.get("ok") is not True \
                            or request.get("kernel_result") != "output" \
                            or request.get("commit_outcome") != "committed":
                        raise RuntimeError("post-commit cancellation hid or replaced the committed Kernel result")
                if len(private_changes) != 1 or private_changes[0].get("changed_paths") != ["tags.py"]:
                    raise RuntimeError("the Candidate B request did not modify only its private scoped snapshot")

            expected_tags = (
                'def parse_tags(value):\n'
                '    return [part.strip() for part in value.split(",") if part.strip()]\n'
            ).encode("utf-8")
            actual_tags = (workspace / "tags.py").read_bytes()
            if args.cancellation_case == "post-commit":
                if actual_tags != expected_tags:
                    raise RuntimeError("post-commit cancellation did not preserve the already committed edit")
            elif actual_tags != b'def parse_tags(value):\n    return value.split(",")\n':
                raise RuntimeError("pre-commit cancellation changed live workspace state")
            if sha256(workspace / "unscoped-canary.txt") != workspace_initial_hashes["unscoped-canary.txt"] \
                    or {path.name for path in workspace.iterdir()} != set(workspace_initial_hashes):
                raise RuntimeError("the cancellation request changed an unscoped entry or left a temporary file")
        elif args.mode == "node-crash":
            if stderr.count("agent-session=tool=approval-presented") != 2 \
                    or stderr.count("agent-session=tool=approved kind=ordinary") != 2 \
                    or stderr.count("agent-session=tool=executed returncode=0") != 2:
                raise RuntimeError("the crash and recovery workflow did not receive two independently approved reads")
            if "Agent Host failed while receiving a tool result" not in stdout \
                    or "Khaos: KHAOS_DSH_RECOVERY_TASK_RESULT" not in stdout:
                raise RuntimeError("the failed Node task did not stop cleanly before a new DSH task succeeded")
            records = [
                json.loads(line.partition("Launcher task record: ")[2])
                for line in stdout.splitlines()
                if "Launcher task record: " in line
            ]
            if len(records) != 2:
                raise RuntimeError("the crash/recovery run did not preserve two separate Launcher task records")
            task_ids = [record.get("task_id") for record in records]
            if not all(isinstance(task_id, str) for task_id in task_ids) or len(set(task_ids)) != 2:
                raise RuntimeError("the post-crash task reused the prior Launcher task identity")
            requests = [
                request
                for record in records
                for request in record.get("workspace_requests", [])
            ]
            request_ids = [request.get("request_id") for request in requests]
            if len(requests) != 2 or len(set(request_ids)) != 2:
                raise RuntimeError("the Node crash triggered a retry or reused a workspace request identity")
            if requests[0].get("kernel_result") != "output" \
                    or requests[0].get("commit_outcome") != "committed" \
                    or requests[1].get("kernel_result") != "output" \
                    or requests[1].get("commit_outcome") != "committed":
                raise RuntimeError("the crash/recovery task records lost one of the original Kernel results")
            spawned = [
                (int(pid), int(group))
                for pid, group in re.findall(
                    r"dsh-runtime=spawned pid=(\d+) process_group=(\d+)", stderr
                )
            ]
            if len(spawned) < 2:
                raise RuntimeError("the signed AgentHost did not start a fresh Node runtime for recovery")
            for pid, group in spawned:
                if not wait_for_group_exit(group, 10):
                    members = group_members(group)
                    _ = os.killpg(group, signal.SIGKILL)
                    raise RuntimeError(f"Node runtime process group {group} survived XPC teardown: {members}")
            if sha256(workspace / "unscoped-canary.txt") != workspace_initial_hashes["unscoped-canary.txt"]:
                raise RuntimeError("the Node crash/recovery flow changed the unscoped sibling")
        else:
            marker = "Khaos: KHAOS_DSH_FAKE_RESULT_CHECK "
            result_lines = [line.partition(marker)[2] for line in stdout.splitlines() if marker in line]
            if len(result_lines) != 1:
                raise RuntimeError("the signed DSH fake-result scenario omitted its result check")
            fake_result = json.loads(result_lines[0])
            if fake_result.get("status") != "PASS" or fake_result.get("actualFailure") is not True \
                    or fake_result.get("fakeSuccessOutput") is not True:
                raise RuntimeError(f"the signed DSH fake-result check failed: {fake_result}")
            if stderr.count("agent-session=tool=approval-presented") != 1 \
                    or stderr.count("agent-session=tool=approved kind=ordinary") != 1:
                raise RuntimeError("the signed fake-result check did not receive one owner-approved operation")
            record_lines = [
                line.partition("Launcher task record: ")[2]
                for line in stdout.splitlines()
                if "Launcher task record: " in line
            ]
            if len(record_lines) != 1:
                raise RuntimeError("the signed fake-result check did not emit one Launcher task record")
            task_record = json.loads(record_lines[0])
            if task_record.get("executed_command_return_codes") != [1]:
                raise RuntimeError("the fake-success command did not retain the actual Runner failure status")
            if not isinstance(task_record.get("workspace_requests"), list) \
                    or len(task_record["workspace_requests"]) != 1:
                raise RuntimeError("the signed fake-result check did not record its Kernel workspace request")

        final_hashes = {
            "workspace_read": sha256(read_canary),
            "workspace_write": sha256(write_canary),
            "credential": sha256(credential_canary),
            "kernel": sha256(kernel),
        }
        if any(final_hashes[name] != initial_hashes[name] for name in initial_hashes):
            raise RuntimeError(f"a protected canary changed: {final_hashes}")
        if final_hashes["kernel"] != kernel_hash:
            raise RuntimeError("the signed Kernel binary changed during the hostile XPC run")
        if local_connections != 0:
            raise RuntimeError(f"the hostile Node child reached the local TCP listener {local_connections} time(s)")
        if args.mode in {"attack", "plugin-lifecycle"} \
                and ("workspace-picker-requested" in stderr or "tool-proposal" in stderr):
            raise RuntimeError("the hostile-plugin-only task unexpectedly requested workspace authority")
        codesign = run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)])
        signed_components = {
            "app": app,
            "agent_host_xpc": app / "Contents/XPCServices/KhaosAgentHost.xpc",
            "kernel_xpc": app / "Contents/XPCServices/KernelProduction.xpc",
            "snapshot_broker_xpc": app / "Contents/XPCServices/KernelSnapshotBroker.xpc",
        }
        team_identifiers = {
            name: team_identifier(path) for name, path in signed_components.items()
        }
        if len(set(team_identifiers.values())) != 1:
            raise RuntimeError(f"signed components do not share one Team ID: {team_identifiers}")

        report = {
            "schema": 1,
            "result": "PASS",
            "source_sha": source_sha,
            "pr41_base_sha": build_record.get("khaos_experiment_base_sha"),
            "dsh_sha": build_record.get("dsh_sha"),
            "node_version": build_record.get("node_version"),
            "node_archive_sha256": build_record.get("node_archive_sha256"),
            "build_record_sha256": sha256(build_record_path),
            "signed_app_bytes": sum(path.stat().st_size for path in app.rglob("*") if path.is_file()),
            "agent_host_xpc_sha256": sha256(
                app / "Contents/XPCServices/KhaosAgentHost.xpc/Contents/MacOS/KhaosAgentHost"
            ),
            "kernel_sha256_before_after": [kernel_hash, final_hashes["kernel"]],
            "canaries_unchanged": True,
            "local_tcp_connections": local_connections,
            "node_pid": node_pid,
            "descendant_pid": descendant_pid,
            "node_rss_bytes": attack.get("nodeRssBytes") if isinstance(attack, dict) else None,
            "node_process_group_clean_after_xpc_teardown": descendant_group_clean,
            "mode": args.mode,
            "hostile_cordis_plugin": attack,
            "cordis_plugin_lifecycle": lifecycle,
            "agenthost_xpc_recovery": xpc_recovery,
            "owner_approved_runner_calls": (
                3 if args.mode == "coding" else
                2 if args.mode in {"node-crash", "xpc-crash"} else
                1 if args.mode == "fake-result" else
                1 if args.mode == "cancellation" and args.cancellation_case != "b32" else
                0
            ),
            "deep_code_signature_verified": True,
            "launcher_workspace_picker_requested": args.mode in {"coding", "fake-result", "cancellation", "node-crash", "xpc-crash"},
            "launcher_tool_proposal_requested": args.mode in {"coding", "fake-result", "cancellation", "node-crash", "xpc-crash"},
            "cancellation_case": args.cancellation_case,
            "cancellation_barrier_reached": cancellation_barrier_seen if args.mode == "cancellation" else None,
            "cancellation_acknowledged": cancellation_ack_seen if args.mode == "cancellation" else None,
            "cancellation_barrier_released": cancellation_released if args.mode == "cancellation" else None,
            "cancellation_events": cancellation_events() if args.mode == "cancellation" else None,
            "cancellation_task_record": task_record if args.mode == "cancellation" else None,
            "dsh_terminal_preserved_original_result": args.mode == "cancellation",
            "node_runtime_spawned_count": len(re.findall(r"dsh-runtime=spawned pid=", stderr)),
            "node_runtime_stopped_count": len(re.findall(r"dsh-runtime=stopped pid=", stderr)),
            "signing_certificate_sha1": build_record.get("certificate_sha1"),
            "team_identifiers": team_identifiers,
        }
        evidence_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, sort_keys=True, indent=2))
        print(f"evidence_path={evidence_path}")
        print(f"codesign_verification={codesign}")
        temporary.cleanup()
        return 0
    except BaseException as error:
        failed_app = locals().get("app")
        if isinstance(failed_app, Path) and failed_app.exists():
            stop_nodes_for_app(failed_app)
        failure_path = evidence_path.with_name(f"{evidence_path.stem}.failed.json")
        if failure_path.exists():
            failure_path = evidence_path.with_name(
                f"{evidence_path.stem}.failed-{time.time_ns()}.json"
            )
        file_hashes = {}
        for name in (
            "read_canary", "write_canary", "credential_canary", "task_path",
            "stdout_path", "stderr_path", "kernel", "build_record_path",
        ):
            path = locals().get(name)
            if isinstance(path, Path) and path.is_file():
                file_hashes[name] = sha256(path)
        failure = {
            "schema": 1,
            "result": "FAILED_ATTEMPT",
            "mode": args.mode,
            "cancellation_case": args.cancellation_case,
            "source_sha": locals().get("source_sha"),
            "scratch_directory": str(scratch),
            "failure": f"{type(error).__name__}: {error}",
            "available_file_sha256": file_hashes,
            "app_bundle_preserved": (scratch / "Khaos DSH XPC Acceptance.app").exists(),
        }
        failure_path.write_text(json.dumps(failure, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        temporary._finalizer.detach()
        print(json.dumps(failure, sort_keys=True, indent=2), file=sys.stderr)
        print(f"failed_attempt_evidence={failure_path}", file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
