import Foundation

@main
enum ApprovalCancelHarnessTests {
    static func main() {
        validRequestProducesBoundPreviewAndRawDetails()
        requestAndScopeMutationsFailClosed()
        malformedScriptAndPayloadFailClosed()
        emptyReplacementAndUnicodeRemainReviewable()
        oversizedPreviewCannotBeApproved()
        cancellationRequiresTheExactActiveIdentity()
        cancelAcknowledgementIsNotTerminal()
        kernelOutcomeControlsTerminalTruth()
        lateHostReplyCannotResumeAnotherTask()
        print("m8-trusted-approval-cancel-nontrusted-harness=PASS")
    }

    private static func require(_ condition: @autoclosure () -> Bool, _ message: String) {
        guard condition() else { fatalError(message) }
    }

    private static func validRequestProducesBoundPreviewAndRawDetails() {
        let request = CandidateBReviewHarness.makeRequest(
            path: "src/example.py", oldText: "return 100", newText: "return 200"
        )
        let review = CandidateBReviewHarness.review(request)
        if !review.runOnceEnabled {
            FileHandle.standardError.write(Data(review.completeDetails.utf8))
        }
        require(review.runOnceEnabled, "valid exact request did not enable the modeled approval")
        require(review.preview.contains("-return 100") && review.preview.contains("+return 200"), "preview changed request parameters")
        require(review.completeDetails.contains("complete argv:"), "complete execution details were omitted")
        require(review.completeDetails.contains(request.approvalDigest), "review omitted its request digest")
    }

    private static func requestAndScopeMutationsFailClosed() {
        let request = CandidateBReviewHarness.makeRequest(
            path: "src/example.py", oldText: "old", newText: "new"
        )
        let changedRequest = TestWorkspaceRunRequest(
            taskID: request.taskID,
            requestID: request.requestID,
            runnerSource: request.runnerSource + "# changed",
            runnerSourceSHA256: request.runnerSourceSHA256,
            readScope: request.readScope,
            writeScope: request.writeScope,
            bookmarkSHA256: request.bookmarkSHA256,
            approvalDigest: request.approvalDigest
        )
        require(!CandidateBReviewHarness.review(changedRequest).runOnceEnabled, "request mutation retained approval")

        let changedID = TestWorkspaceRunRequest(
            taskID: request.taskID,
            requestID: String(repeating: "c", count: 32),
            runnerSource: request.runnerSource,
            runnerSourceSHA256: request.runnerSourceSHA256,
            readScope: request.readScope,
            writeScope: request.writeScope,
            bookmarkSHA256: request.bookmarkSHA256,
            approvalDigest: request.approvalDigest
        )
        require(!CandidateBReviewHarness.review(changedID).runOnceEnabled, "request-id mutation retained approval")

        let broadScope = CandidateBReviewHarness.makeRequest(
            path: "src/example.py", oldText: "old", newText: "new",
            readScope: ["src"], writeScope: ["src/example.py"]
        )
        require(!CandidateBReviewHarness.review(broadScope).runOnceEnabled, "scope mismatch retained preview approval")
    }

    private static func malformedScriptAndPayloadFailClosed() {
        let script = CandidateBReviewHarness.makeRequest(
            path: "a.py", oldText: "old", newText: "new", script: "print('not Candidate B')"
        )
        require(!CandidateBReviewHarness.review(script).runOnceEnabled, "unknown script identity retained approval")

        let extraArgument = CandidateBReviewHarness.makeRequest(
            path: "a.py", oldText: "old", newText: "new", extraArguments: ["extra"]
        )
        require(!CandidateBReviewHarness.review(extraArgument).runOnceEnabled, "extra argument retained approval")

        let unknownField = CandidateBReviewHarness.makeRequest(
            path: "a.py", oldText: "old", newText: "new",
            payloadJSON: #"{"type":"edit","path":"a.py","oldText":"old","newText":"new","extra":true}"#
        )
        require(!CandidateBReviewHarness.review(unknownField).runOnceEnabled, "unknown field retained approval")

        let duplicateField = CandidateBReviewHarness.makeRequest(
            path: "a.py", oldText: "old", newText: "new",
            payloadJSON: #"{"type":"edit","path":"a.py","oldText":"old","newText":"new","newText":"override"}"#
        )
        require(!CandidateBReviewHarness.review(duplicateField).runOnceEnabled, "duplicate JSON field retained approval")

        let traversal = CandidateBReviewHarness.makeRequest(
            path: "../outside.py", oldText: "old", newText: "new"
        )
        require(!CandidateBReviewHarness.review(traversal).runOnceEnabled, "traversal path retained preview approval")
    }

