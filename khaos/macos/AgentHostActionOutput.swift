import Foundation

enum AgentHostActionOutput {
    static func correction(
        for errorCode: String,
        alreadyUsed: Bool
    ) -> String? {
        guard !alreadyUsed,
              [
                "invalid_model_output_json",
                "invalid_model_output_shape",
                "invalid_model_output_field_types",
              ].contains(errorCode) else {
            return nil
        }
        return """
            Host validation feedback: The previous model response was not submitted or executed because it was not one valid action JSON object. Re-read the original user request and the latest Trusted Launcher metadata already in context. Return exactly one raw JSON object with exactly these keys and JSON types: {"type":"text","text":"answer or empty string","argv":[],"readScope":[],"writeScope":[],"pluginID":"","candidateDigest":"","generation":0,"pluginInput":"","evolutionGoal":""}. Do not omit, add, rename, or change the type of a field. Leave every unused field at its documented empty value. Do not add Markdown, commentary, source, Manifest, scope, capability, approval, secret, or lifecycle data. Nothing has run; do not claim execution.
            """
    }
}
