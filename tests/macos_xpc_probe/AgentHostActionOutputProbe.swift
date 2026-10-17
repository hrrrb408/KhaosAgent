import Foundation

private func require(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else {
        fputs("AgentHostActionOutputProbe: \(message)\n", stderr)
        exit(EXIT_FAILURE)
    }
}

@main
enum AgentHostActionOutputProbe {
    static func main() throws {
        try modelOutputDecoding()
        for error in [
            "invalid_model_output_json",
            "invalid_model_output_shape",
            "invalid_model_output_field_types",
        ] {
            guard let correction = AgentHostActionOutput.correction(
                for: error,
                alreadyUsed: false
            ) else {
                fatalError("\(error) did not receive the bounded correction")
            }
            require(
                correction.contains("not submitted or executed")
                    && correction.contains("exactly these keys and JSON types")
                    && correction.contains("Nothing has run"),
                "correction omitted the rejection and exact output contract"
            )
            require(
                AgentHostActionOutput.correction(
                    for: error,
                    alreadyUsed: true
                ) == nil,
                "a second correction was allowed"
            )
        }

        for error in [
            "incomplete_model_response",
            "model_provider_auth_failed",
            "invalid_model_output",
            "model_provider_failed",
        ] {
            require(
                AgentHostActionOutput.correction(
                    for: error,
                    alreadyUsed: false
                ) == nil,
                "non-format failure \(error) was retried"
            )
        }

        try actionValidation()
        try postToolTransitions()
        taskSequencing()
        for rejection in AgentActionRejection.allCases {
            for corrected in [false, true] {
                let code = AgentHostActionOutput.failureCode(rejection, correctionUsed: corrected)
                let frame = try AgentHostProtocol.encodeReply(.failure(code))
                guard case let .failure(decoded)? = AgentHostProtocol.decodeReply(frame) else {
                    fatalError("rejection code violated existing protocol")
                }
                require(decoded == code && code.contains(rejection.rawValue), "lost category")
                require(code.hasSuffix("_after_correction") == corrected, "lost correction status")
            }
            let line = AgentHostActionOutput.diagnostic(rejection, correctionUsed: true)
            require(
                line == "agent-host-action=rejected category=\(rejection.rawValue) attempt=correction terminal=true",
                "diagnostic contains unexpected payload"
            )
        }
        print("agent-host-action-output=passed")
    }

