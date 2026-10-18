import Foundation
import OSLog

struct AgentAction: Decodable {
    let type: String
    let text: String
    let argv: [String]
    let readScope: [String]
    let writeScope: [String]
    let pluginID: String
    let candidateDigest: String
    let generation: Int
    let pluginInput: String
    let evolutionGoal: String
}

// Untrusted Host diagnostics only. No model text, paths, argv, or error payloads.
enum AgentActionRejection: String, Error, CaseIterable {
    case modelJSON = "model_json"
    case modelShape = "model_shape"
    case modelFieldTypes = "model_field_types"
    case unsupportedType = "unsupported_type"
    case postToolAction = "post_tool_action"
    case explicitPluginOperation = "explicit_plugin_operation"
    case repeatedFailedCommand = "repeated_failed_command"
    case unusedFields = "unused_fields"
    case pluginFields = "plugin_fields"
    case pluginInterface = "plugin_interface"
    case evolutionFields = "evolution_fields"
    case workspaceFields = "workspace_fields"
    case wireContract = "wire_contract"

    static func modelOutput(_ code: String) -> Self? {
        switch code {
        case "invalid_model_output_json": return .modelJSON
        case "invalid_model_output_shape": return .modelShape
        case "invalid_model_output_field_types": return .modelFieldTypes
        default: return nil
        }
    }
}

enum AgentHostModelAttempt: String {
    case initial
    case correction

    var failureEvent: String {
        switch self {
        case .initial: return "initial_response_failed"
        case .correction: return "correction_response_failed"
        }
    }
}

enum AgentHostActionProgressEvent: String, CaseIterable {
    case responseReceived = "action_response_received"
    case textNormalized = "action_text_normalized"
    case responseAccepted = "action_response_accepted"
}

enum AgentHostModelDiagnosticStage: String {
    case providerRequest = "provider_request"
    case providerResponse = "provider_response"
    case modelContent = "model_content"
    case actionJSON = "action_json"
    case actionShape = "action_shape"
    case actionFieldTypes = "action_field_types"
    case actionValidation = "agent_action_validation"
    case harnessState = "harness_state"
    case context
}

struct AgentHostJSONShapeDiagnostic: Equatable {
    let rootIsObject: Bool
    let expectedKeyCount: Int
    let actualKeyCount: Int
    let missingKeys: [String]
    let unexpectedKeyCount: Int
}

enum AgentHostJSONInspectionError: Error {
    case invalidJSON
    case invalidShape(AgentHostJSONShapeDiagnostic)
    case invalidFieldTypes
    case contentTooLarge
}

// Host sequencing only; the Launcher independently owns authority and budgets.
struct AgentHostTaskProgress {
    private(set) var awaitingToolResult = false
    private(set) var toolCalls = 0

    mutating func beginTask() -> Bool {
        guard !awaitingToolResult else { return false }
        toolCalls = 0
        return true
    }

    mutating func consumeToolResult() -> Bool {
        guard awaitingToolResult else { return false }
        awaitingToolResult = false
        return true
    }

    mutating func proposeTool() -> Bool {
        guard !awaitingToolResult,
              toolCalls < AgentHostProtocol.maximumToolCallsPerTask else { return false }
        toolCalls += 1
        awaitingToolResult = true
        return true
    }
}

enum AgentHostActionOutput {
    static let actionOutputKeys = [
        "type", "text", "argv", "readScope", "writeScope", "pluginID",
        "candidateDigest", "generation", "pluginInput", "evolutionGoal",
    ]
    static let maximumModelOutputBytes = 48 * 1024
    private static let modelDiagnosticsEnvironmentKey = "KHAOS_AGENT_ACTION_DIAGNOSTICS"
    private static let maximumModelDiagnosticBytes = 512
    private static let modelDiagnosticLogger = Logger(
        subsystem: "org.khaos.Seed.AgentHost",
        category: "action-diagnostics"
    )

    static func diagnose(
        _ rejection: AgentActionRejection, correctionUsed: Bool, terminal: Bool = true
    ) {
        fputs(diagnostic(rejection, correctionUsed: correctionUsed, terminal: terminal) + "\n", stderr)
    }

