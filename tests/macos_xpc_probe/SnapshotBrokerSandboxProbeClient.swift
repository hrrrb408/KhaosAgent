import Foundation

@main
private struct SnapshotBrokerSandboxProbeClient {
    static func main() {
        guard CommandLine.arguments.count == 17,
              let targetProcessID = Int32(CommandLine.arguments[15]),
              let port = Int32(CommandLine.arguments[16]) else {
            fputs("snapshot-broker-sandbox-probe=invalid_arguments\n", stderr)
            exit(EXIT_FAILURE)
        }

        let connection = NSXPCConnection(
            serviceName: "org.khaos.Seed.KernelSnapshotBroker"
        )
        connection.remoteObjectInterface = NSXPCInterface(
            with: SnapshotBrokerSandboxProbeEndpoint.self
        )
        connection.resume()

        let semaphore = DispatchSemaphore(value: 0)
        let lock = NSLock()
        var response: Data?
        var completed = false
        let finish: (Data?) -> Void = { value in
            lock.lock()
            let shouldFinish = !completed
            if shouldFinish {
                response = value
                completed = true
            }
            lock.unlock()
            if shouldFinish { semaphore.signal() }
        }

        let proxy = connection.remoteObjectProxyWithErrorHandler { _ in
            finish(nil)
        } as? SnapshotBrokerSandboxProbeEndpoint
        proxy?.probe(
            1,
            readPath: CommandLine.arguments[1],
            aliasReadPath: CommandLine.arguments[2],
            writePath: CommandLine.arguments[3],
            directoryPath: CommandLine.arguments[4],
            temporaryWritePath: CommandLine.arguments[5],
            temporaryExecutablePath: CommandLine.arguments[6],
            privateTemporaryWritePath: CommandLine.arguments[7],
            tmpAliasWritePath: CommandLine.arguments[8],
            sharedExecutablePath: CommandLine.arguments[9],
            packageExecutablePath: CommandLine.arguments[10],
            packageAliasExecutablePath: CommandLine.arguments[11],
            packageWritePath: CommandLine.arguments[12],
            packageAliasWritePath: CommandLine.arguments[13],
            kernelExecutablePath: CommandLine.arguments[14],
            targetProcessID: targetProcessID,
            loopbackPort: port,
            withReply: finish
        )

        guard semaphore.wait(timeout: .now() + 10) == .success else {
            connection.invalidate()
            fputs("snapshot-broker-sandbox-probe=timeout\n", stderr)
            exit(EXIT_FAILURE)
        }
        connection.invalidate()

        lock.lock()
        let result = response
        lock.unlock()
        guard let result else {
            fputs("snapshot-broker-sandbox-probe=xpc_error\n", stderr)
            exit(EXIT_FAILURE)
        }
        FileHandle.standardOutput.write(result)
        FileHandle.standardOutput.write(Data("\n".utf8))
    }
}
