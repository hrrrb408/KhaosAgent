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
    let manifestData: Data
    let sourceData: Data
    let processExec: Bool
    let readScope: [String]
    let writeScope: [String]
    let evaluationReviewData: Data?
}

private struct MemoryEvaluationReview {
    let proposalDigest: String?
    let baselineDigest: String
    let datasetDigest: String
    let sampleCount: Int
    let baselinePass: Int
    let baselineFail: Int
    let candidateDigest: String
    let candidateManifestDigest: String
    let candidateScopeDigest: String
    let candidatePass: Int
    let candidateFail: Int
    let regressions: [String]
    let improvements: [String]
}

private struct PluginCandidateReview {
    let identifier: String
    let candidateDigest: String
    let manifestDigest: String
    let scopeDigest: String
    let processExec: Bool
    let readScope: [String]
    let writeScope: [String]
    let agentInterface: AgentPluginInterface?
    let approvedAt: Int?
    let expiresAt: Int?
}

private struct PluginStateReview {
    let active: PluginCandidateReview?
    let previous: PluginCandidateReview?
    let generation: Int
}

private struct WorkspaceResult {
    let returncode: Int
    let stdout: String
    let stderr: String
    let added: Int
    let modified: Int
    let deleted: Int
    let pluginStateSHA256: String?
}

private struct AgentToolOutcome {
    let ok: Bool
    let canContinue: Bool
    let text: String
    let returncode: Int?
    let executionSeconds: Double
    var stopReason: String? = nil
    var taskCancelled: Bool = false
    var workspaceRecord: AgentWorkspaceRequestRecord? = nil
}

private struct AgentWorkspaceRequestRecord {
    let requestID: String
    let workspaceSessionID: String
    let connectionID: String?
    let approvalSHA256: String
    let readScope: [String]
    let writeScope: [String]
    let approval: String
    let cancellationRequested: Bool
    let cancellationResult: String
    let kernelResult: String
    let runnerExecution: String
    let runnerReturnCode: Int?
    let added: Int?
    let modified: Int?
    let deleted: Int?
    let commitOutcome: String
}

private struct AgentWorkspaceRequest {
    let requestID: KernelWorkspaceXPC.RequestID
    let request: KernelWorkspaceXPC.WorkspaceRunRequest
    let invocation: Data
    let approvalSHA256: String
    let workspaceSessionID: UUID
    var connectionID: UUID?
}

