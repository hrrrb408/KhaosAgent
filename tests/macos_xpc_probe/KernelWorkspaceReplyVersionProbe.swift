import CryptoKit
import Foundation

@main
struct KernelWorkspaceReplyVersionProbe {
    static func main() throws {
        let requestID = KernelWorkspaceXPC.RequestID(high: 1, low: 2)
        let bridgeReply = try encodedReply(
            version: KernelWorkspaceXPC.operationProtocolVersion,
            requestID: requestID
        )
        let serviceReply = try encodedReply(
            version: KernelWorkspaceXPC.version,
            requestID: requestID
        )

        guard KernelWorkspaceXPC.decode(
            bridgeReply,
            requestID: requestID,
            protocolVersion: KernelWorkspaceXPC.operationProtocolVersion
        ) != nil,
        KernelWorkspaceXPC.decode(bridgeReply, requestID: requestID) == nil,
        KernelWorkspaceXPC.decode(serviceReply, requestID: requestID) != nil,
        KernelWorkspaceXPC.decode(
            serviceReply,
            requestID: requestID,
            protocolVersion: KernelWorkspaceXPC.operationProtocolVersion
        ) == nil
        else {
            FileHandle.standardError.write(
                Data("KernelWorkspaceXPC accepted the wrong reply ABI\n".utf8)
            )
            exit(1)
        }

        let source = "def run():\n    return 0\n"
        let sourceDigest = SHA256.hash(data: Data(source.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
        let request = KernelWorkspaceXPC.WorkspaceRunRequest(
            timeoutSeconds: 5,
            runnerSource: source,
            runnerSourceSHA256: sourceDigest,
            workspaceReadScope: []
        )
        let bookmark = Data("one-shot-bookmark".utf8)
        let bridgeInput = try KernelWorkspaceXPC.encodeBridgeInput(
            request: request,
            requestID: requestID,
            bookmark: bookmark
        )
        var expectedBridgeInput = try request.encodeFrame(requestID: requestID)
        var bookmarkLength = UInt32(bookmark.count).bigEndian
        withUnsafeBytes(of: &bookmarkLength) {
            expectedBridgeInput.append(contentsOf: $0)
        }
        expectedBridgeInput.append(bookmark)
        guard bridgeInput == expectedBridgeInput else {
            FileHandle.standardError.write(
                Data("KernelWorkspaceXPC bridge input framing changed\n".utf8)
            )
            exit(1)
        }

        FileHandle.standardOutput.write(
            Data(
                "kernel-workspace-response-versions=7-and-8-separated;bridge-input=one-request-frame-plus-bookmark\n".utf8
            )
        )
    }

    private static func encodedReply(
        version: Int,
        requestID: KernelWorkspaceXPC.RequestID
    ) throws -> Data {
        try JSONSerialization.data(
            withJSONObject: [
                "version": version,
                "request_id": requestID.token,
                "ok": true,
                "output": "{}",
            ],
            options: [.sortedKeys]
        )
    }
}