    static func inspectJSONObject(
        _ data: Data,
        expectedKeys: [String]
    ) throws -> (object: [String: Any], normalized: Bool) {
        let value: Any
        do {
            value = try JSONSerialization.jsonObject(with: data, options: [.fragmentsAllowed])
        } catch {
            throw AgentHostJSONInspectionError.invalidJSON
        }
        guard let object = value as? [String: Any] else {
            throw AgentHostJSONInspectionError.invalidShape(AgentHostJSONShapeDiagnostic(
                rootIsObject: false,
                expectedKeyCount: expectedKeys.count,
                actualKeyCount: 0,
                missingKeys: [],
                unexpectedKeyCount: 0
            ))
        }
        let expected = Set(expectedKeys)
        let actual = Set(object.keys)
        if expected == actual {
            return (object, false)
        }
        // Only list/shell ignore text; scopes and every other field stay explicit.
        if expected == Set(actionOutputKeys),
           actual == expected.subtracting(["text"]),
           let type = object["type"] as? String,
           (type == "list" || type == "shell") {
            var normalized = object
            normalized["text"] = ""
            return (normalized, true)
        }
        throw AgentHostJSONInspectionError.invalidShape(AgentHostJSONShapeDiagnostic(
            rootIsObject: true,
            expectedKeyCount: expectedKeys.count,
            actualKeyCount: object.count,
            missingKeys: expectedKeys.filter { !actual.contains($0) },
            unexpectedKeyCount: actual.subtracting(expected).count
        ))
    }

    static func validateModelContentSize(_ data: Data) throws {
        guard data.count <= maximumModelOutputBytes else {
            throw AgentHostJSONInspectionError.contentTooLarge
        }
    }

    static func decodeModelOutput<Value: Decodable>(
        _ data: Data,
        as type: Value.Type,
        expectedKeys: [String],
        attempt: AgentHostModelAttempt? = nil
    ) throws -> Value {
        try validateModelContentSize(data)
        let inspection = try inspectJSONObject(data, expectedKeys: expectedKeys)
        let decodeData: Data
        if inspection.normalized {
            if let attempt {
                diagnoseActionProgress(.textNormalized, attempt: attempt)
            }
            do {
                decodeData = try JSONSerialization.data(
                    withJSONObject: inspection.object, options: [.sortedKeys]
                )
            } catch {
                throw AgentHostJSONInspectionError.invalidJSON
            }
        } else {
            decodeData = data
        }
        try validateModelContentSize(decodeData)
        do {
            return try JSONDecoder().decode(type, from: decodeData)
        } catch {
            throw AgentHostJSONInspectionError.invalidFieldTypes
        }
    }

