import CryptoKit
import Foundation

// Report-local, nontrusted test model. It is not linked into Khaos and performs
// no file, process, XPC, or workspace operations.
struct TestWorkspaceRunRequest {
    let taskID: UUID
    let requestID: String
    let runnerSource: String
    let runnerSourceSHA256: String
    let readScope: [String]
    let writeScope: [String]
    let bookmarkSHA256: String
    let approvalDigest: String
}

struct TestPreviewDecision {
    let preview: String
    let completeDetails: String
    let runOnceEnabled: Bool
}

enum CandidateBReviewHarness {
    private static let maximumFieldBytes = 4_096
    private static let candidateScript = "import json, sys\npayload = json.loads(sys.argv[1])\n"
    private static let runnerPrefix = "import base64, json\nfrom khaos.runner_sdk import process_exec, workspace_commit\n\nARGV = json.loads(base64.b64decode("
    private static let runnerSuffix = "))\n\ndef run():\n    process_exec(tuple(ARGV))\n    # A normal nonzero command result still needs the Kernel's scoped commit frame.\n    workspace_commit()\n    return 0\n"

    static func makeRequest(
        taskID: UUID = UUID(),
        requestID: String = String(repeating: "a", count: 32),
        path: String,
        oldText: String,
        newText: String,
        readScope: [String]? = nil,
        writeScope: [String]? = nil,
        script: String? = nil,
        payloadJSON: String? = nil,
        extraArguments: [String] = [],
        bookmarkSHA256: String = String(repeating: "b", count: 64)
    ) -> TestWorkspaceRunRequest {
        let json = payloadJSON ?? encodePayload(path: path, oldText: oldText, newText: newText)
        let argv = [
            "/usr/bin/python3", "-I", "-B", "-c",
            script ?? candidateScript,
            json,
        ] + extraArguments
        let source = makeRunnerSource(argv: argv)
        let provisional = TestWorkspaceRunRequest(
            taskID: taskID,
            requestID: requestID,
            runnerSource: source,
            runnerSourceSHA256: sha256(Data(source.utf8)),
            readScope: readScope ?? [path],
            writeScope: writeScope ?? [path],
            bookmarkSHA256: bookmarkSHA256,
            approvalDigest: ""
        )
        return TestWorkspaceRunRequest(
            taskID: provisional.taskID,
            requestID: provisional.requestID,
            runnerSource: provisional.runnerSource,
            runnerSourceSHA256: provisional.runnerSourceSHA256,
            readScope: provisional.readScope,
            writeScope: provisional.writeScope,
            bookmarkSHA256: provisional.bookmarkSHA256,
            approvalDigest: digest(provisional)
        )
    }

    static func review(_ request: TestWorkspaceRunRequest) -> TestPreviewDecision {
        let rawDetails = """
        Complete raw request details
        request id: \(request.requestID)
        runner source SHA-256: \(request.runnerSourceSHA256)
        read scope: \(request.readScope)
        write scope: \(request.writeScope)
        bookmark SHA-256: \(request.bookmarkSHA256)
        approval request SHA-256: \(request.approvalDigest)
        runner source bytes: \(request.runnerSource.utf8.count)
        runner source:
        \(request.runnerSource)
        """

        guard validRequestID(request.requestID),
              validDigest(request.runnerSourceSHA256),
              validDigest(request.bookmarkSHA256),
              request.runnerSourceSHA256 == sha256(Data(request.runnerSource.utf8)),
              request.approvalDigest == digest(request),
              let argv = decodeRunnerSource(request.runnerSource),
              argv.count == 6,
              argv[0] == "/usr/bin/python3",
              argv[1] == "-I",
              argv[2] == "-B",
              argv[3] == "-c",
              argv[4] == candidateScript,
              let edit = decodeCanonicalEdit(argv[5]),
              validRelativePath(edit.path),
              !edit.oldText.isEmpty,
              edit.path.utf8.count <= maximumFieldBytes,
              edit.oldText.utf8.count <= maximumFieldBytes,
              edit.newText.utf8.count <= maximumFieldBytes,
              request.readScope == [edit.path],
              request.writeScope == [edit.path] else {
            return TestPreviewDecision(
                preview: "PREVIEW_INCOMPLETE\nThe fixed test request, digest, parameters, or exact scopes did not validate.\n",
                completeDetails: rawDetails,
                runOnceEnabled: false
            )
        }

        let preview = CandidateBPreview.render(
            path: edit.path,
            oldText: edit.oldText,
            newText: edit.newText
        )
        let details = rawDetails + "\n\nDecoded Candidate B fields\n"
            + "fixed test script: CandidateBReviewHarness.v1\n"
            + "path: \(edit.path)\noldText UTF-8 bytes: \(edit.oldText.utf8.count)\n"
            + "oldText: \(CandidateBPreview.visible(edit.oldText))\n"
            + "newText UTF-8 bytes: \(edit.newText.utf8.count)\n"
            + "newText: \(CandidateBPreview.visible(edit.newText))\n"
            + "complete argv:\n" + argv.enumerated().map { "[\($0.offset)] \($0.element)" }.joined(separator: "\n")
        return TestPreviewDecision(
            preview: preview,
            completeDetails: details,
            runOnceEnabled: preview.hasPrefix("PREVIEW_COMPLETE\n")
        )
    }

    private static func encodePayload(path: String, oldText: String, newText: String) -> String {
        let object = ["type": "edit", "path": path, "oldText": oldText, "newText": newText]
        let data = (try? JSONSerialization.data(
            withJSONObject: object,
            options: [.sortedKeys, .withoutEscapingSlashes]
        )) ?? Data()
        return String(decoding: data, as: UTF8.self)
    }

