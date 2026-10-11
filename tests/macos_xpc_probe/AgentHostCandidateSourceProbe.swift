import Foundation

@main
struct AgentHostCandidateSourceProbe {
    static func main() {
        let baseline = #"""
        import json

        def _load_items():
            return json.loads("{}")

        def run(request):
            return {"value": request.get("key")}
        """#
        let replacement = #"""
        def run(request):
            key = request.get("key")
            if key is None:
                return {"found": False}
            return {"value": key.casefold()}
        """#
        do {
            let result = try AgentHostCandidateSource.replacingRunFunction(
                in: Data(baseline.utf8),
                with: replacement
            )
            guard let runStart = baseline.range(of: "def run(request):"),
                  String(decoding: result, as: UTF8.self)
                    == String(baseline[..<runStart.lowerBound]) + replacement,
                  String(decoding: result, as: UTF8.self).hasPrefix("import json\n") else {
                exit(EXIT_FAILURE)
            }

            let baselineWithFinalNewline = baseline + "\n"
            let newlineResult = try AgentHostCandidateSource.replacingRunFunction(
                in: Data(baselineWithFinalNewline.utf8),
                with: replacement
            )
            guard let newlineRunStart = baselineWithFinalNewline.range(
                of: "def run(request):"
            ),
            String(decoding: newlineResult, as: UTF8.self)
                == String(baselineWithFinalNewline[..<newlineRunStart.lowerBound])
                    + replacement + "\n" else {
                exit(EXIT_FAILURE)
            }

            let invalidReplacement = replacement + "\nimport os\n"
            do {
                _ = try AgentHostCandidateSource.replacingRunFunction(
                    in: Data(baseline.utf8),
                    with: invalidReplacement
                )
                exit(EXIT_FAILURE)
            } catch AgentHostCandidateSourceError.invalidFunction {
                // Invalid model output must fail instead of changing baseline scope.
            }

            let duplicateBaseline = baseline + "\n\ndef run(request):\n    return None\n"
            do {
                _ = try AgentHostCandidateSource.replacingRunFunction(
                    in: Data(duplicateBaseline.utf8),
                    with: replacement
                )
                exit(EXIT_FAILURE)
            } catch AgentHostCandidateSourceError.invalidFunction {
                // Ambiguous baseline structure fails closed.
            }
            print("agent-host-candidate-source=passed")
        } catch {
            fputs("candidate-source-probe-failed: \(error)\n", stderr)
            exit(EXIT_FAILURE)
        }
    }
}
