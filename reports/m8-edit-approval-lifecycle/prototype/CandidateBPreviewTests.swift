import Foundation

@main
enum CandidateBPreviewTests {
    static func main() {
        simpleReplacement()
        multilineAndLineEndings()
        unicodeAndEscapes()
        exactParameterProvenance()
        staleWorkspaceDisclaimer()
        overflowFailsClosed()
        invalidInputFailsClosed()
        print("candidate-b-preview-prototype=PASS")
    }

    private static func require(_ condition: @autoclosure () -> Bool, _ message: String) {
        guard condition() else { fatalError(message) }
    }

    private static func simpleReplacement() {
        let preview = CandidateBPreview.render(path: "src/example.py", oldText: "return 100", newText: "return 200")
        require(preview.contains("PREVIEW_COMPLETE"), "simple edit was not complete")
        require(preview.contains("-return 100") && preview.contains("+return 200"), "simple diff changed parameters")
        require(preview.contains("not a full-file diff"), "preview semantics are ambiguous")
    }

    private static func multilineAndLineEndings() {
        let preview = CandidateBPreview.render(path: "tags.py", oldText: "first\r\nsecond\n", newText: "one\n\nthree")
        require(preview.contains("-first\\r"), "CR was not made visible")
        require(preview.contains("-second"), "multiline oldText was lost")
        require(preview.contains("+one\n+\n+three"), "blank line or multiline newText was lost")
        require(preview.contains("trailing LF: true") && preview.contains("trailing LF: false"), "line endings are not described")
    }

    private static func unicodeAndEscapes() {
        let preview = CandidateBPreview.render(path: "标签.py", oldText: "café 🧪", newText: "标记\t\u{202E}\u{200B}\u{2028}x")
        require(preview.contains("Target: 标签.py"), "Unicode path changed")
        require(preview.contains("-café 🧪"), "Unicode oldText changed")
        require(preview.contains("+标记\\t\\u{202e}\\u{200b}\\u{2028}x"), "formatting characters can spoof the preview")
    }

    private static func exactParameterProvenance() {
        let base = CandidateBPreview.render(path: "a.py", oldText: "old", newText: "new")
        require(base != CandidateBPreview.render(path: "b.py", oldText: "old", newText: "new"), "path was not rendered from input")
        require(base != CandidateBPreview.render(path: "a.py", oldText: "other", newText: "new"), "oldText was not rendered from input")
        require(base != CandidateBPreview.render(path: "a.py", oldText: "old", newText: "other"), "newText was not rendered from input")
    }

    private static func staleWorkspaceDisclaimer() {
        let preview = CandidateBPreview.render(path: "a.py", oldText: "old", newText: "new")
        require(preview.contains("Current workspace text was not read"), "preview implies a current-file guarantee")
        require(preview.contains("unique-match validation happens during execution"), "execution-time validation is not stated")
    }

    private static func overflowFailsClosed() {
        let control = String(repeating: "\u{0001}", count: 3_000)
        let preview = CandidateBPreview.render(path: "a.py", oldText: control, newText: control)
        require(preview.hasPrefix("PREVIEW_INCOMPLETE\n"), "overflow was silently truncated")
        require(!preview.contains("-\\u{"), "partial diff was returned after overflow")

        let boundary = String(repeating: "x", count: CandidateBPreview.maximumParameterBytes)
        let bounded = CandidateBPreview.render(path: "a.py", oldText: boundary, newText: "")
        require(bounded.utf8.count <= CandidateBPreview.maximumPreviewBytes, "status marker was omitted from the preview byte budget")
    }

    private static func invalidInputFailsClosed() {
        require(CandidateBPreview.render(path: "a.py", oldText: "", newText: "x").hasPrefix("PREVIEW_INCOMPLETE"), "empty match was accepted")
        let oversized = String(repeating: "x", count: CandidateBPreview.maximumParameterBytes + 1)
        require(CandidateBPreview.render(path: "a.py", oldText: "x", newText: oversized).hasPrefix("PREVIEW_INCOMPLETE"), "over-budget input was accepted")
    }
}
