import AppKit
import CoreFoundation
import Darwin
import Foundation
import OSLog

private enum LauncherError: Error {
    case invalidArguments
    case operationRejected(String)
}

private struct ShellRun {
    let command: String
    let request: KernelWorkspaceXPC.WorkspaceRunRequest
}

private struct PluginRun {
    let identifier: String
    let manifestDigest: String
    let sourceDigest: String
    let request: KernelWorkspaceXPC.WorkspaceRunRequest
}

private struct WorkspaceResult {
    let returncode: Int
    let stdout: String
    let stderr: String
    let added: Int
    let modified: Int
    let deleted: Int
}

@main
enum TrustedWorkspaceLauncherMain {
    // Keep diagnostics useful without recording paths or command output.
    private static let logger = Logger(
        subsystem: "org.khaos.Seed",
        category: "workspace-smoke"
    )
    private static let serviceSuffix = ".KernelProduction"
    private static let serviceRequirementKey =
        "KhaosKernelProductionServiceRequirement"
    private static let acceptanceFixtureName = "seed-picker-fixture.txt"

    private static func runnerSource(
        readFixtureScope: Bool,
        writebackFileName: String
    ) -> String {
        """
        from khaos.ipc import IPCProtocolError
        from khaos.runner_sdk import fs_list, fs_read, fs_write, process_exec, workspace_commit

        READ_FIXTURE_SCOPE = \(readFixtureScope ? "True" : "False")
        WRITEBACK_NAME = \(String(reflecting: writebackFileName))
        WRITEBACK_DATA = b"Khaos Seed Kernel writeback smoke"

        def require_denied(action, expected, failure_code):
            try:
                action()
            except IPCProtocolError as error:
                if str(error) != expected:
                    raise SystemExit(failure_code)
            else:
                raise SystemExit(failure_code + 1)

        def run():
            if READ_FIXTURE_SCOPE:
                expected = b"preserve this selected-workspace fixture\\n"
                if fs_read("seed-picker-fixture.txt") != expected:
                    raise SystemExit(41)
                listed_names = [entry["name"] for entry in fs_list()]
                if listed_names != ["seed-picker-fixture.txt"]:
                    raise SystemExit(42)
                require_denied(
                    lambda: fs_read("seed-picker-unscoped-fixture.txt"),
                    "Kernel rejected fs.read: path_not_readable",
                    43,
                )
                require_denied(
                    lambda: fs_list("seed-picker-unscoped-fixture.txt"),
                    "Kernel rejected fs.list: path_not_listable",
                    45,
                )
            else:
                require_denied(
                    lambda: fs_read("seed-picker-fixture.txt"),
                    "Kernel rejected fs.read: path_not_readable",
                    47,
                )
                require_denied(
                    lambda: fs_list(),
                    "Kernel rejected fs.list: path_not_listable",
                    49,
                )
            write_result = fs_write(WRITEBACK_NAME, WRITEBACK_DATA)
            if write_result["written_bytes"] != len(WRITEBACK_DATA):
                raise SystemExit(51)
            require_denied(
                lambda: fs_write(
                    "seed-picker-unscoped-fixture.txt",
                    b"must remain outside the write scope",
                ),
                "Kernel rejected fs.write: path_not_writable",
                53,
            )
            result = process_exec(("/bin/bash", "-c", ":"))
            if result["returncode"] != 0:
                return result["returncode"]
            workspace_commit()
            return 0
        """
    }
    private static let writebackScript = ":"

