import Foundation

@main
struct XPCClientAttack {
    static func main() {
        guard CommandLine.arguments.count == 2,
              !CommandLine.arguments[1].isEmpty
        else {
            exit(2)
        }

        let connection = NSXPCConnection(serviceName: CommandLine.arguments[1])
        connection.remoteObjectInterface = NSXPCInterface(
            with: XPCPeerIdentityProbe.self
        )
        let semaphore = DispatchSemaphore(value: 0)
        let lock = NSLock()
        var response: String?
        let finish: (String) -> Void = { value in
            lock.lock()
            let shouldFinish = response == nil
            if shouldFinish {
                response = value
            }
            lock.unlock()
            if shouldFinish {
                semaphore.signal()
            }
        }
        connection.interruptionHandler = {}
        connection.invalidationHandler = {}
        connection.resume()

        let proxy = connection.remoteObjectProxyWithErrorHandler { error in
            let code = (error as NSError).code
            // An inbound peer mismatch invalidates this connection.
            finish(
                code == NSXPCConnectionInvalid
                    ? "peer=connection-invalidated"
                    : "peer=error:\(code)"
            )
        } as? XPCPeerIdentityProbe
        proxy?.peerIdentity { value in finish(value) }

        _ = semaphore.wait(timeout: .now() + 5)
        connection.invalidate()
        lock.lock()
        let result = response ?? "peer=no-response"
        lock.unlock()
        FileHandle.standardOutput.write(Data("\(result)\n".utf8))
        if result == "peer=accepted" {
            exit(1)
        }
    }
}
