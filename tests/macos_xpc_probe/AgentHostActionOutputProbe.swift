import Foundation

private func require(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else {
        fputs("AgentHostActionOutputProbe: \(message)\n", stderr)
        exit(EXIT_FAILURE)
    }
}

@main
enum AgentHostActionOutputProbe {
    static func main() {
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

        print("agent-host-action-output=passed")
    }
}