    static func main() {
        let application = NSApplication.shared
        application.setActivationPolicy(.regular)
        let arguments = Array(CommandLine.arguments.dropFirst())
        let isBootstrapCheck = arguments == ["--bootstrap-check"]
        let isCommandRun = arguments.first == "--command"
        let isPluginRun = arguments == ["--plugin-run"]
        let isAgentRun = arguments == ["--agent"]
        var acceptanceRunID: String?
        do {
            if isAgentRun {
                try runAgentSession()
                return
            }
            if let shellRun = try shellRun(arguments: arguments) {
                let result = try runShellCommand(shellRun)
                logger.info("workspace-command=passed")
                fputs("workspace-command=passed\n", stderr)
                showCommandSuccess(result)
                return
            }
            if isPluginRun {
                let result = try runPlugin()
                logger.info("workspace-plugin=passed")
                fputs("workspace-plugin=passed\n", stderr)
                showCommandSuccess(result)
                return
            }
            let initialDirectory: URL?
            let acceptanceDirectory: URL?
            if arguments.isEmpty {
                initialDirectory = nil
                acceptanceDirectory = nil
            } else if arguments.count == 4,
                      arguments[0] == "--acceptance-workspace",
                      arguments[2] == "--acceptance-run-id",
                      let runID = UUID(uuidString: arguments[3]) {
                let directory = URL(
                    fileURLWithPath: arguments[1],
                    isDirectory: true
                )
                // Show the exact acceptance folder in its parent directory so
                // it is easy to select, without treating this path as a grant.
                initialDirectory = directory.deletingLastPathComponent()
                acceptanceDirectory = directory
                acceptanceRunID = runID.uuidString.lowercased()
            } else if isBootstrapCheck {
                try verifyKernelBootstrap()
                print("kernel-and-snapshot-broker-peer-authentication=verified")
                return
            } else {
                throw LauncherError.invalidArguments
            }
            if let acceptanceRunID {
                writeDiagnostic("acceptance-run-id=\(acceptanceRunID)")
            }
            let outputName = try verifySelectedWorkspace(
                initialDirectory: initialDirectory,
                acceptanceDirectory: acceptanceDirectory
            )
            let runSuffix = acceptanceRunID.map { " run-id=\($0)" } ?? ""
            logger.info(
                "workspace-kernel-smoke=passed direct-write=denied\(runSuffix, privacy: .public)"
            )
            writeDiagnostic("passed direct-write=denied\(runSuffix)")
            showSuccess(fileName: outputName, runID: acceptanceRunID)
        } catch TrustedWorkspacePickerError.cancelled {
            if isCommandRun || isPluginRun || isAgentRun {
                logger.info("workspace-command=cancelled")
                fputs("workspace-command=cancelled\n", stderr)
            } else {
                logger.info("workspace-kernel-smoke=cancelled")
                writeDiagnostic("cancelled")
            }
            return
        } catch {
            let code = failureCode(for: error)
            let runSuffix = acceptanceRunID.map { " run-id=\($0)" } ?? ""
            logger.error(
                "workspace-kernel-smoke=failed code=\(code, privacy: .public)\(runSuffix, privacy: .public)"
            )
            if isCommandRun || isPluginRun || isAgentRun {
                fputs("workspace-command=failed code=\(code)\n", stderr)
            } else {
                writeDiagnostic("failed code=\(code)\(runSuffix)")
            }
            if isBootstrapCheck {
                fputs("kernel-and-snapshot-broker-peer-authentication=failed code=\(code)\n", stderr)
            } else {
                showFailure(
                    code: code,
                    runID: acceptanceRunID,
                    commandMode: isCommandRun || isPluginRun || isAgentRun
                )
            }
            exit(EXIT_FAILURE)
        }
    }

    private static func shellRun(arguments: [String]) throws -> ShellRun? {
        guard arguments.first == "--command" else { return nil }
        guard arguments.count >= 2 else { throw LauncherError.invalidArguments }
        let command = arguments[1]
        guard !command.isEmpty, reviewable(command),
              command.utf8.count <= 512 else {
            throw LauncherError.invalidArguments
        }
        var readScope: [String] = []
        var writeScope: [String] = []
        var index = 2
        while index < arguments.count {
            guard index + 1 < arguments.count,
                  reviewable(arguments[index + 1]),
                  arguments[index + 1].utf8.count <= 128 else {
                throw LauncherError.invalidArguments
            }
            switch arguments[index] {
            case "--read": readScope.append(arguments[index + 1])
            case "--write": writeScope.append(arguments[index + 1])
            default: throw LauncherError.invalidArguments
            }
            index += 2
        }
        guard readScope.count + writeScope.count <= 8 else {
            throw LauncherError.invalidArguments
        }

        // Only the isolated Runner decodes or executes the user's command.
        let encodedCommand = Data(command.utf8).base64EncodedString()
        let source = """
            from base64 import b64decode
            from khaos.runner_sdk import process_exec, workspace_commit

            COMMAND = b64decode("\(encodedCommand)").decode("utf-8")

            def run():
                result = process_exec(("/bin/bash", "-c", COMMAND))
                if result["returncode"] == 0:
                    workspace_commit()
                return result["returncode"]
            """
        let request = KernelWorkspaceXPC.WorkspaceRunRequest(
            timeoutSeconds: 30,
            runnerSource: source,
            runnerSourceSHA256: KernelWorkspaceXPC.runnerSourceSHA256(source),
            workspaceReadScope: readScope,
            workspaceWriteScope: writeScope
        )
        do {
            _ = try request.encodeFrame(requestID: KernelWorkspaceXPC.newRequestID())
        } catch {
            throw LauncherError.invalidArguments
        }
        return ShellRun(command: command, request: request)
    }

