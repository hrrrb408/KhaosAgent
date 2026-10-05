import Darwin
import Foundation

enum WorkspaceProbeRequest {
    static func rawWorkspaceRequestFrame(
        requestID: KernelWorkspaceXPC.RequestID,
        payload: [String: Any]
    ) throws -> Data {
        let body = try JSONSerialization.data(
            withJSONObject: [
                "version": KernelWorkspaceXPC.operationProtocolVersion,
                "request_id": requestID.token,
                "operation": "workspace.run",
                "payload": payload,
            ],
            options: [.sortedKeys]
        )
        return try rawJSONWorkspaceRequestFrame(body: body)
    }

    static func rawJSONWorkspaceRequestFrame(body: Data) throws -> Data {
        guard !body.isEmpty, body.count <= KernelWorkspaceXPC.maximumMessageBytes else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(EMSGSIZE))
        }
        var frame = Data()
        var length = UInt32(body.count).bigEndian
        withUnsafeBytes(of: &length) {
            frame.append(contentsOf: $0)
        }
        frame.append(body)
        return frame
    }

    static func forWorkspace(
        _ workspace: URL,
        timeoutSeconds: Double = 10
    ) -> KernelWorkspaceXPC.WorkspaceRunRequest {
        let command = #"""
        set -eu
        exec 2>/dev/null
        if (printf '%s' 'must-not-escape' > "$1/kernel-bypass.txt") 2>/dev/null; then
            exit 41
        else
            printf 'xpc-kernel-live-write=denied\n'
        fi
        input_value=$(/bin/cat input.txt)
        case "$input_value" in
            xpc-input|xpc-input-cancel|xpc-input-disconnect) ;;
            *) exit 42 ;;
        esac
        printf 'xpc-kernel-input=%s\n' "$input_value"
        if [ "$input_value" = xpc-input-cancel ] || [ "$input_value" = xpc-input-disconnect ]; then
            /bin/sleep 20
        fi
        printf 'committed:xpc-input' > output.txt
        printf 'xpc-kernel-snapshot-write=done\n'
        """#
        let commandArguments = String(reflecting: [
            "/bin/sh", "-c", command, "khaos-xpc-probe", workspace.path,
        ])
        let runnerSource = #"""
        from khaos.ipc import IPCProtocolError
        from khaos.runner_sdk import fs_list, fs_read, process_exec, workspace_commit

        def require_denied(action, error_code, failure_code):
            try:
                action()
            except IPCProtocolError as error:
                if error_code not in str(error):
                    raise
            else:
                raise SystemExit(failure_code)

        def run():
            if fs_read("input.txt") not in {
                b"xpc-input", b"xpc-input-cancel", b"xpc-input-disconnect"
            }:
                raise SystemExit(71)
            names = [entry["name"] for entry in fs_list()]
            if "input.txt" not in names or "unscoped-secret.txt" in names:
                raise SystemExit(72)
            require_denied(
                lambda: fs_read("unscoped-secret.txt"), "path_not_readable", 73
            )
            require_denied(
                lambda: fs_list("unscoped-secret.txt"), "path_not_listable", 74
            )
            require_denied(
                lambda: fs_read("../sibling-secret.txt"), "path_not_readable", 75
            )
            result = process_exec(\#(commandArguments))
            workspace_commit()
            return result["returncode"]
        """#
        return KernelWorkspaceXPC.WorkspaceRunRequest(
            timeoutSeconds: timeoutSeconds,
            runnerSource: runnerSource,
            runnerSourceSHA256: KernelWorkspaceXPC.runnerSourceSHA256(runnerSource),
            workspaceReadScope: ["input.txt"],
            workspaceWriteScope: ["output.txt"]
        )
    }
}
