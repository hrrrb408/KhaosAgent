import Foundation

@main
enum KernelWorkspaceCommandClientProbe {
    static func main() {
        do {
            try verifyCancellationBeforeCommandStart()
            try verifyCancellationBeforeSubmission()
            try verifyCancellationUsesSubmittingConnectionAndWaitsForFinalReply()
            print("kernel-workspace-command-client=passed")
        } catch {
            fputs("kernel-workspace-command-client=failed \(error)\n", stderr)
            exit(1)
        }
    }

    private static func verifyCancellationBeforeCommandStart() throws {
        let endpoint = ProbeKernelEndpoint()
        let connection = endpoint.clientConnection()
        let identity = requestIdentity()
        let invocation = try invocationFrame(identity.requestID)
        let handle = KernelWorkspaceCommandHandle(
            connection: connection,
            identity: identity,
            invocationFrame: invocation,
            snapshotBrokerEndpoint: nil
        )
        let cancellationCompleted = DispatchSemaphore(value: 0)
        var cancellationResult: KernelWorkspaceCancellationResult?
        handle.requestCancellation(matching: identity) { value in
            cancellationResult = value
            cancellationCompleted.signal()
        }

        let completed = DispatchSemaphore(value: 0)
        var observation: KernelWorkspaceCommandObservation?
        handle.start { value in
            observation = value
            completed.signal()
        }
        guard cancellationCompleted.wait(timeout: .now() + 3) == .success,
              completed.wait(timeout: .now() + 3) == .success,
              cancellationResult == .notSubmitted,
              endpoint.runCount == 0,
              let observation,
              !observation.submitted,
              observation.submittedAt == nil,
              observation.cancellation == .notSubmitted,
              case .some(.cancelledBeforeSubmission) = failure(in: observation) else {
            throw ProbeFailure("cancellation before command start did not prevent workspace.run")
        }
    }

    private static func verifyCancellationBeforeSubmission() throws {
        let endpoint = ProbeKernelEndpoint()
        let connection = endpoint.clientConnection()
        let identity = requestIdentity()
        let invocation = try invocationFrame(identity.requestID)
        let broker = NSXPCListener.anonymous()
        broker.resume()
        let handle = KernelWorkspaceCommandHandle(
            connection: connection,
            identity: identity,
            invocationFrame: invocation,
            snapshotBrokerEndpoint: broker.endpoint
        )
        let completed = DispatchSemaphore(value: 0)
        var observation: KernelWorkspaceCommandObservation?
        handle.start { value in
            observation = value
            completed.signal()
        }
        guard endpoint.waitForBrokerSetup() else {
            throw ProbeFailure("snapshot Broker setup did not reach the test gate")
        }

        let wrongIdentity = KernelWorkspaceRequestIdentity(
            taskID: UUID(),
            workspaceSessionID: identity.workspaceSessionID,
            requestID: identity.requestID,
            connectionID: identity.connectionID
        )
        var staleResult: KernelWorkspaceCancellationResult?
        handle.requestCancellation(matching: wrongIdentity) { value in
            staleResult = value
        }
        guard staleResult == .staleIdentity else {
            throw ProbeFailure("a different task identity was not rejected")
        }

        let cancellationCompleted = DispatchSemaphore(value: 0)
        var cancellationResult: KernelWorkspaceCancellationResult?
        handle.requestCancellation(matching: identity) { value in
            cancellationResult = value
            cancellationCompleted.signal()
        }
        guard cancellationCompleted.wait(timeout: .now() + 3) == .success,
              completed.wait(timeout: .now() + 3) == .success,
              cancellationResult == .notSubmitted,
              endpoint.runCount == 0,
              let observation,
              !observation.submitted,
              observation.cancellation == .notSubmitted else {
            throw ProbeFailure("pre-submission cancellation did not prevent workspace.run")
        }
        guard case .some(.cancelledBeforeSubmission) = failure(in: observation) else {
            throw ProbeFailure("pre-submission cancellation lost its terminal result")
        }
        endpoint.completeBrokerSetup()
    }