    private static func reviewable(_ value: String) -> Bool {
        value.unicodeScalars.allSatisfy { scalar in
            !CharacterSet.controlCharacters.contains(scalar)
                && scalar.properties.generalCategory != .format
        }
    }

    private static func runPlugin() throws -> WorkspaceResult {
        let packageURL = try TrustedWorkspacePicker.selectPluginPackage()
        var packageScopeReleased = false
        defer {
            if !packageScopeReleased {
                packageURL.stopAccessingSecurityScopedResource()
            }
        }
        let manifestData = try readPackageFile(
            packageURL, name: "manifest.json", maximumBytes: 4096
        )
        let sourceData = try readPackageFile(
            packageURL, name: "plugin.py", maximumBytes: 10_240
        )
        guard let manifest = try? JSONSerialization.jsonObject(with: manifestData)
                as? [String: Any],
              let canonical = try? JSONSerialization.data(
                withJSONObject: manifest, options: [.sortedKeys]
              ),
              canonical == manifestData
                || canonical + Data([0x0a]) == manifestData,
              Set(manifest.keys) == [
                "abi_version", "id", "process_exec", "read", "write"
              ],
              let version = manifest["abi_version"] as? NSNumber,
              CFGetTypeID(version) != CFBooleanGetTypeID(),
              version.stringValue == "6",
              let identifier = manifest["id"] as? String,
              identifier.count <= 64,
              identifier.first?.isASCII == true,
              identifier.first?.isLowercase == true,
              identifier.utf8.allSatisfy({
                ($0 >= 97 && $0 <= 122) || ($0 >= 48 && $0 <= 57) || $0 == 45
              }),
              let process = manifest["process_exec"] as? NSNumber,
              CFGetTypeID(process) == CFBooleanGetTypeID(),
              process.boolValue,
              let readScope = manifest["read"] as? [String],
              let writeScope = manifest["write"] as? [String],
              readScope.count + writeScope.count <= 8,
              let source = String(data: sourceData, encoding: .utf8)
        else {
            throw LauncherError.operationRejected("plugin_package_rejected")
        }
        let sourceDigest = KernelWorkspaceXPC.sha256Hex(sourceData)
        let request = KernelWorkspaceXPC.WorkspaceRunRequest(
            timeoutSeconds: 30,
            runnerSource: source,
            runnerSourceSHA256: sourceDigest,
            workspaceReadScope: readScope,
            workspaceWriteScope: writeScope
        )
        do {
            _ = try request.encodeFrame(requestID: KernelWorkspaceXPC.newRequestID())
        } catch {
            throw LauncherError.operationRejected("plugin_package_rejected")
        }
        let plugin = PluginRun(
            identifier: identifier,
            manifestDigest: KernelWorkspaceXPC.sha256Hex(manifestData),
            sourceDigest: sourceDigest,
            request: request
        )
        let details = "Plugin: \(plugin.identifier)\n"
            + "Manifest SHA-256: \(plugin.manifestDigest)\n"
            + "Source SHA-256: \(plugin.sourceDigest)\n"
            + "Process execution: allowed once"
        packageURL.stopAccessingSecurityScopedResource()
        packageScopeReleased = true
        return try runReviewedRequest(
            request, title: "Run this plugin once?", details: details
        )
    }

