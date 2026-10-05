import Foundation

@objc protocol SpoofBootstrap {
    func spoofEndpoint(withReply reply: @escaping (NSXPCListenerEndpoint) -> Void)
}

@objc protocol RunnerProbe {
    func run(
        _ bookmark: Data,
        siblingPath: String,
        outsidePath: String,
        otherRunnerStatePath: String,
        networkPort: Int,
        pluginID: String,
        withReply reply: @escaping (String) -> Void
    )
}

@objc protocol KernelProbe {
    func readInput(_ bookmark: Data, withReply reply: @escaping (String) -> Void)
}

@objc protocol SpoofProbe {
    func attempt(
        endpoint: NSXPCListenerEndpoint,
        bookmark: Data,
        siblingPath: String,
        outsidePath: String,
        networkPort: Int,
        withReply reply: @escaping (String) -> Void
    )
    func attemptKernel(
        endpoint: NSXPCListenerEndpoint,
        bookmark: Data,
        withReply reply: @escaping (String) -> Void
    )
    func attemptKernelExecution(
        endpoint: NSXPCListenerEndpoint,
        bookmark: Data,
        withReply reply: @escaping (String) -> Void
    )
}

final class SpoofService: NSObject, SpoofProbe {
    func attempt(
        endpoint: NSXPCListenerEndpoint,
        bookmark: Data,
        siblingPath: String,
        outsidePath: String,
        networkPort: Int,
        withReply reply: @escaping (String) -> Void
    ) {
        probe(
            endpoint: endpoint,
            bookmark: bookmark,
            siblingPath: siblingPath,
            outsidePath: outsidePath,
            networkPort: networkPort,
            reply: reply
        )
    }

    func attemptKernel(
        endpoint: NSXPCListenerEndpoint,
        bookmark: Data,
        withReply reply: @escaping (String) -> Void
    ) {
        let connection = NSXPCConnection(listenerEndpoint: endpoint)
        connection.remoteObjectInterface = NSXPCInterface(with: KernelProbe.self)
        let lock = NSLock()
        var completed = false
        let finish: (String) -> Void = { result in
            lock.lock()
            let shouldComplete = !completed
            completed = true
            lock.unlock()
            guard shouldComplete else { return }
            connection.invalidate()
            reply(result)
        }

        connection.resume()
        let proxy = connection.remoteObjectProxyWithErrorHandler { _ in
            finish("peer=denied")
        } as? KernelProbe
        guard let proxy else {
            finish("peer=denied")
            return
        }
        proxy.readInput(bookmark) { _ in
            finish("peer=accepted")
        }
        DispatchQueue.global().asyncAfter(deadline: .now() + 4) {
            finish("peer=no-response")
        }
    }

    func attemptKernelExecution(
        endpoint: NSXPCListenerEndpoint,
        bookmark: Data,
        withReply reply: @escaping (String) -> Void
    ) {
        let connection = NSXPCConnection(listenerEndpoint: endpoint)
        connection.remoteObjectInterface = NSXPCInterface(
            with: KernelWorkspaceEndpoint.self
        )
        let lock = NSLock()
        var completed = false
        let finish: (String) -> Void = { result in
            lock.lock()
            let shouldComplete = !completed
            completed = true
            lock.unlock()
            guard shouldComplete else { return }
            connection.invalidate()
            reply(result)
        }

        connection.resume()
        let proxy = connection.remoteObjectProxyWithErrorHandler { _ in
            finish("peer=denied")
        } as? KernelWorkspaceEndpoint
        guard let proxy else {
            finish("peer=denied")
            return
        }
        try? KernelWorkspaceXPC.submit(
            proxy,
            request: WorkspaceProbeRequest.forWorkspace(
                URL(fileURLWithPath: "/tmp/khaos-peer-denial")
            ),
            bookmark: bookmark
        ) { _ in
            finish("peer=accepted")
        }
        DispatchQueue.global().asyncAfter(deadline: .now() + 4) {
            finish("peer=no-response")
        }
    }

    private func probe(
        endpoint: NSXPCListenerEndpoint,
        bookmark: Data,
        siblingPath: String,
        outsidePath: String,
        networkPort: Int,
        reply: @escaping (String) -> Void
    ) {
        let connection = NSXPCConnection(listenerEndpoint: endpoint)
        connection.remoteObjectInterface = NSXPCInterface(with: RunnerProbe.self)

        let lock = NSLock()
        var completed = false
        let finish: (String) -> Void = { result in
            lock.lock()
            let shouldComplete = !completed
            completed = true
            lock.unlock()
            guard shouldComplete else { return }
            connection.invalidate()
            reply(result)
        }

        connection.resume()
        let proxy = connection.remoteObjectProxyWithErrorHandler { _ in
            finish("peer=denied")
        } as? RunnerProbe
        guard let proxy else {
            finish("peer=denied")
            return
        }
        proxy.run(
            bookmark,
            siblingPath: siblingPath,
            outsidePath: outsidePath,
            otherRunnerStatePath: outsidePath,
            networkPort: networkPort,
            pluginID: "peer-auth-spoof"
        ) { _ in
            finish("peer=accepted")
        }
        DispatchQueue.global().asyncAfter(deadline: .now() + 4) {
            finish("peer=no-response")
        }
    }
}

final class SpoofDelegate: NSObject, NSXPCListenerDelegate {
    private let service = SpoofService()

    func listener(
        _ listener: NSXPCListener,
        shouldAcceptNewConnection connection: NSXPCConnection
    ) -> Bool {
        connection.exportedInterface = NSXPCInterface(with: SpoofProbe.self)
        connection.exportedObject = service
        connection.resume()
        return true
    }
}

final class SpoofBootstrapService: NSObject, SpoofBootstrap {
    private let listener: NSXPCListener
    private let delegate: SpoofDelegate

    override init() {
        listener = NSXPCListener.anonymous()
        delegate = SpoofDelegate()
        super.init()
        listener.delegate = delegate
        listener.resume()
    }

    func spoofEndpoint(withReply reply: @escaping (NSXPCListenerEndpoint) -> Void) {
        reply(listener.endpoint)
    }
}

final class SpoofBootstrapDelegate: NSObject, NSXPCListenerDelegate {
    private let service = SpoofBootstrapService()

    func listener(
        _ listener: NSXPCListener,
        shouldAcceptNewConnection connection: NSXPCConnection
    ) -> Bool {
        connection.exportedInterface = NSXPCInterface(with: SpoofBootstrap.self)
        connection.exportedObject = service
        connection.resume()
        return true
    }
}

@main
struct Spoof {
    static func main() {
        let delegate = SpoofBootstrapDelegate()
        let listener = NSXPCListener.service()
        listener.delegate = delegate
        listener.resume()
        RunLoop.main.run()
    }
}
