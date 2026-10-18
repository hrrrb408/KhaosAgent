import CryptoKit
import Foundation

@main
enum TrustedEditApprovalProbe {
    static func main() {
        let fixed = TrustedCandidateBPreview.fixedEditScript
        let oldText = "alpha, beta, "
        let newText = "alpha, beta"
        let base = candidateArgv(oldText: oldText, newText: newText)
        guard let source = try? TrustedAgentRunnerSource.make(argv: base),
              TrustedAgentRunnerSource.decodeCanonicalArgv(source) == base,
              case let .complete(edit) = parse(base, source: source),
              edit.path == "tags.py",
              edit.oldText == oldText,
              edit.newText == newText,
              edit.fixedScriptSHA256 == TrustedCandidateBPreview.fixedScriptSHA256 else {
            fail("the exact signed Candidate B request was not recognized")
        }

        expectIncomplete(Array(base.dropLast()), "wrong argv count")
        var extra = base
        extra.append("unexpected")
        expectIncomplete(extra, "unexpected argument")
        var changedScript = base
        changedScript[4] = jsonString("exec(\(jsonString(fixed + "\nprint('changed')")))")
        expectIncomplete(changedScript, "fixed script mutation")
        var wrongExecutable = base
        wrongExecutable[0] = "/usr/bin/python3"
        expectIncomplete(wrongExecutable, "executable mutation")
        var badFlags = base
        badFlags[1] = "-E"
        expectIncomplete(badFlags, "flag mutation")
        var invalidPath = base
        invalidPath[5] = "../outside.py"
        expectIncomplete(invalidPath, "path traversal")
        var badJSON = base
        badJSON[6] = "{\"oldText\":\"duplicate\",\"oldText\":\"field\"}"
        expectIncomplete(badJSON, "invalid parameter JSON")
        expectIncomplete(base, "wrong scope", readScope: ["tags.py"], writeScope: ["other.py"])
        expectIncomplete(base, "source digest mismatch", digestOverride: String(repeating: "0", count: 64))
        let maximumPath = String(repeating: "p", count: TrustedCandidateBPreview.maximumPathBytes)
        let maximumPathArgv = candidateArgv(path: maximumPath, oldText: "old", newText: "new")
        guard let maximumPathSource = try? TrustedAgentRunnerSource.make(argv: maximumPathArgv),
              case .complete = parse(
                maximumPathArgv,
                source: maximumPathSource,
                readScope: [maximumPath],
                writeScope: [maximumPath]
              ) else {
            fail("the maximum exact-scope path was not reviewable")
        }
        expectIncomplete(
            candidateArgv(path: maximumPath + "p", oldText: "old", newText: "new"),
            "path exceeds exact-scope byte limit",
            readScope: [maximumPath + "p"],
            writeScope: [maximumPath + "p"]
        )
        let oversizedWrapperArgv = candidateArgv(
            oldText: String(repeating: "o", count: 3_800),
            newText: String(repeating: "n", count: 3_800)
        )
        guard oversizedWrapperArgv.allSatisfy({ $0.utf8.count <= 4_096 }),
              TrustedCandidateBPreview.isCandidateBLike(oversizedWrapperArgv),
              (try? TrustedAgentRunnerSource.make(argv: oversizedWrapperArgv)) == nil else {
            fail("an over-budget Candidate B wrapper was not recognized before ordinary approval")
        }
        guard let malformedWrapper = try? TrustedAgentRunnerSource.make(argv: base),
              case .incomplete = TrustedCandidateBPreview.parse(
                runnerSource: malformedWrapper.replacingOccurrences(
                    of: "ARGV = json.loads(base64.b64decode(",
                    with: "ARGV = json.loads("
                ),
                runnerSourceSHA256: digest(malformedWrapper),
                readScope: [],
                writeScope: []
              ) else {
            fail("a malformed wrapped Candidate B request fell through to ordinary approval")
        }

        let oversized = String(repeating: "x", count: TrustedCandidateBPreview.maximumArgumentBytes + 1)
        expectIncomplete(candidateArgv(oldText: "old", newText: oversized), "oversized replacement")
        expectOrdinary(["python3", "-I", "-B", "-c", "print('ordinary command')"])

        let hazardous = "第一行\r\n第二行\u{2028}\u{2029}\u{202E}\u{200B}\u{0000}"
        let hazardousArgv = candidateArgv(oldText: hazardous, newText: "")
        guard let hazardousSource = try? TrustedAgentRunnerSource.make(argv: hazardousArgv),
              case let .complete(hazardousEdit) = parse(hazardousArgv, source: hazardousSource) else {
            fail("multiline Unicode replacement should remain reviewable")
        }
        let summary = hazardousEdit.summary(
            workspacePath: "/tmp/review-workspace",
            requestSHA256: String(repeating: "a", count: 64)
        )
        let details = hazardousEdit.completeDetails(
            workspacePath: "/tmp/review-workspace",
            runnerSourceSHA256: digest(hazardousSource),
            requestID: String(repeating: "b", count: 32),
            requestSHA256: String(repeating: "a", count: 64),
            readScope: ["tags.py"],
            writeScope: ["tags.py"]
        )
        guard summary.contains("Proposed Replacement:"),
              summary.contains("第一行"),
              summary.contains("\\u{000d}"),
              summary.contains("\\u{2028}"),
              summary.contains("\\u{2029}"),
              summary.contains("\\u{202e}"),
              summary.contains("\\u{200b}"),
              summary.contains("\\u{0000}"),
              summary.contains("Request SHA-256:"),
              details.contains("Complete argv (8 arguments):"),
              details.contains("Fixed Candidate B script SHA-256:"),
              details.contains("Decoded oldText"),
              details.contains("Decoded newText (0 UTF-8 bytes)"),
              details.contains("\\u{202e}"),
              !summary.contains("\u{202e}"),
              !summary.contains("\u{200B}") else {
            fail("the review output hid data or left unsafe invisible characters raw")
        }
        let newlineArgv = candidateArgv(oldText: "old\n", newText: "new\n")
        guard let newlineSource = try? TrustedAgentRunnerSource.make(argv: newlineArgv),
              case let .complete(newlineEdit) = parse(newlineArgv, source: newlineSource),
              newlineEdit.summary(
                workspacePath: "/tmp/review-workspace",
                requestSHA256: String(repeating: "c", count: 64)
              ).contains("⟦trailing LF⟧") else {
            fail("a trailing LF was not represented explicitly in the replacement preview")
        }

        let mutated = candidateArgv(oldText: oldText, newText: "different")
        guard let mutatedSource = try? TrustedAgentRunnerSource.make(argv: mutated),
              digest(source) != digest(mutatedSource),
              case let .complete(mutatedEdit) = parse(mutated, source: mutatedSource),
              mutatedEdit.summary(
                workspacePath: "/tmp/review-workspace",
                requestSHA256: digest(mutatedSource)
              )
                .contains(digest(mutatedSource)) else {
            fail("the preview digest did not follow the exact submitted request")
        }

        let requestID = KernelWorkspaceXPC.newRequestID()
        let request = KernelWorkspaceXPC.WorkspaceRunRequest(
            timeoutSeconds: 30,
            runnerSource: source,
            runnerSourceSHA256: digest(source),
            workspaceReadScope: ["tags.py"],
            workspaceWriteScope: ["tags.py"]
        )
        guard let invocation = try? KernelWorkspaceXPC.encodeInvocation(
            request: request,
            requestID: requestID,
            bookmark: Data([1, 2, 3])
        ) else {
            fail("the production workspace invocation could not be encoded")
        }
        let invocationDigest = KernelWorkspaceXPC.sha256Hex(invocation)
        let frozenSummary = edit.summary(
            workspacePath: "/tmp/review-workspace",
            requestSHA256: invocationDigest
        )
        guard frozenSummary.contains(invocationDigest),
              !frozenSummary.contains(digest(source)) else {
            fail("the review digest was not bound to the frozen invocation")
        }

        print("trusted-edit-approval-preview=passed")
        print("candidate-b-fixed-script-sha256=\(TrustedCandidateBPreview.fixedScriptSHA256)")
    }

