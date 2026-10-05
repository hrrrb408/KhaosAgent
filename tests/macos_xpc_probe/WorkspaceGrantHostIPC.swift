import Darwin
import Foundation

@objc protocol WorkspaceGrantHostProbe {
    func checkWorkspaceWrite(
        _ path: String,
        _ kernelServiceName: String,
        withReply reply: @escaping (String) -> Void
    )
    func createRelayedInvocationStream(
        _ requestPrefix: Data,
        withReply reply: @escaping (FileHandle?) -> Void
    )
    func closeRelayedInvocationStream(withReply reply: @escaping () -> Void)
}

enum WorkspaceGrantHostClient {
    static func checkWorkspaceWrite(
        serviceName: String,
        path: String,
        kernelServiceName: String
    ) throws -> String {
        let connection = connect(serviceName: serviceName)
        defer { connection.invalidate() }

        let semaphore = DispatchSemaphore(value: 0)
        let lock = NSLock()
        var outcome: (result: String?, error: String?)?
        let finish: (String?, String?) -> Void = { result, error in
            lock.lock()
            let shouldComplete = outcome == nil
            if shouldComplete {
                outcome = (result, error)
            }
            lock.unlock()
            if shouldComplete {
                semaphore.signal()
            }
        }
        let proxy = connection.remoteObjectProxyWithErrorHandler { error in
            finish(nil, String(describing: error))
        } as? WorkspaceGrantHostProbe
        guard let proxy else {
            throw NSError(domain: "WorkspaceGrantHostClient", code: 1)
        }
        proxy.checkWorkspaceWrite(path, kernelServiceName) { result in
            finish(result, nil)
        }
        guard semaphore.wait(timeout: .now() + 10) == .success else {
            throw NSError(domain: "WorkspaceGrantHostClient", code: 2)
        }
        lock.lock()
        let completedOutcome = outcome
        lock.unlock()
        guard let completedOutcome else {
            throw NSError(domain: "WorkspaceGrantHostClient", code: 3)
        }
        if let error = completedOutcome.error {
            throw NSError(
                domain: "WorkspaceGrantHostClient",
                code: 4,
                userInfo: [NSLocalizedDescriptionKey: error]
            )
        }
        guard let result = completedOutcome.result else {
            throw NSError(domain: "WorkspaceGrantHostClient", code: 5)
        }
        return result
    }

    static func withRelayedInvocationStream<Value>(
        serviceName: String,
        requestPrefix: Data,
        operation: (FileHandle, pid_t) throws -> Value
    ) throws -> Value {
        let connection = connect(serviceName: serviceName)
        defer { connection.invalidate() }

        let semaphore = DispatchSemaphore(value: 0)
        let lock = NSLock()
        var outcome: (stream: FileHandle?, error: String?)?
        let finish: (FileHandle?, String?) -> Void = { stream, error in
            lock.lock()
            let shouldComplete = outcome == nil
            if shouldComplete {
                outcome = (stream, error)
            }
            lock.unlock()
            if shouldComplete {
                semaphore.signal()
            }
        }
        let proxy = connection.remoteObjectProxyWithErrorHandler { error in
            finish(nil, String(describing: error))
        } as? WorkspaceGrantHostProbe
        guard let proxy else {
            throw NSError(domain: "WorkspaceGrantHostClient", code: 6)
        }
        proxy.createRelayedInvocationStream(requestPrefix) { stream in
            finish(stream, nil)
        }
        guard semaphore.wait(timeout: .now() + 10) == .success else {
            throw NSError(domain: "WorkspaceGrantHostClient", code: 7)
        }
        lock.lock()
        let completedOutcome = outcome
        lock.unlock()
        guard let completedOutcome else {
            throw NSError(domain: "WorkspaceGrantHostClient", code: 8)
        }
        if let error = completedOutcome.error {
            throw NSError(
                domain: "WorkspaceGrantHostClient",
                code: 9,
                userInfo: [NSLocalizedDescriptionKey: error]
            )
        }
        guard let stream = completedOutcome.stream else {
            throw NSError(domain: "WorkspaceGrantHostClient", code: 10)
        }
        defer { stream.closeFile() }
        defer {
            let closed = DispatchSemaphore(value: 0)
            proxy.closeRelayedInvocationStream { closed.signal() }
            _ = closed.wait(timeout: .now() + 5)
        }

        var peerProcessID: pid_t = 0
        var peerProcessIDLength = socklen_t(MemoryLayout<pid_t>.size)
        guard getsockopt(
            stream.fileDescriptor,
            SOL_LOCAL,
            LOCAL_PEERPID,
            &peerProcessID,
            &peerProcessIDLength
        ) == 0,
        peerProcessIDLength == MemoryLayout<pid_t>.size,
        peerProcessID > 0,
        peerProcessID == connection.processIdentifier,
        peerProcessID != getpid()
        else {
            throw NSError(domain: "WorkspaceGrantHostClient", code: 11)
        }

        return try operation(stream, peerProcessID)
    }

    private static func connect(serviceName: String) -> NSXPCConnection {
        let connection = NSXPCConnection(serviceName: serviceName)
        connection.remoteObjectInterface = NSXPCInterface(
            with: WorkspaceGrantHostProbe.self
        )
        connection.resume()
        return connection
    }
}