private struct AgentHostTurnOutcome {
    let reply: AgentHostReply?
    let cancellationRequested: Bool
    let error: Error?
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
        application.finishLaunching()
        let arguments = Array(CommandLine.arguments.dropFirst())
        let isBootstrapCheck = arguments == ["--bootstrap-check"]
        let isCommandRun = arguments.first == "--command"
        let isPluginRun = arguments == ["--plugin-run"]
        let isPluginInstall = arguments == ["--plugin-install"]
        let isPluginRollback = arguments == ["--plugin-rollback"]
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
                let result = try runActivePlugin()
                logger.info("workspace-plugin=passed")
                fputs("workspace-plugin=passed\n", stderr)
                showCommandSuccess(result)
                return
            }
            if isPluginInstall {
                try installPlugin()
                showPluginSuccess("Plugin candidate activated.")
                return
            }
            if isPluginRollback {
                try rollbackPlugin()
                showPluginSuccess("Plugin slot rolled back.")
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

    private static func installPlugin() throws {
        let plugin = try selectPluginPackage()
        let candidateOutput = try invokePluginKernel(
            .admit(manifest: plugin.manifestData, source: plugin.sourceData)
        )
        let (candidate, admittedGeneration) = try parseAdmittedCandidate(candidateOutput)
        let state = try parsePluginState(invokePluginKernel(.state))
        guard state.generation == admittedGeneration else {
            throw LauncherError.operationRejected("stale_approval")
        }
        var details = candidateDetails(
            candidate,
            validity: "30 days after activation",
            generation: admittedGeneration
        )
        details += "\nCaptured source SHA-256: \(plugin.sourceDigest)"
        details += "\nTarget slot: primary"
        if let active = state.active {
            details += "\nCurrent active will become the rollback target:\n"
                + candidateDetails(
                    active,
                    validity: approvalExpiry(active),
                    generation: state.generation
                )
        } else {
            details += "\nNo current active Plugin; there is no rollback target yet."
        }
        if let evaluationData = plugin.evaluationReviewData {
            guard let evaluation = try? parseMemoryEvaluationReview(evaluationData),
                  candidate.identifier == "memory",
                  evaluation.candidateDigest == candidate.candidateDigest,
                  evaluation.candidateManifestDigest == candidate.manifestDigest,
                  evaluation.candidateScopeDigest == candidate.scopeDigest,
                  state.active?.identifier == "memory",
                  evaluation.baselineDigest == state.active?.candidateDigest,
                  evaluation.candidatePass > evaluation.baselinePass,
                  evaluation.regressions.isEmpty
            else {
                throw LauncherError.operationRejected("evaluation_binding_rejected")
            }
            details += memoryEvaluationDetails(evaluation)
            writeDiagnostic("plugin-evaluation-review=presented")
        }
        let request = KernelWorkspaceXPC.PluginLifecycleRequest.activate(
            candidateDigest: candidate.candidateDigest,
            manifestDigest: candidate.manifestDigest,
            scopeDigest: candidate.scopeDigest,
            expectedGeneration: admittedGeneration
        )
        let requestID = KernelWorkspaceXPC.newRequestID()
        let invocation = try KernelWorkspaceXPC.encodeInvocation(
            request: request,
            requestID: requestID
        )
        writeDiagnostic("plugin-activation-review=presented")
        guard approvePluginAction(
            title: "Activate this Plugin?",
            action: "Activate for 30 days",
            workspace: nil,
            details: details,
            digest: KernelWorkspaceXPC.sha256Hex(invocation)
        ) else {
            throw TrustedWorkspacePickerError.cancelled
        }
        let activated = try parsePluginState(
            invokePluginKernel(request, requestID: requestID)
        )
        guard activated.active?.candidateDigest == candidate.candidateDigest else {
            throw LauncherError.operationRejected("activation_not_confirmed")
        }
        writeDiagnostic("plugin-activation=passed")
    }

    private static func selectPluginPackage() throws -> PluginRun {
        let packageURL = try TrustedWorkspacePicker.selectPluginPackage()
        // NSOpenPanel starts scoped access for its selected URL; release it after reading.
        defer { packageURL.stopAccessingSecurityScopedResource() }
        let manifestData = try readPackageFile(
            packageURL, name: "manifest.json", maximumBytes: 4096
        )
        let sourceData = try readPackageFile(
            packageURL, name: "plugin.py", maximumBytes: 10_240
        )
        let evaluationReviewData = try readOptionalPackageFile(
            packageURL, name: "evaluation.json", maximumBytes: 4096
        )
        guard let manifest = try? JSONSerialization.jsonObject(with: manifestData)
                as? [String: Any],
              let canonical = try? JSONSerialization.data(
                withJSONObject: manifest,
                options: [.sortedKeys, .withoutEscapingSlashes]
              ),
              canonical == manifestData
                || canonical + Data([0x0a]) == manifestData,
              Set(manifest.keys) == [
                "abi_version", "id", "process_exec", "read", "write"
              ] || Set(manifest.keys) == [
                "abi_version", "agent_interface", "id", "process_exec",
                "read", "write"
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
              let readScope = manifest["read"] as? [String],
              let writeScope = manifest["write"] as? [String],
              readScope.count + writeScope.count <= 8,
              String(data: sourceData, encoding: .utf8) != nil
        else {
            throw LauncherError.operationRejected("plugin_package_rejected")
        }
        let plugin = PluginRun(
            identifier: identifier,
            manifestDigest: KernelWorkspaceXPC.sha256Hex(manifestData),
            sourceDigest: KernelWorkspaceXPC.sha256Hex(sourceData),
            manifestData: manifestData,
            sourceData: sourceData,
            processExec: process.boolValue,
            readScope: readScope,
            writeScope: writeScope,
            evaluationReviewData: evaluationReviewData
        )
        return plugin
    }

    private static func runActivePlugin() throws -> WorkspaceResult {
        var workspace: TrustedWorkspaceSelection?
        return try runActivePlugin(proposal: nil, workspace: &workspace)
    }

    private static func runActivePlugin(
        proposal: AgentPluginBinding?,
        workspace: inout TrustedWorkspaceSelection?
    ) throws -> WorkspaceResult {
        let state = try parsePluginState(invokePluginKernel(.state))
        guard let active = state.active else {
            throw LauncherError.operationRejected("no_active_candidate")
        }
        let activeBinding = AgentHostPluginMetadata(
            pluginID: active.identifier,
            candidateDigest: active.candidateDigest,
            generation: state.generation,
            agentInterface: active.agentInterface
        )
        if let proposal,
           !AgentHostProtocol.proposalMatchesActive(proposal, active: activeBinding) {
            throw LauncherError.operationRejected("stale_proposal")
        }
        let workspaceRequired = active.processExec
            || !active.readScope.isEmpty || !active.writeScope.isEmpty
        let selectedNewWorkspace = workspaceRequired && workspace == nil
        if selectedNewWorkspace {
            let selected = try TrustedWorkspacePicker.selectWorkspace(
                message: "Choose the workspace for the active Plugin."
            )
            guard reviewable(selected.scopeURL.path) else {
                selected.scopeURL.stopAccessingSecurityScopedResource()
                throw LauncherError.operationRejected("workspace_rejected")
            }
            workspace = selected
        }
        let selection = workspaceRequired ? workspace : nil
        if let selection, !reviewable(selection.scopeURL.path) {
            throw LauncherError.operationRejected("workspace_rejected")
        }
        var scopeReleased = false
        defer {
            if selectedNewWorkspace && !scopeReleased, let selection {
                selection.scopeURL.stopAccessingSecurityScopedResource()
            }
        }
        let request = KernelWorkspaceXPC.PluginLifecycleRequest.run(
            pluginID: active.identifier,
            candidateDigest: active.candidateDigest,
            manifestDigest: active.manifestDigest,
            scopeDigest: active.scopeDigest,
            expectedGeneration: state.generation,
            inputJSON: proposal?.inputJSON,
            workspaceRequired: workspaceRequired
        )
        let requestID = KernelWorkspaceXPC.newRequestID()
        let invocation = try KernelWorkspaceXPC.encodeInvocation(
            request: request,
            requestID: requestID,
            bookmark: selection?.bookmark
        )
        var details = candidateDetails(
            active,
            validity: approvalExpiry(active),
            generation: state.generation
        )
            + "\nThe Kernel will run this exact active Candidate in an isolated Runner."
        let invocationInput = proposal?.inputJSON
        if let invocationInput {
            details += "\nExact invocation input (untrusted business data):\n"
                + String(decoding: invocationInput, as: UTF8.self)
        } else {
            details += "\nExact invocation input: (none)"
        }
        if !workspaceRequired {
            details += "\nThis Candidate uses Plugin state only; no workspace is selected."
        }
        writeDiagnostic("plugin-run-review=presented")
        if proposal != nil {
            fputs("agent-plugin=approval-presented\n", stderr)
        }
        guard approvePluginAction(
            title: proposal == nil
                ? (workspaceRequired
                    ? "Run the active Plugin in this workspace?"
                    : "Run the active Plugin? It does not use a workspace.")
                : "Allow the Agent to invoke this active Plugin?",
            action: "Run active Plugin once",
            workspace: selection?.scopeURL,
            details: details,
            digest: KernelWorkspaceXPC.sha256Hex(invocation)
        ) else {
            if proposal != nil {
                throw LauncherError.operationRejected("user_denied")
            }
            throw TrustedWorkspacePickerError.cancelled
        }
        if let selection {
            selection.scopeURL.stopAccessingSecurityScopedResource()
            if selectedNewWorkspace { scopeReleased = true }
            try requireWorkspaceOpenResult(
                workspace: selection.scopeURL,
                fileName: ".",
                flags: O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC,
                expectOpen: false,
                mismatchCode: "plugin_picker_scope_retained",
                unexpectedErrorCode: "plugin_picker_scope_release_failed"
            )
            writeDiagnostic("plugin-picker-scope=released")
        }
        let output = try invokePluginKernel(
            request,
            requestID: requestID,
            bookmark: selection?.bookmark
        )
        let result = try parseWorkspaceResult(output)
        guard result.returncode == 0 else {
            throw LauncherError.operationRejected("plugin_exit_\(result.returncode)")
        }
        return result
    }

    private static func rollbackPlugin() throws {
        let state = try parsePluginState(invokePluginKernel(.state))
        guard let active = state.active, let previous = state.previous else {
            throw LauncherError.operationRejected("invalid_rollback_target")
        }
        let details = "Current active Plugin:\n"
            + candidateDetails(
                active,
                validity: approvalExpiry(active),
                generation: state.generation
            )
            + "\n\nRollback target (future runs only):\n"
            + candidateDetails(
                previous,
                validity: approvalExpiry(previous),
                generation: state.generation
            )
            + "\n\nThe rollback changes the primary slot after approval."
        let request = KernelWorkspaceXPC.PluginLifecycleRequest.rollback(
            candidateDigest: previous.candidateDigest,
            manifestDigest: previous.manifestDigest,
            scopeDigest: previous.scopeDigest,
            expectedGeneration: state.generation
        )
        let requestID = KernelWorkspaceXPC.newRequestID()
        let invocation = try KernelWorkspaceXPC.encodeInvocation(
            request: request,
            requestID: requestID
        )
        writeDiagnostic("plugin-rollback-review=presented")
        guard approvePluginAction(
            title: "Roll back the active Plugin?",
            action: "Roll back",
            workspace: nil,
            details: details,
            digest: KernelWorkspaceXPC.sha256Hex(invocation)
        ) else {
            throw TrustedWorkspacePickerError.cancelled
        }
        let updated = try parsePluginState(
            invokePluginKernel(request, requestID: requestID)
        )
        guard updated.active?.candidateDigest == previous.candidateDigest else {
            throw LauncherError.operationRejected("rollback_not_confirmed")
        }
        writeDiagnostic("plugin-rollback=passed")
    }

    private static func parseAdmittedCandidate(
        _ output: String
    ) throws -> (PluginCandidateReview, Int) {
        guard let value = try? JSONSerialization.jsonObject(with: Data(output.utf8))
                as? [String: Any],
              Set(value.keys) == ["candidate", "generation"],
              let candidateValue = value["candidate"] as? [String: Any],
              let generation = integerValue(value["generation"]),
              generation >= 0
        else {
            throw LauncherError.operationRejected("invalid_kernel_response")
        }
        return (try parseCandidateReview(candidateValue, activation: false), generation)
    }

    private static func integerValue(_ value: Any?) -> Int? {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.rounded(.towardZero) == number.doubleValue
        else {
            return nil
        }
        return number.intValue
    }

    private static func isDigest(_ value: String) -> Bool {
        value.range(of: #"^[0-9a-f]{64}$"#, options: .regularExpression) != nil
    }

    private static func parsePluginState(_ output: String) throws -> PluginStateReview {
        guard let value = try? JSONSerialization.jsonObject(with: Data(output.utf8))
                as? [String: Any],
              Set(value.keys) == ["active", "previous", "generation"],
              let generation = integerValue(value["generation"]),
              generation >= 0
        else {
            throw LauncherError.operationRejected("invalid_kernel_response")
        }
        return PluginStateReview(
            active: try parseOptionalCandidate(value["active"]),
            previous: try parseOptionalCandidate(value["previous"]),
            generation: generation
        )
    }

    private static func parseOptionalCandidate(
        _ value: Any?
    ) throws -> PluginCandidateReview? {
        if value is NSNull { return nil }
        guard let dictionary = value as? [String: Any] else {
            throw LauncherError.operationRejected("invalid_kernel_response")
        }
        return try parseCandidateReview(dictionary, activation: true)
    }

    private static func parseCandidateReview(
        _ value: [String: Any],
        activation: Bool
    ) throws -> PluginCandidateReview {
        let candidateKeys: Set<String> = [
            "plugin_id", "candidate_digest", "manifest_digest", "scope_digest",
            "process_exec", "read_scope", "write_scope", "agent_interface",
        ]
        let activationKeys = candidateKeys.union([
            "slot", "approved_at", "expires_at", "approval_validity_seconds",
        ])
        guard Set(value.keys) == (activation ? activationKeys : candidateKeys),
              let identifier = value["plugin_id"] as? String,
              identifier.range(
                of: #"^[a-z][a-z0-9-]{0,63}$"#,
                options: .regularExpression
              ) != nil,
              let candidateDigest = value["candidate_digest"] as? String,
              isDigest(candidateDigest),
              let manifestDigest = value["manifest_digest"] as? String,
              isDigest(manifestDigest),
              let scopeDigest = value["scope_digest"] as? String,
              isDigest(scopeDigest),
              let processExec = value["process_exec"] as? NSNumber,
              CFGetTypeID(processExec) == CFBooleanGetTypeID(),
              let readScope = value["read_scope"] as? [String],
              let writeScope = value["write_scope"] as? [String],
              let agentInterfaceValue = value["agent_interface"],
              AgentHostProtocol.validAgentInterfaceValue(agentInterfaceValue),
              readScope.count + writeScope.count <= 8,
              (readScope + writeScope).allSatisfy({
                  !$0.isEmpty && !$0.hasPrefix("/") && !$0.contains("\0")
              })
        else {
            throw LauncherError.operationRejected("invalid_kernel_response")
        }
        let approvedAt: Int?
        let expiresAt: Int?
        if activation {
            guard value["slot"] as? String == "primary",
                  let approved = integerValue(value["approved_at"]), approved >= 0,
                  let expires = integerValue(value["expires_at"]),
                  expires - approved == 30 * 24 * 60 * 60,
                  integerValue(value["approval_validity_seconds"]) == 30 * 24 * 60 * 60
            else {
                throw LauncherError.operationRejected("invalid_kernel_response")
            }
            approvedAt = approved
            expiresAt = expires
        } else {
            approvedAt = nil
            expiresAt = nil
        }
        return PluginCandidateReview(
            identifier: identifier,
            candidateDigest: candidateDigest,
            manifestDigest: manifestDigest,
            scopeDigest: scopeDigest,
            processExec: processExec.boolValue,
            readScope: readScope,
            writeScope: writeScope,
            agentInterface: AgentHostProtocol.agentInterface(from: agentInterfaceValue),
            approvedAt: approvedAt,
            expiresAt: expiresAt
        )
    }

    private static func candidateDetails(
        _ candidate: PluginCandidateReview,
        validity: String,
        generation: Int
    ) -> String {
        let readPaths = candidate.readScope.isEmpty
            ? "(none)"
            : candidate.readScope.map { String(reflecting: $0) }
                .joined(separator: "\n")
        let writePaths = candidate.writeScope.isEmpty
            ? "(none)"
            : candidate.writeScope.map { String(reflecting: $0) }
                .joined(separator: "\n")
        let interfaceDetails: String
        if let interface = candidate.agentInterface {
            let operations = interface.operations.map { operation in
                let fields = operation.fields
                    .map { String(reflecting: $0) }
                    .joined(separator: ", ")
                return "  \(String(reflecting: operation.name))(\(fields))"
            }.joined(separator: "\n")
            interfaceDetails = "\nAgent interface (untrusted business metadata):\n"
                + "Summary: \(String(reflecting: interface.summary))\n"
                + "Operations:\n\(operations)"
        } else {
            interfaceDetails = "\nAgent interface: (none)"
        }
        return "Plugin: \(candidate.identifier)\n"
            + "Candidate SHA-256: \(candidate.candidateDigest)\n"
            + "Manifest SHA-256: \(candidate.manifestDigest)\n"
            + "Scope SHA-256: \(candidate.scopeDigest)\n"
            + interfaceDetails + "\n"
            + "Expected slot generation: \(generation)\n"
            + "process.exec: \(candidate.processExec ? "enabled" : "disabled")\n"
            + "Plugin state: bounded read/replace blob owned by this logical Plugin\n"
            + "Readable paths:\n\(readPaths)\n"
            + "Committable paths:\n\(writePaths)\n"
            + "Approval validity: \(validity)"
    }

    private static func parseMemoryEvaluationReview(
        _ data: Data
    ) throws -> MemoryEvaluationReview {
        guard let value = try? JSONSerialization.jsonObject(with: data)
                as? [String: Any],
              let canonical = try? JSONSerialization.data(
                withJSONObject: value,
                options: [.sortedKeys, .withoutEscapingSlashes]
              ),
              canonical == data,
              Set(value.keys) == [
                "baseline_digest", "baseline_fail", "baseline_pass",
                "candidate_digest", "candidate_fail",
                "candidate_manifest_digest", "candidate_pass",
                "candidate_scope_digest", "dataset_digest",
                "evaluator_version", "format", "improvements", "regressions",
                "sample_count",
              ] || Set(value.keys) == [
                "baseline_digest", "baseline_fail", "baseline_pass",
                "candidate_digest", "candidate_fail",
                "candidate_manifest_digest", "candidate_pass",
                "candidate_scope_digest", "dataset_digest", "evaluator_version",
                "format", "improvements", "proposal_digest", "regressions",
                "sample_count",
              ],
              value["format"] as? String == "khaos-memory-eval-v1",
              value["evaluator_version"] as? String
                == AgentHostProtocol.memoryEvaluationEvaluatorVersion,
              let baselineDigest = value["baseline_digest"] as? String,
              isDigest(baselineDigest),
              let datasetDigest = value["dataset_digest"] as? String,
              isDigest(datasetDigest),
              value["proposal_digest"] == nil
                || (value["proposal_digest"] as? String).map(isDigest) == true,
              let candidateDigest = value["candidate_digest"] as? String,
              isDigest(candidateDigest),
              let manifestDigest = value["candidate_manifest_digest"] as? String,
              isDigest(manifestDigest),
              let scopeDigest = value["candidate_scope_digest"] as? String,
              isDigest(scopeDigest),
              let sampleCount = integerValue(value["sample_count"]),
              sampleCount > 0, sampleCount <= 128,
              let baselinePass = integerValue(value["baseline_pass"]),
              let baselineFail = integerValue(value["baseline_fail"]),
              baselinePass >= 0, baselinePass <= sampleCount,
              baselineFail >= 0, baselineFail <= sampleCount,
              baselinePass == sampleCount - baselineFail,
              let candidatePass = integerValue(value["candidate_pass"]),
              let candidateFail = integerValue(value["candidate_fail"]),
              candidatePass >= 0, candidatePass <= sampleCount,
              candidateFail >= 0, candidateFail <= sampleCount,
              candidatePass == sampleCount - candidateFail,
              let regressions = value["regressions"] as? [String],
              regressions.count <= sampleCount,
              Set(regressions).count == regressions.count,
              regressions.allSatisfy({ $0.count <= 64 && reviewable($0) }),
              let improvements = value["improvements"] as? [String],
              improvements.count <= sampleCount,
              Set(improvements).count == improvements.count,
              improvements.allSatisfy({ $0.count <= 64 && reviewable($0) }),
              Set(regressions).isDisjoint(with: Set(improvements)),
              candidatePass - baselinePass
                == improvements.count - regressions.count
        else {
            throw LauncherError.operationRejected("evaluation_binding_rejected")
        }
        return MemoryEvaluationReview(
            proposalDigest: value["proposal_digest"] as? String,
            baselineDigest: baselineDigest,
            datasetDigest: datasetDigest,
            sampleCount: sampleCount,
            baselinePass: baselinePass,
            baselineFail: baselineFail,
            candidateDigest: candidateDigest,
            candidateManifestDigest: manifestDigest,
            candidateScopeDigest: scopeDigest,
            candidatePass: candidatePass,
            candidateFail: candidateFail,
            regressions: regressions,
            improvements: improvements
        )
    }

    private static func memoryEvaluationDetails(
        _ evaluation: MemoryEvaluationReview
    ) -> String {
        let regressions = evaluation.regressions.isEmpty
            ? "(none)"
            : evaluation.regressions.map { String(reflecting: $0) }
                .joined(separator: ", ")
        let improvements = evaluation.improvements.isEmpty
            ? "(none)"
            : evaluation.improvements.map { String(reflecting: $0) }
                .joined(separator: ", ")
        return "\n\nHarness evaluation record (informational, untrusted data):\n"
            + (evaluation.proposalDigest.map { "Proposal SHA-256: \($0)\n" } ?? "")
            + "Candidate B SHA-256: \(evaluation.candidateDigest)\n"
            + "Manifest SHA-256: \(evaluation.candidateManifestDigest)\n"
            + "Capability scope SHA-256: \(evaluation.candidateScopeDigest)\n"
            + "Current Candidate A / rollback target SHA-256: "
            + "\(evaluation.baselineDigest)\n"
            + "Dataset SHA-256: \(evaluation.datasetDigest)\n"
            + "Fixed replay: \(evaluation.sampleCount) samples\n"
            + "A: \(evaluation.baselinePass) passed, "
            + "\(evaluation.baselineFail) failed\n"
            + "B: \(evaluation.candidatePass) passed, "
            + "\(evaluation.candidateFail) failed\n"
            + "Regressions: \(regressions)\n"
            + "Improvements: \(improvements)\n"
            + "The Kernel binds approval to the exact Candidate, Manifest, scope, "
            + "slot generation, and validity; it does not verify this evaluation."
    }

    private static func approvalExpiry(_ candidate: PluginCandidateReview) -> String {
        guard let expiresAt = candidate.expiresAt else { return "not activated" }
        let date = Date(timeIntervalSince1970: TimeInterval(expiresAt))
        return ISO8601DateFormatter().string(from: date)
    }

    private static func approvePluginAction(
        title: String,
        action: String,
        workspace: URL?,
        details: String,
        digest: String,
        digestLabel: String = "Reviewed operation SHA-256"
    ) -> Bool {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = title
        let workspaceText = workspace.map { "Workspace: \($0.path)\n\n" } ?? ""
        let reviewedDetails = workspaceText + details
            + "\n\n\(digestLabel): \(digest)"
        alert.informativeText = "Review the complete request below. Scroll to inspect all fields."
        alert.accessoryView = approvalDetailsView(reviewedDetails)
        alert.addButton(withTitle: "Cancel")
        alert.addButton(withTitle: action)
        return alert.runModal() == .alertSecondButtonReturn
    }

    private static func approvalDetailsView(_ details: String) -> NSScrollView {
        let width: CGFloat = 520
        let screenHeight = NSScreen.main?.visibleFrame.height ?? 800
        let height = min(340, max(180, screenHeight * 0.4))
        let size = NSSize(width: width, height: height)
        let textView = NSTextView(frame: NSRect(origin: .zero, size: size))
        textView.string = details
        textView.isEditable = false
        textView.isSelectable = true
        textView.isRichText = false
        textView.drawsBackground = false
        textView.font = .systemFont(ofSize: NSFont.smallSystemFontSize)
        textView.textContainerInset = NSSize(width: 8, height: 8)
        textView.minSize = NSSize(width: 0, height: 0)
        textView.maxSize = NSSize(
            width: CGFloat.greatestFiniteMagnitude,
            height: CGFloat.greatestFiniteMagnitude
        )
        textView.isVerticallyResizable = true
        textView.isHorizontallyResizable = false
        textView.autoresizingMask = [.width]
        textView.textContainer?.widthTracksTextView = true
        textView.textContainer?.containerSize = NSSize(
            width: width,
            height: CGFloat.greatestFiniteMagnitude
        )

        let scrollView = NSScrollView(frame: NSRect(origin: .zero, size: size))
        scrollView.borderType = .bezelBorder
        scrollView.hasVerticalScroller = true
        scrollView.autohidesScrollers = false
        scrollView.documentView = textView
        return scrollView
    }

    private static func showPluginSuccess(_ message: String) {
        let alert = NSAlert()
        alert.alertStyle = .informational
        alert.messageText = "Kernel operation completed"
        alert.informativeText = message
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    private static func readPackageFile(
        _ packageURL: URL, name: String, maximumBytes: Int
    ) throws -> Data {
        guard let data = try readOptionalPackageFile(
            packageURL, name: name, maximumBytes: maximumBytes
        ) else {
            throw LauncherError.operationRejected("plugin_package_rejected")
        }
        return data
    }

    private static func readOptionalPackageFile(
        _ packageURL: URL, name: String, maximumBytes: Int
    ) throws -> Data? {
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
        if descriptor < 0 && errno == ENOENT {
            return nil
        }
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
        let modelProvider = AgentModelProvider.from(bundle: .main)
        fputs(
            "Khaos Agent. The model is untrusted; each tool proposal needs separate approval. Type /exit to quit.\n",
            stdout
        )

        var workspace: TrustedWorkspaceSelection?
        var host = AgentHostClient()
        defer { host.stop() }
        while true {
            fputs("You: ", stdout)
            fflush(stdout)
            guard let prompt = readLine(strippingNewline: true) else { return }
            if prompt == "/exit" { return }
            if modelProvider.isRemote,
               !approveRemoteModelData(
                    provider: modelProvider,
                    includesPluginSource: false
               ) {
                fputs(
                    "Khaos: This task was not sent to the remote model; no task or workspace content was transmitted.\n",
                    stdout
                )
                fflush(stdout)
                writeAgentDiagnostic("remote-data=denied")
                continue
            }
            let taskID = UUID()
            var awaitingNextUser = false
            var resetHostAfterTask = false
            var taskToolCalls = 0
            var taskExecutionSeconds = 0.0
            var taskResultBytes = 0
            var commandReturnCodes: [Int] = []
            var workspaceRequestRecords: [AgentWorkspaceRequestRecord] = []
            var taskStopReason: String?

            let initialTurn = awaitAgentHostReply(
                taskID: taskID,
                host: host,
                title: "Agent Host is processing this task",
                message: "The Host receives untrusted task input. Cancel closes this task's Host connection; late replies are discarded."
            ) { completion in
                try host.sendUserTurnAsync(
                    prompt,
                    activePlugin: currentAgentPluginMetadata(),
                    completion: completion
                )
            }
            if initialTurn.cancellationRequested {
                taskStopReason = "user cancelled while Agent Host was processing the task; its connection was invalidated and late replies are discarded"
                fputs("Launcher task status: cancelled: \(taskStopReason!).\n", stdout)
                printAgentTaskRecord(
                    taskID: taskID,
                    toolCalls: taskToolCalls,
                    executionSeconds: taskExecutionSeconds,
                    resultBytes: taskResultBytes,
                    returnCodes: commandReturnCodes,
                    stopReason: taskStopReason,
                    cancellationRequested: true,
                    hostConnectionInvalidated: true,
                    workspaceRequests: workspaceRequestRecords
                )
                fflush(stdout)
                host.stop()
                host = AgentHostClient()
                continue
            }
            if let initialError = initialTurn.error {
                fputs("Local Agent request failed: \(failureCode(for: initialError))\n", stderr)
                host.stop()
                host = AgentHostClient()
                continue
            }
            guard let initialReply = initialTurn.reply else {
                fputs("Local Agent request failed: invalid_response\n", stderr)
                host.stop()
                host = AgentHostClient()
                continue
            }
            var reply = initialReply
            while !awaitingNextUser {
                switch reply {
                case let .text(text):
                    fputs("Khaos: \(terminalSafe(text))\n", stdout)
                    if taskToolCalls > 0 {
                        let status: String
                        if let taskStopReason {
                            status = "stopped: \(taskStopReason)"
                        } else {
                            status = terminalTaskStatus(
                                lastReturnCode: commandReturnCodes.last,
                                workspaceRequests: workspaceRequestRecords
                            )
                        }
                        fputs("Launcher task status: \(status).\n", stdout)
                        taskStopReason = status
                    }
                    printAgentTaskRecord(
                        taskID: taskID,
                        toolCalls: taskToolCalls,
                        executionSeconds: taskExecutionSeconds,
                        resultBytes: taskResultBytes,
                        returnCodes: commandReturnCodes,
                        stopReason: taskStopReason,
                        workspaceRequests: workspaceRequestRecords
                    )
                    fflush(stdout)
                    awaitingNextUser = true
                case let .shell(proposal), let .list(proposal):
                    let directoryListing: Bool
                    if case .list = reply { directoryListing = true } else { directoryListing = false }
                    let proposalKind = directoryListing ? "list" : "shell"
                    writeAgentDiagnostic("tool-proposal kind=\(proposalKind)")
                    let outcome: AgentToolOutcome
                    if taskToolCalls >= AgentHostProtocol.maximumToolCallsPerTask {
                        outcome = AgentToolOutcome(
                            ok: false,
                            canContinue: false,
                            text: "Launcher stopped this proposal because the per-task tool-call budget is exhausted. It was not shown for approval or executed.",
                            returncode: nil,
                            executionSeconds: 0,
                            stopReason: "tool-call budget exhausted"
                        )
                    } else {
                        taskToolCalls += 1
                        let remainingExecution = max(
                            0,
                            AgentHostProtocol.maximumToolExecutionSecondsPerTask
                                - taskExecutionSeconds
                        )
                        let remainingResultBytes = max(
                            0,
                            AgentHostProtocol.maximumToolResultBytesPerTask
                                - taskResultBytes
                        )
                        if remainingExecution <= 0 || remainingResultBytes < 512 {
                            outcome = AgentToolOutcome(
                                ok: false,
                                canContinue: false,
                                text: "Launcher stopped this proposal because the per-task execution-time or result-size budget is exhausted. It was not shown for approval or executed.",
                                returncode: nil,
                                executionSeconds: 0,
                                stopReason: remainingExecution <= 0
                                    ? "cumulative Runner time budget exhausted"
                                    : "cumulative result-size budget exhausted"
                            )
                        } else {
                            outcome = runAgentTool(
                                proposal,
                                taskID: taskID,
                                directoryListing: directoryListing,
                                workspace: &workspace,
                                timeoutSeconds: min(
                                    AgentHostProtocol.maximumToolExecutionSecondsPerCall,
                                    remainingExecution
                                ),
                                maximumResultBytes: min(
                                    AgentHostProtocol.maximumToolResultBytes,
                                    remainingResultBytes
                                )
                            )
                        }
                    }
                    taskExecutionSeconds += outcome.executionSeconds
                    let resultBytes = outcome.text.utf8.count
                    taskResultBytes += resultBytes
                    if let returncode = outcome.returncode {
                        commandReturnCodes.append(returncode)
                    }
                    if let workspaceRecord = outcome.workspaceRecord {
                        workspaceRequestRecords.append(workspaceRecord)
                    }
                    if outcome.taskCancelled {
                        // Deliver the original outcome as terminal data, never as a
                        // new approval. Ignore every Host reply, including proposals.
                        let terminalDelivery = awaitAgentHostReply(
                            taskID: taskID,
                            host: host,
                            title: "Recording the cancelled operation's actual result",
                            message: "The Kernel result is final. The Host cannot continue this task; Cancel ends result delivery."
                        ) { completion in
                            try host.sendToolResultAsync(
                                ok: outcome.ok,
                                canContinue: false,
                                text: outcome.text,
                                activePlugin: currentAgentPluginMetadata(),
                                completion: completion
                            )
                        }
                        let deliveryStatus: String
                        if case .text = terminalDelivery.reply {
                            deliveryStatus = "delivered"
                        } else {
                            deliveryStatus = "unconfirmed"
                        }
                        writeAgentDiagnostic("task=cancelled-terminal-delivery status=\(deliveryStatus)")
                        resetHostAfterTask = true
                        taskStopReason = cancellationTaskStatus(
                            workspaceRequests: workspaceRequestRecords
                        )
                        fputs("Launcher task status: \(taskStopReason!).\n", stdout)
                        printAgentTaskRecord(
                            taskID: taskID,
                            toolCalls: taskToolCalls,
                            executionSeconds: taskExecutionSeconds,
                            resultBytes: taskResultBytes,
                            returnCodes: commandReturnCodes,
                            stopReason: taskStopReason,
                            cancellationRequested: true,
                            hostConnectionInvalidated: true,
                            workspaceRequests: workspaceRequestRecords,
                            terminalResultDelivery: deliveryStatus
                        )
                        fflush(stdout)
                        awaitingNextUser = true
                        continue
                    }
                    let budgetExhausted = taskToolCalls
                            >= AgentHostProtocol.maximumToolCallsPerTask
                        || taskExecutionSeconds
                            >= AgentHostProtocol.maximumToolExecutionSecondsPerTask
                        || taskResultBytes
                            >= AgentHostProtocol.maximumToolResultBytesPerTask
                    let canContinue = outcome.canContinue && !budgetExhausted
                    if budgetExhausted {
                        taskStopReason = taskToolCalls
                                >= AgentHostProtocol.maximumToolCallsPerTask
                            ? "tool-call budget exhausted"
                            : taskExecutionSeconds
                                >= AgentHostProtocol.maximumToolExecutionSecondsPerTask
                                ? "cumulative Runner time budget exhausted"
                                : "cumulative result-size budget exhausted"
                    } else if let stopReason = outcome.stopReason {
                        taskStopReason = stopReason
                    }
                    let returnCode = outcome.returncode.map(String.init) ?? "none"
                    writeAgentDiagnostic(
                        "tool-result kind=\(proposalKind) returncode=\(returnCode) output_bytes=\(resultBytes) can_continue=\(canContinue)"
                    )
                    let hostTurn = awaitAgentHostReply(
                        taskID: taskID,
                        host: host,
                        title: "Agent Host is processing the reviewed result",
                        message: "Cancel ends this task. Any late Host response will be discarded."
                    ) { completion in
                        try host.sendToolResultAsync(
                            ok: outcome.ok,
                            canContinue: canContinue,
                            text: outcome.text,
                            activePlugin: currentAgentPluginMetadata(),
                            completion: completion
                        )
                    }
                    if hostTurn.cancellationRequested {
                        resetHostAfterTask = true
                        taskStopReason = "user cancelled while Agent Host was processing the result; its connection was invalidated and late replies are discarded"
                        fputs("Launcher task status: cancelled: \(taskStopReason!).\n", stdout)
                        printAgentTaskRecord(
                            taskID: taskID,
                            toolCalls: taskToolCalls,
                            executionSeconds: taskExecutionSeconds,
                            resultBytes: taskResultBytes,
                            returnCodes: commandReturnCodes,
                            stopReason: taskStopReason,
                            cancellationRequested: true,
                            hostConnectionInvalidated: true,
                            workspaceRequests: workspaceRequestRecords
                        )
                        fflush(stdout)
                        awaitingNextUser = true
                        continue
                    }
                    if let error = hostTurn.error {
                        resetHostAfterTask = true
                        taskStopReason = "Agent Host failed while receiving a tool result"
                        fputs(
                            "Launcher task status: stopped: Agent Host failed while receiving a tool result (\(failureCode(for: error))).\n",
                            stdout
                        )
                        printAgentTaskRecord(
                            taskID: taskID,
                            toolCalls: taskToolCalls,
                            executionSeconds: taskExecutionSeconds,
                            resultBytes: taskResultBytes,
                            returnCodes: commandReturnCodes,
                            stopReason: taskStopReason,
                            workspaceRequests: workspaceRequestRecords
                        )
                        fflush(stdout)
                        awaitingNextUser = true
                        continue
                    }
                    guard let nextReply = hostTurn.reply else {
                        taskStopReason = "Agent Host returned no tool result reply"
                        awaitingNextUser = true
                        continue
                    }
                    let replyAllowed = AgentHostProtocol.replyAllowedAfterToolResult(
                        nextReply,
                        canContinue: canContinue
                    )
                    let responseStatus = replyAllowed ? "accepted" : "rejected"
                    writeAgentDiagnostic(
                        "tool-response kind=\(proposalKind) status=\(responseStatus) can_continue=\(canContinue)"
                    )
                    if replyAllowed {
                        reply = nextReply
                    } else {
                        writeAgentDiagnostic("task=disallowed_post_result_reply_ignored")
                        taskStopReason = (taskStopReason ?? "tool result ended the task")
                            + "; Launcher ignored a disallowed Agent Host action"
                        reply = .text(outcome.text)
                    }
                case let .plugin(proposal):
                    if taskToolCalls >= AgentHostProtocol.maximumToolCallsPerTask {
                        let hostTurn = awaitAgentHostReply(
                            taskID: taskID,
                            host: host,
                            title: "Agent Host is processing a bounded result",
                            message: "Cancel ends this task. Any late Host response will be discarded."
                        ) { completion in
                            try host.sendToolResultAsync(
                                ok: false,
                                canContinue: false,
                                text: "Launcher stopped this proposal because the per-task tool-call budget is exhausted. It was not approved or executed.",
                                activePlugin: currentAgentPluginMetadata(),
                                completion: completion
                            )
                        }
                        if hostTurn.cancellationRequested {
                            resetHostAfterTask = true
                            taskStopReason = "user cancelled while Agent Host was processing the result; its connection was invalidated and late replies are discarded"
                            fputs("Launcher task status: cancelled: \(taskStopReason!).\n", stdout)
                            printAgentTaskRecord(taskID: taskID, toolCalls: taskToolCalls, executionSeconds: taskExecutionSeconds, resultBytes: taskResultBytes, returnCodes: commandReturnCodes, stopReason: taskStopReason, cancellationRequested: true, hostConnectionInvalidated: true, workspaceRequests: workspaceRequestRecords)
                            fflush(stdout)
                            awaitingNextUser = true
                        } else if let nextReply = hostTurn.reply {
                            reply = nextReply
                        } else {
                            resetHostAfterTask = true
                            taskStopReason = "Agent Host failed while receiving a bounded result"
                            awaitingNextUser = true
                        }
                        continue
                    }
                    taskToolCalls += 1
                    let outcome = runAgentPlugin(proposal, workspace: &workspace)
                    taskResultBytes += outcome.text.utf8.count
                    taskStopReason = "Plugin operation ended the task"
                    let hostTurn = awaitAgentHostReply(
                        taskID: taskID,
                        host: host,
                        title: "Agent Host is processing the Plugin result",
                        message: "Cancel ends this task. Any late Host response will be discarded."
                    ) { completion in
                        try host.sendToolResultAsync(
                            ok: outcome.ok,
                            canContinue: false,
                            text: outcome.text,
                            activePlugin: currentAgentPluginMetadata(),
                            completion: completion
                        )
                    }
                    if hostTurn.cancellationRequested {
                        resetHostAfterTask = true
                        taskStopReason = "user cancelled while Agent Host was processing the Plugin result; its connection was invalidated and late replies are discarded"
                        fputs("Launcher task status: cancelled: \(taskStopReason!).\n", stdout)
                        printAgentTaskRecord(taskID: taskID, toolCalls: taskToolCalls, executionSeconds: taskExecutionSeconds, resultBytes: taskResultBytes, returnCodes: commandReturnCodes, stopReason: taskStopReason, cancellationRequested: true, hostConnectionInvalidated: true, workspaceRequests: workspaceRequestRecords)
                        fflush(stdout)
                        awaitingNextUser = true
                    } else if let nextReply = hostTurn.reply {
                        reply = nextReply
                    } else {
                        resetHostAfterTask = true
                        fputs("Local Agent stopped: \(failureCode(for: hostTurn.error ?? AgentHostClientError.unavailable))\n", stderr)
                        awaitingNextUser = true
                    }
                case let .evolution(proposal):
                    if taskToolCalls >= AgentHostProtocol.maximumToolCallsPerTask {
                        let hostTurn = awaitAgentHostReply(
                            taskID: taskID,
                            host: host,
                            title: "Agent Host is processing a bounded result",
                            message: "Cancel ends this task. Any late Host response will be discarded."
                        ) { completion in
                            try host.sendToolResultAsync(
                                ok: false,
                                canContinue: false,
                                text: "Launcher stopped this proposal because the per-task tool-call budget is exhausted. It was not approved or executed.",
                                activePlugin: currentAgentPluginMetadata(),
                                completion: completion
                            )
                        }
                        if hostTurn.cancellationRequested {
                            resetHostAfterTask = true
                            taskStopReason = "user cancelled while Agent Host was processing the result; its connection was invalidated and late replies are discarded"
                            fputs("Launcher task status: cancelled: \(taskStopReason!).\n", stdout)
                            printAgentTaskRecord(taskID: taskID, toolCalls: taskToolCalls, executionSeconds: taskExecutionSeconds, resultBytes: taskResultBytes, returnCodes: commandReturnCodes, stopReason: taskStopReason, cancellationRequested: true, hostConnectionInvalidated: true, workspaceRequests: workspaceRequestRecords)
                            fflush(stdout)
                            awaitingNextUser = true
                        } else if let nextReply = hostTurn.reply {
                            reply = nextReply
                        } else {
                            resetHostAfterTask = true
                            taskStopReason = "Agent Host failed while receiving a bounded result"
                            awaitingNextUser = true
                        }
                        continue
                    }
                    taskToolCalls += 1
                    let outcome = runAgentEvolution(
                        proposal,
                        evidence: prompt,
                        host: host
                    )
                    taskResultBytes += outcome.text.utf8.count
                    taskStopReason = "Candidate evolution operation ended the task"
                    let hostTurn = awaitAgentHostReply(
                        taskID: taskID,
                        host: host,
                        title: "Agent Host is processing the evolution result",
                        message: "Cancel ends this task. Any late Host response will be discarded."
                    ) { completion in
                        try host.sendToolResultAsync(
                            ok: outcome.ok,
                            canContinue: false,
                            text: outcome.text,
                            activePlugin: currentAgentPluginMetadata(),
                            completion: completion
                        )
                    }
                    if hostTurn.cancellationRequested {
                        resetHostAfterTask = true
                        taskStopReason = "user cancelled while Agent Host was processing the evolution result; its connection was invalidated and late replies are discarded"
                        fputs("Launcher task status: cancelled: \(taskStopReason!).\n", stdout)
                        printAgentTaskRecord(taskID: taskID, toolCalls: taskToolCalls, executionSeconds: taskExecutionSeconds, resultBytes: taskResultBytes, returnCodes: commandReturnCodes, stopReason: taskStopReason, cancellationRequested: true, hostConnectionInvalidated: true, workspaceRequests: workspaceRequestRecords)
                        fflush(stdout)
                        awaitingNextUser = true
                    } else if let nextReply = hostTurn.reply {
                        reply = nextReply
                    } else {
                        resetHostAfterTask = true
                        fputs("Local Agent stopped: \(failureCode(for: hostTurn.error ?? AgentHostClientError.unavailable))\n", stderr)
                        awaitingNextUser = true
                    }
                case let .failure(code):
                    resetHostAfterTask = true
                    fputs("Local Agent error: \(code)\n", stderr)
                    taskStopReason = taskStopReason
                        ?? "Agent Host or model failed: \(code)"
                    if taskToolCalls > 0 {
                        fputs("Launcher task status: stopped: \(taskStopReason!).\n", stdout)
                    }
                    printAgentTaskRecord(
                        taskID: taskID,
                        toolCalls: taskToolCalls,
                        executionSeconds: taskExecutionSeconds,
                        resultBytes: taskResultBytes,
                        returnCodes: commandReturnCodes,
                        stopReason: taskStopReason,
                        workspaceRequests: workspaceRequestRecords
                    )
                    fflush(stdout)
                    awaitingNextUser = true
                case .candidate(_), .evaluation(_):
                    resetHostAfterTask = true
                    fputs("Local Agent error: unexpected_evolution_reply\n", stderr)
                    taskStopReason = "unexpected Agent Host reply"
                    printAgentTaskRecord(
                        taskID: taskID,
                        toolCalls: taskToolCalls,
                        executionSeconds: taskExecutionSeconds,
                        resultBytes: taskResultBytes,
                        returnCodes: commandReturnCodes,
                        stopReason: taskStopReason,
                        workspaceRequests: workspaceRequestRecords
                    )
                    fflush(stdout)
                    awaitingNextUser = true
                }
            }
            if resetHostAfterTask {
                host.stop()
                host = AgentHostClient()
            }
        }
    }

    private static func approveRemoteModelData(
        provider: AgentModelProvider,
        includesPluginSource: Bool
    ) -> Bool {
        guard provider.isRemote, let endpoint = provider.endpoint else { return true }
        writeAgentDiagnostic("remote-data=approval-presented")
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = "Send this task's data to BigModel?"
        var categories = [
            "This task's text and bounded active Plugin metadata",
            "Proposed argv and requested workspace paths for each separately approved operation",
            "Text returned from files and workspace listings within each approved read scope",
            "Command return codes, changed-path lists, and bounded stdout/stderr from approved operations",
        ]
        if includesPluginSource {
            categories.append("The exact active Plugin Manifest and source")
        }
        let service = provider == .bigmodelCodingPlan
            ? "BigModel GLM-5.3-Flash Coding Plan"
            : "BigModel GLM-5.3-Flash"
        alert.informativeText = "Service: \(service)\nEndpoint: \(endpoint.absoluteString)\n\n"
            + "Data that may be sent:\n• " + categories.joined(separator: "\n• ") + "\n\n"
            + "The API key is used only in the request Authorization header. BigModel is an external recipient. This decision authorizes these data categories for this task only. It does not approve any command; each operation still needs separate Launcher approval. Approving a shell command does not authorize sending its data to BigModel."
        alert.addButton(withTitle: "Do not send")
        alert.addButton(withTitle: "Send task data")
        let approved = alert.runModal() == .alertSecondButtonReturn
        writeAgentDiagnostic(approved ? "remote-data=approved" : "remote-data=denied")
        return approved
    }

    private static func awaitAgentHostReply(
        taskID: UUID,
        host: AgentHostClient,
        title: String,
        message: String,
        start: @escaping (@escaping (Result<AgentHostReply, Error>) -> Void) throws -> Void
    ) -> AgentHostTurnOutcome {
        let progress = AgentTaskProgress<AgentHostReply>(
            taskID: taskID,
            title: title,
            message: message,
            cancelCompletesImmediately: true
        )
        let waited = progress.wait(start: { completion in
            DispatchQueue.global(qos: .userInitiated).async {
                do {
                    try start(completion)
                } catch {
                    completion(.failure(error))
                }
            }
        }, cancel: {
            host.stop()
        })
        switch waited.result {
        case let .success(reply):
            return AgentHostTurnOutcome(
                reply: reply,
                cancellationRequested: waited.cancellationRequested,
                error: nil
            )
        case let .failure(error):
            return AgentHostTurnOutcome(
                reply: nil,
                cancellationRequested: waited.cancellationRequested,
                error: error
            )
        }
    }

    private static func terminalTaskStatus(
        lastReturnCode: Int?,
        workspaceRequests: [AgentWorkspaceRequestRecord]
    ) -> String {
        guard let latest = workspaceRequests.last else {
            if let lastReturnCode {
                return "last Runner return code=\(lastReturnCode); no workspace.run outcome was recorded"
            }
            return "Agent Host returned final text; no workspace.run request was submitted"
        }
        switch latest.commitOutcome {
        case "uncertain":
            return "workspace outcome uncertain for request \(latest.requestID) (\(latest.kernelResult))"
        case "rejected":
            return "Kernel rejected the changeset for request \(latest.requestID) (\(latest.kernelResult))"
        case "not_committed" where latest.kernelResult == "error:process_cancelled":
            return "Kernel cancelled request \(latest.requestID) before commit; workspace changes were discarded"
        case "not_committed" where latest.kernelResult.hasPrefix("not_submitted:"):
            return "request \(latest.requestID) was cancelled before workspace.run submission; Runner did not start and no changes were committed"
        case "committed":
            let returnCode = latest.runnerReturnCode.map(String.init) ?? "unknown"
            return "Kernel completed request \(latest.requestID), committed the accepted changeset, Runner return code=\(returnCode)"
        default:
            return "request \(latest.requestID) terminal result=\(latest.kernelResult); workspace outcome=\(latest.commitOutcome)"
        }
    }

    private static func cancellationTaskStatus(
        workspaceRequests: [AgentWorkspaceRequestRecord]
    ) -> String {
        guard let latest = workspaceRequests.last else {
            return "user cancelled; no workspace.run request was submitted"
        }
        let outcome = terminalTaskStatus(
            lastReturnCode: latest.runnerReturnCode,
            workspaceRequests: workspaceRequests
        )
        if latest.cancellationRequested {
            return "user cancellation requested; cancellation handling=\(latest.cancellationResult); \(outcome)"
        }
        return "user cancelled while Agent Host was processing; latest workspace result remains: \(outcome)"
    }

    private static func printAgentTaskRecord(
        taskID: UUID,
        toolCalls: Int,
        executionSeconds: Double,
        resultBytes: Int,
        returnCodes: [Int],
        stopReason: String? = nil,
        cancellationRequested: Bool = false,
        hostConnectionInvalidated: Bool = false,
        workspaceRequests: [AgentWorkspaceRequestRecord] = [],
        terminalResultDelivery: String = "not_applicable"
    ) {
        let workspaceEntries: [[String: Any]] = workspaceRequests.map { request in
            [
                "request_id": request.requestID,
                "workspace_session_id": request.workspaceSessionID,
                "xpc_connection_id": request.connectionID as Any? ?? NSNull(),
                "invocation_sha256": request.approvalSHA256,
                "read_scope": request.readScope,
                "write_scope": request.writeScope,
                "approval": request.approval,
                "cancellation_requested": request.cancellationRequested,
                "cancellation_result": request.cancellationResult,
                "kernel_result": request.kernelResult,
                "runner_execution": request.runnerExecution,
                "runner_return_code": request.runnerReturnCode.map { $0 as Any } ?? NSNull(),
                "changeset": [
                    "added": request.added.map { $0 as Any } ?? NSNull(),
                    "modified": request.modified.map { $0 as Any } ?? NSNull(),
                    "deleted": request.deleted.map { $0 as Any } ?? NSNull(),
                ],
                "commit_outcome": request.commitOutcome,
            ]
        }
        let record: [String: Any] = [
            "task_id": taskID.uuidString.lowercased(),
            "proposals": toolCalls,
            "executed_command_return_codes": returnCodes,
            "cumulative_runner_seconds": String(format: "%.3f", executionSeconds),
            "bounded_result_bytes": resultBytes,
            "cancellation_requested": cancellationRequested,
            "agent_host_connection_invalidated": hostConnectionInvalidated,
            "stop_reason": stopReason ?? "Agent Host returned final text",
            "workspace_requests": workspaceEntries,
            "terminal_result_delivery": terminalResultDelivery,
        ]
        guard let data = try? JSONSerialization.data(
            withJSONObject: record,
            options: [.sortedKeys, .withoutEscapingSlashes]
        ) else {
            fputs("Launcher task record: encoding_failed task_id=\(taskID.uuidString.lowercased())\n", stdout)
            return
        }
        fputs("Launcher task record: \(String(decoding: data, as: UTF8.self))\n", stdout)
    }

    private static func writeAgentDiagnostic(_ result: String) {
        fputs("agent-session=\(result)\n", stderr)
        fflush(stderr)
    }

    private static func currentAgentPluginMetadata() -> AgentHostPluginMetadata? {
        guard let output = try? invokePluginKernel(.state),
              let state = try? parsePluginState(output),
              let active = state.active else {
            return nil
        }
        return AgentHostPluginMetadata(
            pluginID: active.identifier,
            candidateDigest: active.candidateDigest,
            generation: state.generation,
            agentInterface: active.agentInterface
        )
    }

    private static func runAgentPlugin(
        _ proposal: AgentPluginBinding,
        workspace: inout TrustedWorkspaceSelection?
    ) -> (ok: Bool, text: String) {
        do {
            let result = try runActivePlugin(proposal: proposal, workspace: &workspace)
            fputs("agent-plugin=passed\n", stderr)
            return try agentResult(result)
        } catch TrustedWorkspacePickerError.cancelled {
            return (false, "User cancelled Plugin workspace selection.")
        } catch LauncherError.operationRejected(let code) {
            switch code {
            case "no_active_candidate", "stale_proposal", "stale_approval":
                fputs("agent-plugin=denied code=\(code)\n", stderr)
                return (false, "Launcher denied the Plugin proposal: \(code)")
            case "user_denied":
                fputs("agent-plugin=approval-denied\n", stderr)
                return (false, "The user denied this Plugin invocation.")
            default:
                fputs(
                    "agent-plugin=failed code=\(pluginFailureDiagnostic(code))\n",
                    stderr
                )
                return (false, "Launcher could not run the Plugin: \(code)")
            }
        } catch {
            fputs("agent-plugin=failed code=unexpected\n", stderr)
            return (false, "Launcher could not run the Plugin.")
        }
    }

    private static func pluginFailureDiagnostic(_ code: String) -> String {
        let runnerPrefix = "plugin_exit_"
        if code.hasPrefix(runnerPrefix),
           let status = Int(code.dropFirst(runnerPrefix.count)) {
            return "\(runnerPrefix)\(status)"
        }
        switch code {
        case "invalid_plugin_operation", "workspace_rejected",
             "plugin_package_rejected", "invalid_kernel_response":
            return code
        default:
            return "operation_rejected"
        }
    }

    private static func runAgentEvolution(
        _ action: AgentEvolutionProposal,
        evidence: String,
        host: AgentHostClient
    ) -> (ok: Bool, text: String) {
        do {
            return try evolveMemory(action, evidence: evidence, host: host)
        } catch TrustedWorkspacePickerError.cancelled {
            return (false, "The user denied Memory development or activation.")
        } catch LauncherError.operationRejected(let code) {
            fputs("agent-evolution=denied code=\(code)\n", stderr)
            if code == "remote_data_denied" {
                return (false, "The user declined sending Plugin source to BigModel; no Plugin source was transmitted.")
            }
            return (false, "Launcher denied Memory evolution: \(code)")
        } catch {
            fputs("agent-evolution=failed code=\(failureCode(for: error))\n", stderr)
            return (false, "Launcher could not complete Memory evolution.")
        }
    }

    private static func evolveMemory(
        _ action: AgentEvolutionProposal,
        evidence: String,
        host: AgentHostClient
    ) throws -> (ok: Bool, text: String) {
        let initialState = try parsePluginState(invokePluginKernel(.state))
        guard let baseline = initialState.active,
              baseline.identifier == "memory",
              baseline.candidateDigest == action.candidateDigest,
              initialState.generation == action.generation else {
            throw LauncherError.operationRejected("stale_proposal")
        }
        guard !baseline.processExec,
              baseline.readScope.isEmpty,
              baseline.writeScope.isEmpty,
              baseline.agentInterface != nil,
              reviewable(evidence),
              evidence.utf8.count <= AgentHostProtocol.maximumTextBytes else {
            throw LauncherError.operationRejected("capability_denied")
        }

        let (dataset, samples) = try loadMemoryEvaluationDataset()
        let datasetDigest = KernelWorkspaceXPC.sha256Hex(dataset)
        let evidenceDigest = KernelWorkspaceXPC.sha256Hex(Data(evidence.utf8))
        let proposalData = try AgentHostProtocol.evolutionProposal(
            target: AgentHostPluginMetadata(
                pluginID: baseline.identifier,
                candidateDigest: baseline.candidateDigest,
                generation: initialState.generation,
                agentInterface: baseline.agentInterface
            ),
            goal: action.goal,
            evidenceDigest: evidenceDigest,
            manifestDigest: baseline.manifestDigest,
            scopeDigest: baseline.scopeDigest,
            datasetDigest: datasetDigest
        )
        guard let proposalObject = try? JSONSerialization.jsonObject(
            with: proposalData
        ) as? [String: Any],
        let proposalDigest = proposalObject["proposal_digest"] as? String,
        isDigest(proposalDigest) else {
            throw LauncherError.operationRejected("invalid_evolution_proposal")
        }
        writeDiagnostic(
            "agent-evolution-proposal-base64=\(proposalData.base64EncodedString())"
        )

        let developmentDetails = "Target Plugin: memory\n"
            + "Current Candidate SHA-256: \(baseline.candidateDigest)\n"
            + "Current generation: \(initialState.generation)\n"
            + "Change goal: \(String(reflecting: action.goal))\n"
            + "User feedback evidence (untrusted data):\n"
            + String(reflecting: evidence) + "\n"
            + "Evidence SHA-256: \(evidenceDigest)\n"
            + "Fixed evaluation dataset SHA-256: \(datasetDigest)\n"
            + "Maximum capability: process.exec disabled; workspace read/write scopes empty\n"
            + "Persistent state requirement: khaos-memory-v1 remains compatible\n"
            + "Resource limits: generation \(AgentHostProtocol.maximumModelRequestSeconds) seconds / \(AgentHostProtocol.maximumCandidateGenerationTokens) tokens; evaluation 5 samples, 10 seconds each, 100 seconds total\n"
            + "Proposal digest: \(proposalDigest)\n"
            + "This approval permits only Candidate generation, admission, and isolated evaluation. It does not permit activation."
        writeDiagnostic("agent-evolution-development-review=presented")
        guard approvePluginAction(
            title: "Approve Memory Candidate development?",
            action: "Approve development",
            workspace: nil,
            details: developmentDetails,
            digest: proposalDigest,
            digestLabel: "Proposal SHA-256"
        ) else {
            writeDiagnostic("agent-evolution-development=denied")
            throw TrustedWorkspacePickerError.cancelled
        }

        try requireCurrentEvolutionBaseline(baseline, generation: initialState.generation)
        let sourceOutput = try invokePluginKernel(.source(
            candidateDigest: baseline.candidateDigest,
            manifestDigest: baseline.manifestDigest,
            scopeDigest: baseline.scopeDigest,
            expectedGeneration: initialState.generation
        ))
        let (baselineManifest, baselineSource) = try parseEvolutionSource(
            sourceOutput,
            candidate: baseline,
            generation: initialState.generation
        )

        let provider = AgentModelProvider.from(bundle: .main)
        if provider.isRemote,
           !approveRemoteModelData(provider: provider, includesPluginSource: true) {
            throw LauncherError.operationRejected("remote_data_denied")
        }

        let generated = try host.generateCandidate(
            proposal: proposalData,
            evidence: evidence,
            baselineManifest: baselineManifest,
            baselineSource: baselineSource
        )
        if let usage = generated.modelUsage {
            let promptTokens = usage.promptTokens.map(String.init) ?? "unknown"
            let completionTokens = usage.completionTokens.map(String.init) ?? "unknown"
            writeDiagnostic(
                "agent-evolution-model-usage=untrusted "
                    + "provider=\(AgentModelProvider.from(bundle: .main).rawValue) "
                    + "elapsed_ms=\(usage.elapsedMilliseconds) "
                    + "prompt_tokens=\(promptTokens) "
                    + "completion_tokens=\(completionTokens)"
            )
        } else {
            writeDiagnostic("agent-evolution-model-usage=unavailable")
        }
        let generatedDigest = AgentHostProtocol.candidateContentDigest(generated)
        let generatedManifestDigest = AgentHostProtocol.sha256(generated.manifest)
        writeDiagnostic(
            "agent-evolution-candidate-generated digest=\(generatedDigest) "
                + "manifest_digest=\(generatedManifestDigest) "
                + "source_sha256=\(AgentHostProtocol.sha256(generated.source))"
        )
        let admittedOutput = try invokePluginKernel(.admitEvolution(
            manifest: generated.manifest,
            source: generated.source,
            baselineCandidateDigest: baseline.candidateDigest,
            expectedGeneration: initialState.generation
        ))
        let (candidate, admissionGeneration) = try parseAdmittedCandidate(admittedOutput)
        guard admissionGeneration == initialState.generation,
              candidate.identifier == "memory",
              candidate.candidateDigest == generatedDigest,
              candidate.manifestDigest == generatedManifestDigest,
              !candidate.processExec,
              candidate.readScope.isEmpty,
              candidate.writeScope.isEmpty,
              candidate.agentInterface == baseline.agentInterface else {
            throw LauncherError.operationRejected("evolution_candidate_rejected")
        }
        writeDiagnostic(
            "agent-evolution-candidate-admitted digest=\(candidate.candidateDigest) "
                + "manifest_digest=\(candidate.manifestDigest) "
                + "scope_digest=\(candidate.scopeDigest)"
        )

        let observations = try evaluateMemoryCandidates(
            baseline: baseline,
            candidate: candidate,
            generation: initialState.generation,
            samples: samples
        )
        let observationData = try canonicalJSON(observations)
        writeDiagnostic(
            "agent-evolution-evaluation-observations-base64="
                + observationData.base64EncodedString()
        )
        let evaluationRecord = try host.evaluateMemory(
            proposalDigest: proposalDigest,
            baselineCandidateDigest: baseline.candidateDigest,
            candidateDigest: candidate.candidateDigest,
            manifestDigest: candidate.manifestDigest,
            scopeDigest: candidate.scopeDigest,
            datasetDigest: datasetDigest,
            dataset: dataset,
            results: observations
        )
        writeDiagnostic(
            "agent-evolution-evaluation-record-base64="
                + evaluationRecord.base64EncodedString()
        )
        let evaluation = try parseMemoryEvaluationReview(evaluationRecord)
        guard evaluation.proposalDigest == proposalDigest,
              evaluation.baselineDigest == baseline.candidateDigest,
              evaluation.candidateDigest == candidate.candidateDigest,
              evaluation.candidateManifestDigest == candidate.manifestDigest,
              evaluation.candidateScopeDigest == candidate.scopeDigest,
              evaluation.datasetDigest == datasetDigest,
              evaluation.sampleCount == samples.count,
              evaluation.candidatePass > evaluation.baselinePass,
              evaluation.regressions.isEmpty else {
            throw LauncherError.operationRejected("evaluation_binding_rejected")
        }
        try requireCurrentEvolutionBaseline(baseline, generation: initialState.generation)
        guard KernelWorkspaceXPC.sha256Hex(try loadMemoryEvaluationDataset().data)
                == datasetDigest else {
            throw LauncherError.operationRejected("evaluation_binding_rejected")
        }
        let activation = KernelWorkspaceXPC.PluginLifecycleRequest.activate(
            candidateDigest: candidate.candidateDigest,
            manifestDigest: candidate.manifestDigest,
            scopeDigest: candidate.scopeDigest,
            expectedGeneration: initialState.generation
        )
        let activationRequestID = KernelWorkspaceXPC.newRequestID()
        let activationInvocation = try KernelWorkspaceXPC.encodeInvocation(
            request: activation,
            requestID: activationRequestID
        )
        let reviewDigest = KernelWorkspaceXPC.sha256Hex(
            Data("Khaos Seed Evolution Activation Review v1\0".utf8)
                + activationInvocation + proposalData + evaluationRecord + dataset
        )
        let activationDetails = "Approved goal: \(String(reflecting: action.goal))\n"
            + "Proposal SHA-256: \(proposalDigest)\n"
            + candidateDetails(
                candidate,
                validity: "30 days after activation",
                generation: initialState.generation
            )
            + memoryEvaluationDetails(evaluation)
            + "\n\nRollback target: \(baseline.candidateDigest)\n"
            + "Activation is a separate approval. The Kernel will bind the exact Candidate, Manifest, capability scope, and current generation. This review digest also binds the Proposal, fixed dataset, and informational evaluation record."
        writeDiagnostic("agent-evolution-activation-review=presented")
        guard approvePluginAction(
            title: "Activate the evaluated Memory Candidate?",
            action: "Activate Candidate",
            workspace: nil,
            details: activationDetails,
            digest: reviewDigest,
            digestLabel: "Activation review SHA-256"
        ) else {
            try requireCurrentEvolutionBaseline(baseline, generation: initialState.generation)
            writeDiagnostic("agent-evolution-activation=denied")
            throw TrustedWorkspacePickerError.cancelled
        }

        try requireCurrentEvolutionBaseline(baseline, generation: initialState.generation)
        guard KernelWorkspaceXPC.sha256Hex(try loadMemoryEvaluationDataset().data)
                == datasetDigest else {
            throw LauncherError.operationRejected("evaluation_binding_rejected")
        }
        let activated = try parsePluginState(
            invokePluginKernel(activation, requestID: activationRequestID)
        )
        guard activated.active?.candidateDigest == candidate.candidateDigest,
              activated.generation == initialState.generation + 1 else {
            throw LauncherError.operationRejected("activation_not_confirmed")
        }
        writeDiagnostic("agent-evolution=adopted")
        return (
            true,
            "Memory Candidate \(candidate.candidateDigest) was approved and activated. "
                + "The isolated replay improved from \(evaluation.baselinePass)/\(evaluation.sampleCount) "
                + "to \(evaluation.candidatePass)/\(evaluation.sampleCount), with no regressions. "
                + "Production Memory state remains owned by logical Plugin memory; rollback target is \(baseline.candidateDigest)."
        )
    }

    private static func requireCurrentEvolutionBaseline(
        _ expected: PluginCandidateReview,
        generation: Int
    ) throws {
        let state = try parsePluginState(invokePluginKernel(.state))
        guard state.generation == generation,
              let active = state.active,
              active.identifier == expected.identifier,
              active.candidateDigest == expected.candidateDigest,
              active.manifestDigest == expected.manifestDigest,
              active.scopeDigest == expected.scopeDigest else {
            throw LauncherError.operationRejected("stale_approval")
        }
    }

    private static func parseEvolutionSource(
        _ output: String,
        candidate: PluginCandidateReview,
        generation: Int
    ) throws -> (Data, Data) {
        guard let value = try? JSONSerialization.jsonObject(with: Data(output.utf8))
                as? [String: Any],
              Set(value.keys) == [
                "candidate_digest", "generation", "manifest_base64", "source_base64",
              ],
              value["candidate_digest"] as? String == candidate.candidateDigest,
              integerValue(value["generation"]) == generation,
              let manifestText = value["manifest_base64"] as? String,
              let manifest = Data(base64Encoded: manifestText),
              manifest.base64EncodedString() == manifestText,
              let sourceText = value["source_base64"] as? String,
              let source = Data(base64Encoded: sourceText),
              source.base64EncodedString() == sourceText,
              KernelWorkspaceXPC.sha256Hex(manifest) == candidate.manifestDigest,
              AgentHostProtocol.candidateContentDigest(
                AgentCandidateFiles(manifest: manifest, source: source)
              ) == candidate.candidateDigest else {
            throw LauncherError.operationRejected("plugin_source_rejected")
        }
        return (manifest, source)
    }

    private static func loadMemoryEvaluationDataset() throws -> (
        data: Data,
        samples: [[String: Any]]
    ) {
        // Bind the exact bundled bytes; Foundation and Python sort casefold-
        // colliding keys such as "Name" and "name" differently.
        guard let url = Bundle.main.url(
            forResource: "memory-evaluation",
            withExtension: "json"
        ),
        let data = try? Data(contentsOf: url),
        !data.isEmpty, data.count <= 16 * 1024,
        let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
        Set(value.keys) == ["format", "samples"],
        value["format"] as? String == "khaos-memory-eval-v1",
        let samples = value["samples"] as? [[String: Any]],
        samples.count == AgentHostProtocol.maximumEvaluationSamples else {
            throw LauncherError.operationRejected("evaluation_dataset_rejected")
        }
        var ids = Set<String>()
        for sample in samples {
            guard Set(sample.keys) == ["expected", "id", "initial_items", "request"],
                  let id = sample["id"] as? String,
                  !id.isEmpty, id.utf8.count <= 64, ids.insert(id).inserted,
                  let initial = sample["initial_items"] as? [String: String],
                  let request = sample["request"] as? [String: Any],
                  let expected = sample["expected"] as? [String: Any],
                  initial.allSatisfy({ $0.key.utf8.count <= 128 && $0.value.utf8.count <= 4_096 }) else {
                throw LauncherError.operationRejected("evaluation_dataset_rejected")
            }
            switch request["operation"] as? String {
            case "recall":
                guard Set(request.keys) == ["key", "operation"],
                      request["key"] as? String != nil,
                      Set(expected.keys) == ["found", "value"],
                      expected["found"] as? Bool != nil,
                      (expected["value"] is NSNull || expected["value"] as? String != nil) else {
                    throw LauncherError.operationRejected("evaluation_dataset_rejected")
                }
            case "remember":
                guard Set(request.keys) == ["key", "operation", "value"],
                      request["key"] as? String != nil,
                      let value = request["value"] as? String,
                      value.utf8.count <= 4_096,
                      Set(expected.keys) == ["remembered"],
                      expected["remembered"] as? Bool == true else {
                    throw LauncherError.operationRejected("evaluation_dataset_rejected")
                }
            default:
                throw LauncherError.operationRejected("evaluation_dataset_rejected")
            }
        }
        return (data, samples)
    }

    private static func evaluateMemoryCandidates(
        baseline: PluginCandidateReview,
        candidate: PluginCandidateReview,
        generation: Int,
        samples: [[String: Any]]
    ) throws -> [[String: Any]] {
        var observations: [[String: Any]] = []
        observations.reserveCapacity(samples.count)
        for sample in samples {
            guard let sampleID = sample["id"] as? String,
                  let initialItems = sample["initial_items"] as? [String: String],
                  let input = sample["request"] as? [String: Any],
                  JSONSerialization.isValidJSONObject(input),
                  let inputJSON = try? JSONSerialization.data(
                    withJSONObject: input,
                    options: [.sortedKeys, .withoutEscapingSlashes]
                  ) else {
                throw LauncherError.operationRejected("evaluation_dataset_rejected")
            }
            let initialState = AgentHostProtocol.canonicalMemoryState(items: initialItems)
            let baselineResult = try evaluateMemoryCandidate(
                baseline,
                activeBaselineDigest: baseline.candidateDigest,
                generation: generation,
                initialState: initialState,
                inputJSON: inputJSON
            )
            let candidateResult = try evaluateMemoryCandidate(
                candidate,
                activeBaselineDigest: baseline.candidateDigest,
                generation: generation,
                initialState: initialState,
                inputJSON: inputJSON
            )
            observations.append([
                "sample_id": sampleID,
                "baseline": evaluationObservation(baselineResult),
                "candidate": evaluationObservation(candidateResult),
            ])
        }
        return observations
    }

    private static func evaluateMemoryCandidate(
        _ candidate: PluginCandidateReview,
        activeBaselineDigest: String,
        generation: Int,
        initialState: Data,
        inputJSON: Data
    ) throws -> WorkspaceResult {
        let request = KernelWorkspaceXPC.PluginLifecycleRequest.evaluate(
            baselineCandidateDigest: activeBaselineDigest,
            candidateDigest: candidate.candidateDigest,
            manifestDigest: candidate.manifestDigest,
            scopeDigest: candidate.scopeDigest,
            expectedGeneration: generation,
            initialState: initialState,
            inputJSON: inputJSON
        )
        let result = try parseWorkspaceResult(invokePluginKernel(request))
        guard result.returncode == 0,
              result.added == 0, result.modified == 0, result.deleted == 0 else {
            throw LauncherError.operationRejected("evaluation_runner_failed")
        }
        return result
    }

    private static func evaluationObservation(
        _ result: WorkspaceResult
    ) -> [String: Any] {
        [
            "returncode": result.returncode,
            "stdout": String(result.stdout.prefix(AgentHostProtocol.maximumEvaluationOutputBytes)),
            "added": result.added,
            "modified": result.modified,
            "deleted": result.deleted,
            "plugin_state_sha256": result.pluginStateSHA256 as Any? ?? NSNull(),
        ]
    }

    private static func canonicalJSON(_ value: Any) throws -> Data {
        guard JSONSerialization.isValidJSONObject(value),
              let data = try? JSONSerialization.data(
                withJSONObject: value,
                options: [.sortedKeys, .withoutEscapingSlashes]
              ) else {
            throw LauncherError.operationRejected("invalid_evaluation_input")
        }
        return data
    }

    private static func runAgentTool(
        _ proposal: AgentShellProposal,
        taskID: UUID,
        directoryListing: Bool = false,
        workspace: inout TrustedWorkspaceSelection?,
        timeoutSeconds: Double,
        maximumResultBytes: Int
    ) -> AgentToolOutcome {
        guard (directoryListing
                ? proposal.argv.isEmpty && proposal.writeScope.isEmpty && !proposal.readScope.isEmpty
                : !proposal.argv.isEmpty),
              proposal.argv.count <= AgentHostProtocol.maximumArguments,
              proposal.argv.allSatisfy(reviewable),
              proposal.readScope.count + proposal.writeScope.count
                <= AgentHostProtocol.maximumScopePaths,
              (proposal.readScope + proposal.writeScope).allSatisfy(reviewable),
              timeoutSeconds.isFinite,
              timeoutSeconds > 0,
              timeoutSeconds <= AgentHostProtocol.maximumToolExecutionSecondsPerCall,
              maximumResultBytes >= 512,
              maximumResultBytes <= AgentHostProtocol.maximumToolResultBytes else {
            return AgentToolOutcome(
                ok: false,
                canContinue: false,
                text: "Launcher rejected the malformed or over-budget tool proposal.",
                returncode: nil,
                executionSeconds: 0,
                stopReason: "malformed or over-budget proposal rejected"
            )
        }
        let source: String
        do {
            source = try directoryListing
                ? agentDirectoryRunnerSource(
                    paths: proposal.readScope,
                    maximumBytes: max(0, agentStreamLimit(maximumBytes: maximumResultBytes) - 1)
                )
                : TrustedAgentRunnerSource.make(argv: proposal.argv)
        } catch {
            if !directoryListing,
               TrustedCandidateBPreview.isCandidateBLike(proposal.argv) {
                let reason = "Candidate B Runner wrapper exceeds the supported request size."
                TrustedCandidateBApproval.showIncomplete(reason)
                writeAgentDiagnostic("tool=preview-incomplete")
                return AgentToolOutcome(
                    ok: false,
                    canContinue: false,
                    text: "PREVIEW_INCOMPLETE: \(reason) The request was not submitted.",
                    returncode: nil,
                    executionSeconds: 0,
                    stopReason: "PREVIEW_INCOMPLETE: \(reason)"
                )
            }
            return AgentToolOutcome(
                ok: false,
                canContinue: false,
                text: "Launcher could not encode the bounded tool proposal.",
                returncode: nil,
                executionSeconds: 0,
                stopReason: "Launcher could not encode the tool proposal"
            )
        }
        let request = KernelWorkspaceXPC.WorkspaceRunRequest(
            timeoutSeconds: timeoutSeconds,
            runnerSource: source,
            runnerSourceSHA256: KernelWorkspaceXPC.runnerSourceSHA256(source),
            workspaceReadScope: proposal.readScope,
            workspaceWriteScope: proposal.writeScope
        )
        let requestID = KernelWorkspaceXPC.newRequestID()
        let candidatePreview: TrustedCandidateBPreviewResult
        if directoryListing {
            candidatePreview = .ordinaryRequest
        } else {
            candidatePreview = TrustedCandidateBPreview.parse(
                runnerSource: source,
                runnerSourceSHA256: request.runnerSourceSHA256,
                readScope: request.workspaceReadScope,
                writeScope: request.workspaceWriteScope
            )
        }
        if case let .incomplete(reason) = candidatePreview {
            TrustedCandidateBApproval.showIncomplete(reason)
            writeAgentDiagnostic("tool=preview-incomplete")
            return AgentToolOutcome(
                ok: false,
                canContinue: false,
                text: "Launcher refused the Candidate B request because its trusted preview was incomplete. The request was not submitted.",
                returncode: nil,
                executionSeconds: 0,
                stopReason: "PREVIEW_INCOMPLETE: \(reason)"
            )
        }

        do {
            _ = try request.encodeFrame(requestID: requestID)
        } catch {
            return AgentToolOutcome(
                ok: false,
                canContinue: false,
                text: "Kernel rejected the requested argv or workspace scope as invalid.",
                returncode: nil,
                executionSeconds: 0,
                stopReason: "Kernel rejected the proposed argv or scope"
            )
        }

        if workspace == nil {
            do {
                writeAgentDiagnostic("tool=workspace-picker-requested")
                let selected = try TrustedWorkspacePicker.selectWorkspace(
                    message: "Choose the workspace for this reviewed Agent tool request."
                )
                guard reviewable(selected.scopeURL.path) else {
                    selected.scopeURL.stopAccessingSecurityScopedResource()
                    return AgentToolOutcome(
                        ok: false,
                        canContinue: false,
                        text: "Launcher rejected the selected workspace path.",
                        returncode: nil,
                        executionSeconds: 0,
                        stopReason: "selected workspace path rejected"
                    )
                }
                selected.scopeURL.stopAccessingSecurityScopedResource()
                workspace = selected
            } catch TrustedWorkspacePickerError.cancelled {
                writeAgentDiagnostic("tool=workspace-selection-cancelled")
                return AgentToolOutcome(
                    ok: false,
                    canContinue: false,
                    text: "The user cancelled workspace selection. This task stopped; no command ran.",
                    returncode: nil,
                    executionSeconds: 0,
                    stopReason: "user cancelled workspace selection; no command ran"
                )
            } catch {
                return AgentToolOutcome(
                    ok: false,
                    canContinue: false,
                    text: "Launcher could not establish the selected workspace.",
                    returncode: nil,
                    executionSeconds: 0,
                    stopReason: "Launcher could not establish the workspace"
                )
            }
        }
        guard let selection = workspace,
              let bundleID = Bundle.main.bundleIdentifier else {
            return AgentToolOutcome(
                ok: false,
                canContinue: false,
                text: "Trusted workspace session is unavailable.",
                returncode: nil,
                executionSeconds: 0,
                stopReason: "trusted workspace session unavailable"
            )
        }

        let invocation: Data
        do {
            invocation = try KernelWorkspaceXPC.encodeInvocation(
                request: request,
                requestID: requestID,
                bookmark: selection.bookmark
            )
        } catch {
            return AgentToolOutcome(
                ok: false,
                canContinue: false,
                text: "Launcher could not encode the trusted workspace invocation.",
                returncode: nil,
                executionSeconds: 0,
                stopReason: "Launcher could not encode the workspace invocation"
            )
        }
        let command = directoryListing
            ? "Kernel fs.list: immediate entries of each requested directory; symlink targets are omitted."
            : "Proposed argv:\n" + proposal.argv.map { "  \($0)" }.joined(separator: "\n")
        let approvalDigest = KernelWorkspaceXPC.sha256Hex(invocation)
        var frozenRequest = AgentWorkspaceRequest(
            requestID: requestID,
            request: request,
            invocation: invocation,
            approvalSHA256: approvalDigest,
            workspaceSessionID: selection.identity,
            connectionID: nil
        )
        writeAgentDiagnostic("tool=approval-presented")
        var approved = false
        var previewFailure: String?
        let approvalKind: String
        switch candidatePreview {
        case .ordinaryRequest:
            approvalKind = "ordinary"
            approved = approveReviewedRequest(
                request,
                title: "Approve this local Agent tool once?",
                details: command,
                workspace: selection.scopeURL,
                digest: approvalDigest
            )
        case let .complete(edit):
            approvalKind = "candidate_b_preview"
            let decision = TrustedCandidateBApproval.present(
                edit: edit,
                workspacePath: selection.scopeURL.path,
                requestID: requestID.token,
                requestSHA256: approvalDigest,
                runnerSourceSHA256: request.runnerSourceSHA256,
                readScope: request.workspaceReadScope,
                writeScope: request.workspaceWriteScope
            )
            switch decision {
            case .approved:
                approved = true
            case .denied:
                approved = false
            case let .incomplete(reason):
                previewFailure = reason
            }
        case .incomplete:
            // The incomplete case is handled before workspace selection and cannot reach approval.
            return AgentToolOutcome(
                ok: false,
                canContinue: false,
                text: "Launcher refused the Candidate B request because its trusted preview was incomplete. The request was not submitted.",
                returncode: nil,
                executionSeconds: 0,
                stopReason: "PREVIEW_INCOMPLETE"
            )
        }
        if let previewFailure {
            let record = agentWorkspaceRequestRecord(
                frozenRequest,
                approval: "preview_incomplete",
                cancellationRequested: false,
                cancellationResult: "not_requested",
                kernelResult: "not_submitted",
                runnerExecution: "not_started",
                workspaceResult: nil,
                commitOutcome: "not_committed"
            )
            return AgentToolOutcome(
                ok: false,
                canContinue: false,
                text: "PREVIEW_INCOMPLETE: \(previewFailure). The request was not submitted.",
                returncode: nil,
                executionSeconds: 0,
                stopReason: "PREVIEW_INCOMPLETE: \(previewFailure)",
                workspaceRecord: record
            )
        }
        guard approved else {
            writeAgentDiagnostic("tool=approval-denied")
            let record = agentWorkspaceRequestRecord(
                frozenRequest,
                approval: "denied",
                cancellationRequested: false,
                cancellationResult: "not_requested",
                kernelResult: "not_submitted",
                runnerExecution: "not_started",
                workspaceResult: nil,
                commitOutcome: "not_committed"
            )
            return AgentToolOutcome(
                ok: false,
                canContinue: false,
                text: "The user denied this tool request. This task stopped; the command was not executed. Do not retry or restate it.",
                returncode: nil,
                executionSeconds: 0,
                stopReason: "user denied the proposed operation; it was not executed",
                workspaceRecord: record
            )
        }

        writeAgentDiagnostic("tool=approved kind=\(approvalKind)")
        let progress = AgentTaskProgress<KernelWorkspaceCommandObservation>(
            taskID: taskID,
            title: "Preparing the approved workspace operation",
            message: "Cancel remains available while Khaos establishes the authenticated Kernel path. It will stop this request before workspace.run is submitted."
        )
        let handleLock = NSLock()
        var commandHandle: KernelWorkspaceCommandHandle?
        var cancellationBeforeHandle = false
        let sendCancellation: (KernelWorkspaceCommandHandle) -> Void = { handle in
            handle.requestCancellation(matching: handle.identity) { cancellation in
                let status = cancellation == .notSubmitted
                    ? "Cancellation stopped workspace.run before submission. Runner did not start; recording this request's terminal result."
                    : "Kernel cancellation result: \(cancellationLabel(cancellation)). Waiting for the original workspace.run result."
                progress.updateStatus(status)
            }
        }
        let waited = progress.wait(start: { completion in
            DispatchQueue.global(qos: .userInitiated).async {
                do {
                    let target = try connectKernel(bundleID: bundleID)
                    let snapshotBrokerEndpoint = try KernelSnapshotBrokerBootstrapClient.endpoint()
                    let handle = try KernelWorkspaceClient.workspaceCommand(
                        target,
                        taskID: taskID,
                        workspaceSessionID: selection.identity,
                        requestID: requestID,
                        invocationFrame: frozenRequest.invocation,
                        snapshotBrokerEndpoint: snapshotBrokerEndpoint
                    )
                    handleLock.lock()
                    commandHandle = handle
                    let cancelBeforeSubmission = cancellationBeforeHandle
                    handleLock.unlock()
                    if cancelBeforeSubmission {
                        sendCancellation(handle)
                    }
                    progress.updateStatus(
                        cancelBeforeSubmission
                            ? "Cancellation was recorded before workspace.run submission. Waiting for the request's terminal record."
                            : "Approved workspace operation is running. Cancel uses this request's authenticated connection and waits for its final Kernel result."
                    )
                    handle.start { observation in
                        completion(.success(observation))
                    }
                } catch {
                    completion(.failure(error))
                }
            }
        }, cancel: {
            handleLock.lock()
            let handle = commandHandle
            if handle == nil {
                cancellationBeforeHandle = true
            }
            handleLock.unlock()
            if let handle {
                sendCancellation(handle)
            } else {
                progress.updateStatus(
                    "Cancellation requested while preparing the Kernel path. workspace.run will be stopped before submission."
                )
            }
        })
        handleLock.lock()
        let handle = commandHandle
        handleLock.unlock()
        if let handle {
            frozenRequest.connectionID = handle.identity.connectionID
        }
        let observation: KernelWorkspaceCommandObservation
        switch waited.result {
        case let .success(value):
            observation = value
        case let .failure(error):
            let code = failureCode(for: error)
            let record = agentWorkspaceRequestRecord(
                frozenRequest,
                approval: "approved_\(approvalKind)",
                cancellationRequested: waited.cancellationRequested,
                cancellationResult: waited.cancellationRequested
                    ? "not_submitted"
                    : "not_requested",
                kernelResult: "not_submitted:\(code)",
                runnerExecution: "not_started",
                workspaceResult: nil,
                commitOutcome: "not_committed"
            )
            return AgentToolOutcome(
                ok: false,
                canContinue: false,
                text: waited.cancellationRequested
                    ? "Task cancelled before workspace.run submission (\(code)). Runner did not start and no workspace changes were committed."
                    : "Launcher could not establish the authenticated Kernel request path (\(code)). workspace.run was not submitted; Runner did not start.",
                returncode: nil,
                executionSeconds: 0,
                stopReason: waited.cancellationRequested
                    ? "cancelled before workspace.run submission; Runner did not start"
                    : "Kernel request was not submitted: \(code)",
                taskCancelled: waited.cancellationRequested,
                workspaceRecord: record
            )
        }

        let elapsed = observation.submittedAt.map {
            max(0, ProcessInfo.processInfo.systemUptime - $0)
        } ?? 0
        if observation.submitted {
            writeAgentDiagnostic("tool=submitted request_id=\(requestID.token)")
        }
        let cancellationResult = cancellationLabel(observation.cancellation)
        switch observation.reply {
        case let .failure(error):
            let code = failureCode(for: error)
            let submitted = observation.submitted
            let kernelResult = submitted
                ? "reply_unavailable:\(code)"
                : "not_submitted:\(code)"
            let commitOutcome = submitted ? "unknown" : "not_committed"
            let record = agentWorkspaceRequestRecord(
                frozenRequest,
                approval: "approved_\(approvalKind)",
                cancellationRequested: waited.cancellationRequested,
                cancellationResult: cancellationResult,
                kernelResult: kernelResult,
                runnerExecution: submitted ? "unknown" : "not_started",
                workspaceResult: nil,
                commitOutcome: commitOutcome
            )
            writeAgentDiagnostic("tool=reply-unavailable code=\(code)")
            let text = submitted
                ? "The original Kernel result is unavailable (\(code)); workspace outcome is unknown. Khaos did not retry the request."
                : "The workspace.run request was not submitted (\(code)); Runner did not start and no workspace changes were committed."
            return AgentToolOutcome(
                ok: false,
                canContinue: false,
                text: text,
                returncode: nil,
                executionSeconds: elapsed,
                stopReason: waited.cancellationRequested
                    ? cancellationTaskStatus(workspaceRequests: [record])
                    : submitted
                        ? "Kernel result unavailable; workspace outcome unknown"
                        : "workspace.run was not submitted; Runner did not start",
                taskCancelled: waited.cancellationRequested,
                workspaceRecord: record
            )
        case let .success(reply):
            if let errorCode = reply.errorCode {
                let code = safeWorkspaceErrorCode(errorCode)
                let commitOutcome: String
                switch code {
                case "process_cancelled": commitOutcome = "not_committed"
                case "commit_rejected": commitOutcome = "rejected"
                case "commit_outcome_uncertain": commitOutcome = "uncertain"
                default: commitOutcome = "unknown"
                }
                let runnerExecution: String
                switch code {
                case "commit_rejected", "commit_outcome_uncertain":
                    runnerExecution = "completed"
                case "runner_failed":
                    runnerExecution = "attempted"
                default:
                    runnerExecution = "unknown"
                }
                let record = agentWorkspaceRequestRecord(
                    frozenRequest,
                    approval: "approved_\(approvalKind)",
                    cancellationRequested: waited.cancellationRequested,
                    cancellationResult: cancellationResult,
                    kernelResult: "error:\(code)",
                    runnerExecution: runnerExecution,
                    workspaceResult: nil,
                    commitOutcome: commitOutcome
                )
                let text: String
                if code == "commit_outcome_uncertain" {
                    text = "Kernel returned commit_outcome_uncertain. Workspace outcome is uncertain; Khaos did not retry."
                } else if code == "commit_rejected" {
                    text = "Kernel returned commit_rejected. The requested changeset was rejected; Khaos did not retry."
                } else if code == "process_cancelled" {
                    text = "Kernel returned process_cancelled after cancelling the workspace operation. The snapshot was not committed."
                } else {
                    text = "Kernel rejected or failed the workspace request: \(code). No retry was made; workspace outcome is \(commitOutcome)."
                }
                return AgentToolOutcome(
                    ok: false,
                    canContinue: false,
                    text: text,
                    returncode: nil,
                    executionSeconds: elapsed,
                    stopReason: waited.cancellationRequested
                        ? cancellationTaskStatus(workspaceRequests: [record])
                        : "Kernel returned \(code); workspace outcome=\(commitOutcome)",
                    taskCancelled: waited.cancellationRequested,
                    workspaceRecord: record
                )
            }
            guard let output = reply.output else {
                let record = agentWorkspaceRequestRecord(
                    frozenRequest,
                    approval: "approved_\(approvalKind)",
                    cancellationRequested: waited.cancellationRequested,
                    cancellationResult: cancellationResult,
                    kernelResult: "invalid_final_reply",
                    runnerExecution: "unknown",
                    workspaceResult: nil,
                    commitOutcome: "unknown"
                )
                return AgentToolOutcome(
                    ok: false,
                    canContinue: false,
                    text: "Kernel returned no final workspace result. Workspace outcome is unknown; Khaos did not retry.",
                    returncode: nil,
                    executionSeconds: elapsed,
                    stopReason: "Kernel final result missing; workspace outcome unknown",
                    taskCancelled: waited.cancellationRequested,
                    workspaceRecord: record
                )
            }
            let result: WorkspaceResult
            do {
                result = try parseWorkspaceResult(output)
            } catch let LauncherError.operationRejected(code) {
                let record = agentWorkspaceRequestRecord(
                    frozenRequest,
                    approval: "approved_\(approvalKind)",
                    cancellationRequested: waited.cancellationRequested,
                    cancellationResult: cancellationResult,
                    kernelResult: "invalid_runner_output:\(code)",
                    runnerExecution: "completed",
                    workspaceResult: nil,
                    commitOutcome: "committed"
                )
                return AgentToolOutcome(
                    ok: false,
                    canContinue: false,
                    text: "Kernel returned a completed workspace result, so its commit was accepted, but Launcher could not parse Runner output (\(code)); the changeset details are unavailable.",
                    returncode: nil,
                    executionSeconds: elapsed,
                    stopReason: "Kernel completed the request; Runner result could not be parsed",
                    taskCancelled: waited.cancellationRequested,
                    workspaceRecord: record
                )
            } catch {
                let record = agentWorkspaceRequestRecord(
                    frozenRequest,
                    approval: "approved_\(approvalKind)",
                    cancellationRequested: waited.cancellationRequested,
                    cancellationResult: cancellationResult,
                    kernelResult: "invalid_runner_output",
                    runnerExecution: "completed",
                    workspaceResult: nil,
                    commitOutcome: "committed"
                )
                return AgentToolOutcome(
                    ok: false,
                    canContinue: false,
                    text: "Kernel returned a completed workspace result, so its commit was accepted, but Launcher could not parse Runner output; the changeset details are unavailable.",
                    returncode: nil,
                    executionSeconds: elapsed,
                    stopReason: "Kernel completed the request; Runner result could not be parsed",
                    taskCancelled: waited.cancellationRequested,
                    workspaceRecord: record
                )
            }
            let record = agentWorkspaceRequestRecord(
                frozenRequest,
                approval: "approved_\(approvalKind)",
                cancellationRequested: waited.cancellationRequested,
                cancellationResult: cancellationResult,
                kernelResult: "output",
                runnerExecution: "completed",
                workspaceResult: result,
                commitOutcome: "committed"
            )
            do {
                let bounded = try agentResult(result, maximumBytes: maximumResultBytes)
                writeAgentDiagnostic("tool=executed returncode=\(result.returncode)")
                let text = waited.cancellationRequested
                    ? "Cancellation was requested, but the original Kernel operation completed first. Its changeset was committed. Runner return code=\(result.returncode).\n\(bounded.text)"
                    : bounded.text
                return AgentToolOutcome(
                    ok: result.returncode == 0,
                    canContinue: !waited.cancellationRequested,
                    text: text,
                    returncode: result.returncode,
                    executionSeconds: elapsed,
                    stopReason: waited.cancellationRequested
                        ? terminalTaskStatus(
                            lastReturnCode: result.returncode,
                            workspaceRequests: [record]
                        )
                        : nil,
                    taskCancelled: waited.cancellationRequested,
                    workspaceRecord: record
                )
            } catch let LauncherError.operationRejected(code) {
                return AgentToolOutcome(
                    ok: false,
                    canContinue: false,
                    text: "Kernel committed the completed workspace result, but Launcher could not bound the result for the Agent Host (\(code)).",
                    returncode: result.returncode,
                    executionSeconds: elapsed,
                    stopReason: "Kernel committed the request; bounded result preparation failed",
                    taskCancelled: waited.cancellationRequested,
                    workspaceRecord: record
                )
            } catch {
                return AgentToolOutcome(
                    ok: false,
                    canContinue: false,
                    text: "Kernel committed the completed workspace result, but Launcher could not prepare the bounded Agent Host result.",
                    returncode: result.returncode,
                    executionSeconds: elapsed,
                    stopReason: "Kernel committed the request; result preparation failed",
                    taskCancelled: waited.cancellationRequested,
                    workspaceRecord: record
                )
            }
        }
    }

    private static func agentWorkspaceRequestRecord(
        _ request: AgentWorkspaceRequest,
        approval: String,
        cancellationRequested: Bool,
        cancellationResult: String,
        kernelResult: String,
        runnerExecution: String,
        workspaceResult: WorkspaceResult?,
        commitOutcome: String
    ) -> AgentWorkspaceRequestRecord {
        AgentWorkspaceRequestRecord(
            requestID: request.requestID.token,
            workspaceSessionID: request.workspaceSessionID.uuidString.lowercased(),
            connectionID: request.connectionID?.uuidString.lowercased(),
            approvalSHA256: request.approvalSHA256,
            readScope: request.request.workspaceReadScope,
            writeScope: request.request.workspaceWriteScope,
            approval: approval,
            cancellationRequested: cancellationRequested,
            cancellationResult: cancellationResult,
            kernelResult: kernelResult,
            runnerExecution: runnerExecution,
            runnerReturnCode: workspaceResult?.returncode,
            added: workspaceResult?.added,
            modified: workspaceResult?.modified,
            deleted: workspaceResult?.deleted,
            commitOutcome: commitOutcome
        )
    }

    private static func cancellationLabel(
        _ result: KernelWorkspaceCancellationResult
    ) -> String {
        switch result {
        case .notRequested: return "not_requested"
        case .notSubmitted: return "not_sent_before_submission"
        case .accepted: return "cancel_accepted"
        case let .rejected(code): return "rejected:\(code)"
        case .unavailable: return "unavailable"
        case .notActive: return "not_active"
        case .staleIdentity: return "stale_identity"
        case .alreadyRequested: return "already_requested"
        }
    }

    private static func agentResult(
        _ result: WorkspaceResult,
        maximumBytes: Int = AgentHostProtocol.maximumToolResultBytes
    ) throws -> (ok: Bool, text: String) {
        guard maximumBytes >= 512,
              maximumBytes <= AgentHostProtocol.maximumToolResultBytes else {
            throw LauncherError.invalidArguments
        }
        var streamLimit = agentStreamLimit(maximumBytes: maximumBytes)
        while true {
            let stdout = boundedUTF8Prefix(result.stdout, maximumBytes: streamLimit)
            let stderr = boundedUTF8Prefix(result.stderr, maximumBytes: streamLimit)
            let resultObject: [String: Any] = [
                "returncode": result.returncode,
                "added": result.added,
                "modified": result.modified,
                "deleted": result.deleted,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": stdout.utf8.count < result.stdout.utf8.count,
                "stderr_truncated": stderr.utf8.count < result.stderr.utf8.count,
            ]
            let resultData = try JSONSerialization.data(
                withJSONObject: resultObject,
                options: [.sortedKeys, .withoutEscapingSlashes]
            )
            if resultData.count <= maximumBytes {
                return (
                    result.returncode == 0,
                    String(decoding: resultData, as: UTF8.self)
                )
            }
            guard streamLimit > 0 else {
                throw LauncherError.operationRejected("tool_result_too_large")
            }
            streamLimit /= 2
        }
    }

    private static func agentStreamLimit(maximumBytes: Int) -> Int {
        min(1_400, max(0, (maximumBytes - 512) / 2))
    }

    private static func agentDirectoryRunnerSource(paths: [String], maximumBytes: Int) throws -> String {
        let encodedPaths = try JSONSerialization.data(withJSONObject: paths).base64EncodedString()
        return try boundedAgentRunnerSource("""
            import base64, json
            from khaos.runner_sdk import fs_list, process_exec, workspace_commit
            from khaos.ipc import IPCProtocolError

            PATHS = json.loads(base64.b64decode(\(String(reflecting: encodedPaths))))

            def run():
                listings = {}
                status = 0
                errors = {
                    "Kernel rejected fs.list: path_not_listable": "path_not_listable",
                    "Kernel rejected fs.list: directory_too_large": "directory_too_large",
                }
                for path in PATHS:
                    try:
                        listings[path] = fs_list(path)
                    except IPCProtocolError as error:
                        category = errors.get(str(error))
                        if category is None:
                            raise
                        listings[path] = {"error": category}
                        status = 1
                text = json.dumps(listings, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                if len(text.encode("utf-8")) > \(maximumBytes):
                    text = '{"error":"directory_list_too_large"}'
                    status = 1
                process_exec(("python3", "-I", "-B", "-c", "print(" + repr(text) + "); raise SystemExit(" + str(status) + ")"))
                workspace_commit()
                return 0
            """)
    }

    private static func boundedAgentRunnerSource(_ source: String) throws -> String {
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
            + "A directory read root authorizes its entire subtree, including descendant file contents. A file read root authorizes that file only.\n\n"
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

    private static func invokePluginKernel(
        _ request: KernelWorkspaceXPC.PluginLifecycleRequest,
        requestID: KernelWorkspaceXPC.RequestID = KernelWorkspaceXPC.newRequestID(),
        bookmark: Data? = nil
    ) throws -> String {
        guard request.needsBookmark == (bookmark != nil) else {
            throw LauncherError.operationRejected("invalid_plugin_operation")
        }
        guard let bundleID = Bundle.main.bundleIdentifier else {
            throw LauncherError.operationRejected("bundle_identity_unavailable")
        }
        let target = try connectKernel(bundleID: bundleID)
        let snapshotBrokerEndpoint = request.needsSnapshotBroker
            ? try KernelSnapshotBrokerBootstrapClient.endpoint() : nil
        let reply = try KernelWorkspaceClient.request(
            target,
            requestID: requestID,
            snapshotBrokerEndpoint: snapshotBrokerEndpoint
        ) { proxy, withReply in
            try KernelWorkspaceXPC.submit(
                proxy,
                requestID: requestID,
                request: request,
                bookmark: bookmark,
                withReply: withReply
            )
        }
        if let errorCode = reply.errorCode {
            throw LauncherError.operationRejected(safePluginErrorCode(errorCode))
        }
        guard let output = reply.output else {
            throw LauncherError.operationRejected("missing_kernel_result")
        }
        return output
    }

    private static func safePluginErrorCode(_ code: String) -> String {
        switch code {
        case "activation_outcome_uncertain", "activation_state_corrupt",
             "activation_state_unavailable", "approval_binding_mismatch",
             "approval_expired", "candidate_corrupt", "candidate_missing",
             "candidate_store_failed", "invalid_rollback_target", "invalid_time",
             "evaluation_workspace_changed",
             "manifest_rejected", "no_active_candidate", "plugin_lifecycle_failed",
             "plugin_source_rejected", "stale_approval", "store_unavailable",
             "plugin_input_too_large", "plugin_invocation_unsupported",
             "plugin_output_too_large", "plugin_state_corrupt",
             "plugin_state_outcome_uncertain", "plugin_state_too_large",
             "plugin_state_unavailable", "capability_denied":
            return code
        default:
            return safeWorkspaceErrorCode(code)
        }
    }

    private static func parseWorkspaceResult(_ output: String) throws -> WorkspaceResult {
        guard let data = output.data(using: .utf8),
              let result = try? JSONSerialization.jsonObject(with: data)
                as? [String: Any]
        else {
            throw LauncherError.operationRejected("result_not_json")
        }
        let baseFields: Set<String> = [
            "returncode", "stdout", "stderr", "added", "modified", "deleted",
        ]
        guard Set(result.keys) == baseFields
                || Set(result.keys) == baseFields.union(["plugin_state_sha256"]) else {
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
        let pluginStateSHA256: String?
        if let value = result["plugin_state_sha256"] {
            if value is NSNull {
                pluginStateSHA256 = nil
            } else if let digest = value as? String, isDigest(digest) {
                pluginStateSHA256 = digest
            } else {
                throw LauncherError.operationRejected("result_types_mismatch")
            }
        } else {
            pluginStateSHA256 = nil
        }
        return WorkspaceResult(
            returncode: returncode,
            stdout: stdout,
            stderr: stderr,
            added: added,
            modified: modified,
            deleted: deleted,
            pluginStateSHA256: pluginStateSHA256
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
        case KernelWorkspaceClientError.cancelledBeforeSubmission:
            return "cancelled_before_runner_submission"
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
        case let AgentHostClientError.invalidResponse(stage):
            writeAgentDiagnostic("host-response=invalid stage=\(stage.rawValue)")
            return "agent_host_invalid_response"
        case AgentHostProtocolError.invalidRequest:
            return "agent_host_request_invalid"
        case AgentHostProtocolError.invalidResponse:
            return "agent_host_protocol_invalid_response"
        case AgentHostProtocolError.frameTooLarge:
            return "agent_host_frame_too_large"
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
