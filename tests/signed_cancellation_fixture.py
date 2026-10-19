"""Build-time-only overlays for the three signed cancellation acceptance cases.

The production builder never imports this module. Anchors must match exactly;
only the private build snapshot is edited, before hashing and signing.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

MARKER = "KHAOS_SIGNED_CANCELLATION_ACCEPTANCE_ONLY"
CASES = {"b32", "pre-commit", "post-commit"}


def host_receipt_contains_terminal(sent_base64: str, received_base64: str) -> bool:
    sent = base64.b64decode(sent_base64, validate=True)
    received = base64.b64decode(received_base64, validate=True)
    return received.startswith(sent)


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"acceptance source anchor must occur once: {old[:100]!r}")
    return source.replace(old, new, 1)


def overlay(snapshot: Path, control: Path, case: str) -> dict[str, str]:
    if case not in CASES or not control.is_absolute():
        raise ValueError("invalid acceptance fixture configuration")
    if MARKER in (snapshot / "khaos/kernel/broker.py").read_text():
        raise ValueError("acceptance source anchor must occur once: already overlaid")
    changed: dict[str, str] = {}

    def edit(relative: str, transform) -> None:
        target = snapshot / relative
        source = transform(target.read_text())
        target.write_text(source)
        changed[relative] = hashlib.sha256(target.read_bytes()).hexdigest()

    # These files are outside the workspace; neither Host nor Runner receives
    # access. The unconfined test controller only releases a timing barrier.
    event_path = json.dumps(str(control / "kernel-events.jsonl"))
    release_path = json.dumps(str(control / "release"))
    python_helpers = f'''\n# {MARKER}\ndef _acceptance_event(stage, **fields):
    import json, os
    entry = dict(stage=stage, pid=os.getpid(), **fields)
    with open({event_path}, "a") as stream:
        stream.write(json.dumps(entry, sort_keys=True) + "\\n")
        stream.flush()


def _acceptance_barrier(stage, **fields):
    import time
    from pathlib import Path
    _acceptance_event(stage, **fields)
    deadline = time.monotonic() + 55
    while not Path({release_path}).exists():
        if time.monotonic() >= deadline:
            _acceptance_event("barrier_timeout", barrier=stage)
            return False
        time.sleep(0.01)
    _acceptance_event("barrier_released", barrier=stage)
    return True
\n'''

    def broker(source: str) -> str:
        # Place helper after future imports, before ordinary imports.
        source = replace_once(source, "import base64\n", python_helpers + "import base64\n")
        source = replace_once(
            source,
            "        return _serve_process_exec(\n            request_id,\n",
            '        if workspace_request_id is not None:\n'
            '            _acceptance_event("RUNNER_EXECUTION", workspace_request_id=workspace_request_id,\n'
            '                          runner_request_id=request_id)\n'
            "        return _serve_process_exec(\n            request_id,\n",
        )
        source = replace_once(
            source,
            "    cancel_requested: Callable[[], bool] | None = None,\n) -> WorkspaceCommitSummary:\n",
            "    cancel_requested: Callable[[], bool] | None = None,\n"
            "    workspace_request_id: str | None = None,\n"
            ") -> WorkspaceCommitSummary:\n",
        )
        source = replace_once(
            source,
            "            cancel_requested=cancel_requested,\n        )\n    except WorkspaceCommitOutcomeUncertain:\n",
            "            cancel_requested=cancel_requested,\n"
            "            workspace_request_id=workspace_request_id,\n"
            "        )\n    except WorkspaceCommitOutcomeUncertain:\n",
        )
        source = replace_once(
            source,
            "def _commit_snapshot_in_sandbox(\n"
            "    snapshot: WorkspaceSnapshot,\n"
            "    workspace_write_scope: WorkspaceWriteScope,\n"
            "    *,\n"
            "    cancel_requested: Callable[[], bool] | None,\n"
            ") -> WorkspaceCommitSummary:\n",
            "def _commit_snapshot_in_sandbox(\n"
            "    snapshot: WorkspaceSnapshot,\n"
            "    workspace_write_scope: WorkspaceWriteScope,\n"
            "    *,\n"
            "    cancel_requested: Callable[[], bool] | None,\n"
            "    workspace_request_id: str | None = None,\n"
            ") -> WorkspaceCommitSummary:\n",
        )
        source = replace_once(
            source,
            "            authorized = _await_commit_authorization(\n"
            "                ready_read_fd,\n"
            "                decision_write_fd,\n"
            "                cancel_requested,\n"
            "            )\n",
            "            authorized = _await_commit_authorization(\n"
            "                ready_read_fd,\n"
            "                decision_write_fd,\n"
            "                cancel_requested,\n"
            "                workspace_request_id=workspace_request_id,\n"
            "            )\n",
        )
        source = replace_once(
            source,
            "def _await_commit_authorization(\n"
            "    ready_read_fd: int,\n"
            "    decision_write_fd: int,\n"
            "    cancel_requested: Callable[[], bool] | None,\n"
            ") -> bool | None:\n",
            "def _await_commit_authorization(\n"
            "    ready_read_fd: int,\n"
            "    decision_write_fd: int,\n"
            "    cancel_requested: Callable[[], bool] | None,\n"
            "    *,\n"
            "    workspace_request_id: str | None = None,\n"
            ") -> bool | None:\n",
        )
        if case in {"pre-commit", "post-commit"}:
            callback_anchor = (
                "            ) -> None:\n"
                "                apply_workspace_commit_sandbox(\n"
                "                    snapshot,\n"
                "                    staging_path,\n"
                "                    file_write_paths,\n"
                "                    create_unlink_paths,\n"
                "                )\n"
            )
            callback_replacement = (
                "            ) -> None:\n"
                "                import hashlib\n"
                '                staged_write_paths = ["/".join(path) for path in file_write_paths]\n'
                "                staged_file_sha256 = {\n"
                '                    "/".join(path): hashlib.sha256(\n'
                "                        staging_path.joinpath(*path).read_bytes()\n"
                "                    ).hexdigest()\n"
                "                    for path in file_write_paths\n"
                "                    if staging_path.joinpath(*path).is_file()\n"
                "                }\n"
                "                if workspace_request_id is not None:\n"
                "                    _acceptance_event(\n"
                '                        "PRIVATE_CHANGESET_READY",\n'
                "                        workspace_request_id=workspace_request_id,\n"
                "                        staged_write_paths=staged_write_paths,\n"
                "                        staged_file_sha256=staged_file_sha256,\n"
                "                    )\n"
                "                apply_workspace_commit_sandbox(\n"
                "                    snapshot,\n"
                "                    staging_path,\n"
                "                    file_write_paths,\n"
                "                    create_unlink_paths,\n"
                "                )\n"
            )
            source = replace_once(source, callback_anchor, callback_replacement)
        if case == "pre-commit":
            anchor = '            if message != _COMMIT_READY:\n                raise WorkspaceCommitError("workspace commit gate is invalid")\n'
            source = replace_once(source, anchor, anchor + '''            if workspace_request_id is not None and not _acceptance_barrier(
                "KERNEL_READY_PRE_ACCEPT",
                workspace_request_id=workspace_request_id,
            ):
                _write_all(decision_write_fd, _COMMIT_ABORT)
                return False
''')
        if case == "post-commit":
            anchor = '    return WorkspaceCommitSummary(added, modified, deleted)\n'
            source = replace_once(source, anchor, '''    if workspace_request_id is not None:
        _acceptance_event(
            "COMMIT_APPLIED",
            workspace_request_id=workspace_request_id,
            added=added,
            modified=modified,
            deleted=deleted,
        )
        _acceptance_barrier(
            "KERNEL_POST_COMMIT_PRE_REPLY",
            workspace_request_id=workspace_request_id,
        )
''' + anchor)
        return source

    edit("khaos/kernel/broker.py", broker)

    def worker(source: str) -> str:
        anchor = '''                    changes = serve_workspace_commit(
                        process.stdout.fileno(),
                        process.stdin.fileno(),
                        snapshot,
'''
        return replace_once(source, anchor, anchor + '''                        workspace_request_id=workspace_request_id,
''')

    edit("khaos/kernel/worker.py", worker)

    def service(source: str) -> str:
        # File output is test-only; protocol response bytes remain untouched.
        helper = f'''\n// {MARKER}
private func acceptanceEvent(_ stage: String, _ requestID: String, response: Data? = nil) {{
    var entry: [String: Any] = ["stage": stage, "request_id": requestID]
    if let response {{ entry["response_base64"] = response.base64EncodedString() }}
    guard var data = try? JSONSerialization.data(withJSONObject: entry, options: [.sortedKeys]),
          let stream = FileHandle(forWritingAtPath: {event_path}) else {{ fatalError("acceptance event unavailable") }}
    data.append(10)
    stream.seekToEndOfFile()
    stream.write(data)
    stream.closeFile()
}}
\n'''
        source += helper
        anchor = '        DispatchQueue.global(qos: .userInitiated).async {\n            let response: Data\n'
        source = replace_once(source, anchor, '''        if case .workspaceRun = invocation.request {
            acceptanceEvent("WORKSPACE_RUN_SUBMISSION", requestID.token)
        }
''' + anchor)
        anchor = '            self.finishWorkspaceRequest(requestID, cancellation: cancellation)\n            reply(response)\n'
        return replace_once(source, anchor, '''            if case .workspaceRun = invocation.request {
                acceptanceEvent("ORIGINAL_KERNEL_REPLY", requestID.token, response: response)
            }
''' + anchor)
    edit("khaos/macos/KernelWorkspaceService.swift", service)

    def launcher(source: str) -> str:
        anchor = '            handle.requestCancellation(matching: handle.identity) { cancellation in\n'
        source = replace_once(source, anchor, anchor + '''                writeAgentDiagnostic("acceptance-cancellation-ack=\\(cancellationLabel(cancellation))")
''')
        anchor = '                        let deliveryStatus: String\n'
        return replace_once(source, anchor, '''                        writeAgentDiagnostic("acceptance-terminal-sent=" + Data(outcome.text.utf8).base64EncodedString())
                        if case let .text(text) = terminalDelivery.reply {
                            writeAgentDiagnostic("acceptance-host-receipt=" + text)
                        }
''' + anchor)
    edit("khaos/macos/TrustedWorkspaceLauncherMain.swift", launcher)

    if case == "b32":
        def client(source: str) -> str:
            source = replace_once(source, '    private func beginSubmission() {\n', f'''    // {MARKER}
    private let acceptanceBarrier = DispatchSemaphore(value: 0)

    private func beginSubmission() {{
        fputs("acceptance-barrier=POST_APPROVAL_PRE_SUBMIT\\n", stderr)
        fflush(stderr)
        guard acceptanceBarrier.wait(timeout: .now() + 55) == .success else {{
            fputs("acceptance-barrier=TIMEOUT\\n", stderr)
            finishOriginal(.failure(.timedOut))
            return
        }}
''')
            anchor = '        if shouldSchedule {\n            scheduleCancellation()\n'
            return replace_once(source, anchor, '''        acceptanceBarrier.signal()
''' + anchor)
        edit("khaos/macos/KernelWorkspaceClient.swift", client)
    return changed
