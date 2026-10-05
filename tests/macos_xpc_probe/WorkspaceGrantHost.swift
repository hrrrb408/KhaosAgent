import Darwin
import Foundation

@main
struct WorkspaceGrantHost {
    static func main() {
        let listener = NSXPCListener.service()
        let delegate = WorkspaceGrantHostDelegate()
        listener.delegate = delegate
        listener.resume()
        RunLoop.main.run()
    }
}

private final class WorkspaceGrantHostDelegate: NSObject, NSXPCListenerDelegate {
    private let service = WorkspaceGrantHostService()

    func listener(
        _ listener: NSXPCListener,
        shouldAcceptNewConnection connection: NSXPCConnection
    ) -> Bool {
        guard XPCPeerIdentity.requirePeerIdentity(
            connection,
            requirementKey: "KhaosHostRequirement"
        ) else {
            return false
        }
        connection.exportedInterface = NSXPCInterface(
            with: WorkspaceGrantHostProbe.self
        )
        connection.exportedObject = service
        connection.resume()
        return true
    }
}

private final class WorkspaceGrantHostService: NSObject, WorkspaceGrantHostProbe {
    private let streamLock = NSLock()
    private var relayedWriter: FileHandle?

    func checkWorkspaceWrite(
        _ path: String,
        _ kernelServiceName: String,
        withReply reply: @escaping (String) -> Void
    ) {
        guard path.hasPrefix("/"), path.utf8.count <= 4096 else {
            reply("untrusted-xpc-workspace-write=invalid-path")
            return
        }

        let containerWrite = writeControlFileInContainer()
        let descriptor = Darwin.open(
            path,
            O_WRONLY | O_CLOEXEC | O_NOFOLLOW
        )
        let workspaceWrite: String
        if descriptor >= 0 {
            Darwin.close(descriptor)
            workspaceWrite = "allowed"
        } else {
            workspaceWrite = "denied:\(errno)"
        }
        let kernelBootstrap = KernelBootstrapPeerProbe.status(
            serviceName: kernelServiceName
        )
        reply(
            "untrusted-xpc-container-write=\(containerWrite)\n"
                + "untrusted-xpc-workspace-write=\(workspaceWrite)\n"
                + "untrusted-xpc-kernel-bootstrap=\(kernelBootstrap)"
        )
    }

    func createRelayedInvocationStream(
        _ requestPrefix: Data,
        withReply reply: @escaping (FileHandle?) -> Void
    ) {
        let maximumPrefix = KernelWorkspaceXPC.maximumRequestFrameBytes
            + KernelWorkspaceXPC.transferLengthBytes
        guard !requestPrefix.isEmpty, requestPrefix.count <= maximumPrefix else {
            reply(nil)
            return
        }

        streamLock.lock()
        guard relayedWriter == nil else {
            streamLock.unlock()
            reply(nil)
            return
        }
        var sockets: [Int32] = [-1, -1]
        guard socketpair(AF_UNIX, SOCK_STREAM, 0, &sockets) == 0 else {
            streamLock.unlock()
            reply(nil)
            return
        }
        let reader = FileHandle(fileDescriptor: sockets[0], closeOnDealloc: true)
        let writer = FileHandle(fileDescriptor: sockets[1], closeOnDealloc: true)
        var noSignal: Int32 = 1
        guard setsockopt(
            writer.fileDescriptor,
            SOL_SOCKET,
            SO_NOSIGPIPE,
            &noSignal,
            socklen_t(MemoryLayout<Int32>.size)
        ) == 0 else {
            reader.closeFile()
            writer.closeFile()
            streamLock.unlock()
            reply(nil)
            return
        }
        do {
            try writer.write(contentsOf: requestPrefix)
            guard Darwin.shutdown(writer.fileDescriptor, SHUT_WR) == 0 else {
                throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
            }
        } catch {
            reader.closeFile()
            writer.closeFile()
            streamLock.unlock()
            reply(nil)
            return
        }
        relayedWriter = writer
        streamLock.unlock()
        reply(reader)
    }

    func closeRelayedInvocationStream(withReply reply: @escaping () -> Void) {
        streamLock.lock()
        let writer = relayedWriter
        relayedWriter = nil
        streamLock.unlock()
        writer?.closeFile()
        reply()
    }

    private func writeControlFileInContainer() -> String {
        do {
            let directory = try FileManager.default.url(
                for: .applicationSupportDirectory,
                in: .userDomainMask,
                appropriateFor: nil,
                create: true
            )
            let path = directory.appendingPathComponent(
                "KhaosWorkspaceGrantProbe-\(UUID().uuidString)"
            )
            defer { try? FileManager.default.removeItem(at: path) }
            try Data("writable".utf8).write(to: path)
            return "allowed"
        } catch {
            return "denied"
        }
    }
}
