import Darwin
import Foundation

private final class ProbeResult {
    private let lock = NSLock()
    private var finished = false
    private var accepted = false

    func finish(accepted: Bool) {
        lock.lock()
        defer { lock.unlock() }
        guard !finished else { return }
        finished = true
        self.accepted = accepted
    }

    var wasAccepted: Bool {
        lock.lock()
        defer { lock.unlock() }
        return accepted
    }
}

@main
enum DSHModelBridgePeerProbe {
    static func main() {
        let connection = NSXPCConnection(serviceName: DSHModelBridgeLimits.serviceName)
        connection.remoteObjectInterface = NSXPCInterface(
            with: DSHModelBridgeEndpoint.self
        )
        let result = ProbeResult()
        let completed = DispatchSemaphore(value: 0)
        let finish: (Bool) -> Void = { accepted in
            result.finish(accepted: accepted)
            completed.signal()
        }
        connection.invalidationHandler = { finish(false) }
        connection.interruptionHandler = { finish(false) }
        connection.resume()
        guard let endpoint = connection.remoteObjectProxyWithErrorHandler({ _ in
            finish(false)
        }) as? DSHModelBridgeEndpoint else {
            connection.invalidate()
            print("MODEL_BRIDGE_PEER_REJECTED")
            exit(EXIT_SUCCESS)
        }
        endpoint.complete(
            NSData(),
            headers: NSData(),
            apiKey: "" as NSString,
            timeoutSeconds: 1
        ) { _, _, _ in
            finish(true)
        }
        _ = completed.wait(timeout: .now() + .seconds(5))
        connection.invalidate()
        if result.wasAccepted {
            print("MODEL_BRIDGE_PEER_ACCEPTED")
            exit(EXIT_FAILURE)
        }
        print("MODEL_BRIDGE_PEER_REJECTED")
        exit(EXIT_SUCCESS)
    }
}
