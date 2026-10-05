import Darwin
import Foundation

@main
private struct SnapshotBrokerSandboxProbeService {
    static func main() {
        guard let identifier = Bundle.main.object(
            forInfoDictionaryKey: "KhaosKernelContainerIdentifier"
        ) as? String else {
            FileHandle.standardError.write(
                Data("broker-sandbox-probe=configuration_failed\n".utf8)
            )
            exit(EXIT_FAILURE)
        }
        do {
            try KernelSnapshotBrokerSandbox.apply(kernelIdentifier: identifier)
        } catch {
            FileHandle.standardError.write(
                Data("broker-sandbox-probe=sandbox_failed\n".utf8)
            )
            exit(EXIT_FAILURE)
        }

        let listener = NSXPCListener.service()
        let delegate = ServiceDelegate()
        listener.delegate = delegate
        listener.resume()
        withExtendedLifetime(delegate) {
            RunLoop.main.run()
        }
    }
}

private final class ServiceDelegate: NSObject, NSXPCListenerDelegate {
    private let endpoint = ProbeEndpoint()

    func listener(
        _ listener: NSXPCListener,
        shouldAcceptNewConnection connection: NSXPCConnection
    ) -> Bool {
        connection.exportedInterface = NSXPCInterface(
            with: SnapshotBrokerSandboxProbeEndpoint.self
        )
        connection.exportedObject = endpoint
        connection.resume()
        return true
    }
}

private final class ProbeEndpoint: NSObject, SnapshotBrokerSandboxProbeEndpoint {
    func probe(
        _ version: Int,
        readPath: String,
        aliasReadPath: String,
        writePath: String,
        directoryPath: String,
        temporaryWritePath: String,
        temporaryExecutablePath: String,
        privateTemporaryWritePath: String,
        tmpAliasWritePath: String,
        sharedExecutablePath: String,
        packageExecutablePath: String,
        packageAliasExecutablePath: String,
        packageWritePath: String,
        packageAliasWritePath: String,
        kernelExecutablePath: String,
        targetProcessID: Int32,
        loopbackPort: Int32,
        withReply reply: @escaping (Data) -> Void
    ) {
        guard version == 1,
              readPath.utf8.count <= 4096,
              aliasReadPath.utf8.count <= 4096,
              writePath.utf8.count <= 4096,
              directoryPath.utf8.count <= 4096,
              temporaryWritePath.utf8.count <= 4096,
              temporaryExecutablePath.utf8.count <= 4096,
              privateTemporaryWritePath.utf8.count <= 4096,
              tmpAliasWritePath.utf8.count <= 4096,
              sharedExecutablePath.utf8.count <= 4096,
              packageExecutablePath.utf8.count <= 4096,
              packageAliasExecutablePath.utf8.count <= 4096,
              packageWritePath.utf8.count <= 4096,
              packageAliasWritePath.utf8.count <= 4096,
              kernelExecutablePath.utf8.count <= 4096,
              targetProcessID > 0,
              (1...65535).contains(loopbackPort) else {
            reply(Data("invalid_request".utf8))
            return
        }

        var result: [String: Int32] = [
            "external_read_errno": readErrno(readPath),
            "external_alias_read_errno": readErrno(aliasReadPath),
            "external_metadata_errno": metadataErrno(readPath),
            "external_write_errno": createErrno(writePath),
            "external_chmod_errno": chmodErrno(directoryPath),
            "temporary_write_errno": createErrno(temporaryWritePath),
            "temporary_executable_spawn_errno": spawnErrno(
                temporaryExecutablePath
            ),
            "private_temporary_write_errno": createErrno(privateTemporaryWritePath),
            "private_temporary_metadata_errno": metadataErrno(
                URL(fileURLWithPath: privateTemporaryWritePath)
                    .deletingLastPathComponent().path
            ),
            "private_temporary_existence_errno": (
                Darwin.access(
                    URL(fileURLWithPath: privateTemporaryWritePath)
                        .deletingLastPathComponent().path,
                    F_OK
                ) == 0 ? 0 : errno
            ),
            "tmp_alias_write_errno": createErrno(tmpAliasWritePath),
            "shared_root_executable_spawn_errno": spawnErrno(sharedExecutablePath),
            "kernel_write_open_errno": openErrno(kernelExecutablePath),
            "external_process_signal_zero_errno": signalZeroErrno(targetProcessID),
            "same_sandbox_child_cancel_errno": cancelSameSandboxChild(),
            "loopback_connect_errno": connectErrno(port: UInt16(loopbackPort)),
        ]
        if !packageExecutablePath.isEmpty {
            result["package_manager_executable_spawn_errno"] =
                spawnErrno(packageExecutablePath)
        }
        if !packageAliasExecutablePath.isEmpty {
            result["package_manager_alias_executable_spawn_errno"] =
                spawnErrno(packageAliasExecutablePath)
        }
        if !packageWritePath.isEmpty {
            result["package_manager_write_errno"] = createErrno(packageWritePath)
        }
        if !packageAliasWritePath.isEmpty {
            result["package_manager_alias_write_errno"] =
                createErrno(packageAliasWritePath)
        }
        let data = (try? JSONSerialization.data(withJSONObject: result)) ?? Data()
        reply(data)
    }

