import AppKit
import Foundation

enum TrustedAgentRunnerSourceError: Error {
    case overBudget
}

enum TrustedAgentRunnerSource {
    static let maximumBytes = 10_240

    private static let wrapperHeader =
        "import base64, json\n"
        + "from khaos.runner_sdk import process_exec, workspace_commit\n\n"
        + "ARGV = "
    private static let prefix = wrapperHeader
        + "json.loads(base64.b64decode("
    private static let suffix = """
        ))

        def run():
            process_exec(tuple(ARGV))
            # A normal nonzero command result still needs the Kernel's scoped commit frame.
            workspace_commit()
            return 0
        """

    static func make(argv: [String]) throws -> String {
        let encodedArgv = try canonicalJSON(argv).base64EncodedString()
        let source = prefix + String(reflecting: encodedArgv) + suffix
        guard source.utf8.count <= maximumBytes else {
            throw TrustedAgentRunnerSourceError.overBudget
        }
        return source
    }

    static func decodeCanonicalArgv(_ source: String) -> [String]? {
        guard source.utf8.count <= maximumBytes,
              source.hasPrefix(prefix),
              source.hasSuffix(suffix) else {
            return nil
        }
        let literal = source.dropFirst(prefix.count).dropLast(suffix.count)
        guard literal.count >= 2,
              literal.first == "\"",
              literal.last == "\"" else {
            return nil
        }
        let encoded = String(literal.dropFirst().dropLast())
        guard encoded.utf8.allSatisfy(isBase64Byte),
              let data = Data(base64Encoded: encoded),
              data.base64EncodedString() == encoded,
              let argv = try? JSONSerialization.jsonObject(with: data) as? [String],
              let canonical = try? canonicalJSON(argv),
              canonical == data,
              (try? make(argv: argv)) == source else {
            return nil
        }
        return argv
    }

    static func isWrapperLike(_ source: String) -> Bool {
        source.hasPrefix(wrapperHeader)
            || source.contains("ARGV = json.loads(base64.b64decode(")
    }

    private static func canonicalJSON(_ value: Any) throws -> Data {
        try JSONSerialization.data(
            withJSONObject: value,
            options: [.sortedKeys, .withoutEscapingSlashes]
        )
    }

    private static func isBase64Byte(_ byte: UInt8) -> Bool {
        (65...90).contains(byte) || (97...122).contains(byte)
            || (48...57).contains(byte) || byte == 43 || byte == 47 || byte == 61
    }
}

struct TrustedCandidateBEdit {
    let argv: [String]
    let path: String
    let oldText: String
    let newText: String
    let fixedScriptSHA256: String

    func summary(workspacePath: String, requestSHA256: String) -> String {
        [
            "Workspace:",
            CandidateBReviewText.visible(workspacePath),
            "",
            "Target:",
            CandidateBReviewText.visible(path),
            "",
            "Proposed Replacement:",
            CandidateBReviewText.replacementLines(oldText: oldText, newText: newText),
            "",
            "This shows the requested text replacement; current workspace text was not read.",
            "The fixed Runner script checks for one exact match before replacement.",
            "",
            "Read Scope:",
            CandidateBReviewText.visible(path),
            "",
            "Write Scope:",
            CandidateBReviewText.visible(path),
            "",
            "Request SHA-256:",
            requestSHA256,
        ].joined(separator: "\n")
    }

    func completeDetails(
        workspacePath: String,
        runnerSourceSHA256: String,
        requestID: String,
        requestSHA256: String,
        readScope: [String],
        writeScope: [String]
    ) -> String {
        let encodedArgv = argv.enumerated().map { index, argument in
            "[\(index)] \(CandidateBReviewText.quoted(argument))"
        }.joined(separator: "\n")
        return [
            "Complete approval details",
            "",
            "Executable:",
            CandidateBReviewText.visible(argv[0]),
            "",
            "Complete argv (\(argv.count) arguments):",
            encodedArgv,
            "",
            "Runner source SHA-256:",
            runnerSourceSHA256,
            "Fixed Candidate B script SHA-256:",
            fixedScriptSHA256,
            "Request ID:",
            requestID,
            "",
            "Decoded path:",
            CandidateBReviewText.visible(path),
            "",
            "Decoded oldText (\(oldText.utf8.count) UTF-8 bytes):",
            CandidateBReviewText.visible(oldText),
            "",
            "Decoded newText (\(newText.utf8.count) UTF-8 bytes):",
            CandidateBReviewText.visible(newText),
            "",
            "Workspace:",
            CandidateBReviewText.visible(workspacePath),
            "",
            "Exact readScope:",
            CandidateBReviewText.scope(readScope),
            "",
            "Exact writeScope:",
            CandidateBReviewText.scope(writeScope),
            "",
            "Request SHA-256:",
            requestSHA256,
        ].joined(separator: "\n")
    }
}