    private static func modelOutputDecoding() throws {
        let expectedKeys = [
            "type", "text", "argv", "readScope", "writeScope", "pluginID",
            "candidateDigest", "generation", "pluginInput", "evolutionGoal",
        ]
        let keys = AgentHostActionOutput.actionOutputKeys
        require(keys == expectedKeys, "the ten-field Action Contract changed")
        let value: [String: Any] = [
            "type": "text", "text": "ok", "argv": [], "readScope": [],
            "writeScope": [], "pluginID": "", "candidateDigest": "",
            "generation": 0, "pluginInput": "", "evolutionGoal": "",
        ]
        let valid = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        let action = try AgentHostActionOutput.decodeModelOutput(
            valid, as: AgentAction.self, expectedKeys: keys
        )
        require(action.type == "text", "valid ten-field action was rejected")
        try AgentHostActionOutput.validateModelContentSize(
            Data(repeating: 0, count: AgentHostActionOutput.maximumModelOutputBytes)
        )
        let oversized = inspectionError(
            Data(repeating: 0, count: AgentHostActionOutput.maximumModelOutputBytes + 1),
            expectedKeys: keys
        )
        guard case .contentTooLarge = oversized else {
            fatalError("oversized model content was not rejected before parsing")
        }

        let malformed = inspectionError(Data("{".utf8), expectedKeys: keys)
        guard case .invalidJSON = malformed else {
            fatalError("malformed response JSON was classified as shape")
        }
        let scalar = inspectionError(Data("null".utf8), expectedKeys: keys)
        guard case let .invalidShape(nonObject) = scalar else {
            fatalError("valid non-object JSON was classified as a parse failure")
        }
        require(
            !nonObject.rootIsObject && nonObject.expectedKeyCount == 10
                && nonObject.actualKeyCount == 0,
            "non-object shape summary is inaccurate"
        )

        var missingValue = value
        missingValue.removeValue(forKey: "evolutionGoal")
        let missingData = try JSONSerialization.data(withJSONObject: missingValue)
        let missingError = inspectionError(missingData, expectedKeys: keys)
        guard case let .invalidShape(missing) = missingError else {
            fatalError("missing field was not rejected as a shape failure")
        }
        require(
            missing.rootIsObject && missing.expectedKeyCount == 10
                && missing.actualKeyCount == 9
                && missing.missingKeys == ["evolutionGoal"]
                && missing.unexpectedKeyCount == 0,
            "missing field summary is inaccurate"
        )

        var extraValue = value
        extraValue["private_extra_canary"] = "PRIVATE_OUTPUT_CANARY"
        let extraData = try JSONSerialization.data(withJSONObject: extraValue)
        let extraError = inspectionError(extraData, expectedKeys: keys)
        guard case let .invalidShape(extra) = extraError else {
            fatalError("extra field was not rejected as a shape failure")
        }
        require(
            extra.actualKeyCount == 11 && extra.missingKeys.isEmpty
                && extra.unexpectedKeyCount == 1,
            "extra field summary is inaccurate"
        )

        var wrongTypeValue = value
        wrongTypeValue["argv"] = "not-an-array"
        let wrongTypeData = try JSONSerialization.data(withJSONObject: wrongTypeValue)
        let typeError = inspectionError(wrongTypeData, expectedKeys: keys)
        guard case .invalidFieldTypes = typeError else {
            fatalError("type mismatch was not classified as a field-type failure")
        }

        require(
            !AgentHostActionOutput.modelDiagnosticsEnabled(environment: [:])
                && AgentHostActionOutput.modelDiagnosticsEnabled(
                    environment: ["KHAOS_AGENT_ACTION_DIAGNOSTICS": "1"]
                ),
            "structured diagnostics are not explicitly opt-in"
        )
        require(
            AgentHostActionOutput.modelFailureDiagnostic(
                attempt: .initial, stage: .actionShape,
                errorCode: "invalid_model_output_shape", shape: extra, enabled: false
            ) == nil,
            "disabled diagnostics produced an event"
        )
        let extraLine = AgentHostActionOutput.modelFailureDiagnostic(
            attempt: .initial, stage: .actionShape,
            errorCode: "invalid_model_output_shape", shape: extra, enabled: true
        )!
        require(
            extraLine.contains("event=initial_response_failed")
                && extraLine.contains("expected_key_count=10")
                && extraLine.contains("actual_key_count=11")
                && extraLine.contains("unexpected_key_count=1")
                && !extraLine.contains("private_extra_canary")
                && !extraLine.contains("PRIVATE_OUTPUT_CANARY")
                && extraLine.utf8.count <= 512,
            "shape diagnostics exposed output data or exceeded their bound"
        )
        let correctionLine = AgentHostActionOutput.modelFailureDiagnostic(
            attempt: .correction, stage: .actionFieldTypes,
            errorCode: "invalid_model_output_field_types", enabled: true
        )!
        require(
            correctionLine.contains("event=correction_response_failed")
                && correctionLine.contains("attempt=correction")
                && !correctionLine.contains("PRIVATE_OUTPUT_CANARY"),
            "correction type failure was not attributed safely"
        )
        require(
            AgentHostActionOutput.correctionRequestedDiagnostic(
                cause: .modelShape, enabled: true
            )?.contains("event=correction_requested cause=model_shape") == true
                && AgentHostActionOutput.correctionAcceptedDiagnostic(enabled: true)?
                    .contains("event=correction_response_accepted attempt=correction") == true,
            "correction lifecycle diagnostics are incomplete"
        )
        let harnessLine = AgentHostActionOutput.harnessStateFailureDiagnostic(
            errorCode: "tool_result_without_pending_proposal", enabled: true
        )
        require(
            harnessLine?.contains("event=harness_state_rejected attempt=none stage=harness_state") == true
                && (harnessLine?.utf8.count ?? 513) <= 512
                && AgentHostActionOutput.harnessStateFailureDiagnostic(
                    errorCode: "private value with spaces", enabled: true
                ) == nil,
            "harness-state diagnostics were not classified or bounded"
        )
        AgentHostActionOutput.diagnoseModelFailure(
            attempt: .initial,
            stage: .actionShape,
            errorCode: "invalid_model_output_shape",
            shape: extra
        )
    }

    private static func inspectionError(
        _ data: Data,
        expectedKeys: [String]
    ) -> AgentHostJSONInspectionError {
        do {
            _ = try AgentHostActionOutput.decodeModelOutput(
                data, as: AgentAction.self, expectedKeys: expectedKeys
            )
            fatalError("invalid model output was accepted")
        } catch let error as AgentHostJSONInspectionError {
            return error
        } catch {
            fatalError("unexpected model output failure: \(error)")
        }
    }

    private static func action(
        _ type: String = "text", text: String = "", argv: [String] = [],
        read: [String] = [], write: [String] = [], pluginID: String = "",
        digest: String = "", generation: Int = 0, input: String = "", goal: String = ""
    ) -> AgentAction {
        AgentAction(type: type, text: text, argv: argv, readScope: read,
                    writeScope: write, pluginID: pluginID, candidateDigest: digest,
                    generation: generation, pluginInput: input, evolutionGoal: goal)
    }

    private static func rejects(
        _ expected: AgentActionRejection, _ operation: () throws -> Void
    ) {
        do {
            try operation()
            fatalError("rejected action was encoded: \(expected)")
        } catch let actual as AgentActionRejection {
            require(actual == expected, "wrong rejection: \(actual), expected \(expected)")
        } catch {
            fatalError("unexpected error type")
        }
    }