    private static func emptyReplacementAndUnicodeRemainReviewable() {
        let request = CandidateBReviewHarness.makeRequest(
            path: "src/标签.py", oldText: "café 🧪\r\n", newText: ""
        )
        let review = CandidateBReviewHarness.review(request)
        require(review.runOnceEnabled, "valid empty replacement was denied")
        require(review.preview.contains("Target: src/标签.py"), "Unicode path changed")
        require(review.preview.contains("-café 🧪\\r"), "CRLF detail was hidden")
        require(review.preview.contains("+ (empty)"), "empty replacement was hidden")

        let directional = CandidateBReviewHarness.makeRequest(
            path: "a.py", oldText: "old", newText: "left\u{202E}\u{200B}\u{2028}right"
        )
        let directionalReview = CandidateBReviewHarness.review(directional)
        require(directionalReview.runOnceEnabled, "bounded formatting characters made preview incomplete")
        require(directionalReview.preview.contains("\\u{202e}\\u{200b}\\u{2028}"), "bidi or zero-width characters were not made visible")
    }

    private static func oversizedPreviewCannotBeApproved() {
        let large = String(repeating: "\u{0001}", count: 3_000)
        let request = CandidateBReviewHarness.makeRequest(
            path: "a.py", oldText: large, newText: large
        )
        let review = CandidateBReviewHarness.review(request)
        require(!review.runOnceEnabled, "preview overflow retained approval")
        require(review.preview.hasPrefix("PREVIEW_INCOMPLETE"), "overflow was not explicit")
        require(review.completeDetails.contains(request.runnerSource), "incomplete preview discarded raw request details")
    }

    private static func cancellationRequiresTheExactActiveIdentity() {
        let task = UUID()
        let connection = UUID()
        let active = TestTaskRequestIdentity(taskID: task, requestID: "active", connectionID: connection)
        require(CancellationOutcomeHarness.cancellationMatches(active: active, requested: active), "matching cancellation was rejected")
        require(!CancellationOutcomeHarness.cancellationMatches(
            active: active,
            requested: TestTaskRequestIdentity(taskID: UUID(), requestID: "active", connectionID: connection)
        ), "stale task cancellation matched")
        require(!CancellationOutcomeHarness.cancellationMatches(
            active: active,
            requested: TestTaskRequestIdentity(taskID: task, requestID: "old", connectionID: connection)
        ), "stale request cancellation matched")
        require(!CancellationOutcomeHarness.cancellationMatches(
            active: active,
            requested: TestTaskRequestIdentity(taskID: task, requestID: "active", connectionID: UUID())
        ), "different XPC connection cancellation matched")
    }

    private static func cancelAcknowledgementIsNotTerminal() {
        require(
            CancellationOutcomeHarness.terminal(cancelRequested: true, cancelAccepted: true, result: nil)
                == .awaitingKernelResult(cancelRequested: true, cancelAccepted: true),
            "cancel acknowledgement was treated as a final outcome"
        )
    }

    private static func kernelOutcomeControlsTerminalTruth() {
        require(
            CancellationOutcomeHarness.terminal(cancelRequested: true, cancelAccepted: true, result: .processCancelled)
                == .cancelledNotCommitted,
            "pre-commit process_cancelled was misreported"
        )
        require(
            CancellationOutcomeHarness.terminal(
                cancelRequested: true,
                cancelAccepted: true,
                result: .completed(returncode: 0, changedEntries: 1)
            ) == .executionFinished(returncode: 0, workspaceCommitted: true, lateCancelObserved: true),
            "late cancellation hid an already committed result"
        )
        require(
            CancellationOutcomeHarness.terminal(
                cancelRequested: true,
                cancelAccepted: false,
                result: .completed(returncode: 0, changedEntries: 1)
            ) == .executionFinished(returncode: 0, workspaceCommitted: true, lateCancelObserved: true),
            "a rejected late cancel erased an already committed result"
        )
        require(
            CancellationOutcomeHarness.terminal(
                cancelRequested: false,
                cancelAccepted: false,
                result: .completed(returncode: 1, changedEntries: 1)
            ) == .executionFinished(returncode: 1, workspaceCommitted: true, lateCancelObserved: false),
            "nonzero command exit was treated as proof that no changes committed"
        )
        require(
            CancellationOutcomeHarness.terminal(cancelRequested: false, cancelAccepted: false, result: .commitRejected)
                == .commitRejected,
            "commit_rejected was lost"
        )
        require(
            CancellationOutcomeHarness.terminal(cancelRequested: true, cancelAccepted: true, result: .commitOutcomeUncertain)
                == .workspaceOutcomeUncertain,
            "uncertain commit was reported as rollback"
        )
        require(
            CancellationOutcomeHarness.terminal(cancelRequested: true, cancelAccepted: true, result: .transportLost)
                == .terminalResultUnavailable,
            "lost final reply was reported as cancellation success"
        )
    }

    private static func lateHostReplyCannotResumeAnotherTask() {
        let current = UUID()
        require(CancellationOutcomeHarness.acceptsLateHostReply(activeTaskID: current, replyTaskID: current), "current task reply was lost")
        require(!CancellationOutcomeHarness.acceptsLateHostReply(activeTaskID: current, replyTaskID: UUID()), "stale task reply was accepted")
    }
}