    static func modelDiagnosticsEnabled(
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> Bool {
        environment[modelDiagnosticsEnvironmentKey] == "1"
    }

    static func modelFailureDiagnostic(
        attempt: AgentHostModelAttempt,
        stage: AgentHostModelDiagnosticStage,
        errorCode: String,
        shape: AgentHostJSONShapeDiagnostic? = nil,
        enabled: Bool
    ) -> String? {
        guard enabled,
              safeDiagnosticCode(errorCode),
              shape?.missingKeys.allSatisfy({ actionOutputKeys.contains($0) }) ?? true else {
            return nil
        }
        var line = "agent-host-model-diagnostic event=\(attempt.failureEvent) attempt=\(attempt.rawValue) stage=\(stage.rawValue) error=\(errorCode)"
        if let shape {
            let missing = shape.missingKeys.isEmpty ? "none" : shape.missingKeys.joined(separator: ",")
            line += " root_is_object=\(shape.rootIsObject) expected_key_count=\(shape.expectedKeyCount) actual_key_count=\(shape.actualKeyCount) missing_keys=\(missing) unexpected_key_count=\(shape.unexpectedKeyCount)"
        }
        guard line.utf8.count <= maximumModelDiagnosticBytes else { return nil }
        return line
    }

    static func correctionRequestedDiagnostic(
        cause: AgentActionRejection,
        enabled: Bool
    ) -> String? {
        guard enabled else { return nil }
        return "agent-host-model-diagnostic event=correction_requested cause=\(cause.rawValue)"
    }

    static func correctionAcceptedDiagnostic(enabled: Bool) -> String? {
        guard enabled else { return nil }
        return "agent-host-model-diagnostic event=correction_response_accepted attempt=correction"
    }

    static func actionProgressDiagnostic(
        event: AgentHostActionProgressEvent,
        attempt: AgentHostModelAttempt,
        enabled: Bool
    ) -> String? {
        guard enabled else { return nil }
        return "agent-host-model-diagnostic event=\(event.rawValue) attempt=\(attempt.rawValue)"
    }

    static func diagnoseActionProgress(
        _ event: AgentHostActionProgressEvent,
        attempt: AgentHostModelAttempt
    ) {
        guard modelDiagnosticsEnabled() else { return }
        emitModelDiagnostic(actionProgressDiagnostic(event: event, attempt: attempt, enabled: true))
    }

    static func harnessStateFailureDiagnostic(
        errorCode: String,
        enabled: Bool
    ) -> String? {
        guard enabled, safeDiagnosticCode(errorCode) else { return nil }
        let line = "agent-host-model-diagnostic event=harness_state_rejected attempt=none stage=harness_state error=\(errorCode)"
        return line.utf8.count <= maximumModelDiagnosticBytes ? line : nil
    }

    static func diagnoseModelFailure(
        attempt: AgentHostModelAttempt,
        stage: AgentHostModelDiagnosticStage,
        errorCode: String,
        shape: AgentHostJSONShapeDiagnostic? = nil
    ) {
        guard modelDiagnosticsEnabled() else { return }
        emitModelDiagnostic(modelFailureDiagnostic(
            attempt: attempt,
            stage: stage,
            errorCode: errorCode,
            shape: shape,
            enabled: true
        ))
    }

    static func diagnoseCorrectionRequested(cause: AgentActionRejection) {
        guard modelDiagnosticsEnabled() else { return }
        emitModelDiagnostic(correctionRequestedDiagnostic(cause: cause, enabled: true))
    }

    static func diagnoseCorrectionAccepted() {
        guard modelDiagnosticsEnabled() else { return }
        emitModelDiagnostic(correctionAcceptedDiagnostic(enabled: true))
    }

    static func diagnoseHarnessStateFailure(errorCode: String) {
        guard modelDiagnosticsEnabled() else { return }
        emitModelDiagnostic(harnessStateFailureDiagnostic(errorCode: errorCode, enabled: true))
    }

    static func diagnostic(
        _ rejection: AgentActionRejection, correctionUsed: Bool, terminal: Bool = true
    ) -> String {
        "agent-host-action=rejected category=\(rejection.rawValue) attempt=\(correctionUsed ? "correction" : "initial") terminal=\(terminal)"
    }

    static func failureCode(_ rejection: AgentActionRejection, correctionUsed: Bool) -> String {
        "invalid_agent_action_\(rejection.rawValue)\(correctionUsed ? "_after_correction" : "")"
    }

    static func toolStatus(ok: Bool, canContinue: Bool) -> String {
        if ok {
            return "The trusted Launcher reports that the Runner returned exit code zero."
        }
        if canContinue {
            return "The trusted Launcher reports that the Runner returned a nonzero exit code. Its exact numeric returncode is in the bounded result JSON below."
        }
        return "The trusted Launcher reports an unsuccessful operation or a stopped task. This may be refusal, cancellation, or execution failure. Do not infer that a command ran or invent a returncode; use only an explicit returncode in the bounded result below."
    }

    static func validateContext(
        _ action: AgentAction,
        isToolResult: Bool,
        canContinue: Bool,
        hasExplicitPluginOperation: Bool,
        failedCommand: [String]?
    ) throws {
        guard !isToolResult || AgentHostProtocol.actionTypeAllowedAfterToolResult(
            action.type, canContinue: canContinue
        ) else { throw AgentActionRejection.postToolAction }
        guard action.type != "evolution" || !hasExplicitPluginOperation else {
            throw AgentActionRejection.explicitPluginOperation
        }
        guard action.type != "shell" || !AgentHostProtocol.repeatsFailedCommand(
            action.argv, failedCommand: failedCommand
        ) else { throw AgentActionRejection.repeatedFailedCommand }
    }

    private static func encodeReply(_ reply: AgentHostReply) throws -> Data {
        do {
            return try AgentHostProtocol.encodeReply(reply)
        } catch AgentHostProtocolError.invalidResponse {
            throw AgentActionRejection.wireContract
        } catch AgentHostProtocolError.frameTooLarge {
            throw AgentActionRejection.wireContract
        }
    }

    static func encodeAction(
        _ generated: AgentAction,
        activePlugin: AgentHostPluginMetadata?
    ) throws -> Data {
        guard generated.type == "text" || generated.type == "shell" || generated.type == "list"
                || generated.type == "plugin" || generated.type == "evolution" else {
            throw AgentActionRejection.unsupportedType
        }
        if generated.type == "text" {
            guard generated.argv.isEmpty,
                  generated.readScope.isEmpty,
                  generated.writeScope.isEmpty,
                  generated.pluginID.isEmpty,
                  generated.candidateDigest.isEmpty,
                  generated.pluginInput.isEmpty,
                  generated.evolutionGoal.isEmpty,
                  generated.generation == 0 else {
                throw AgentActionRejection.unusedFields
            }
            return try encodeReply(.text(generated.text))
        }
        if generated.type == "plugin" {
            let input = generated.pluginInput.isEmpty
                ? nil
                : AgentHostProtocol.canonicalPluginInput(generated.pluginInput)
            guard generated.text.isEmpty,
                  generated.argv.isEmpty,
                  generated.readScope.isEmpty,
                  generated.writeScope.isEmpty,
                  generated.generation >= 0,
                  generated.evolutionGoal.isEmpty,
                  generated.pluginInput.isEmpty || input != nil else {
                throw AgentActionRejection.pluginFields
            }
            if let interface = activePlugin?.agentInterface {
                guard let input,
                      AgentHostProtocol.pluginInputMatchesInterface(
                        input,
                        interface: interface
                      ) else {
                    throw AgentActionRejection.pluginInterface
                }
            }
            return try encodeReply(.plugin(AgentPluginBinding(
                pluginID: generated.pluginID,
                candidateDigest: generated.candidateDigest,
                generation: generated.generation,
                inputJSON: input
            )))
        }
        if generated.type == "evolution" {
            guard generated.text.isEmpty,
                  generated.argv.isEmpty,
                  generated.readScope.isEmpty,
                  generated.writeScope.isEmpty,
                  generated.pluginID == "memory",
                  generated.candidateDigest.range(
                    of: #"^[0-9a-f]{64}$"#,
                    options: .regularExpression
                  ) != nil,
                  generated.generation >= 0,
                  generated.pluginInput.isEmpty,
                  !generated.evolutionGoal.isEmpty,
                  generated.evolutionGoal.utf8.count
                    <= AgentHostProtocol.maximumEvolutionGoalBytes else {
                throw AgentActionRejection.evolutionFields
            }
            let proposal = AgentEvolutionProposal(
                pluginID: generated.pluginID,
                candidateDigest: generated.candidateDigest,
                generation: generated.generation,
                goal: generated.evolutionGoal
            )
            return try encodeReply(.evolution(proposal))
        }
        guard generated.text.isEmpty,
              generated.pluginID.isEmpty,
              generated.candidateDigest.isEmpty,
              generated.pluginInput.isEmpty,
              generated.evolutionGoal.isEmpty,
              generated.generation == 0,
              (generated.type == "list"
                ? generated.argv.isEmpty && generated.writeScope.isEmpty && !generated.readScope.isEmpty
                : !generated.argv.isEmpty),
              generated.argv.count <= AgentHostProtocol.maximumArguments,
              generated.readScope.count + generated.writeScope.count
                <= AgentHostProtocol.maximumScopePaths else {
            throw AgentActionRejection.workspaceFields
        }
        let proposal = AgentShellProposal(
            argv: generated.argv,
            readScope: generated.readScope,
            writeScope: generated.writeScope
        )
        return try encodeReply(
            generated.type == "list" ? .list(proposal) : .shell(proposal)
        )
    }

    static func correction(
        for errorCode: String,
        alreadyUsed: Bool
    ) -> String? {
        guard !alreadyUsed,
              AgentActionRejection.modelOutput(errorCode) != nil else {
            return nil
        }
        return """
            Host validation feedback: The previous model response was not submitted or executed because it was not one valid action JSON object. Re-read the original user request and the latest Trusted Launcher metadata already in context. Return exactly one raw JSON object with exactly these keys and JSON types: {"type":"text","text":"answer or empty string","argv":[],"readScope":[],"writeScope":[],"pluginID":"","candidateDigest":"","generation":0,"pluginInput":"","evolutionGoal":""}. Do not omit, add, rename, or change the type of a field. Leave every unused field at its documented empty value. Do not add Markdown, commentary, source, Manifest, scope, capability, approval, secret, or lifecycle data. Nothing has run; do not claim execution.
            """
    }

    private static func emitModelDiagnostic(_ line: String?) {
        guard let line, line.utf8.count <= maximumModelDiagnosticBytes else { return }
        // This fixed-format line is already redacted and bounded before public logging.
        modelDiagnosticLogger.info("\(line, privacy: .public)")
    }

    private static func safeDiagnosticCode(_ value: String) -> Bool {
        value.utf8.count <= 64 && value.utf8.allSatisfy {
            (97...122).contains($0) || (48...57).contains($0) || $0 == 95 || $0 == 45
        }
    }
}
