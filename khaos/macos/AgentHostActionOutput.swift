import Foundation

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
    static func diagnose(
        _ rejection: AgentActionRejection, correctionUsed: Bool, terminal: Bool = true
    ) {
        fputs(diagnostic(rejection, correctionUsed: correctionUsed, terminal: terminal) + "\n", stderr)
    }

    static func diagnostic(
        _ rejection: AgentActionRejection, correctionUsed: Bool, terminal: Bool = true
    ) -> String {
        "agent-host-action=rejected category=\(rejection.rawValue) attempt=\(correctionUsed ? "correction" : "initial") terminal=\(terminal)"
    }

    static func failureCode(_ rejection: AgentActionRejection, correctionUsed: Bool) -> String {
        "invalid_agent_action_\(rejection.rawValue)\(correctionUsed ? "_after_correction" : "")"
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
}
