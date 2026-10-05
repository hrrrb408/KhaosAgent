import Foundation

final class AgentHostClient {
    private let connection: NSXPCConnection

    init() {
        connection = NSXPCConnection(serviceName: "org.khaos.Seed.AgentHost")
        connection.remoteObjectInterface = NSXPCInterface(
            with: AgentHostSessionEndpoint.self
        )
        connection.resume()
    }

    func sendUserTurn(_ text: String) throws -> AgentHostReply {
        try request(AgentHostProtocol.userTurn(text))
    }

    func sendToolResult(ok: Bool, text: String) throws -> AgentHostReply {
        try request(AgentHostProtocol.toolResult(ok: ok, text: text))
    }

    func stop() {
        connection.invalidate()
    }

    deinit {
        stop()
    }

    private func request(_ frame: Data) throws -> AgentHostReply {
        let semaphore = DispatchSemaphore(value: 0)
        let lock = NSLock()
        var response: Data?
        var failed = false
        let finishWithFailure: (Error) -> Void = { _ in
            lock.lock()
            failed = true
            lock.unlock()
            semaphore.signal()
        }
        guard let endpoint = connection.remoteObjectProxyWithErrorHandler(
            finishWithFailure
        ) as? AgentHostSessionEndpoint else {
            throw AgentHostClientError.unavailable
        }
        endpoint.handle(NSData(data: frame)) { value in
            lock.lock()
            response = value.map(Data.init(referencing:))
            lock.unlock()
            semaphore.signal()
        }
        guard semaphore.wait(timeout: .now() + 180) == .success else {
            connection.invalidate()
            throw AgentHostClientError.timedOut
        }
        lock.lock()
        let data = response
        let didFail = failed
        lock.unlock()
        guard !didFail, let data,
              let reply = AgentHostProtocol.decodeReply(data) else {
            throw AgentHostClientError.invalidResponse
        }
        return reply
    }
}

enum AgentHostClientError: Error {
    case unavailable
    case timedOut
    case invalidResponse
}
