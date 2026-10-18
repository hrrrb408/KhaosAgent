import Foundation

@main
enum AgentHostACContractProbe {
    static func main() throws {
        let strict = CommandLine.arguments.last == "A"
        let keys = AgentHostActionOutput.actionOutputKeys
        let shell: [String: Any] = [
            "type": "shell", "argv": ["python3", "-V"], "readScope": [], "writeScope": [],
            "pluginID": "", "candidateDigest": "", "generation": 0,
            "pluginInput": "", "evolutionGoal": "",
        ]
        func accepted(_ value: [String: Any]) -> Bool {
            do {
                let action = try AgentHostActionOutput.decodeModelOutput(
                    JSONSerialization.data(withJSONObject: value), as: AgentAction.self,
                    expectedKeys: keys
                )
                try AgentHostActionOutput.validateContext(
                    action, isToolResult: false, canContinue: false,
                    hasExplicitPluginOperation: false, failedCommand: nil
                )
                _ = try AgentHostActionOutput.encodeAction(action, activePlugin: nil)
                return true
            } catch { return false }
        }
        func require(_ value: Bool) {
            if !value { fatalError("A/C contract check failed") }
        }
        var full = shell
        full["text"] = ""
        require(accepted(full))
        require(accepted(shell) == !strict)
        var list = shell
        list["type"] = "list"; list["argv"] = [String](); list["readScope"] = ["tests"]
        require(accepted(list) == !strict)
        for key in ["readScope", "writeScope"] {
            var invalid = full; invalid.removeValue(forKey: key)
            require(!accepted(invalid))
        }
        for (key, value) in [("type", "unknown" as Any), ("extra", ""),
                             ("argv", 1), ("pluginID", "memory"), ("evolutionGoal", "expand")] {
            var invalid = full; invalid[key] = value
            require(!accepted(invalid))
        }
        var invalidText = shell; invalidText["type"] = "text"
        require(!accepted(invalidText))
        var invalidTypes = shell; invalidTypes["readScope"] = "tests"
        require(!accepted(invalidTypes))
        let denied = try AgentHostActionOutput.decodeModelOutput(
            JSONSerialization.data(withJSONObject: full), as: AgentAction.self, expectedKeys: keys
        )
        do {
            try AgentHostActionOutput.validateContext(
                denied, isToolResult: true, canContinue: false,
                hasExplicitPluginOperation: false, failedCommand: nil
            )
            fatalError("denied continuation accepted a tool")
        } catch is AgentActionRejection {}
        require(AgentHostActionOutput.correction(
            for: "invalid_model_output_shape", alreadyUsed: true
        ) == nil)
        // One separately attributable diagnostic sample, with no provider or Runner.
        AgentHostActionOutput.diagnoseActionProgress(.responseReceived, attempt: .initial)
        do {
            let action = try AgentHostActionOutput.decodeModelOutput(
                JSONSerialization.data(withJSONObject: shell), as: AgentAction.self,
                expectedKeys: keys, attempt: .initial
            )
            _ = try AgentHostActionOutput.encodeAction(action, activePlugin: nil)
            AgentHostActionOutput.diagnoseActionProgress(.responseAccepted, attempt: .initial)
        } catch let AgentHostJSONInspectionError.invalidShape(shape) {
            AgentHostActionOutput.diagnoseModelFailure(
                attempt: .initial, stage: .actionShape,
                errorCode: "invalid_model_output_shape", shape: shape
            )
        }
        print("ac-contract=passed group=\(strict ? "A" : "C")")
    }
}
