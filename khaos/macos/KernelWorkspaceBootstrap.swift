import Foundation

enum KernelWorkspaceBootstrapError: Error {
    case missingWorkspaceCallerRequirement
    case missingBootstrapRequirement
}

final class KernelWorkspaceBootstrapService: NSObject,
    KernelWorkspaceBootstrapEndpoint,
    NSXPCListenerDelegate
{
    private let bootstrapListener = NSXPCListener.service()
    private let workspaceListener = NSXPCListener.anonymous()
    private let workspaceService: KernelWorkspaceService
    private let workspaceCallerRequirement: String
    private let bootstrapRequirement: String

    init(executor: @escaping KernelWorkspaceService.Executor) throws {
        guard let workspaceCallerRequirement = XPCPeerIdentity.codeSigningRequirement(
            forInfoKey: "KhaosWorkspaceCallerRequirement"
        )
        else {
            throw KernelWorkspaceBootstrapError.missingWorkspaceCallerRequirement
        }
        guard let bootstrapRequirement = XPCPeerIdentity.codeSigningRequirement(
            forInfoKey: "KhaosBootstrapRequirement"
        )
        else {
            throw KernelWorkspaceBootstrapError.missingBootstrapRequirement
        }
        self.workspaceCallerRequirement = workspaceCallerRequirement
        self.bootstrapRequirement = bootstrapRequirement
        workspaceService = KernelWorkspaceService(executor: executor)
        super.init()
        workspaceListener.setConnectionCodeSigningRequirement(workspaceCallerRequirement)
        workspaceListener.delegate = self
        workspaceListener.resume()
    }

    func run() {
        bootstrapListener.delegate = self
        bootstrapListener.resume()
        RunLoop.main.run()
    }

    func kernelEndpoint(withReply reply: @escaping (NSXPCListenerEndpoint) -> Void) {
        reply(workspaceListener.endpoint)
    }

    func listener(
        _ listener: NSXPCListener,
        shouldAcceptNewConnection connection: NSXPCConnection
    ) -> Bool {
        if listener === bootstrapListener {
            connection.setCodeSigningRequirement(bootstrapRequirement)
            connection.exportedInterface = NSXPCInterface(
                with: KernelWorkspaceBootstrapEndpoint.self
            )
            connection.exportedObject = self
        } else if listener === workspaceListener {
            connection.exportedInterface = NSXPCInterface(
                with: KernelWorkspaceEndpoint.self
            )
            connection.exportedObject = workspaceService
        } else {
            return false
        }
        connection.resume()
        return true
    }
}