enum TrustedCandidateBPreviewResult {
    case ordinaryRequest
    case incomplete(String)
    case complete(TrustedCandidateBEdit)
}

enum TrustedCandidateBPreview {
    static let maximumArgumentBytes = 4_096
    static let maximumPreviewBytes = 16_384
    static let maximumDetailsBytes = 32_768
    static let maximumPathBytes = AgentHostProtocol.maximumScopePathBytes

    static let fixedEditScript = #"""
        import json, os, stat, sys
        from pathlib import Path
        p=Path(sys.argv[1]); old=json.loads(sys.argv[2]); new=json.loads(sys.argv[3]); st=p.lstat()
        if not stat.S_ISREG(st.st_mode): raise SystemExit(20)
        s=p.read_text(encoding="utf-8"); i=s.find(old)
        if not old or i<0 or s.find(old,i+1)>=0 or old==new: raise SystemExit(21)
        d=(s[:i]+new+s[i+len(old):]).encode("utf-8"); q=p.with_name(".khaos-edit-"+os.urandom(16).hex())
        u=os.umask(0)
        try: fd=os.open(q,os.O_WRONLY|os.O_CREAT|os.O_EXCL,stat.S_IMODE(st.st_mode))
        finally: os.umask(u)
        try:
            with os.fdopen(fd,"wb") as f: f.write(d); f.flush(); os.fsync(f.fileno())
            os.replace(q,p); q=None
        finally:
            if q is not None: os.unlink(q)
        print("EDIT_APPLIED")
        """#

    private static let fixedScriptArgument: String? =
        "exec(\(CandidateBReviewText.quotedJSON(fixedEditScript)))"

    static var fixedScriptSHA256: String {
        KernelWorkspaceXPC.sha256Hex(Data(fixedEditScript.utf8))
    }

    static func parse(
        runnerSource: String,
        runnerSourceSHA256: String,
        readScope: [String],
        writeScope: [String]
    ) -> TrustedCandidateBPreviewResult {
        guard let argv = TrustedAgentRunnerSource.decodeCanonicalArgv(runnerSource) else {
            if TrustedAgentRunnerSource.isWrapperLike(runnerSource) {
                return .incomplete("Runner source wrapper is malformed or over budget.")
            }
            return .ordinaryRequest
        }

        guard isCandidateBLike(argv) else { return .ordinaryRequest }
        guard KernelWorkspaceXPC.runnerSourceSHA256(runnerSource) == runnerSourceSHA256 else {
            return .incomplete("Runner source digest does not match the submitted source.")
        }
        guard argv.count == 8 else {
            return .incomplete("Candidate B requires exactly eight argv entries.")
        }
        guard argv[0] == "python3",
              argv[1] == "-I",
              argv[2] == "-B",
              argv[3] == "-c" else {
            return .incomplete("Candidate B executable or fixed Python flags changed.")
        }
        guard argv[4] == fixedScriptArgument else {
            return .incomplete("Candidate B fixed script identity does not match the approved version.")
        }
        guard argv.allSatisfy({ $0.utf8.count <= maximumArgumentBytes }) else {
            return .incomplete("A Candidate B argv entry exceeds the 4096-byte limit.")
        }
        let path = argv[5]
        guard validRelativePath(path) else {
            return .incomplete("Candidate B target path is not a valid relative workspace path.")
        }
        guard readScope == [path], writeScope == [path] else {
            return .incomplete("Candidate B read and write scope must each equal the target path exactly.")
        }
        guard let oldText = decodeCanonicalJSONString(argv[6]), !oldText.isEmpty else {
            return .incomplete("Candidate B oldText must be a nonempty canonical JSON string.")
        }
        guard let newText = decodeCanonicalJSONString(argv[7]) else {
            return .incomplete("Candidate B newText is not a canonical JSON string.")
        }
        guard oldText.utf8.count <= maximumArgumentBytes,
              newText.utf8.count <= maximumArgumentBytes else {
            return .incomplete("Candidate B replacement text exceeds the 4096-byte limit.")
        }
        let preview = CandidateBReviewText.replacementLines(oldText: oldText, newText: newText)
        guard preview.utf8.count <= maximumPreviewBytes else {
            return .incomplete("Complete replacement preview exceeds the display limit.")
        }
        return .complete(TrustedCandidateBEdit(
            argv: argv,
            path: path,
            oldText: oldText,
            newText: newText,
            fixedScriptSHA256: fixedScriptSHA256
        ))
    }

    static func isCandidateBLike(_ argv: [String]) -> Bool {
        if argv.contains(fixedScriptArgument ?? "\u{0}") { return true }
        guard argv.count >= 5,
              argv[1] == "-I",
              argv[2] == "-B",
              argv[3] == "-c" else {
            return false
        }
        let script = argv[4]
        if script.hasPrefix("exec(") { return true }
        return script.contains("from pathlib import Path")
            && script.contains("os.replace(")
            && script.contains("sys.argv")
    }

    private static func decodeCanonicalJSONString(_ value: String) -> String? {
        guard let data = value.data(using: .utf8),
              let decoded = try? JSONSerialization.jsonObject(
                with: data,
                options: [.fragmentsAllowed]
              ) as? String,
              let canonical = try? JSONSerialization.data(
                withJSONObject: decoded,
                options: [.fragmentsAllowed, .withoutEscapingSlashes]
              ),
              canonical == data else {
            return nil
        }
        return decoded
    }

    private static func validRelativePath(_ path: String) -> Bool {
        guard !path.isEmpty,
              path.utf8.count <= maximumPathBytes,
              !path.hasPrefix("/"),
              !path.contains("\\"),
              !path.unicodeScalars.contains(where: { $0.value == 0 }) else {
            return false
        }
        let components = path.split(separator: "/", omittingEmptySubsequences: false)
        return components.count <= 64
            && components.allSatisfy { !$0.isEmpty && $0 != "." && $0 != ".." }
    }
}

enum TrustedCandidateBApprovalDecision {
    case approved
    case denied
    case incomplete(String)
}

enum TrustedCandidateBApproval {
    static func present(
        edit: TrustedCandidateBEdit,
        workspacePath: String,
        requestID: String,
        requestSHA256: String,
        runnerSourceSHA256: String,
        readScope: [String],
        writeScope: [String]
    ) -> TrustedCandidateBApprovalDecision {
        let summary = edit.summary(
            workspacePath: workspacePath,
            requestSHA256: requestSHA256
        )
        let details = edit.completeDetails(
            workspacePath: workspacePath,
            runnerSourceSHA256: runnerSourceSHA256,
            requestID: requestID,
            requestSHA256: requestSHA256,
            readScope: readScope,
            writeScope: writeScope
        )
        guard summary.utf8.count <= TrustedCandidateBPreview.maximumPreviewBytes,
              details.utf8.count <= TrustedCandidateBPreview.maximumDetailsBytes else {
            let reason = "The complete Candidate B approval view exceeds its display limit."
            showIncomplete(reason)
            return .incomplete(reason)
        }

        var showingDetails = false
        while true {
            let alert = NSAlert()
            alert.alertStyle = .warning
            alert.messageText = showingDetails
                ? "Review complete Candidate B details"
                : "Approve this Candidate B replacement once?"
            alert.informativeText = showingDetails
                ? "Review the full argv, decoded replacement, scopes, and frozen request digest before approving."
                : "Review the requested replacement and exact file scopes. The current workspace file has not been read for this preview."
            if showingDetails {
                alert.accessoryView = scrollableText(details)
                alert.addButton(withTitle: "Back to Preview")
                alert.addButton(withTitle: "Cancel Request")
                alert.addButton(withTitle: "Run once")
                switch alert.runModal() {
                case .alertThirdButtonReturn:
                    return .approved
                case .alertFirstButtonReturn:
                    showingDetails = false
                default:
                    return .denied
                }
            } else {
                alert.accessoryView = scrollableText(summary)
                alert.addButton(withTitle: "Cancel Request")
                alert.addButton(withTitle: "View Complete Details")
                alert.addButton(withTitle: "Run once")
                switch alert.runModal() {
                case .alertThirdButtonReturn:
                    return .approved
                case .alertSecondButtonReturn:
                    showingDetails = true
                default:
                    return .denied
                }
            }
        }
    }

    static func showIncomplete(_ reason: String) {
        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = "PREVIEW_INCOMPLETE"
        alert.informativeText = CandidateBReviewText.visible(reason)
            + "\n\nThis edit cannot be approved or run because its full request could not be reviewed."
        alert.addButton(withTitle: "Cancel Request")
        _ = alert.runModal()
    }

    private static func scrollableText(_ value: String) -> NSView {
        let width: CGFloat = 660
        let height: CGFloat = 270
        let scrollView = NSScrollView(
            frame: NSRect(x: 0, y: 0, width: width, height: height)
        )
        scrollView.borderType = .bezelBorder
        scrollView.hasVerticalScroller = true
        scrollView.hasHorizontalScroller = false
        scrollView.autohidesScrollers = false

        let textView = NSTextView(
            frame: NSRect(x: 0, y: 0, width: width - 18, height: height)
        )
        textView.string = value
        textView.isEditable = false
        textView.isSelectable = true
        textView.isRichText = false
        textView.minSize = NSSize(width: width - 18, height: 0)
        textView.maxSize = NSSize(
            width: width - 18,
            height: CGFloat.greatestFiniteMagnitude
        )
        textView.isVerticallyResizable = true
        textView.isHorizontallyResizable = false
        textView.autoresizingMask = [.width]
        textView.textContainer?.widthTracksTextView = true
        textView.textContainer?.containerSize = NSSize(
            width: width - 18,
            height: CGFloat.greatestFiniteMagnitude
        )
        textView.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        textView.textContainerInset = NSSize(width: 8, height: 8)
        if let textContainer = textView.textContainer {
            textView.layoutManager?.ensureLayout(for: textContainer)
            let usedHeight = textView.layoutManager?.usedRect(for: textContainer).height ?? height
            textView.setFrameSize(
                NSSize(width: width - 18, height: max(height, usedHeight + 16))
            )
        }
        scrollView.documentView = textView
        return scrollView
    }
}

private enum CandidateBReviewText {
    static func replacementLines(oldText: String, newText: String) -> String {
        let oldLines = prefixedLines("-", oldText)
        let newLines = prefixedLines("+", newText)
        return (oldLines + newLines).joined(separator: "\n")
    }

    static func visible(_ text: String) -> String {
        var result = ""
        for scalar in text.unicodeScalars {
            if scalar.value == 0x0A {
                result.append("\n")
            } else if scalar.properties.generalCategory == .format
                || scalar.properties.generalCategory == .lineSeparator
                || scalar.properties.generalCategory == .paragraphSeparator
                || CharacterSet.controlCharacters.contains(scalar) {
                result += String(format: "\\u{%04x}", scalar.value)
            } else {
                result.unicodeScalars.append(scalar)
            }
        }
        return result
    }

    static func quoted(_ text: String) -> String {
        visible(quotedJSON(text))
    }

    static func quotedJSON(_ text: String) -> String {
        guard let data = try? JSONSerialization.data(
            withJSONObject: text,
            options: [.fragmentsAllowed, .withoutEscapingSlashes]
        ) else { return "<encoding failed>" }
        return String(decoding: data, as: UTF8.self)
    }

    static func scope(_ values: [String]) -> String {
        "[" + values.map(quoted).joined(separator: ", ") + "]"
    }

    private static func prefixedLines(_ prefix: String, _ text: String) -> [String] {
        guard !text.isEmpty else { return ["\(prefix) (empty)"] }
        var lines = text.components(separatedBy: "\n")
        let hasTrailingLineFeed = text.hasSuffix("\n")
        if hasTrailingLineFeed { lines.removeLast() }
        let rendered = lines.map { "\(prefix)\(visible($0))" }
        return hasTrailingLineFeed
            ? rendered + ["\(prefix)⟦trailing LF⟧"]
            : rendered
    }
}