    private static func makeRunnerSource(argv: [String]) -> String {
        let data = (try? JSONSerialization.data(
            withJSONObject: argv,
            options: [.sortedKeys, .withoutEscapingSlashes]
        )) ?? Data()
        return runnerPrefix + String(reflecting: data.base64EncodedString()) + runnerSuffix
    }

    private static func decodeRunnerSource(_ source: String) -> [String]? {
        guard source.hasPrefix(runnerPrefix), source.hasSuffix(runnerSuffix) else { return nil }
        let literal = source.dropFirst(runnerPrefix.count).dropLast(runnerSuffix.count)
        guard literal.count >= 2, literal.first == "\"", literal.last == "\"" else { return nil }
        let encoded = String(literal.dropFirst().dropLast())
        guard encoded.unicodeScalars.allSatisfy({
            (65...90).contains(Int($0.value)) || (97...122).contains(Int($0.value))
                || (48...57).contains(Int($0.value)) || $0 == "+" || $0 == "/" || $0 == "="
        }),
        let data = Data(base64Encoded: encoded),
        data.base64EncodedString() == encoded,
        let argv = try? JSONSerialization.jsonObject(with: data) as? [String],
        let canonical = try? JSONSerialization.data(
            withJSONObject: argv,
            options: [.sortedKeys, .withoutEscapingSlashes]
        ),
        canonical == data,
        makeRunnerSource(argv: argv) == source else { return nil }
        return argv
    }

    private static func decodeCanonicalEdit(_ json: String) -> (path: String, oldText: String, newText: String)? {
        let data = Data(json.utf8)
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              Set(object.keys) == ["type", "path", "oldText", "newText"],
              object["type"] as? String == "edit",
              let path = object["path"] as? String,
              let oldText = object["oldText"] as? String,
              let newText = object["newText"] as? String,
              let canonical = try? JSONSerialization.data(
                withJSONObject: object,
                options: [.sortedKeys, .withoutEscapingSlashes]
              ),
              canonical == data else { return nil }
        return (path, oldText, newText)
    }

    private static func validRelativePath(_ path: String) -> Bool {
        !path.isEmpty && !path.hasPrefix("/") && !path.contains("\\")
            && !path.unicodeScalars.contains(where: { $0.value == 0 })
            && path.split(separator: "/", omittingEmptySubsequences: false)
                .allSatisfy { !$0.isEmpty && $0 != "." && $0 != ".." }
    }

    private static func validRequestID(_ value: String) -> Bool {
        value.utf8.count == 32 && value.utf8.allSatisfy {
            (48...57).contains(Int($0)) || (97...102).contains(Int($0))
        }
    }

    private static func validDigest(_ value: String) -> Bool {
        value.utf8.count == 64 && value.utf8.allSatisfy {
            (48...57).contains(Int($0)) || (97...102).contains(Int($0))
        }
    }

    private static func digest(_ request: TestWorkspaceRunRequest) -> String {
        var data = Data("Khaos test-only workspace invocation v1\0".utf8)
        for field in [
            request.requestID,
            request.runnerSource,
            request.readScope.joined(separator: "\0"),
            request.writeScope.joined(separator: "\0"),
            request.bookmarkSHA256,
        ] {
            let bytes = Data(field.utf8)
            var length = UInt64(bytes.count).bigEndian
            withUnsafeBytes(of: &length) { data.append(contentsOf: $0) }
            data.append(bytes)
        }
        return sha256(data)
    }

    private static func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}

struct TestTaskRequestIdentity: Equatable {
    let taskID: UUID
    let requestID: String
    let connectionID: UUID
}

enum TestKernelWorkspaceResult {
    case processCancelled
    case completed(returncode: Int, changedEntries: Int)
    case commitRejected
    case commitOutcomeUncertain
    case transportLost
}

enum TestTaskTerminal: Equatable {
    case awaitingKernelResult(cancelRequested: Bool, cancelAccepted: Bool)
    case cancelledNotCommitted
    case executionFinished(returncode: Int, workspaceCommitted: Bool, lateCancelObserved: Bool)
    case commitRejected
    case workspaceOutcomeUncertain
    case terminalResultUnavailable
}

enum CancellationOutcomeHarness {
    static func cancellationMatches(
        active: TestTaskRequestIdentity,
        requested: TestTaskRequestIdentity
    ) -> Bool {
        active == requested
    }

    static func acceptsLateHostReply(activeTaskID: UUID, replyTaskID: UUID) -> Bool {
        activeTaskID == replyTaskID
    }

    static func terminal(
        cancelRequested: Bool,
        cancelAccepted: Bool,
        result: TestKernelWorkspaceResult?
    ) -> TestTaskTerminal {
        guard let result else {
            return .awaitingKernelResult(
                cancelRequested: cancelRequested,
                cancelAccepted: cancelAccepted
            )
        }
        switch result {
        case .processCancelled:
            return .cancelledNotCommitted
        case let .completed(returncode, changedEntries):
            return .executionFinished(
                returncode: returncode,
                workspaceCommitted: changedEntries > 0,
                lateCancelObserved: cancelRequested
            )
        case .commitRejected:
            return .commitRejected
        case .commitOutcomeUncertain:
            return .workspaceOutcomeUncertain
        case .transportLost:
            return .terminalResultUnavailable
        }
    }
}