    private func readErrno(_ path: String) -> Int32 {
        let descriptor = Darwin.open(path, O_RDONLY | O_CLOEXEC)
        guard descriptor >= 0 else { return errno }
        defer { _ = Darwin.close(descriptor) }
        var byte: UInt8 = 0
        return Darwin.read(descriptor, &byte, 1) < 0 ? errno : 0
    }

    private func metadataErrno(_ path: String) -> Int32 {
        var info = stat()
        return Darwin.lstat(path, &info) == 0 ? 0 : errno
    }

    private func createErrno(_ path: String) -> Int32 {
        let descriptor = Darwin.open(
            path,
            O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC,
            S_IRUSR | S_IWUSR
        )
        guard descriptor >= 0 else { return errno }
        _ = Darwin.close(descriptor)
        return 0
    }

    private func chmodErrno(_ path: String) -> Int32 {
        Darwin.chmod(path, 0o711) == 0 ? 0 : errno
    }

    private func openErrno(_ path: String) -> Int32 {
        let descriptor = Darwin.open(path, O_WRONLY | O_CLOEXEC)
        guard descriptor >= 0 else { return errno }
        _ = Darwin.close(descriptor)
        return 0
    }

    private func spawnErrno(_ path: String) -> Int32 {
        var process: pid_t = 0
        let argument = strdup(path)
        guard let argument else { return ENOMEM }
        defer { free(argument) }
        var arguments: [UnsafeMutablePointer<CChar>?] = [argument, nil]
        let status = path.withCString {
            Darwin.posix_spawn(&process, $0, nil, nil, &arguments, environ)
        }
        if status == 0 {
            var waitStatus: Int32 = 0
            _ = Darwin.waitpid(process, &waitStatus, 0)
        }
        return status
    }

    private func connectErrno(port: UInt16) -> Int32 {
        let descriptor = Darwin.socket(AF_INET, SOCK_STREAM, 0)
        guard descriptor >= 0 else { return errno }
        defer { _ = Darwin.close(descriptor) }

        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = port.bigEndian
        address.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))

        let result = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.connect(
                    descriptor,
                    $0,
                    socklen_t(MemoryLayout<sockaddr_in>.size)
                )
            }
        }
        return result == 0 ? 0 : errno
    }

    private func signalZeroErrno(_ processID: Int32) -> Int32 {
        Darwin.kill(pid_t(processID), 0) == 0 ? 0 : errno
    }

    private func cancelSameSandboxChild() -> Int32 {
        var cancellationRequested = false
        var childWasReaped = false
        do {
            _ = try KernelSnapshotBrokerToolRunner.run(
                executable: "/bin/sleep",
                arguments: ["1"],
                environment: ["PATH": "/usr/bin:/bin"],
                currentDirectory: URL(fileURLWithPath: "/", isDirectory: true),
                timeout: 3,
                outputLimit: 1024,
                isCancelled: { cancellationRequested },
                processStarted: { _ in cancellationRequested = true },
                processFinished: { _ in childWasReaped = true }
            )
            return EIO
        } catch KernelSnapshotBrokerToolFailure.cancelled {
            return childWasReaped ? 0 : EIO
        } catch {
            return EIO
        }
    }
}
