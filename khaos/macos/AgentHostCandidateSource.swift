import Foundation

enum AgentHostCandidateSourceError: Error {
    case invalidFunction
    case sourceTooLarge
}

enum AgentHostCandidateSource {
    static func replacingRunFunction(
        in baseline: Data,
        with replacementFunction: String
    ) throws -> Data {
        let signature = "def run(request):"
        guard let baselineSource = String(data: baseline, encoding: .utf8),
              replacementFunction.utf8.count
                <= AgentHostProtocol.maximumCandidateSourceBytes,
              replacementFunction.hasPrefix(signature + "\n"),
              replacementFunction.components(separatedBy: signature).count == 2,
              let functionRange = baselineSource.range(of: signature),
              functionRange.lowerBound == baselineSource.startIndex
                || baselineSource[baselineSource.index(before: functionRange.lowerBound)] == "\n"
        else {
            throw AgentHostCandidateSourceError.invalidFunction
        }

        func isIndentedOrEmpty(_ line: String) -> Bool {
            line.isEmpty || line.first == " " || line.first == "\t"
        }

        let baselineTail = String(baselineSource[functionRange.lowerBound...])
            .components(separatedBy: "\n")
        let generatedLines = replacementFunction.components(separatedBy: "\n")
        guard baselineTail.first == signature,
              baselineTail.dropFirst().allSatisfy(isIndentedOrEmpty),
              generatedLines.first == signature,
              generatedLines.dropFirst().allSatisfy(isIndentedOrEmpty),
              generatedLines.dropFirst().contains(where: { !$0.isEmpty }) else {
            throw AgentHostCandidateSourceError.invalidFunction
        }

        let finalNewline = baselineSource.hasSuffix("\n")
            && !replacementFunction.hasSuffix("\n")
            ? "\n"
            : ""
        let source = String(baselineSource[..<functionRange.lowerBound])
            + replacementFunction
            + finalNewline
        guard source.utf8.count <= AgentHostProtocol.maximumCandidateSourceBytes else {
            throw AgentHostCandidateSourceError.sourceTooLarge
        }
        return Data(source.utf8)
    }
}
