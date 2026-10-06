import Foundation
import Darwin

private func require(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else {
        fputs("AgentHostProtocolProbe: \(message)\n", stderr)
        exit(EXIT_FAILURE)
    }
}

private func frame(_ object: [String: Any]) -> Data {
    (try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])) ?? Data()
}

private func isNil<T>(_ value: T?) -> Bool {
    if case nil = value { return true }
    return false
}

@main
enum AgentHostProtocolProbe {
    static func main() throws {
        let active = AgentPluginBinding(
            pluginID: "seed-writer",
            candidateDigest: String(repeating: "a", count: 64),
            generation: 7
        )
        let activeInput = try AgentHostProtocol.userTurn(
            "write the approved output",
            activePlugin: active
        )
        guard let decodedInput = AgentHostProtocol.decodeInput(activeInput) else {
            fatalError("valid user turn was rejected")
        }
        require(
            AgentHostProtocol.activePlugin(in: decodedInput) == active,
            "active binding did not survive the Launcher-to-Host frame"
        )
        let inputObject = try JSONSerialization.jsonObject(with: activeInput) as! [String: Any]
        let activeObject = inputObject["active_plugin"] as! [String: Any]
        require(
            Set(activeObject.keys) == ["plugin_id", "candidate_digest", "generation"],
            "Host received authority beyond the minimal active binding"
        )

        var forgedAvailability = inputObject
        var forgedAvailabilityFields = activeObject
        forgedAvailabilityFields["read_scope"] = ["private.txt"]
        forgedAvailability["active_plugin"] = forgedAvailabilityFields
        require(
            isNil(AgentHostProtocol.decodeInput(frame(forgedAvailability))),
            "Host availability accepted a supplied scope"
        )

        let proposalFrame = try AgentHostProtocol.encodeReply(.plugin(active))
        guard case let .plugin(proposal)? = AgentHostProtocol.decodeReply(proposalFrame) else {
            fatalError("valid Plugin proposal was rejected")
        }
        require(
            AgentHostProtocol.proposalMatchesActive(proposal, active: active),
            "matching Plugin proposal did not bind to fresh state"
        )

        let forgedDigest = AgentPluginBinding(
            pluginID: active.pluginID,
            candidateDigest: String(repeating: "b", count: 64),
            generation: active.generation
        )
        require(
            !AgentHostProtocol.proposalMatchesActive(forgedDigest, active: active),
            "forged Candidate digest matched fresh active state"
        )
        let forgedGeneration = AgentPluginBinding(
            pluginID: active.pluginID,
            candidateDigest: active.candidateDigest,
            generation: active.generation + 1
        )
        require(
            !AgentHostProtocol.proposalMatchesActive(forgedGeneration, active: active),
            "forged generation matched fresh active state"
        )
        let replacement = AgentPluginBinding(
            pluginID: "plugin-b",
            candidateDigest: String(repeating: "c", count: 64),
            generation: active.generation + 1
        )
        require(
            !AgentHostProtocol.proposalMatchesActive(proposal, active: replacement),
            "proposal for the replaced active Candidate was not stale"
        )

        let forbidden = [
            "runner_source": "print('injected')",
            "manifest": ["read": ["private.txt"]],
            "read_scope": ["private.txt"],
            "write_scope": ["private.txt"],
            "capability": "process.exec",
            "approval": true,
        ] as [String: Any]
        for (key, value) in forbidden {
            var injected: [String: Any] = [
                "version": AgentHostProtocol.version,
                "type": "plugin",
                "plugin_id": active.pluginID,
                "candidate_digest": active.candidateDigest,
                "generation": active.generation,
            ]
            injected[key] = value
            require(
                isNil(AgentHostProtocol.decodeReply(frame(injected))),
                "Plugin proposal accepted forbidden field \(key)"
            )
        }

        let lifecycleMutation = frame([
            "version": AgentHostProtocol.version,
            "type": "plugin.activate",
            "plugin_id": active.pluginID,
            "candidate_digest": active.candidateDigest,
            "generation": active.generation,
        ])
        require(
            isNil(AgentHostProtocol.decodeReply(lifecycleMutation)),
            "Agent Host response accepted lifecycle mutation"
        )
        let lifecyclePayload = frame([
            "version": AgentHostProtocol.version,
            "type": "plugin",
            "operation": "plugin.rollback",
            "plugin_id": active.pluginID,
            "candidate_digest": active.candidateDigest,
            "generation": active.generation,
        ])
        require(
            isNil(AgentHostProtocol.decodeReply(lifecyclePayload)),
            "Agent Host response accepted a lifecycle operation field"
        )

        let shellFrame = try AgentHostProtocol.encodeReply(.shell(AgentShellProposal(
            argv: ["/bin/true"],
            readScope: [],
            writeScope: []
        )))
        guard case .shell? = AgentHostProtocol.decodeReply(shellFrame) else {
            fatalError("valid shell proposal was rejected")
        }
        do {
            _ = try AgentHostProtocol.toolResult(
                ok: true,
                text: String(repeating: "x", count: AgentHostProtocol.maximumTextBytes + 1),
                activePlugin: active
            )
            fatalError("oversized untrusted execution result was accepted")
        } catch AgentHostProtocolError.invalidRequest {
            // The Runner result is bounded before it can re-enter the model.
        }
        require(
            AgentHostProtocol.pluginContext(active).contains("information only"),
            "Plugin metadata was not labeled as non-authoritative"
        )
        print("agent-host-protocol=passed")
    }
}