    private static func candidateArgv(
        path: String = "tags.py",
        oldText: String,
        newText: String
    ) -> [String] {
        [
            "python3", "-I", "-B", "-c",
            "exec(\(jsonString(TrustedCandidateBPreview.fixedEditScript)))",
            path,
            jsonString(oldText),
            jsonString(newText),
        ]
    }

    private static func parse(
        _ argv: [String],
        source: String,
        readScope: [String] = ["tags.py"],
        writeScope: [String] = ["tags.py"],
        digestOverride: String? = nil
    ) -> TrustedCandidateBPreviewResult {
        TrustedCandidateBPreview.parse(
            runnerSource: source,
            runnerSourceSHA256: digestOverride ?? digest(source),
            readScope: readScope,
            writeScope: writeScope
        )
    }

    private static func expectIncomplete(
        _ argv: [String],
        _ label: String,
        readScope: [String] = ["tags.py"],
        writeScope: [String] = ["tags.py"],
        digestOverride: String? = nil
    ) {
        guard let source = try? TrustedAgentRunnerSource.make(argv: argv),
              case .incomplete = parse(
                argv,
                source: source,
                readScope: readScope,
                writeScope: writeScope,
                digestOverride: digestOverride
              ) else {
            fail("expected PREVIEW_INCOMPLETE for \(label)")
        }
    }

    private static func expectOrdinary(_ argv: [String]) {
        guard let source = try? TrustedAgentRunnerSource.make(argv: argv),
              case .ordinaryRequest = parse(argv, source: source) else {
            fail("ordinary shell request was misclassified as Candidate B")
        }
    }

    private static func jsonString(_ value: String) -> String {
        let data = try! JSONSerialization.data(
            withJSONObject: value,
            options: [.fragmentsAllowed, .withoutEscapingSlashes]
        )
        return String(decoding: data, as: UTF8.self)
    }

    private static func digest(_ source: String) -> String {
        SHA256.hash(data: Data(source.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
    }

    private static func fail(_ message: String) -> Never {
        fputs("trusted-edit-approval-probe failed: \(message)\n", stderr)
        exit(1)
    }
}