    private static func verifyCancellationUsesSubmittingConnectionAndWaitsForFinalReply() throws {
        let endpoint = ProbeKernelEndpoint()
        let connection = endpoint.clientConnection()
        let identity = requestIdentity()
        let invocation = try invocationFrame(identity.requestID)
        let handle = KernelWorkspaceCommandHandle(
            connection: connection,
            identity: identity,
            invocationFrame: invocation,
            snapshotBrokerEndpoint: nil
        )
        let completed = DispatchSemaphore(value: 0)
        var observation: KernelWorkspaceCommandObservation?
        handle.start { value in
            observation = value
            completed.signal()
        }
        guard endpoint.waitForRun() else {
            _ = completed.wait(timeout: .now() + 1)
            throw ProbeFailure("workspace.run was not received by the test service")
        }
        guard endpoint.receivedInvocation == invocation else {
            throw ProbeFailure("the submitted invocation changed after request creation")
        }

        let wrongIdentity = KernelWorkspaceRequestIdentity(
            taskID: UUID(),
            workspaceSessionID: identity.workspaceSessionID,
            requestID: identity.requestID,
            connectionID: identity.connectionID
        )
        var staleResult: KernelWorkspaceCancellationResult?
        handle.requestCancellation(matching: wrongIdentity) { value in
            staleResult = value
        }
        guard staleResult == .staleIdentity, endpoint.cancelCount == 0 else {
            throw ProbeFailure("a stale task identity reached Kernel cancellation")
        }

        let cancellationCompleted = DispatchSemaphore(value: 0)
        var cancellationResult: KernelWorkspaceCancellationResult?
        handle.requestCancellation(matching: identity) { value in
            cancellationResult = value
            cancellationCompleted.signal()
        }
        guard cancellationCompleted.wait(timeout: .now() + 3) == .success,
              completed.wait(timeout: .now() + 3) == .success,
              cancellationResult == .accepted,
              endpoint.sameConnectionForRunAndCancel,
              endpoint.cancelCount == 1,
              let observation,
              observation.submitted,
              observation.submittedAt != nil,
              observation.cancellation == .accepted else {
            throw ProbeFailure("matching cancellation was not bound to the submitted request")
        }
        guard case let .success(reply) = observation.reply,
              reply.errorCode == "process_cancelled",
              reply.output == nil else {
            throw ProbeFailure("cancel_accepted was mistaken for the original final result")
        }
    }

    private static func failure(
        in observation: KernelWorkspaceCommandObservation
    ) -> KernelWorkspaceClientError? {
        guard case let .failure(error) = observation.reply else { return nil }
        return error
    }

    private static func requestIdentity() -> KernelWorkspaceRequestIdentity {
        KernelWorkspaceRequestIdentity(
            taskID: UUID(),
            workspaceSessionID: UUID(),
            requestID: KernelWorkspaceXPC.newRequestID(),
            connectionID: UUID()
        )
    }

    private static func invocationFrame(
        _ requestID: KernelWorkspaceXPC.RequestID
    ) throws -> Data {
        let source = "def run():\n    return 0\n"
        let request = KernelWorkspaceXPC.WorkspaceRunRequest(
            timeoutSeconds: 5,
            runnerSource: source,
            runnerSourceSHA256: KernelWorkspaceXPC.runnerSourceSHA256(source),
            workspaceReadScope: ["tags.py"],
            workspaceWriteScope: ["tags.py"]
        )
        return try KernelWorkspaceXPC.encodeInvocation(
            request: request,
            requestID: requestID,
            bookmark: Data([1, 2, 3])
        )
    }
}

private struct ProbeFailure: Error, CustomStringConvertible {
    let description: String

    init(_ description: String) {
        self.description = description
    }
}

