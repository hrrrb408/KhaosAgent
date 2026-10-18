import Foundation

/// Offline, untrusted prototype. It renders only the exact replacement strings
/// supplied by the caller; it never reads a workspace file or authorizes work.
enum CandidateBPreview {
    static let maximumParameterBytes = 4_096
    static let maximumPreviewBytes = 16_384

    static func render(path: String, oldText: String, newText: String) -> String {
        guard !path.isEmpty,
              !oldText.isEmpty,
              path.utf8.count <= maximumParameterBytes,
              oldText.utf8.count <= maximumParameterBytes,
              newText.utf8.count <= maximumParameterBytes else {
            return incomplete("invalid or over-budget replacement parameters")
        }

        var output = [
            "PROPOSED REPLACEMENT ONLY — not a full-file diff",
            "Target: \(visible(path))",
            "Current workspace text was not read; unique-match validation happens during execution.",
            "OldText (\(oldText.utf8.count) UTF-8 bytes; trailing LF: \(oldText.hasSuffix("\n"))):",
        ]
        output.append(contentsOf: prefixedLines("-", oldText))
        output.append("NewText (\(newText.utf8.count) UTF-8 bytes; trailing LF: \(newText.hasSuffix("\n"))):")
        output.append(contentsOf: prefixedLines("+", newText))

        let preview = "PREVIEW_COMPLETE\n" + output.joined(separator: "\n") + "\n"
        guard preview.utf8.count <= maximumPreviewBytes else {
            return incomplete("rendered replacement exceeds \(maximumPreviewBytes) bytes")
        }
        return preview
    }

    private static func prefixedLines(_ prefix: String, _ text: String) -> [String] {
        guard !text.isEmpty else { return ["\(prefix) (empty)"] }
        var lines = text.components(separatedBy: "\n")
        if text.hasSuffix("\n") { lines.removeLast() }
        return lines.map { "\(prefix)\(visible($0))" }
    }

    private static func visible(_ text: String) -> String {
        var result = ""
        for scalar in text.unicodeScalars {
            switch scalar.value {
            case 0x09: result += "\\t"
            case 0x0D: result += "\\r"
            case 0x0000...0x001F, 0x007F...0x009F,
                 0x00AD, 0x061C, 0x200B...0x200F, 0x2028...0x202E,
                 0x2060...0x206F, 0xFEFF:
                result += String(format: "\\u{%04x}", scalar.value)
            default:
                result.unicodeScalars.append(scalar)
            }
        }
        return result
    }

    private static func incomplete(_ reason: String) -> String {
        "PREVIEW_INCOMPLETE\n\(reason)\n"
    }
}