    private static func readPackageFile(
        _ packageURL: URL, name: String, maximumBytes: Int
    ) throws -> Data {
        let directory = Darwin.open(
            packageURL.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC
        )
        guard directory >= 0 else {
            throw LauncherError.operationRejected("plugin_package_rejected")
        }
        defer { Darwin.close(directory) }
        let descriptor = Darwin.openat(
            directory, name, O_RDONLY | O_NOFOLLOW | O_CLOEXEC
        )
        guard descriptor >= 0 else {
            throw LauncherError.operationRejected("plugin_package_rejected")
        }
        defer { Darwin.close(descriptor) }
        var info = Darwin.stat()
        guard Darwin.fstat(descriptor, &info) == 0,
              info.st_mode & S_IFMT == S_IFREG,
              info.st_nlink == 1,
              info.st_size > 0,
              info.st_size <= maximumBytes else {
            throw LauncherError.operationRejected("plugin_package_rejected")
        }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: false)
        guard let data = try handle.read(upToCount: maximumBytes + 1),
              !data.isEmpty,
              data.count <= maximumBytes else {
            throw LauncherError.operationRejected("plugin_package_rejected")
        }
        return data
    }

    private static func runShellCommand(_ shellRun: ShellRun) throws -> WorkspaceResult {
        try runReviewedRequest(
            shellRun.request,
            title: "Run this command once?",
            details: "Command:\n\(shellRun.command)"
        )
    }

    private static func runAgentSession() throws {
        let host = AgentHostClient()
        defer { host.stop() }
        fputs(
            "Khaos local Agent. The model is untrusted; each workspace command needs your approval. Type /exit to quit.\n",
            stdout
        )

        var workspace: TrustedWorkspaceSelection?
        while true {
            fputs("You: ", stdout)
            fflush(stdout)
            guard let prompt = readLine(strippingNewline: true) else { return }
            if prompt == "/exit" { return }
            var reply: AgentHostReply
            do {
                reply = try host.sendUserTurn(prompt)
            } catch {
                fputs("Local Agent request failed: \(failureCode(for: error))\n", stderr)
                continue
            }

            var awaitingNextUser = false
            while !awaitingNextUser {
                switch reply {
                case let .text(text):
                    fputs("Khaos: \(terminalSafe(text))\n", stdout)
                    fflush(stdout)
                    awaitingNextUser = true
                case let .tool(proposal):
                    let outcome = try runAgentTool(proposal, workspace: &workspace)
                    do {
                        reply = try host.sendToolResult(ok: outcome.ok, text: outcome.text)
                    } catch {
                        fputs(
                            "Local Agent stopped: \(failureCode(for: error))\n",
                            stderr
                        )
                        return
                    }
                case let .failure(code):
                    fputs("Local Agent error: \(code)\n", stderr)
                    awaitingNextUser = true
                }
            }
        }
    }

    private static func runAgentTool(
        _ proposal: AgentToolProposal,
        workspace: inout TrustedWorkspaceSelection?
    ) throws -> (ok: Bool, text: String) {
        guard !proposal.argv.isEmpty,
              proposal.argv.count <= AgentHostProtocol.maximumArguments,
              proposal.argv.allSatisfy(reviewable),
              proposal.readScope.count + proposal.writeScope.count
                <= AgentHostProtocol.maximumScopePaths,
              (proposal.readScope + proposal.writeScope).allSatisfy(reviewable) else {
            return (false, "Launcher rejected the malformed tool proposal.")
        }
        let source: String
        do {
            source = try agentRunnerSource(argv: proposal.argv)
        } catch {
            return (false, "Launcher could not encode the bounded tool proposal.")
        }
        let request = KernelWorkspaceXPC.WorkspaceRunRequest(
            timeoutSeconds: 30,
            runnerSource: source,
            runnerSourceSHA256: KernelWorkspaceXPC.runnerSourceSHA256(source),
            workspaceReadScope: proposal.readScope,
            workspaceWriteScope: proposal.writeScope
        )
        do {
            _ = try request.encodeFrame(requestID: KernelWorkspaceXPC.newRequestID())
        } catch {
            return (false, "Kernel rejected the requested argv or workspace scope as invalid.")
        }

        if workspace == nil {
            do {
                let selected = try TrustedWorkspacePicker.selectWorkspace(
                    message: "Choose the workspace for this reviewed Agent tool request."
                )
                guard reviewable(selected.scopeURL.path) else {
                    selected.scopeURL.stopAccessingSecurityScopedResource()
                    return (false, "Launcher rejected the selected workspace path.")
                }
                selected.scopeURL.stopAccessingSecurityScopedResource()
                workspace = selected
            } catch TrustedWorkspacePickerError.cancelled {
                return (false, "User cancelled workspace selection.")
            }
        }
        guard let selection = workspace,
              let bundleID = Bundle.main.bundleIdentifier else {
            return (false, "Trusted workspace session is unavailable.")
        }

        let requestID = KernelWorkspaceXPC.newRequestID()
        let invocation: Data
        do {
            invocation = try KernelWorkspaceXPC.encodeInvocation(
                request: request,
                requestID: requestID,
                bookmark: selection.bookmark
            )
        } catch {
            return (false, "Launcher could not encode the trusted workspace invocation.")
        }
        let command = proposal.argv.map { "  \($0)" }.joined(separator: "\n")
        guard approveReviewedRequest(
            request,
            title: "Run this local Agent tool once?",
            details: "Proposed argv:\n\(command)",
            workspace: selection.scopeURL,
            digest: KernelWorkspaceXPC.sha256Hex(invocation)
        ) else {
            return (false, "User denied this tool request.")
        }

        do {
            let output = try runInKernel(
                bundleID: bundleID,
                selection: selection,
                requestID: requestID,
                request: request
            )
            let result = try parseWorkspaceResult(output)
            let resultObject: [String: Any] = [
                "returncode": result.returncode,
                "added": result.added,
                "modified": result.modified,
                "deleted": result.deleted,
                "stdout": String(result.stdout.prefix(2_000)),
                "stderr": String(result.stderr.prefix(2_000)),
            ]
            let resultData = try JSONSerialization.data(
                withJSONObject: resultObject,
                options: [.sortedKeys, .withoutEscapingSlashes]
            )
            let boundedResult = boundedUTF8Prefix(
                String(decoding: resultData, as: UTF8.self),
                maximumBytes: AgentHostProtocol.maximumTextBytes
            )
            return (result.returncode == 0, boundedResult)
        } catch let LauncherError.operationRejected(code) {
            return (false, "Kernel rejected or failed the request: \(code)")
        } catch {
            return (false, "Kernel request failed closed.")
        }
    }

    private static func agentRunnerSource(argv: [String]) throws -> String {
        let encodedArgv = try JSONSerialization.data(
            withJSONObject: argv,
            options: [.sortedKeys, .withoutEscapingSlashes]
        ).base64EncodedString()
        let source = """
            import base64, json
            from khaos.runner_sdk import process_exec, workspace_commit

            ARGV = json.loads(base64.b64decode(\(String(reflecting: encodedArgv))))

            def run():
                result = process_exec(tuple(ARGV))
                if result["returncode"] == 0:
                    workspace_commit()
                return result["returncode"]
            """
        guard source.utf8.count <= 10_240 else {
            throw LauncherError.invalidArguments
        }
        return source
    }

    private static func boundedUTF8Prefix(_ text: String, maximumBytes: Int) -> String {
        var result = ""
        var byteCount = 0
        for scalar in text.unicodeScalars {
            let scalarBytes = scalar.utf8.count
            guard byteCount + scalarBytes <= maximumBytes else { break }
            result.unicodeScalars.append(scalar)
            byteCount += scalarBytes
        }
        return result
    }

    private static func terminalSafe(_ text: String) -> String {
        var result = ""
        for scalar in text.unicodeScalars {
            if CharacterSet.controlCharacters.contains(scalar),
               scalar != "\n", scalar != "\t" {
                result += String(format: "\\u{%04x}", scalar.value)
            } else {
                result.unicodeScalars.append(scalar)
            }
        }
        return result
    }

    private static func runReviewedRequest(
        _ request: KernelWorkspaceXPC.WorkspaceRunRequest,
        title: String,
        details: String
    ) throws -> WorkspaceResult {
        guard let bundleID = Bundle.main.bundleIdentifier else {
            throw LauncherError.operationRejected("bundle_identity_unavailable")
        }
        let selection = try TrustedWorkspacePicker.selectWorkspace(
            message: "Choose the workspace for this one-time Kernel operation."
        )
        var scopeReleased = false
        defer {
            if !scopeReleased {
                selection.scopeURL.stopAccessingSecurityScopedResource()
            }
        }
        guard reviewable(selection.scopeURL.path) else {
            throw LauncherError.operationRejected("workspace_rejected")
        }
        let requestID = KernelWorkspaceXPC.newRequestID()
        let invocation = try KernelWorkspaceXPC.encodeInvocation(
            request: request,
            requestID: requestID,
            bookmark: selection.bookmark
        )
        guard approveReviewedRequest(
            request,
            title: title,
            details: details,
            workspace: selection.scopeURL,
            digest: KernelWorkspaceXPC.sha256Hex(invocation)
        ) else {
            throw TrustedWorkspacePickerError.cancelled
        }
        // The trusted Launcher relinquishes its Picker scope before Runner launch.
        selection.scopeURL.stopAccessingSecurityScopedResource()
        scopeReleased = true

        let output = try runInKernel(
            bundleID: bundleID,
            selection: selection,
            requestID: requestID,
            request: request
        )
        let result = try parseWorkspaceResult(output)
        guard result.returncode == 0 else {
            throw LauncherError.operationRejected("command_exit_\(result.returncode)")
        }
        return result
    }

    private static func approveReviewedRequest(
        _ request: KernelWorkspaceXPC.WorkspaceRunRequest,
        title: String,
        details: String,
        workspace: URL,
        digest: String
    ) -> Bool {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = title
        let readPaths = request.workspaceReadScope.joined(separator: "\n")
        let writePaths = request.workspaceWriteScope.joined(separator: "\n")
        alert.informativeText = "Workspace: \(workspace.path)\n\n"
            + "\(details)\n\n"
            + "Readable paths:\n\(readPaths.isEmpty ? "(none)" : readPaths)\n\n"
            + "Committable paths:\n\(writePaths.isEmpty ? "(none)" : writePaths)\n\n"
            + "Request SHA-256: \(digest)"
        alert.addButton(withTitle: "Cancel")
        alert.addButton(withTitle: "Run once")
        return alert.runModal() == .alertSecondButtonReturn
    }

    private static func verifySelectedWorkspace(
        initialDirectory: URL?,
        acceptanceDirectory: URL?
    ) throws -> String {
        guard let bundleID = Bundle.main.bundleIdentifier else {
            throw LauncherError.operationRejected("bundle_identity_unavailable")
        }
        var pickerMessage = "Khaos will create one unique test file through the Kernel. "
            + "Choose a disposable workspace folder."
        if let acceptanceDirectory {
            try requireWorkspaceOpenResult(
                workspace: acceptanceDirectory,
                fileName: acceptanceFixtureName,
                flags: O_RDONLY | O_CLOEXEC | O_NOFOLLOW,
                expectOpen: false,
                mismatchCode: "preselection_read_allowed",
                unexpectedErrorCode: "preselection_read_check_failed"
            )
            writeDiagnostic("preselection-read=denied")
            pickerMessage += "\nSelect the folder named "
                + "\(acceptanceDirectory.lastPathComponent) and choose Open:\n"
                + acceptanceDirectory.path
        }
        writeDiagnostic("picker-requested")
        let selection = try TrustedWorkspacePicker.selectWorkspace(
            initialDirectory: initialDirectory,
            message: pickerMessage
        )
        if let acceptanceDirectory,
           selection.scopeURL.standardizedFileURL.resolvingSymlinksInPath().path
                != acceptanceDirectory.standardizedFileURL.resolvingSymlinksInPath().path {
            throw LauncherError.operationRejected("selected_workspace_mismatch")
        }
        writeDiagnostic("workspace-selected")
        if acceptanceDirectory != nil {
            try requireWorkspaceOpenResult(
                workspace: selection.scopeURL,
                fileName: acceptanceFixtureName,
                flags: O_RDONLY | O_CLOEXEC | O_NOFOLLOW,
                expectOpen: true,
                mismatchCode: "selected_read_unavailable",
                unexpectedErrorCode: "selected_read_check_failed"
            )
            writeDiagnostic("selected-read=available")
        }
        // The Kernel receives the bookmark. Release the Launcher's panel scope before
        // the untrusted Runner starts.
        selection.scopeURL.stopAccessingSecurityScopedResource()
        if acceptanceDirectory != nil {
            try requireWorkspaceOpenResult(
                workspace: selection.scopeURL,
                fileName: acceptanceFixtureName,
                flags: O_RDONLY | O_CLOEXEC | O_NOFOLLOW,
                expectOpen: false,
                mismatchCode: "picker_read_scope_retained",
                unexpectedErrorCode: "picker_read_check_failed"
            )
            writeDiagnostic("selected-read=denied")
        }

        let requestID = KernelWorkspaceXPC.newRequestID()
        let readFixtureScope = acceptanceDirectory != nil
        let outputName = "khaos-seed-writeback-smoke-\(UUID().uuidString.lowercased()).txt"
        let runner = Self.runnerSource(
            readFixtureScope: readFixtureScope,
            writebackFileName: outputName
        )
        let request = KernelWorkspaceXPC.WorkspaceRunRequest(
            timeoutSeconds: 5,
            runnerSource: runner,
            runnerSourceSHA256: KernelWorkspaceXPC.runnerSourceSHA256(runner),
            workspaceReadScope: readFixtureScope ? [acceptanceFixtureName] : [],
            workspaceWriteScope: [outputName]
        )
        let output = try runInKernel(
            bundleID: bundleID,
            selection: selection,
            requestID: requestID,
            request: request
        )
        if let code = writebackFailureCode(output) {
            throw LauncherError.operationRejected(code)
        }
        writeDiagnostic(
            acceptanceDirectory == nil
                ? "runner-read-list-scope=deny-all"
                : "runner-read-list-scope=allow-deny-verified"
        )
        writeDiagnostic("runner-write-scope=allow-deny-verified")
        // writebackFailureCode has already required exactly one Kernel addition
        // and no modification or deletion in the authenticated XPC reply.
        writeDiagnostic("kernel-commit=one-addition-no-overwrite")
        try requireWorkspaceOpenResult(
            workspace: selection.scopeURL,
            fileName: outputName,
            flags: O_WRONLY | O_CLOEXEC | O_NOFOLLOW,
            expectOpen: false,
            mismatchCode: "picker_write_scope_retained",
            unexpectedErrorCode: "picker_write_check_failed"
        )
        writeDiagnostic("released-scope-direct-write=denied")
        return outputName
    }

    private static func requireWorkspaceOpenResult(
        workspace: URL,
        fileName: String,
        flags: Int32,
        expectOpen: Bool,
        mismatchCode: String,
        unexpectedErrorCode: String
    ) throws {
        // Use one OS-level check for both positive and negative access controls.
        let path = workspace.appendingPathComponent(fileName).path
        let descriptor = Darwin.open(path, flags)
        if descriptor >= 0 {
            guard !expectOpen else {
                guard Darwin.close(descriptor) == 0 else {
                    throw LauncherError.operationRejected(unexpectedErrorCode)
                }
                return
            }
            Darwin.close(descriptor)
            throw LauncherError.operationRejected(mismatchCode)
        }
        guard !expectOpen else {
            throw LauncherError.operationRejected(mismatchCode)
        }
        guard errno == EPERM || errno == EACCES else {
            throw LauncherError.operationRejected(unexpectedErrorCode)
        }
    }

    private static func verifyKernelBootstrap() throws {
        guard let bundleID = Bundle.main.bundleIdentifier else {
            throw LauncherError.operationRejected("bundle_identity_unavailable")
        }
        let target = try connectKernel(bundleID: bundleID)
        let snapshotBrokerEndpoint = try KernelSnapshotBrokerBootstrapClient.endpoint()
        try KernelWorkspaceClient.registerSnapshotBrokerEndpoint(
            snapshotBrokerEndpoint,
            with: target
        )
    }

    private static func connectKernel(
        bundleID: String
    ) throws -> KernelWorkspaceTarget {
        try KernelWorkspaceClient.connect(
            serviceName: bundleID + serviceSuffix,
            peerRequirementKey: serviceRequirementKey
        )
    }

    private static func runInKernel(
        bundleID: String,
        selection: TrustedWorkspaceSelection,
        requestID: KernelWorkspaceXPC.RequestID,
        request: KernelWorkspaceXPC.WorkspaceRunRequest
    ) throws -> String {
        let target = try connectKernel(bundleID: bundleID)
        let snapshotBrokerEndpoint = try KernelSnapshotBrokerBootstrapClient.endpoint()
        let reply = try KernelWorkspaceClient.request(
            target,
            requestID: requestID,
            snapshotBrokerEndpoint: snapshotBrokerEndpoint
        ) { proxy, withReply in
            try KernelWorkspaceXPC.submit(
                proxy,
                requestID: requestID,
                request: request,
                bookmark: selection.bookmark,
                withReply: withReply
            )
        }
        if let errorCode = reply.errorCode {
            throw LauncherError.operationRejected(
                safeWorkspaceErrorCode(errorCode)
            )
        }
        guard let output = reply.output else {
            throw LauncherError.operationRejected("missing_workspace_result")
        }
        return output
    }

    private static func parseWorkspaceResult(_ output: String) throws -> WorkspaceResult {
        guard let data = output.data(using: .utf8),
              let result = try? JSONSerialization.jsonObject(with: data)
                as? [String: Any]
        else {
            throw LauncherError.operationRejected("result_not_json")
        }
        guard Set(result.keys) == [
            "returncode", "stdout", "stderr", "added", "modified", "deleted",
        ] else {
            throw LauncherError.operationRejected("result_fields_mismatch")
        }
        guard let returncode = result["returncode"] as? Int,
              let stdout = result["stdout"] as? String,
              let stderr = result["stderr"] as? String,
              let added = result["added"] as? Int,
              let modified = result["modified"] as? Int,
              let deleted = result["deleted"] as? Int
        else {
            throw LauncherError.operationRejected("result_types_mismatch")
        }
        return WorkspaceResult(
            returncode: returncode,
            stdout: stdout,
            stderr: stderr,
            added: added,
            modified: modified,
            deleted: deleted
        )
    }

    private static func writebackFailureCode(_ output: String) -> String? {
        let result: WorkspaceResult
        do {
            result = try parseWorkspaceResult(output)
        } catch let LauncherError.operationRejected(code) {
            return code
        } catch {
            return "operation_failed"
        }
        guard result.returncode == 0 else {
            return "command_exit_\(result.returncode)"
        }
        guard result.added == 1, result.modified == 0, result.deleted == 0 else {
            return "commit_counts_a\(result.added)_m\(result.modified)_d\(result.deleted)"
        }
        return nil
    }

    private static func showSuccess(fileName: String, runID: String?) {
        let alert = NSAlert()
        alert.messageText = "Kernel writeback check passed."
        let runDescription = runID.map { "Acceptance run: \($0)\n" } ?? ""
        alert.informativeText = runDescription
            + "The Kernel committed one file and direct Picker write was denied: \(fileName)"
        alert.runModal()
    }

    private static func showCommandSuccess(_ result: WorkspaceResult) {
        let alert = NSAlert()
        alert.messageText = "Kernel operation completed."
        alert.informativeText = "Committed changes: \(result.added) added, "
            + "\(result.modified) modified, \(result.deleted) deleted."
            + outputPreview(result.stdout, label: "stdout")
            + outputPreview(result.stderr, label: "stderr")
        alert.runModal()
    }

    private static func outputPreview(_ output: String, label: String) -> String {
        guard !output.isEmpty else { return "" }
        let maximumCharacters = 2_048
        let prefix = String(output.prefix(maximumCharacters))
        let suffix = output.count > maximumCharacters ? "\n[output truncated]" : ""
        return "\n\n\(label):\n\(prefix)\(suffix)"
    }

    private static func showFailure(
        code: String,
        runID: String?,
        commandMode: Bool = false
    ) {
        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = commandMode
            ? "Khaos could not complete the workspace operation."
            : "Khaos could not complete the local security check."
        let runDescription = runID.map { "Acceptance run: \($0)\n" } ?? ""
        alert.informativeText = runDescription + "Check code: \(code)"
        alert.runModal()
    }

    private static func writeDiagnostic(_ result: String) {
        // Keep terminal acceptance evidence useful without printing workspace paths.
        fputs("workspace-kernel-smoke=\(result)\n", stderr)
        fflush(stderr)
    }

    private static func failureCode(for error: Error) -> String {
        switch error {
        case LauncherError.invalidArguments:
            return "invalid_arguments"
        case let LauncherError.operationRejected(code):
            return code
        case KernelWorkspaceClientError.missingPeerRequirement(_):
            return "kernel_peer_auth_failed"
        case KernelWorkspaceClientError.invalidBootstrapProxy,
             KernelWorkspaceClientError.bootstrapFailed:
            return "kernel_bootstrap_failed"
        case KernelWorkspaceClientError.invalidWorkspaceProxy,
             KernelWorkspaceClientError.requestFailed:
            return "kernel_request_failed"
        case KernelWorkspaceClientError.snapshotBrokerEndpointRejected:
            return "snapshot_broker_rejected"
        case KernelWorkspaceClientError.invalidResponse:
            return "invalid_kernel_response"
        case KernelWorkspaceClientError.timedOut:
            return "kernel_request_timeout"
        case KernelSnapshotBrokerBootstrapError.notConfigured:
            return "snapshot_broker_not_configured"
        case KernelSnapshotBrokerBootstrapError.connectionFailed:
            return "snapshot_broker_connection_failed"
        case KernelSnapshotBrokerBootstrapError.invalidProxy:
            return "snapshot_broker_protocol_failed"
        case KernelSnapshotBrokerBootstrapError.timedOut:
            return "snapshot_broker_timeout"
        case AgentHostClientError.timedOut:
            return "agent_host_timeout"
        case AgentHostClientError.unavailable:
            return "agent_host_unavailable"
        case AgentHostClientError.invalidResponse:
            return "agent_host_invalid_response"
        default:
            return "operation_failed"
        }
    }

    private static func safeWorkspaceErrorCode(_ code: String) -> String {
        switch code {
        case "sandbox_unavailable_probe_child",
             "sandbox_unavailable_probe_readiness",
             "sandbox_unavailable_probe_snapshot",
             "sandbox_unavailable_probe_verification":
            return "sandbox_unavailable"
        case "commit_outcome_uncertain", "commit_rejected", "invalid_bookmark",
             "invalid_request", "kernel_bridge_failed", "kernel_failed",
             "kernel_runtime_unavailable", "kernel_timeout", "operation_busy",
             "process_cancelled", "runner_failed", "sandbox_unavailable",
             "snapshot_broker_busy", "snapshot_broker_connection_failed",
             "snapshot_broker_invalid_lease", "snapshot_broker_not_configured",
             "snapshot_broker_operation_failed", "snapshot_broker_peer_auth_failed",
             "snapshot_broker_protocol_failed", "snapshot_broker_release_failed",
             "snapshot_broker_rejected", "snapshot_broker_timeout",
             "unsupported_version", "workspace_rejected":
            return code
        default:
            return "kernel_rejected_request"
        }
    }
}
