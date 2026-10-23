import Darwin
import Foundation

private final class ProbeResult {
    private let lock = NSLock()
    private var finished = false
    private var outcome = "MODEL_BRIDGE_NOT_VISIBLE"

    func finish(_ outcome: String) {
        lock.lock()
        defer { lock.unlock() }
        guard !finished else { return }
        finished = true
        self.outcome = outcome
    }

    var value: String {
        lock.lock()
        defer { lock.unlock() }
        return outcome
    }
}

@main
enum DSHModelBridgePeerProbe {
    static func main() {
        guard ProcessInfo.processInfo.environment[
            "KHAOS_DSH_MODEL_BRIDGE_AVAILABLE"
        ] == "1" else {
            print("MODEL_BRIDGE_UNAVAILABLE")
            exit(EXIT_FAILURE)
        }
        guard let requirement = ProcessInfo.processInfo.environment[
            "KHAOS_DSH_MODEL_BRIDGE_REQUIREMENT"
        ], !requirement.isEmpty else {
            print("MODEL_BRIDGE_UNAVAILABLE")
            exit(EXIT_FAILURE)
        }

        let connection = NSXPCConnection(serviceName: DSHModelBridgeLimits.serviceName)
        connection.setCodeSigningRequirement(requirement)
        let bootstrapInterface = NSXPCInterface(
            with: DSHModelBridgeBootstrapEndpoint.self
        )
        connection.remoteObjectInterface = bootstrapInterface

        let result = ProbeResult()
        let completed = DispatchSemaphore(value: 0)
        let finish: (String) -> Void = { outcome in
            result.finish(outcome)
            completed.signal()
        }
        connection.invalidationHandler = { finish("MODEL_BRIDGE_NOT_VISIBLE") }
        connection.interruptionHandler = { finish("MODEL_BRIDGE_NOT_VISIBLE") }
        connection.resume()
        guard let bootstrap = connection.remoteObjectProxyWithErrorHandler({ _ in
            finish("MODEL_BRIDGE_NOT_VISIBLE")
        }) as? DSHModelBridgeBootstrapEndpoint else {
            connection.invalidate()
            print("MODEL_BRIDGE_NOT_VISIBLE")
            exit(EXIT_SUCCESS)
        }
        bootstrap.modelEndpoint { endpoint in
            guard let endpoint else {
                finish("MODEL_BRIDGE_NOT_VISIBLE")
                return
            }
            let modelConnection = NSXPCConnection(listenerEndpoint: endpoint)
            modelConnection.setCodeSigningRequirement(requirement)
            modelConnection.remoteObjectInterface = NSXPCInterface(
                with: DSHModelBridgeEndpoint.self
            )
            modelConnection.resume()
            guard let model = modelConnection.remoteObjectProxyWithErrorHandler({ _ in
                finish("MODEL_BRIDGE_PEER_REJECTED")
            }) as? DSHModelBridgeEndpoint else {
                modelConnection.invalidate()
                finish("MODEL_BRIDGE_PEER_REJECTED")
                return
            }
            model.complete(
                NSData(),
                headers: NSData(),
                apiKey: "" as NSString,
                timeoutSeconds: 1
            ) { _, _, _ in
                finish("MODEL_BRIDGE_PEER_ACCEPTED")
            }
            DispatchQueue.global(qos: .utility).asyncAfter(
                deadline: .now() + .seconds(5)
            ) {
                modelConnection.invalidate()
            }
        }
        guard completed.wait(timeout: .now() + .seconds(7)) == .success else {
            connection.invalidate()
            print("MODEL_BRIDGE_PROBE_TIMEOUT")
            exit(EXIT_FAILURE)
        }
        connection.invalidate()
        let outcome = result.value
        print(outcome)
        if outcome == "MODEL_BRIDGE_PEER_ACCEPTED" {
            exit(EXIT_FAILURE)
        }
        if outcome == "MODEL_BRIDGE_UNAVAILABLE" {
            exit(EXIT_FAILURE)
        }
        exit(EXIT_SUCCESS)
    }
}