    private static func actionValidation() throws {
        let cases: [(AgentAction, AgentActionRejection)] = [
            (action("approve"), .unsupportedType),
            (action(text: "answer", argv: ["unapproved-command"]), .unusedFields),
            (action("plugin", argv: ["unapproved-command"]), .pluginFields),
            (action("evolution", pluginID: "other"), .evolutionFields),
            (action("shell"), .workspaceFields),
            (action("list", argv: ["unapproved-command"], read: ["tests"]), .workspaceFields),
            (action("list"), .workspaceFields),
            (action("list", read: ["tests", "tests"]), .wireContract),
            (action("shell", argv: ["command\nsecret"]), .wireContract),
            (action("shell", argv: [String(repeating: "x", count: 4097)]), .wireContract),
            (action("list", read: [String(repeating: "x", count: 129)]), .wireContract),
        ]
        for (value, reason) in cases {
            rejects(reason) { _ = try AgentHostActionOutput.encodeAction(value, activePlugin: nil) }
        }
        let active = AgentHostPluginMetadata(
            pluginID: "probe", candidateDigest: String(repeating: "a", count: 64),
            generation: 1,
            agentInterface: AgentPluginInterface(
                summary: "untrusted summary",
                operations: [AgentPluginOperation(name: "publish", fields: ["message"])]
            )
        )
        rejects(.pluginInterface) {
            _ = try AgentHostActionOutput.encodeAction(
                action("plugin", pluginID: active.pluginID,
                       digest: active.candidateDigest, generation: 1), activePlugin: active
            )
        }
        for valid in [
            action(text: "done"), action("shell", argv: ["python3", "-V"]),
            action("list", read: ["tests"]),
            action("plugin", pluginID: active.pluginID, digest: active.candidateDigest,
                   generation: 1, input: "{\"operation\":\"publish\",\"message\":\"hello\"}"),
            action("evolution", pluginID: "memory", digest: active.candidateDigest,
                   generation: 1, goal: "Improve bounded recall"),
        ] {
            let encoded = try AgentHostActionOutput.encodeAction(valid, activePlugin: nil)
            require(AgentHostProtocol.decodeReply(encoded) != nil, "valid action did not round trip")
        }
    }

    private static func postToolTransitions() throws {
        require(AgentHostActionOutput.toolStatus(ok: true, canContinue: true).contains("exit code zero"),
                "success observation lost")
        require(AgentHostActionOutput.toolStatus(ok: false, canContinue: true).contains("nonzero exit code"),
                "failed execution observation lost")
        let stopped = AgentHostActionOutput.toolStatus(ok: false, canContinue: false)
        require(stopped.contains("Do not infer that a command ran") && !stopped.contains("returned a nonzero"),
                "refusal or cancellation fabricated an executed command")
        // Both success and exit-1 may continue; refusal/cancel/budget stop use false.
        for canContinue in [true, false] {
            for type in ["text", "list", "shell", "plugin", "evolution"] {
                let allowed = type == "text" || (canContinue && ["list", "shell"].contains(type))
                let validate = {
                    try AgentHostActionOutput.validateContext(
                        action(type), isToolResult: true, canContinue: canContinue,
                        hasExplicitPluginOperation: false, failedCommand: nil
                    )
                }
                if allowed { try validate() } else { rejects(.postToolAction, validate) }
            }
        }
        rejects(.explicitPluginOperation) {
            try AgentHostActionOutput.validateContext(
                action("evolution"), isToolResult: false, canContinue: false,
                hasExplicitPluginOperation: true, failedCommand: nil
            )
        }
        rejects(.repeatedFailedCommand) {
            try AgentHostActionOutput.validateContext(
                action("shell", argv: ["python3", "test.py"]),
                isToolResult: true, canContinue: true,
                hasExplicitPluginOperation: false, failedCommand: ["python3", "test.py"]
            )
        }
        // An approved write result clears the existing failed-command marker in Host.
        try AgentHostActionOutput.validateContext(
            action("shell", argv: ["python3", "test.py"]),
            isToolResult: true, canContinue: true,
            hasExplicitPluginOperation: false, failedCommand: nil
        )
    }


    private static func taskSequencing() {
        var task = AgentHostTaskProgress()
        require(!task.consumeToolResult(), "result accepted without proposal")
        require(task.beginTask(), "initial user request rejected")
        for call in 1...AgentHostProtocol.maximumToolCallsPerTask {
            require(task.proposeTool(), "valid proposal rejected")
            require(task.toolCalls == call && task.awaitingToolResult, "proposal not pending")
            require(!task.beginTask(), "new user task displaced pending result")
            require(!task.proposeTool(), "second proposal replaced pending result")
            require(task.toolCalls == call, "rejected proposal consumed a call")
            require(task.consumeToolResult(), "pending result rejected")
            require(!task.consumeToolResult(), "same result consumed twice without a new proposal")
        }
        require(!task.proposeTool() && !task.awaitingToolResult, "call budget exceeded")
        require(task.beginTask() && task.toolCalls == 0, "new task did not reset accounting")
        require(!task.consumeToolResult(), "old result reused in a new task")
    }

}