private final class ProbeKernelEndpoint: NSObject, NSXPCListenerDelegate, KernelWorkspaceEndpoint {
    private let listener = NSXPCListener.anonymous()
    private let lock = NSLock()
    private let brokerSetupSignal = DispatchSemaphore(value: 0)
    private let runSignal = DispatchSemaphore(value: 0)
    private var brokerSetupReply: ((Bool) -> Void)?
    private var activeRequestID: KernelWorkspaceXPC.RequestID?
    private var activeConnection: ObjectIdentifier?
    private var activeRunReply: ((Data) -> Void)?
    private var invocation: Data?
    private var runCountValue = 0
    private var cancelCountValue = 0
    private var sameConnectionValue = false

    override init() {
        super.init()
        listener.delegate = self
        listener.resume()
    }

    var runCount: Int {
        lock.lock()
        defer { lock.unlock() }
        return runCountValue
    }

    var cancelCount: Int {
        lock.lock()
        defer { lock.unlock() }
        return cancelCountValue
    }

    var sameConnectionForRunAndCancel: Bool {
        lock.lock()
        defer { lock.unlock() }
        return sameConnectionValue
    }

    var receivedInvocation: Data? {
        lock.lock()
        defer { lock.unlock() }
        return invocation
    }

    func clientConnection() -> NSXPCConnection {
        let connection = NSXPCConnection(listenerEndpoint: listener.endpoint)
        connection.remoteObjectInterface = NSXPCInterface(
            with: KernelWorkspaceEndpoint.self
        )
        connection.resume()
        return connection
    }

    func waitForBrokerSetup() -> Bool {
        brokerSetupSignal.wait(timeout: .now() + 3) == .success
    }

    func waitForRun() -> Bool {
        runSignal.wait(timeout: .now() + 3) == .success
    }

    func completeBrokerSetup() {
        lock.lock()
        let reply = brokerSetupReply
        brokerSetupReply = nil
        lock.unlock()
        reply?(true)
    }

    func listener(
        _ listener: NSXPCListener,
        shouldAcceptNewConnection connection: NSXPCConnection
    ) -> Bool {
        connection.exportedInterface = NSXPCInterface(
            with: KernelWorkspaceEndpoint.self
        )
        connection.exportedObject = self
        connection.resume()
        return true
    }

    func setSnapshotBrokerEndpoint(
        _ version: Int,
        endpoint: NSXPCListenerEndpoint,
        withReply reply: @escaping (Bool) -> Void
    ) {
        lock.lock()
        brokerSetupReply = reply
        lock.unlock()
        brokerSetupSignal.signal()
    }

    func runWorkspaceCommand(
        _ version: Int,
        requestIDHigh: UInt64,
        requestIDLow: UInt64,
        invocationStream: FileHandle,
        withReply reply: @escaping (Data) -> Void
    ) {
        let requestID = KernelWorkspaceXPC.RequestID(
            high: requestIDHigh,
            low: requestIDLow
        )
        let connection = NSXPCConnection.current()
        lock.lock()
        runCountValue += 1
        activeRequestID = requestID
        activeConnection = connection.map(ObjectIdentifier.init)
        activeRunReply = reply
        lock.unlock()
        let received = invocationStream.readDataToEndOfFile()
        lock.lock()
        invocation = received
        lock.unlock()
        runSignal.signal()
    }

    func cancelWorkspaceCommand(
        _ version: Int,
        requestIDHigh: UInt64,
        requestIDLow: UInt64,
        withReply reply: @escaping (Data) -> Void
    ) {
        let requestID = KernelWorkspaceXPC.RequestID(
            high: requestIDHigh,
            low: requestIDLow
        )
        let connection = NSXPCConnection.current()
        lock.lock()
        cancelCountValue += 1
        sameConnectionValue = activeConnection == connection.map(ObjectIdentifier.init)
            && activeRequestID == requestID
        let runReply = activeRunReply
        activeRunReply = nil
        lock.unlock()
        reply(KernelWorkspaceXPC.cancellationAccepted(requestID: requestID))
        runReply?(KernelWorkspaceXPC.failure(requestID: requestID, code: "process_cancelled"))
    }
}
