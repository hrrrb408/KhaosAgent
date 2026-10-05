import Foundation

enum KernelBootstrapPeerProbe {
    static func status(serviceName: String) -> String {
        let connection = NSXPCConnection(serviceName: serviceName)
        connection.remoteObjectInterface = NSXPCInterface(
            with: KernelWorkspaceBootstrapEndpoint.self
        )
        let semaphore = DispatchSemaphore(value: 0)
        let lock = NSLock()
        var response: String?
        let finish: (String) -> Void = { value in
            lock.lock()
            let shouldFinish = response == nil
            if shouldFinish { response = value }
            lock.unlock()
            if shouldFinish { semaphore.signal() }
        }
        connection.resume()

        let proxy = connection.remoteObjectProxyWithErrorHandler { error in
            let code = (error as NSError).code
            finish(
                code == NSXPCConnectionInvalid
                    ? "peer=connection-invalidated"
                    : "peer=error:\(code)"
            )
        } as? KernelWorkspaceBootstrapEndpoint
        proxy?.kernelEndpoint { _ in finish("peer=accepted") }
        let completed = semaphore.wait(timeout: .now() + 5) == .success

        lock.lock()
        let result = completed ? response : nil
        lock.unlock()
        connection.invalidate()
        return result ?? "peer=no-response"
    }
}
