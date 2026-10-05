import Darwin
import Foundation

// The Kernel keeps its single-operation slot until cancellation and APFS teardown finish.
private let kernelWorkspaceRetryWindowSeconds: TimeInterval = 75

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
    func runUnscopedPythonRunner(
        snapshotPath: String,
        siblingPath: String,
        outsidePath: String,
        networkPort: Int,
        withReply reply: @escaping (String) -> Void
    )
}

@objc protocol RunnerBootstrap {
    func runnerEndpoint(withReply reply: @escaping (NSXPCListenerEndpoint) -> Void)
}

@objc protocol KernelProbe {
    func readUnscopedInput(_ path: String, withReply reply: @escaping (String) -> Void)
    func readInput(_ bookmark: Data, withReply reply: @escaping (String) -> Void)
}

@objc protocol SpoofBootstrap {
    func spoofEndpoint(withReply reply: @escaping (NSXPCListenerEndpoint) -> Void)
}

@objc protocol HostClientProbe: XPCPeerIdentityProbe {
    func runProbe(
        _ kernelEndpoint: NSXPCListenerEndpoint,
        kernelExecutionEndpoint: NSXPCListenerEndpoint,
        runnerEndpoint: NSXPCListenerEndpoint,
        pluginAEndpoint: NSXPCListenerEndpoint,
        pluginBEndpoint: NSXPCListenerEndpoint,
        spoofEndpoint: NSXPCListenerEndpoint,
        outsidePath: String,
        networkPort: Int,
        selectedWorkspaceInput: String,
        withReply reply: @escaping (String, Bool) -> Void
    )
    func startKernelWorkspaceRequest(
        _ endpoint: NSXPCListenerEndpoint,
        runID: String,
        withReply reply: @escaping (Int32) -> Void
    )
    func recoverKernelWorkspace(
        _ endpoint: NSXPCListenerEndpoint,
        runID: String,
        withReply reply: @escaping (String, Bool) -> Void
    )
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

private final class KernelWorkspaceEndpointCallCounter: NSObject,
    KernelWorkspaceEndpoint
{
    private(set) var runInvoked = false

    func setSnapshotBrokerEndpoint(
        _ version: Int,
        endpoint: NSXPCListenerEndpoint,
        withReply reply: @escaping (Bool) -> Void
    ) {
        reply(false)
    }

    func runWorkspaceCommand(
        _ version: Int,
        requestIDHigh: UInt64,
        requestIDLow: UInt64,
        invocationStream: FileHandle,
        withReply reply: @escaping (Data) -> Void
    ) {
        runInvoked = true
        invocationStream.closeFile()
        reply(Data())
    }

    func cancelWorkspaceCommand(
        _ version: Int,
        requestIDHigh: UInt64,
        requestIDLow: UInt64,
        withReply reply: @escaping (Data) -> Void
    ) {
        reply(Data())
    }
}

final class HostClientService: NSObject, HostClientProbe {
    private let kernelConnectionLock = NSLock()
    private var activeKernelConnection: NSXPCConnection?

    func peerIdentity(withReply reply: @escaping (String) -> Void) {
        reply("peer=accepted")
    }

    func runProbe(
        _ kernelEndpoint: NSXPCListenerEndpoint,
        kernelExecutionEndpoint: NSXPCListenerEndpoint,
        runnerEndpoint: NSXPCListenerEndpoint,
        pluginAEndpoint: NSXPCListenerEndpoint,
        pluginBEndpoint: NSXPCListenerEndpoint,
        spoofEndpoint: NSXPCListenerEndpoint,
        outsidePath: String,
        networkPort: Int,
        selectedWorkspaceInput: String,
        withReply reply: @escaping (String, Bool) -> Void
    ) {
        do {
            let report = try Host.runProbe(
                kernelEndpoint: kernelEndpoint,
                kernelExecutionEndpoint: kernelExecutionEndpoint,
                runnerEndpoint: runnerEndpoint,
                pluginAEndpoint: pluginAEndpoint,
                pluginBEndpoint: pluginBEndpoint,
                spoofEndpoint: spoofEndpoint,
                outsidePath: outsidePath,
                networkPort: networkPort,
                selectedWorkspaceInput: selectedWorkspaceInput
            )
            reply(report, true)
        } catch {
            reply(String(describing: error), false)
        }
    }

    func startKernelWorkspaceRequest(
        _ endpoint: NSXPCListenerEndpoint,
        runID: String,
        withReply reply: @escaping (Int32) -> Void
    ) {
        do {
            let fixtures = try CallerCrashFixtures(runID: runID)
            let bookmark = try fixtures.crashingBookmark()
            let connection = NSXPCConnection(listenerEndpoint: endpoint)
            connection.remoteObjectInterface = NSXPCInterface(
                with: KernelWorkspaceEndpoint.self
            )
            connection.resume()
            guard let proxy = connection.remoteObjectProxyWithErrorHandler({ _ in })
                as? KernelWorkspaceEndpoint else {
                connection.invalidate()
                reply(-1)
                return
            }

            kernelConnectionLock.lock()
            activeKernelConnection = connection
            kernelConnectionLock.unlock()
            try KernelWorkspaceXPC.submit(
                proxy,
                request: WorkspaceProbeRequest.forWorkspace(
                    fixtures.crashingWorkspace,
                    timeoutSeconds: 30
                ),
                bookmark: bookmark
            ) { _ in }
            let callerPID = Int32(getpid())
            DispatchQueue.global(qos: .userInitiated).async {
                let deadline = Date().addingTimeInterval(45)
                while Date() < deadline {
                    if FileManager.default.fileExists(
                        atPath: fixtures.descriptorMarker.path
                    ) {
                        // Kill only after the Kernel has admitted the workspace request.
                        Thread.sleep(forTimeInterval: 4)
                        _ = Darwin.kill(callerPID, SIGKILL)
                        return
                    }
                    Thread.sleep(forTimeInterval: 0.05)
                }
            }
            reply(callerPID)
        } catch {
            reply(-1)
        }
    }

    func recoverKernelWorkspace(
        _ endpoint: NSXPCListenerEndpoint,
        runID: String,
        withReply reply: @escaping (String, Bool) -> Void
    ) {
        do {
            let fixtures = try CallerCrashFixtures(runID: runID)
            let bookmark = try fixtures.recoveryBookmark()
            let output = try Host.recoverKernelWorkspace(
                endpoint: endpoint,
                bookmark: bookmark,
                workspace: fixtures.recoveryWorkspace
            )
            try fixtures.verifyRecovery(output)
            try FileManager.default.removeItem(at: fixtures.runRoot)
            reply(fixtures.report, true)
        } catch {
            reply(String(describing: error), false)
        }
    }
}

private struct CallerCrashFixtures {
    let runRoot: URL
    let crashingWorkspace: URL
    let crashingDescriptor: URL
    let recoveryWorkspace: URL
    let recoveryDescriptor: URL
    let descriptorMarker: URL

    var report: String {
        "xpc-kernel-caller-process=terminated\n"
            + "xpc-kernel-caller-connection=interrupted\n"
            + "xpc-kernel-after-caller-crash=healthy\n"
            + "xpc-kernel-crash-no-writeback=verified"
    }

    init(runID: String) throws {
        guard let identifier = UUID(uuidString: runID) else {
            throw ProbeError.invalidArguments
        }
        let support = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        )[0]
        runRoot = support
            .appendingPathComponent("KhaosXPCProbe", isDirectory: true)
            .appendingPathComponent("caller-crash-\(identifier.uuidString)", isDirectory: true)
        let crashingGrantRoot = runRoot.appendingPathComponent(
            "crashing-grant", isDirectory: true
        )
        crashingWorkspace = crashingGrantRoot.appendingPathComponent(
            "kernel-workspace", isDirectory: true
        )
        crashingDescriptor = crashingGrantRoot.appendingPathComponent(
            "kernel-descriptor-scope", isDirectory: true
        )
        let recoveryGrantRoot = runRoot.appendingPathComponent(
            "recovery-grant", isDirectory: true
        )
        recoveryWorkspace = recoveryGrantRoot.appendingPathComponent(
            "kernel-workspace", isDirectory: true
        )
        recoveryDescriptor = recoveryGrantRoot.appendingPathComponent(
            "kernel-descriptor-scope", isDirectory: true
        )
        descriptorMarker = crashingDescriptor.appendingPathComponent(
            "descriptor-probe-started.txt"
        )
        for directory in [
            crashingWorkspace,
            crashingDescriptor,
            recoveryWorkspace,
            recoveryDescriptor,
        ] {
            try FileManager.default.createDirectory(
                at: directory,
                withIntermediateDirectories: true
            )
        }
        try Data("xpc-input-disconnect".utf8).write(
            to: crashingWorkspace.appendingPathComponent("input.txt")
        )
        for directory in [crashingDescriptor, recoveryWorkspace, recoveryDescriptor] {
            try Data("xpc-input".utf8).write(
                to: directory.appendingPathComponent("input.txt")
            )
        }
        try Data("sibling-secret".utf8).write(
            to: crashingGrantRoot.appendingPathComponent("sibling-secret.txt")
        )
        try Data("sibling-secret".utf8).write(
            to: recoveryGrantRoot.appendingPathComponent("sibling-secret.txt")
        )
    }

    func crashingBookmark() throws -> Data {
        try crashingWorkspace.deletingLastPathComponent().bookmarkData(
            options: [], includingResourceValuesForKeys: nil, relativeTo: nil
        )
    }

    func recoveryBookmark() throws -> Data {
        try recoveryWorkspace.deletingLastPathComponent().bookmarkData(
            options: [], includingResourceValuesForKeys: nil, relativeTo: nil
        )
    }

    func verifyRecovery(_ output: String) throws {
        guard output.contains("kernel-workspace-exit=0"),
              !FileManager.default.fileExists(
                atPath: crashingWorkspace.appendingPathComponent("output.txt").path
              ),
              !FileManager.default.fileExists(
                atPath: crashingWorkspace.appendingPathComponent("kernel-bypass.txt").path
              ),
              try String(
                contentsOf: recoveryWorkspace.appendingPathComponent("output.txt"),
                encoding: .utf8
              ) == "committed:xpc-input"
        else {
            throw ProbeError.hostClientFailed(
                "caller-crash recovery invariant failed: " + String(output.prefix(3000))
            )
        }
    }
}

final class HostClientDelegate: NSObject, NSXPCListenerDelegate {
    private let service = HostClientService()

    func listener(
        _ listener: NSXPCListener,
        shouldAcceptNewConnection connection: NSXPCConnection
    ) -> Bool {
        guard XPCPeerIdentity.requirePeerIdentity(
            connection,
            requirementKey: "KhaosCallerRequirement"
        ) else {
            return false
        }
        connection.exportedInterface = NSXPCInterface(with: HostClientProbe.self)
        connection.exportedObject = service
        connection.resume()
        return true
    }
}

@main
struct Host {
    static func main() {
#if KHAOS_XPC_CLIENT
        let delegate = HostClientDelegate()
        let listener = NSXPCListener.service()
        listener.delegate = delegate
        listener.resume()
        RunLoop.main.run()
#else
        do {
            if CommandLine.arguments.count == 4,
               CommandLine.arguments[1] == "--verify-kernel-bundle-immutability" {
                try verifyKernelBundleMutationDenial(
                    at: CommandLine.arguments[2],
                    serviceBundlePath: CommandLine.arguments[3]
                )
                return
            }
            try run()
        } catch {
            FileHandle.standardError.write(Data("host-error: \(error)\n".utf8))
            exit(2)
        }
#endif
    }

    private static func verifyKernelBundleMutationDenial(
        at path: String,
        serviceBundlePath: String
    ) throws {
        let fileManager = FileManager.default
        let appSupport = try fileManager.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let probeDirectory = appSupport.appendingPathComponent(
            "KhaosKernelWriteProbe-\(UUID().uuidString)",
            isDirectory: true
        )
        try fileManager.createDirectory(
            at: probeDirectory,
            withIntermediateDirectories: true
        )
        defer { try? fileManager.removeItem(at: probeDirectory) }

        // The positive control distinguishes bundle-write denial from a general I/O failure.
        let controlFile = probeDirectory.appendingPathComponent("control")
        try Data("writable".utf8).write(to: controlFile)
        let controlDescriptor = open(controlFile.path, O_WRONLY | O_CLOEXEC)
        guard controlDescriptor >= 0 else {
            throw NSError(
                domain: "KhaosKernelWriteProbe", code: Int(errno), userInfo: nil
            )
        }
        close(controlDescriptor)

        let protectedFile = URL(fileURLWithPath: path)
        let serviceBundle = URL(fileURLWithPath: serviceBundlePath)
        try requireSameDevice(probeDirectory.path, protectedFile.path)
        try requireSameDevice(probeDirectory.path, serviceBundle.path)

        try requireAppSandboxDenial("kernel-helper-open-write") {
            let descriptor = open(path, O_WRONLY | O_CLOEXEC)
            guard descriptor >= 0 else { return errno }
            close(descriptor)
            return nil
        }

        let createdFile = protectedFile.deletingLastPathComponent()
            .appendingPathComponent(".khaos-create-\(UUID().uuidString)")
        defer { _ = unlink(createdFile.path) }
        try requireAppSandboxDenial("kernel-helper-create") {
            let descriptor = open(
                createdFile.path,
                O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC,
                0o600
            )
            guard descriptor >= 0 else { return errno }
            close(descriptor)
            return nil
        }

        try requireAppSandboxDenial("kernel-helper-chmod") {
            guard chmod(path, 0o600) == 0 else { return errno }
            return nil
        }

        let hardlink = probeDirectory.appendingPathComponent("hardlink")
        defer { _ = unlink(hardlink.path) }
        try requireAppSandboxDenial("kernel-helper-hardlink") {
            guard link(path, hardlink.path) == 0 else { return errno }
            return nil
        }

        let swapSource = probeDirectory.appendingPathComponent("swap-source")
        try Data("replacement".utf8).write(to: swapSource)
        try requireAppSandboxDenial("kernel-helper-swap") {
            let result = swapSource.path.withCString { source in
                path.withCString { destination in
                    renameatx_np(
                        AT_FDCWD,
                        source,
                        AT_FDCWD,
                        destination,
                        UInt32(RENAME_SWAP)
                    )
                }
            }
            guard result == 0 else { return errno }
            return nil
        }

        let renameSource = probeDirectory.appendingPathComponent("rename-source")
        try Data("replacement".utf8).write(to: renameSource)
        try requireAppSandboxDenial("kernel-helper-rename") {
            guard rename(renameSource.path, path) == 0 else { return errno }
            return nil
        }

        let symlinkSource = probeDirectory.appendingPathComponent("symlink-source")
        defer { _ = unlink(symlinkSource.path) }
        guard symlink("/dev/null", symlinkSource.path) == 0 else {
            throw NSError(domain: "KhaosKernelWriteProbe", code: Int(errno))
        }
        try requireAppSandboxDenial("kernel-helper-symlink-replace") {
            guard rename(symlinkSource.path, path) == 0 else { return errno }
            return nil
        }

        try requireAppSandboxDenial("kernel-helper-unlink") {
            guard unlink(path) == 0 else { return errno }
            return nil
        }

        let bundleReplacement = probeDirectory.appendingPathComponent(
            "replacement-bundle",
            isDirectory: true
        )
        try fileManager.createDirectory(
            at: bundleReplacement,
            withIntermediateDirectories: false
        )
        try requireAppSandboxDenial("kernel-bundle-swap") {
            let result = bundleReplacement.path.withCString { source in
                serviceBundle.path.withCString { destination in
                    renameatx_np(
                        AT_FDCWD,
                        source,
                        AT_FDCWD,
                        destination,
                        UInt32(RENAME_SWAP)
                    )
                }
            }
            guard result == 0 else { return errno }
            return nil
        }

        print("app-container-write=allowed")
    }

    private static func requireAppSandboxDenial(
        _ operation: String,
        attempt: () -> Int32?
    ) throws {
        guard let error = attempt() else {
            throw NSError(
                domain: "KhaosKernelWriteProbe",
                code: Int(EPERM),
                userInfo: [NSLocalizedDescriptionKey: "\(operation) unexpectedly succeeded"]
            )
        }
        guard error == EPERM || error == EACCES else {
            throw NSError(
                domain: "KhaosKernelWriteProbe",
                code: Int(error),
                userInfo: [NSLocalizedDescriptionKey: "\(operation) was not denied by App Sandbox"]
            )
        }
        print("\(operation)=denied:\(error)")
    }

    private static func requireSameDevice(_ leftPath: String, _ rightPath: String) throws {
        var left = stat()
        var right = stat()
        let leftResult = leftPath.withCString { lstat($0, &left) }
        let rightResult = rightPath.withCString { lstat($0, &right) }
        guard leftResult == 0, rightResult == 0 else {
            throw NSError(domain: "KhaosKernelWriteProbe", code: Int(errno))
        }
        guard left.st_dev == right.st_dev else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(EXDEV))
        }
    }

    private static func run() throws {
        guard CommandLine.arguments.count == 6,
              !CommandLine.arguments[1].isEmpty,
              let networkPort = Int(CommandLine.arguments[3]),
              ["yes", "no"].contains(CommandLine.arguments[5])
        else {
            throw ProbeError.invalidArguments
        }

        let bundleID = CommandLine.arguments[1]
        let kernelEndpoint = try requestKernelEndpoint(
            serviceName: "\(bundleID).Kernel"
        )
        let kernelExecutionEndpoint = try requestKernelEndpoint(
            serviceName: "\(bundleID).KernelExecution"
        )
        let mainRunnerEndpoint = try runnerEndpoint(
            serviceName: "\(bundleID).Runner"
        )
        let pluginAEndpoint = try runnerEndpoint(
            serviceName: "\(bundleID).PluginA"
        )
        let pluginBEndpoint = try runnerEndpoint(
            serviceName: "\(bundleID).PluginB"
        )
        let spoofEndpoint = try spoofEndpoint(
            serviceName: "\(bundleID).Spoof"
        )
        let connection = NSXPCConnection(
            serviceName: "\(bundleID).HostClient"
        )
        connection.remoteObjectInterface = NSXPCInterface(
            with: HostClientProbe.self
        )
        connection.resume()
        defer { connection.invalidate() }

        let semaphore = DispatchSemaphore(value: 0)
        var output = ""
        var succeeded = false
        var connectionError: String?
        let proxy = connection.remoteObjectProxyWithErrorHandler { error in
            connectionError = String(describing: error)
            semaphore.signal()
        } as? HostClientProbe
        guard let proxy else {
            throw ProbeError.invalidProxy
        }
        proxy.runProbe(
            kernelEndpoint,
            kernelExecutionEndpoint: kernelExecutionEndpoint,
            runnerEndpoint: mainRunnerEndpoint,
            pluginAEndpoint: pluginAEndpoint,
            pluginBEndpoint: pluginBEndpoint,
            spoofEndpoint: spoofEndpoint,
            outsidePath: CommandLine.arguments[2],
            networkPort: networkPort,
            selectedWorkspaceInput: CommandLine.arguments[4]
        ) { result, success in
            output = result
            succeeded = success
            semaphore.signal()
        }
        guard semaphore.wait(timeout: .now() + 190) == .success else {
            throw ProbeError.xpcTimeout
        }
        if let connectionError {
            throw ProbeError.hostClientFailed(connectionError)
        }
        guard succeeded else {
            throw ProbeError.hostClientFailed(output)
        }
        if CommandLine.arguments[5] == "yes" {
            let crashResult = try runKernelCallerCrashTest(
                proxy: proxy,
                helperConnection: connection,
                serviceName: "\(bundleID).HostClient",
                endpoint: kernelExecutionEndpoint
            )
            guard var report = try JSONSerialization.jsonObject(
                with: Data(output.utf8)
            ) as? [String: Any] else {
                throw ProbeError.hostClientFailed("invalid HostClient report")
            }
            report["kernel_workspace_caller_crash"] = crashResult
            let reportData = try JSONSerialization.data(
                withJSONObject: report,
                options: [.sortedKeys]
            )
            guard let reportOutput = String(data: reportData, encoding: .utf8) else {
                throw ProbeError.hostClientFailed("invalid HostClient report encoding")
            }
            output = reportOutput
        }
        FileHandle.standardOutput.write(Data(output.utf8))
        FileHandle.standardOutput.write(Data([0x0a]))
    }

    private static func runKernelCallerCrashTest(
        proxy: HostClientProbe,
        helperConnection: NSXPCConnection,
        serviceName: String,
        endpoint: NSXPCListenerEndpoint
    ) throws -> String {
        let runID = UUID().uuidString
        let interruption = DispatchSemaphore(value: 0)
        let interruptionLock = NSLock()
        var interrupted = false
        helperConnection.interruptionHandler = {
            interruptionLock.lock()
            let shouldSignal = !interrupted
            interrupted = true
            interruptionLock.unlock()
            if shouldSignal {
                interruption.signal()
            }
        }
        let callerPIDReply = DispatchSemaphore(value: 0)
        var callerPID: Int32 = -1
        proxy.startKernelWorkspaceRequest(
            endpoint,
            runID: runID
        ) { value in
            callerPID = value
            callerPIDReply.signal()
        }
        guard callerPIDReply.wait(timeout: .now() + 15) == .success,
              callerPID > 0,
              callerPID != getpid()
        else {
            throw ProbeError.hostClientFailed("Kernel caller did not start")
        }
        guard interruption.wait(timeout: .now() + 60) == .success else {
            throw ProbeError.hostClientFailed(
                "SIGKILL did not interrupt the XPC caller connection"
            )
        }

        let recoveryConnection = NSXPCConnection(serviceName: serviceName)
        recoveryConnection.remoteObjectInterface = NSXPCInterface(
            with: HostClientProbe.self
        )
        recoveryConnection.resume()
        defer { recoveryConnection.invalidate() }
        let recoveryProxy = recoveryConnection.remoteObjectProxyWithErrorHandler { _ in }
            as? HostClientProbe
        guard let recoveryProxy else {
            throw ProbeError.invalidProxy
        }
        let recoveryReply = DispatchSemaphore(value: 0)
        var recoveryOutput = ""
        var recoverySucceeded = false
        recoveryProxy.recoverKernelWorkspace(
            endpoint,
            runID: runID
        ) { output, succeeded in
            recoveryOutput = output
            recoverySucceeded = succeeded
            recoveryReply.signal()
        }
        guard recoveryReply.wait(timeout: .now() + 60) == .success,
              recoverySucceeded,
              recoveryOutput.contains("xpc-kernel-caller-process=terminated")
        else {
            throw ProbeError.hostClientFailed(
                "Kernel did not recover after its caller crashed: "
                    + String(recoveryOutput.prefix(600))
            )
        }
        return recoveryOutput
    }

    static func runProbe(
        kernelEndpoint: NSXPCListenerEndpoint,
        kernelExecutionEndpoint: NSXPCListenerEndpoint,
        runnerEndpoint: NSXPCListenerEndpoint,
        pluginAEndpoint: NSXPCListenerEndpoint,
        pluginBEndpoint: NSXPCListenerEndpoint,
        spoofEndpoint: NSXPCListenerEndpoint,
        outsidePath: String,
        networkPort: Int,
        selectedWorkspaceInput inputPath: String
    ) throws -> String {
        let support = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        )[0]
        let runRoot = support
            .appendingPathComponent("KhaosXPCProbe", isDirectory: true)
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: runRoot) }

        let snapshotA = runRoot.appendingPathComponent("plugin-a", isDirectory: true)
        let snapshotB = runRoot.appendingPathComponent("plugin-b", isDirectory: true)
        let executionGrantRoot = runRoot.appendingPathComponent(
            "kernel-execution-grant", isDirectory: true
        )
        let executionWorkspace = executionGrantRoot.appendingPathComponent(
            "kernel-workspace", isDirectory: true
        )
        // Keep hostile aliases out of the clean snapshot/commit fixture.
        let descriptorWorkspace = executionGrantRoot.appendingPathComponent(
            "kernel-descriptor-scope", isDirectory: true
        )
        let cancellationGrantRoot = runRoot.appendingPathComponent(
            "kernel-cancellation-grant", isDirectory: true
        )
        let cancellationWorkspace = cancellationGrantRoot.appendingPathComponent(
            "kernel-workspace", isDirectory: true
        )
        let cancellationDescriptorWorkspace = cancellationGrantRoot.appendingPathComponent(
            "kernel-descriptor-scope", isDirectory: true
        )
        let disconnectGrantRoot = runRoot.appendingPathComponent(
            "kernel-disconnect-grant", isDirectory: true
        )
        let disconnectWorkspace = disconnectGrantRoot.appendingPathComponent(
            "kernel-workspace", isDirectory: true
        )
        let disconnectDescriptorWorkspace = disconnectGrantRoot.appendingPathComponent(
            "kernel-descriptor-scope", isDirectory: true
        )
        let sibling = runRoot.appendingPathComponent("sibling-secret.txt")
        try FileManager.default.createDirectory(at: snapshotA, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: snapshotB, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(
            at: executionWorkspace,
            withIntermediateDirectories: true
        )
        try FileManager.default.createDirectory(
            at: descriptorWorkspace,
            withIntermediateDirectories: true
        )
        try FileManager.default.createDirectory(
            at: cancellationWorkspace,
            withIntermediateDirectories: true
        )
        try FileManager.default.createDirectory(
            at: cancellationDescriptorWorkspace,
            withIntermediateDirectories: true
        )
        try FileManager.default.createDirectory(
            at: disconnectWorkspace,
            withIntermediateDirectories: true
        )
        try FileManager.default.createDirectory(
            at: disconnectDescriptorWorkspace,
            withIntermediateDirectories: true
        )
        try Data("plugin-a-secret".utf8).write(to: snapshotA.appendingPathComponent("input.txt"))
        try Data("plugin-b-secret".utf8).write(to: snapshotB.appendingPathComponent("input.txt"))
        try Data("xpc-input".utf8).write(
            to: executionWorkspace.appendingPathComponent("input.txt")
        )
        try Data("xpc-input".utf8).write(
            to: descriptorWorkspace.appendingPathComponent("input.txt")
        )
        try Data("xpc-input-cancel".utf8).write(
            to: cancellationWorkspace.appendingPathComponent("input.txt")
        )
        try Data("xpc-input".utf8).write(
            to: cancellationDescriptorWorkspace.appendingPathComponent("input.txt")
        )
        try Data("xpc-input-disconnect".utf8).write(
            to: disconnectWorkspace.appendingPathComponent("input.txt")
        )
        try Data("xpc-input".utf8).write(
            to: disconnectDescriptorWorkspace.appendingPathComponent("input.txt")
        )
        try Data("sibling-secret".utf8).write(to: sibling)
        try Data("sibling-secret".utf8).write(
            to: executionGrantRoot.appendingPathComponent("sibling-secret.txt")
        )
        try Data("sibling-secret".utf8).write(
            to: cancellationGrantRoot.appendingPathComponent("sibling-secret.txt")
        )
        try Data("sibling-secret".utf8).write(
            to: disconnectGrantRoot.appendingPathComponent("sibling-secret.txt")
        )
        try FileManager.default.createSymbolicLink(
            at: descriptorWorkspace.appendingPathComponent("sibling-link"),
            withDestinationURL: executionGrantRoot.appendingPathComponent(
                "sibling-secret.txt"
            )
        )
        let siblingHardlink = descriptorWorkspace.appendingPathComponent(
            "sibling-hardlink"
        )
        var workspaceHardlinkStatus = "created"
        do {
            try FileManager.default.linkItem(
                at: executionGrantRoot.appendingPathComponent("sibling-secret.txt"),
                to: siblingHardlink
            )
        } catch {
            workspaceHardlinkStatus = "unavailable:\(error)"
        }

        let selectedWorkspaceInput = URL(fileURLWithPath: inputPath)
        let selectedWorkspaceRead: String
        do {
            selectedWorkspaceRead = "allowed:\(try read(selectedWorkspaceInput))"
        } catch {
            selectedWorkspaceRead = "denied:\(error)"
        }
        let unscopedKernelRead = try requestKernelUnscopedRead(
            endpoint: kernelEndpoint,
            path: snapshotA.appendingPathComponent("input.txt").path
        )
        let kernelRead = try requestKernelRead(
            endpoint: kernelEndpoint,
            snapshot: snapshotA
        )
        let kernelWorkspaceDisconnect = try requestKernelWorkspaceDisconnect(
            endpoint: kernelExecutionEndpoint,
            workspace: disconnectWorkspace,
            descriptorWorkspace: disconnectDescriptorWorkspace
        )
        let kernelWorkspaceExecution = try requestKernelWorkspaceExecution(
            endpoint: kernelExecutionEndpoint,
            workspace: executionWorkspace,
            descriptorWorkspace: descriptorWorkspace
        )
        let kernelWorkspaceCancellation = try requestKernelWorkspaceCancellation(
            endpoint: kernelExecutionEndpoint,
            workspace: cancellationWorkspace,
            descriptorWorkspace: cancellationDescriptorWorkspace
        )
        let unscopedPythonRunner = try requestUnscopedPythonRunner(
            endpoint: runnerEndpoint,
            snapshotPath: snapshotA.appendingPathComponent("input.txt").path,
            siblingPath: sibling.path,
            outsidePath: outsidePath,
            networkPort: networkPort
        )
        let first = try request(
            endpoint: runnerEndpoint,
            snapshot: snapshotA,
            sibling: sibling,
            outsidePath: outsidePath,
            otherRunnerStatePath: outsidePath,
            networkPort: networkPort,
            pluginID: "plugin-a"
        )
        let second = try request(
            endpoint: runnerEndpoint,
            snapshot: snapshotB,
            sibling: sibling,
            outsidePath: outsidePath,
            otherRunnerStatePath: try statePath(from: first),
            networkPort: networkPort,
            pluginID: "plugin-b"
        )
        let isolatedA = try request(
            endpoint: pluginAEndpoint,
            snapshot: snapshotA,
            sibling: sibling,
            outsidePath: outsidePath,
            otherRunnerStatePath: outsidePath,
            networkPort: networkPort,
            pluginID: "plugin-a"
        )
        let isolatedB = try request(
            endpoint: pluginBEndpoint,
            snapshot: snapshotB,
            sibling: sibling,
            outsidePath: outsidePath,
            otherRunnerStatePath: try statePath(from: isolatedA),
            networkPort: networkPort,
            pluginID: "plugin-b"
        )

        let spoofSnapshot = runRoot.appendingPathComponent(
            "spoof-target", isDirectory: true
        )
        try FileManager.default.createDirectory(
            at: spoofSnapshot,
            withIntermediateDirectories: true
        )
        try Data("spoof-input".utf8).write(
            to: spoofSnapshot.appendingPathComponent("input.txt")
        )
        let spoofStatus = try runSpoofClient(
            spoofEndpoint: spoofEndpoint,
            runnerEndpoint: runnerEndpoint,
            bookmark: try spoofSnapshot.bookmarkData(
                options: [],
                includingResourceValuesForKeys: nil,
                relativeTo: nil
            ),
            sibling: sibling,
            outsidePath: outsidePath,
            networkPort: networkPort
        )
        let spoofKernelStatus = try runSpoofKernelClient(
            spoofEndpoint: spoofEndpoint,
            kernelEndpoint: kernelEndpoint,
            bookmark: try snapshotA.bookmarkData(
                options: [],
                includingResourceValuesForKeys: nil,
                relativeTo: nil
            )
        )
        let spoofKernelExecutionStatus = try runSpoofKernelExecutionClient(
            spoofEndpoint: spoofEndpoint,
            kernelEndpoint: kernelExecutionEndpoint,
            workspace: executionWorkspace,
            descriptorWorkspace: descriptorWorkspace
        )

        let spoofOutput = spoofSnapshot.appendingPathComponent("runner-output.txt")
        let report: [String: String] = [
            "plugin_a": first,
            "plugin_b": second,
            "isolated_plugin_a": isolatedA,
            "isolated_plugin_b": isolatedB,
            "kernel_unscoped_read": unscopedKernelRead,
            "kernel_read": kernelRead,
            "kernel_workspace_disconnect": kernelWorkspaceDisconnect,
            "kernel_workspace_execution": kernelWorkspaceExecution,
            "kernel_workspace_cancellation": kernelWorkspaceCancellation,
            "kernel_workspace_disconnect_output": (try? read(
                disconnectWorkspace.appendingPathComponent("output.txt")
            )) ?? "missing",
            "kernel_descriptor_hardlink": workspaceHardlinkStatus,
            "kernel_workspace_output": (try? read(
                executionWorkspace.appendingPathComponent("output.txt")
            )) ?? "missing",
            "selected_workspace_direct_read": selectedWorkspaceRead,
            "kernel_workspace_bypass": FileManager.default.fileExists(
                atPath: executionWorkspace.appendingPathComponent("kernel-bypass.txt").path
            ) ? "present" : "missing",
            "spoof_kernel_status": spoofKernelStatus,
            "spoof_kernel_execution_status": spoofKernelExecutionStatus,
            "khaos_runner": unscopedPythonRunner,
            "spoof_status": spoofStatus,
            "spoof_output": (try? read(spoofOutput)) ?? "missing",
            "snapshot_a_output": try read(snapshotA.appendingPathComponent("runner-output.txt")),
            "sibling": try read(sibling),
        ]
        let data = try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys])
        guard let output = String(data: data, encoding: .utf8) else {
            throw ProbeError.invalidReport
        }
        return output
    }

    private static func request(
        endpoint: NSXPCListenerEndpoint,
        snapshot: URL,
        sibling: URL,
        outsidePath: String,
        otherRunnerStatePath: String,
        networkPort: Int,
        pluginID: String
    ) throws -> String {
        let (connection, proxy) = try connectRunner(endpoint: endpoint)
        defer { connection.invalidate() }
        let bookmark = try snapshot.bookmarkData(
            options: [],
            includingResourceValuesForKeys: nil,
            relativeTo: nil
        )
        var stale = false
        _ = try URL(
            resolvingBookmarkData: bookmark,
            options: [],
            relativeTo: nil,
            bookmarkDataIsStale: &stale
        )

        let semaphore = DispatchSemaphore(value: 0)
        var result = ""
        proxy.run(
            bookmark,
            siblingPath: sibling.path,
            outsidePath: outsidePath,
            otherRunnerStatePath: otherRunnerStatePath,
            networkPort: networkPort,
            pluginID: pluginID
        ) { value in
            result = "host-bookmark-stale=\(stale)\n" + value
            semaphore.signal()
        }
        guard semaphore.wait(timeout: .now() + 15) == .success else {
            throw ProbeError.xpcTimeout
        }
        return result
    }

    private static func requestKernelEndpoint(
        serviceName: String
    ) throws -> NSXPCListenerEndpoint {
        let bootstrapConnection = NSXPCConnection(serviceName: serviceName)
        bootstrapConnection.remoteObjectInterface = NSXPCInterface(
            with: KernelWorkspaceBootstrapEndpoint.self
        )
        bootstrapConnection.resume()
        defer { bootstrapConnection.invalidate() }
        let bootstrap = bootstrapConnection.remoteObjectProxyWithErrorHandler { error in
            FileHandle.standardError.write(Data("kernel-bootstrap-error: \(error)\n".utf8))
        } as? KernelWorkspaceBootstrapEndpoint
        guard let bootstrap else {
            throw ProbeError.invalidProxy
        }
        let endpointSemaphore = DispatchSemaphore(value: 0)
        var endpoint: NSXPCListenerEndpoint?
        bootstrap.kernelEndpoint { value in
            endpoint = value
            endpointSemaphore.signal()
        }
        guard endpointSemaphore.wait(timeout: .now() + 15) == .success,
              let endpoint
        else {
            throw ProbeError.xpcTimeout
        }
        return endpoint
    }

    private static func requestKernelRead(
        endpoint: NSXPCListenerEndpoint,
        snapshot: URL
    ) throws -> String {
        let connection = NSXPCConnection(listenerEndpoint: endpoint)
        connection.remoteObjectInterface = NSXPCInterface(with: KernelProbe.self)
        connection.resume()
        defer { connection.invalidate() }

        let proxy = connection.remoteObjectProxyWithErrorHandler { error in
            FileHandle.standardError.write(Data("kernel-xpc-error: \(error)\n".utf8))
        } as? KernelProbe
        guard let proxy else {
            throw ProbeError.invalidProxy
        }
        let bookmark = try snapshot.bookmarkData(
            options: [],
            includingResourceValuesForKeys: nil,
            relativeTo: nil
        )
        try relocateWorkspaceForBookmarkTest(snapshot)
        let semaphore = DispatchSemaphore(value: 0)
        var result = ""
        proxy.readInput(bookmark) { value in
            result = value
            semaphore.signal()
        }
        guard semaphore.wait(timeout: .now() + 15) == .success else {
            throw ProbeError.xpcTimeout
        }
        return result
    }

    private static func commonWorkspaceRoot(
        workspace: URL,
        descriptorWorkspace: URL
    ) throws -> URL {
        let root = workspace.deletingLastPathComponent().standardizedFileURL
        guard workspace.lastPathComponent == "kernel-workspace",
              descriptorWorkspace.lastPathComponent == "kernel-descriptor-scope",
              descriptorWorkspace.deletingLastPathComponent().standardizedFileURL == root
        else {
            throw ProbeError.invalidArguments
        }
        return root
    }

    fileprivate static func recoverKernelWorkspace(
        endpoint: NSXPCListenerEndpoint,
        bookmark: Data,
        workspace: URL
    ) throws -> String {
        let connection = NSXPCConnection(listenerEndpoint: endpoint)
        connection.remoteObjectInterface = NSXPCInterface(
            with: KernelWorkspaceEndpoint.self
        )
        connection.resume()
        defer { connection.invalidate() }
        let proxy = connection.remoteObjectProxyWithErrorHandler { _ in }
            as? KernelWorkspaceEndpoint
        guard let proxy else { throw ProbeError.invalidProxy }

        let result = try runKernelWorkspaceCommandWhenAvailable(
            proxy,
            bookmark: bookmark,
            request: WorkspaceProbeRequest.forWorkspace(workspace),
            timeoutSeconds: 45
        )
        guard let output = result.output, result.errorCode == nil else {
            throw ProbeError.hostClientFailed(
                "post-crash Kernel request failed: \(result.errorCode ?? "no output")"
            )
        }
        return output
    }

    private static func requestKernelWorkspaceExecution(
        endpoint: NSXPCListenerEndpoint,
        workspace: URL,
        descriptorWorkspace: URL
    ) throws -> String {
        let connection = NSXPCConnection(listenerEndpoint: endpoint)
        connection.remoteObjectInterface = NSXPCInterface(
            with: KernelWorkspaceEndpoint.self
        )
        connection.resume()
        defer { connection.invalidate() }

        let proxy = connection.remoteObjectProxyWithErrorHandler { error in
            FileHandle.standardError.write(
                Data("kernel-workspace-xpc-error: \(error)\n".utf8)
            )
        } as? KernelWorkspaceEndpoint
        guard let proxy else {
            throw ProbeError.invalidProxy
        }
        let workspaceRoot = try commonWorkspaceRoot(
            workspace: workspace,
            descriptorWorkspace: descriptorWorkspace
        )
        let bookmark = try workspaceRoot.bookmarkData(
            options: [], includingResourceValuesForKeys: nil, relativeTo: nil
        )
        let request = WorkspaceProbeRequest.forWorkspace(workspace)
        let streamPeerEvidence = try rejectMismatchedStreamPeer(
            request: request,
            requestID: KernelWorkspaceXPC.newRequestID(),
            bookmark: bookmark
        )
        let unsupportedVersion = try runKernelWorkspaceCommand(
            proxy,
            bookmark: bookmark,
            request: request,
            version: KernelWorkspaceXPC.version + 1,
            timeoutSeconds: 10
        )
        guard unsupportedVersion.errorCode == "unsupported_version" else {
            throw ProbeError.hostClientFailed("unsupported XPC version was accepted")
        }
        try verifyClientRejectsOversizedBookmark()
        let descriptorMarker = descriptorWorkspace.appendingPathComponent(
            "descriptor-probe-started.txt"
        )
        let oversizedRequestID = KernelWorkspaceXPC.newRequestID()
        let oversizedRequest = try retryKernelWorkspaceRequestWhenAvailable {
            try runInvalidInvocationStream(
                proxy,
                requestID: oversizedRequestID,
                requestFrame: nil,
                declaredRequestLength: KernelWorkspaceXPC.maximumRequestFrameBytes + 1
            )
        }
        guard oversizedRequest.errorCode == "invalid_request",
              !FileManager.default.fileExists(atPath: descriptorMarker.path)
        else {
            throw ProbeError.hostClientFailed(
                "oversized request frame was not rejected before execution: "
                    + "code=\(oversizedRequest.errorCode ?? "none"), "
                    + "marker=\(FileManager.default.fileExists(atPath: descriptorMarker.path))"
            )
        }
        let outerRequestID = KernelWorkspaceXPC.newRequestID()
        let mismatchedRequest = try request.encodeFrame(
            requestID: KernelWorkspaceXPC.newRequestID()
        )
        let mismatchedRequestResult = try retryKernelWorkspaceRequestWhenAvailable {
            try runInvalidInvocationStream(
                proxy,
                requestID: outerRequestID,
                requestFrame: mismatchedRequest,
                declaredRequestLength: mismatchedRequest.count
            )
        }
        guard mismatchedRequestResult.errorCode == "invalid_request",
              !FileManager.default.fileExists(atPath: descriptorMarker.path)
        else {
            throw ProbeError.hostClientFailed(
                "request ID mismatch was not rejected before execution"
            )
        }
        let invalidPayloadRequestID = KernelWorkspaceXPC.newRequestID()
        let invalidPayloadFrame = try WorkspaceProbeRequest.rawWorkspaceRequestFrame(
            requestID: invalidPayloadRequestID,
            payload: [
                "argv": [],
                "timeout_seconds": 10,
                "runner_source": "def run(): return 0",
                "workspace_read_scope": [],
                "workspace_write_scope": [],
            ]
        )
        let invalidPayloadResult = try retryKernelWorkspaceRequestWhenAvailable {
            try runInvalidInvocationStream(
                proxy,
                requestID: invalidPayloadRequestID,
                requestFrame: invalidPayloadFrame,
                declaredRequestLength: invalidPayloadFrame.count
            )
        }
        guard invalidPayloadResult.errorCode == "invalid_request",
              !FileManager.default.fileExists(atPath: descriptorMarker.path)
        else {
            throw ProbeError.hostClientFailed(
                "invalid workspace payload was not rejected before execution"
            )
        }
        let stalledResult = try retryKernelWorkspaceRequestWhenAvailable {
            try rejectStalledBookmarkStream(proxy, request: request)
        }
        guard stalledResult.errorCode == "invalid_bookmark" else {
            throw ProbeError.hostClientFailed(
                "stalled bookmark stream returned \(stalledResult.errorCode ?? "no error")"
            )
        }
        guard !FileManager.default.fileExists(atPath: descriptorMarker.path) else {
            throw ProbeError.hostClientFailed(
                "stalled bookmark stream started the descriptor probe"
            )
        }
        let oversizedResult = try retryKernelWorkspaceRequestWhenAvailable {
            try rejectOversizedBookmarkStream(proxy, request: request)
        }
        guard oversizedResult.errorCode?.hasPrefix("invalid_bookmark") == true else {
            throw ProbeError.hostClientFailed(
                "oversized bookmark was not rejected before execution: \(oversizedResult.errorCode ?? "no error")"
            )
        }
        let executionOutput = workspace.appendingPathComponent("output.txt")
        guard !FileManager.default.fileExists(atPath: descriptorMarker.path),
              !FileManager.default.fileExists(atPath: executionOutput.path)
        else {
            throw ProbeError.hostClientFailed(
                "invalid bookmark request started workspace execution"
            )
        }

        try relocateWorkspaceForBookmarkTest(workspaceRoot)
        var result: KernelWorkspaceXPC.Reply
        result = try runKernelWorkspaceCommandWhenAvailable(
            proxy,
            bookmark: bookmark,
            request: WorkspaceProbeRequest.forWorkspace(workspace),
            timeoutSeconds: 180
        )
        guard let output = result.output, result.errorCode == nil else {
            throw ProbeError.hostClientFailed(
                "valid XPC workspace request failed: \(result.errorCode ?? "no output")"
            )
        }
        guard FileManager.default.fileExists(atPath: descriptorMarker.path) else {
            throw ProbeError.hostClientFailed(
                "valid bookmark request did not run the descriptor probe: \(output)"
            )
        }
        return "xpc-kernel-abi=versioned-bounded\n"
            + "xpc-kernel-request-id=fixed-width\n"
            + "xpc-kernel-request-frame=bounded-schema-and-id-bound\n"
            + "\(streamPeerEvidence)\n"
            + "xpc-kernel-client-bookmark=bounded-before-copy\n"
            + "xpc-kernel-stalled-bookmark=bounded-deadline\n"
            + "xpc-kernel-oversized-bookmark=rejected-before-buffer-allocation\n"
            + "\(try rejectSymlinkedWorkspaceChildren(proxy, beside: workspaceRoot))\n"
            + output
    }

    private static func rejectMismatchedStreamPeer(
        request: KernelWorkspaceXPC.WorkspaceRunRequest,
        requestID: KernelWorkspaceXPC.RequestID,
        bookmark: Data
    ) throws -> String {
        let expectedPeerProcessID = getppid()
        guard expectedPeerProcessID > 0,
              expectedPeerProcessID != getpid()
        else {
            throw ProbeError.hostClientFailed("could not select a mismatched peer PID")
        }
        let invocation = try KernelWorkspaceXPC.encodeInvocation(
            request: request,
            requestID: requestID,
            bookmark: bookmark
        )
        var descriptors: [Int32] = [-1, -1]
        guard socketpair(AF_UNIX, SOCK_STREAM, 0, &descriptors) == 0 else {
            throw ProbeError.hostClientFailed("peer-check socketpair failed")
        }
        let reader = FileHandle(fileDescriptor: descriptors[0], closeOnDealloc: true)
        let writer = descriptors[1]
        defer {
            reader.closeFile()
            _ = Darwin.close(writer)
        }
        var noSignal: Int32 = 1
        guard setsockopt(
            writer,
            SOL_SOCKET,
            SO_NOSIGPIPE,
            &noSignal,
            socklen_t(MemoryLayout<Int32>.size)
        ) == 0 else {
            throw ProbeError.hostClientFailed("peer-check socket setup failed")
        }
        try send(Array(invocation), to: writer)
        guard Darwin.shutdown(writer, SHUT_WR) == 0 else {
            throw ProbeError.hostClientFailed("peer-check stream shutdown failed")
        }
        let result = KernelWorkspaceXPC.readInvocation(
            from: reader,
            requestID: requestID,
            expectedPeerProcessID: expectedPeerProcessID
        )
        guard result.invocation == nil,
              result.errorCode == "invalid_request"
        else {
            throw ProbeError.hostClientFailed(
                "workspace stream accepted a mismatched peer process"
            )
        }
        return "xpc-kernel-stream-peer=mismatch-rejected-before-parse"
    }

    private static func rejectSymlinkedWorkspaceChildren(
        _ proxy: KernelWorkspaceEndpoint,
        beside workspaceRoot: URL
    ) throws -> String {
        let parent = workspaceRoot.deletingLastPathComponent()
        var reports: [String] = []
        for childName in ["kernel-workspace", "kernel-descriptor-scope"] {
            let grantRoot = parent.appendingPathComponent(
                "xpc-symlink-grant-\(UUID().uuidString)",
                isDirectory: true
            )
            let outsideTarget = parent.appendingPathComponent(
                "xpc-symlink-target-\(UUID().uuidString)",
                isDirectory: true
            )
            defer {
                try? FileManager.default.removeItem(at: grantRoot)
                try? FileManager.default.removeItem(at: outsideTarget)
            }
            try FileManager.default.createDirectory(
                at: grantRoot,
                withIntermediateDirectories: true
            )
            try FileManager.default.createDirectory(
                at: outsideTarget,
                withIntermediateDirectories: true
            )
            let workspace = grantRoot.appendingPathComponent(
                "kernel-workspace",
                isDirectory: true
            )
            let descriptorWorkspace = grantRoot.appendingPathComponent(
                "kernel-descriptor-scope",
                isDirectory: true
            )
            let symlinkedChild = grantRoot.appendingPathComponent(
                childName,
                isDirectory: true
            )
            let otherChild = childName == "kernel-workspace"
                ? descriptorWorkspace
                : workspace
            try FileManager.default.createDirectory(
                at: otherChild,
                withIntermediateDirectories: true
            )
            try Data("xpc-input".utf8).write(
                to: otherChild.appendingPathComponent("input.txt")
            )
            try Data("sibling-secret".utf8).write(
                to: outsideTarget.appendingPathComponent("input.txt")
            )
            try Data("unchanged".utf8).write(
                to: outsideTarget.appendingPathComponent("canary.txt")
            )
            try FileManager.default.createSymbolicLink(
                at: symlinkedChild,
                withDestinationURL: outsideTarget
            )

            let bookmark = try grantRoot.bookmarkData(
                options: [],
                includingResourceValuesForKeys: nil,
                relativeTo: nil
            )
            let response = try runKernelWorkspaceCommandWhenAvailable(
                proxy,
                bookmark: bookmark,
                request: WorkspaceProbeRequest.forWorkspace(workspace),
                timeoutSeconds: 45
            )
            let markerWorkspace = childName == "kernel-workspace"
                ? descriptorWorkspace
                : outsideTarget
            let marker = markerWorkspace.appendingPathComponent(
                "descriptor-probe-started.txt"
            )
            let output = workspace.appendingPathComponent("output.txt")
            let canary = outsideTarget.appendingPathComponent("canary.txt")
            guard response.errorCode == "kernel_failed",
                  !FileManager.default.fileExists(atPath: marker.path),
                  !FileManager.default.fileExists(atPath: output.path),
                  try String(contentsOf: canary, encoding: .utf8) == "unchanged"
            else {
                throw ProbeError.hostClientFailed(
                    "Kernel followed symlinked workspace child \(childName)"
                )
            }
            let label = childName == "kernel-workspace"
                ? "workspace-child"
                : "descriptor-child"
            reports.append("xpc-kernel-\(label)-symlink=denied-before-probe")
        }
        return reports.joined(separator: "\n")
    }

    private static func verifyClientRejectsOversizedBookmark() throws {
        let endpoint = KernelWorkspaceEndpointCallCounter()
        do {
            try KernelWorkspaceXPC.submit(
                endpoint,
                request: WorkspaceProbeRequest.forWorkspace(
                    URL(fileURLWithPath: "/tmp/khaos-oversized-bookmark")
                ),
                bookmark: Data(
                    repeating: 0,
                    count: KernelWorkspaceXPC.maximumMessageBytes + 1
                )
            ) { _ in }
        } catch let error as NSError {
            guard error.domain == NSPOSIXErrorDomain,
                  error.code == Int(EMSGSIZE),
                  !endpoint.runInvoked
            else {
                throw ProbeError.hostClientFailed(
                    "XPC client did not reject an oversized bookmark before sending"
                )
            }
            return
        }
        throw ProbeError.hostClientFailed(
            "XPC client accepted an oversized bookmark"
        )
    }

    private static func rejectOversizedBookmarkStream(
        _ proxy: KernelWorkspaceEndpoint,
        request: KernelWorkspaceXPC.WorkspaceRunRequest
    ) throws -> KernelWorkspaceXPC.Reply {
        var descriptors: [Int32] = [-1, -1]
        guard socketpair(AF_UNIX, SOCK_STREAM, 0, &descriptors) == 0 else {
            throw ProbeError.hostClientFailed("bookmark socketpair failed")
        }
        let writer = descriptors[1]
        var noSignal: Int32 = 1
        guard setsockopt(
            writer,
            SOL_SOCKET,
            SO_NOSIGPIPE,
            &noSignal,
            socklen_t(MemoryLayout<Int32>.size)
        ) == 0 else {
            _ = Darwin.close(descriptors[0])
            _ = Darwin.close(writer)
            throw ProbeError.hostClientFailed("bookmark socket setup failed")
        }
        let reader = FileHandle(fileDescriptor: descriptors[0], closeOnDealloc: true)
        defer {
            reader.closeFile()
            _ = Darwin.close(writer)
        }

        let requestID = KernelWorkspaceXPC.newRequestID()
        let lock = NSLock()
        let completed = DispatchSemaphore(value: 0)
        var responseData: Data?
        let startedAt = Date()
        proxy.runWorkspaceCommand(
            KernelWorkspaceXPC.version,
            requestIDHigh: requestID.high,
            requestIDLow: requestID.low,
            invocationStream: reader
        ) { data in
            lock.lock()
            responseData = data
            lock.unlock()
            completed.signal()
        }

        try sendInvocationPrefix(
            request: request,
            requestID: requestID,
            bookmarkLength: KernelWorkspaceXPC.maximumMessageBytes + 1,
            to: writer
        )
        guard shutdown(writer, SHUT_WR) == 0 else {
            throw ProbeError.hostClientFailed("oversized bookmark stream close failed")
        }
        guard completed.wait(timeout: .now() + 7) == .success,
              Date().timeIntervalSince(startedAt) < 7
        else {
            throw ProbeError.hostClientFailed(
                "oversized bookmark response exceeded its deadline"
            )
        }
        lock.lock()
        let data = responseData
        lock.unlock()
        guard let data,
              let response = KernelWorkspaceXPC.decode(data, requestID: requestID)
        else {
            throw ProbeError.hostClientFailed("invalid oversized bookmark response")
        }
        return response
    }

    private static func runInvalidInvocationStream(
        _ proxy: KernelWorkspaceEndpoint,
        requestID: KernelWorkspaceXPC.RequestID,
        requestFrame: Data?,
        declaredRequestLength: Int
    ) throws -> KernelWorkspaceXPC.Reply {
        var descriptors: [Int32] = [-1, -1]
        guard socketpair(AF_UNIX, SOCK_STREAM, 0, &descriptors) == 0 else {
            throw ProbeError.hostClientFailed("request socketpair failed")
        }
        let writer = descriptors[1]
        var noSignal: Int32 = 1
        guard setsockopt(
            writer,
            SOL_SOCKET,
            SO_NOSIGPIPE,
            &noSignal,
            socklen_t(MemoryLayout<Int32>.size)
        ) == 0 else {
            _ = Darwin.close(descriptors[0])
            _ = Darwin.close(writer)
            throw ProbeError.hostClientFailed("request socket setup failed")
        }
        let reader = FileHandle(fileDescriptor: descriptors[0], closeOnDealloc: true)
        defer {
            reader.closeFile()
            _ = Darwin.close(writer)
        }
        let completed = DispatchSemaphore(value: 0)
        let lock = NSLock()
        var responseData: Data?
        let startedAt = Date()
        proxy.runWorkspaceCommand(
            KernelWorkspaceXPC.version,
            requestIDHigh: requestID.high,
            requestIDLow: requestID.low,
            invocationStream: reader
        ) { data in
            lock.lock()
            responseData = data
            lock.unlock()
            completed.signal()
        }
        guard declaredRequestLength >= 0,
              declaredRequestLength <= Int(UInt32.max)
        else {
            throw ProbeError.hostClientFailed("invalid request length fixture")
        }
        var length = UInt32(declaredRequestLength).bigEndian
        let header = withUnsafeBytes(of: &length) { Array($0) }
        try send(header, to: writer)
        if let requestFrame {
            try send(Array(requestFrame), to: writer)
        }
        guard shutdown(writer, SHUT_WR) == 0,
              completed.wait(timeout: .now() + 7) == .success,
              Date().timeIntervalSince(startedAt) < 7
        else {
            throw ProbeError.hostClientFailed("invalid request response exceeded deadline")
        }
        lock.lock()
        let data = responseData
        lock.unlock()
        guard let data,
              let response = KernelWorkspaceXPC.decode(data, requestID: requestID)
        else {
            throw ProbeError.hostClientFailed("invalid request response")
        }
        return response
    }

    private static func rejectStalledBookmarkStream(
        _ proxy: KernelWorkspaceEndpoint,
        request: KernelWorkspaceXPC.WorkspaceRunRequest
    ) throws -> KernelWorkspaceXPC.Reply {
        var descriptors: [Int32] = [-1, -1]
        guard socketpair(AF_UNIX, SOCK_STREAM, 0, &descriptors) == 0 else {
            throw ProbeError.hostClientFailed("bookmark socketpair failed")
        }
        let writer = descriptors[1]
        var noSignal: Int32 = 1
        guard setsockopt(
            writer,
            SOL_SOCKET,
            SO_NOSIGPIPE,
            &noSignal,
            socklen_t(MemoryLayout<Int32>.size)
        ) == 0 else {
            _ = Darwin.close(descriptors[0])
            _ = Darwin.close(writer)
            throw ProbeError.hostClientFailed("bookmark socket setup failed")
        }
        let reader = FileHandle(fileDescriptor: descriptors[0], closeOnDealloc: true)
        defer {
            reader.closeFile()
            _ = Darwin.close(writer)
        }

        let requestID = KernelWorkspaceXPC.newRequestID()
        let lock = NSLock()
        let completed = DispatchSemaphore(value: 0)
        var responseData: Data?
        let startedAt = Date()
        proxy.runWorkspaceCommand(
            KernelWorkspaceXPC.version,
            requestIDHigh: requestID.high,
            requestIDLow: requestID.low,
            invocationStream: reader
        ) { data in
            lock.lock()
            responseData = data
            lock.unlock()
            completed.signal()
        }

        // Finish the outer length and begin its body just before the five-second
        // absolute deadline. A per-read timeout reset would take longer to reply.
        let requestFrame = try request.encodeFrame(requestID: requestID)
        try sendLengthAndFrame(requestFrame, to: writer)
        var declaredLength = UInt32(2048).bigEndian
        let bookmarkHeader = withUnsafeBytes(of: &declaredLength) { Array($0) }
        try send(Array(bookmarkHeader.prefix(2)), to: writer)
        if completed.wait(timeout: .now() + 0.1) != .success {
            Thread.sleep(forTimeInterval: 3.9)
            try send(Array(bookmarkHeader.suffix(2)) + [0], to: writer)
            guard completed.wait(timeout: .now() + 7) == .success else {
                throw ProbeError.hostClientFailed(
                    "stalled bookmark stream exceeded its absolute deadline"
                )
            }
        }
        guard Date().timeIntervalSince(startedAt) < 7 else {
            throw ProbeError.hostClientFailed(
                "stalled bookmark stream response exceeded its deadline"
            )
        }
        lock.lock()
        let data = responseData
        lock.unlock()
        guard let data,
              let response = KernelWorkspaceXPC.decode(data, requestID: requestID)
        else {
            throw ProbeError.hostClientFailed("invalid stalled bookmark response")
        }
        return response
    }

    private static func sendInvocationPrefix(
        request: KernelWorkspaceXPC.WorkspaceRunRequest,
        requestID: KernelWorkspaceXPC.RequestID,
        bookmarkLength: Int,
        to descriptor: Int32
    ) throws {
        let requestFrame = try request.encodeFrame(requestID: requestID)
        try sendLengthAndFrame(requestFrame, to: descriptor)
        var length = UInt32(bookmarkLength).bigEndian
        try send(Array(withUnsafeBytes(of: &length) { Array($0) }), to: descriptor)
    }

    private static func sendLengthAndFrame(_ frame: Data, to descriptor: Int32) throws {
        guard frame.count <= Int(UInt32.max) else {
            throw ProbeError.hostClientFailed("request frame is too large")
        }
        var length = UInt32(frame.count).bigEndian
        let prefix = withUnsafeBytes(of: &length) { Array($0) }
        try send(prefix + frame, to: descriptor)
    }

    private static func send(_ bytes: [UInt8], to descriptor: Int32) throws {
        var offset = 0
        while offset < bytes.count {
            let amount = bytes.withUnsafeBytes { buffer -> Int in
                guard let base = buffer.baseAddress else { return -1 }
                return Darwin.send(
                    descriptor,
                    base.advanced(by: offset),
                    bytes.count - offset,
                    0
                )
            }
            if amount > 0 {
                offset += amount
            } else if amount < 0 && errno == EINTR {
                continue
            } else {
                throw ProbeError.hostClientFailed("XPC invocation stream write failed")
            }
        }
    }

    private static func runKernelWorkspaceCommand(
        _ proxy: KernelWorkspaceEndpoint,
        bookmark: Data,
        request: KernelWorkspaceXPC.WorkspaceRunRequest,
        version: Int = KernelWorkspaceXPC.version,
        requestID: KernelWorkspaceXPC.RequestID = KernelWorkspaceXPC.newRequestID(),
        timeoutSeconds: TimeInterval
    ) throws -> KernelWorkspaceXPC.Reply {
        let semaphore = DispatchSemaphore(value: 0)
        let lock = NSLock()
        var result: Data?
        try KernelWorkspaceXPC.submit(
            proxy,
            version: version,
            requestID: requestID,
            request: request,
            bookmark: bookmark
        ) { data in
            lock.lock()
            result = data
            lock.unlock()
            semaphore.signal()
        }
        guard semaphore.wait(timeout: .now() + timeoutSeconds) == .success else {
            throw ProbeError.xpcTimeout
        }
        lock.lock()
        let responseData = result
        lock.unlock()
        guard let responseData,
              let response = KernelWorkspaceXPC.decode(responseData, requestID: requestID)
        else {
            throw ProbeError.hostClientFailed("invalid Kernel XPC response")
        }
        return response
    }

    private static func runKernelWorkspaceCommandWhenAvailable(
        _ proxy: KernelWorkspaceEndpoint,
        bookmark: Data,
        request: KernelWorkspaceXPC.WorkspaceRunRequest,
        timeoutSeconds: TimeInterval
    ) throws -> KernelWorkspaceXPC.Reply {
        try retryKernelWorkspaceRequestWhenAvailable {
            try runKernelWorkspaceCommand(
                proxy,
                bookmark: bookmark,
                request: request,
                timeoutSeconds: timeoutSeconds
            )
        }
    }

    private static func retryKernelWorkspaceRequestWhenAvailable(
        _ request: () throws -> KernelWorkspaceXPC.Reply
    ) throws -> KernelWorkspaceXPC.Reply {
        let retryDeadline = Date().addingTimeInterval(kernelWorkspaceRetryWindowSeconds)
        var result = try request()
        while result.errorCode == "operation_busy", Date() < retryDeadline {
            Thread.sleep(forTimeInterval: 0.1)
            result = try request()
        }
        return result
    }

    private static func requestKernelWorkspaceCancellation(
        endpoint: NSXPCListenerEndpoint,
        workspace: URL,
        descriptorWorkspace: URL
    ) throws -> String {
        let connection = NSXPCConnection(listenerEndpoint: endpoint)
        connection.remoteObjectInterface = NSXPCInterface(
            with: KernelWorkspaceEndpoint.self
        )
        connection.resume()
        defer { connection.invalidate() }

        let proxy = connection.remoteObjectProxyWithErrorHandler { error in
            FileHandle.standardError.write(
                Data("kernel-cancel-xpc-error: \(error)\n".utf8)
            )
        } as? KernelWorkspaceEndpoint
        guard let proxy else {
            throw ProbeError.invalidProxy
        }
        let root = try commonWorkspaceRoot(
            workspace: workspace,
            descriptorWorkspace: descriptorWorkspace
        )
        let bookmark = try root.bookmarkData(
            options: [], includingResourceValuesForKeys: nil, relativeTo: nil
        )
        let requestID = KernelWorkspaceXPC.newRequestID()
        let runSemaphore = DispatchSemaphore(value: 0)
        let responseLock = NSLock()
        var runData: Data?
        try KernelWorkspaceXPC.submit(
            proxy,
            version: KernelWorkspaceXPC.version,
            requestID: requestID,
            request: WorkspaceProbeRequest.forWorkspace(
                workspace,
                timeoutSeconds: 30
            ),
            bookmark: bookmark
        ) { data in
            responseLock.lock()
            runData = data
            responseLock.unlock()
            runSemaphore.signal()
        }

        Thread.sleep(forTimeInterval: 2)
        responseLock.lock()
        let completedEarlyData = runData
        responseLock.unlock()
        if let completedEarlyData,
           let completedEarly = KernelWorkspaceXPC.decode(
                completedEarlyData,
                requestID: requestID
           ) {
            let detail = completedEarly.errorCode
                ?? String((completedEarly.output ?? "").prefix(1200))
            throw ProbeError.hostClientFailed(
                "cancellation fixture completed before cancel: \(detail)"
            )
        }
        let staleCancellation = try sendKernelWorkspaceCancellation(
            proxy,
            requestID: KernelWorkspaceXPC.newRequestID()
        )
        guard staleCancellation.errorCode == "process_not_active" else {
            throw ProbeError.hostClientFailed("cancellation ignored request binding")
        }
        let otherConnection = NSXPCConnection(listenerEndpoint: endpoint)
        otherConnection.remoteObjectInterface = NSXPCInterface(
            with: KernelWorkspaceEndpoint.self
        )
        otherConnection.resume()
        defer { otherConnection.invalidate() }
        let otherProxy = otherConnection.remoteObjectProxyWithErrorHandler { _ in }
            as? KernelWorkspaceEndpoint
        guard let otherProxy else {
            throw ProbeError.invalidProxy
        }
        let otherConnectionCancellation = try sendKernelWorkspaceCancellation(
            otherProxy,
            requestID: requestID
        )
        guard otherConnectionCancellation.errorCode == "process_not_active" else {
            throw ProbeError.hostClientFailed(
                "another XPC connection cancelled the active request"
            )
        }
        let cancellation = try sendKernelWorkspaceCancellation(
            proxy,
            requestID: requestID
        )
        let cancellationStatus = cancellation.errorCode ?? "no status"
        guard cancellation.cancellationAccepted == true else {
            throw ProbeError.hostClientFailed(
                "active XPC cancellation was rejected: \(cancellationStatus)"
            )
        }
        guard runSemaphore.wait(timeout: .now() + 45) == .success else {
            throw ProbeError.xpcTimeout
        }
        responseLock.lock()
        let responseData = runData
        responseLock.unlock()
        guard let responseData,
              let result = KernelWorkspaceXPC.decode(
                responseData,
                requestID: requestID
              ),
              result.errorCode == "process_cancelled"
        else {
            let detail = responseData.flatMap {
                KernelWorkspaceXPC.decode($0, requestID: requestID)
            }
            let status = detail?.errorCode
                ?? String((detail?.output ?? "no response").prefix(600))
            throw ProbeError.hostClientFailed(
                "Kernel XPC cancellation did not stop execution: \(status)"
            )
        }
        guard !FileManager.default.fileExists(
                atPath: workspace.appendingPathComponent("output.txt").path
              ),
              !FileManager.default.fileExists(
                atPath: workspace.appendingPathComponent("kernel-bypass.txt").path
              )
        else {
            throw ProbeError.hostClientFailed("cancelled XPC request committed output")
        }
        return "xpc-kernel-cancel=process_cancelled\n"
            + "xpc-kernel-cancel-scope=bound\n"
            + "xpc-kernel-cancel-connection=bound"
    }

    private static func requestKernelWorkspaceDisconnect(
        endpoint: NSXPCListenerEndpoint,
        workspace: URL,
        descriptorWorkspace: URL
    ) throws -> String {
        let connection = NSXPCConnection(listenerEndpoint: endpoint)
        connection.remoteObjectInterface = NSXPCInterface(
            with: KernelWorkspaceEndpoint.self
        )
        connection.resume()

        let proxy = connection.remoteObjectProxyWithErrorHandler { _ in } as? KernelWorkspaceEndpoint
        guard let proxy else {
            connection.invalidate()
            throw ProbeError.invalidProxy
        }
        defer { connection.invalidate() }
        let root = try commonWorkspaceRoot(
            workspace: workspace,
            descriptorWorkspace: descriptorWorkspace
        )
        let bookmark = try root.bookmarkData(
            options: [], includingResourceValuesForKeys: nil, relativeTo: nil
        )
        try KernelWorkspaceXPC.submit(
            proxy,
            version: KernelWorkspaceXPC.version,
            requestID: KernelWorkspaceXPC.newRequestID(),
            request: WorkspaceProbeRequest.forWorkspace(
                workspace,
                timeoutSeconds: 30
            ),
            bookmark: bookmark
        ) { _ in }

        Thread.sleep(forTimeInterval: 2)
        connection.invalidate()
        let output = workspace.appendingPathComponent("output.txt")
        let bypass = workspace.appendingPathComponent("kernel-bypass.txt")
        guard !FileManager.default.fileExists(atPath: output.path),
              !FileManager.default.fileExists(atPath: bypass.path)
        else {
            throw ProbeError.hostClientFailed(
                "disconnected XPC request wrote to the workspace"
            )
        }
        return "xpc-kernel-disconnect=no-writeback"
    }

    private static func sendKernelWorkspaceCancellation(
        _ proxy: KernelWorkspaceEndpoint,
        requestID: KernelWorkspaceXPC.RequestID
    ) throws -> KernelWorkspaceXPC.Reply {
        let semaphore = DispatchSemaphore(value: 0)
        let lock = NSLock()
        var responseData: Data?
        proxy.cancelWorkspaceCommand(
            KernelWorkspaceXPC.version,
            requestIDHigh: requestID.high,
            requestIDLow: requestID.low
        ) { data in
            lock.lock()
            responseData = data
            lock.unlock()
            semaphore.signal()
        }
        guard semaphore.wait(timeout: .now() + 10) == .success else {
            throw ProbeError.xpcTimeout
        }
        lock.lock()
        let data = responseData
        lock.unlock()
        guard let data,
              let reply = KernelWorkspaceXPC.decode(data, requestID: requestID)
        else {
            throw ProbeError.hostClientFailed("invalid Kernel XPC cancellation reply")
        }
        return reply
    }

    private static func relocateWorkspaceForBookmarkTest(_ workspace: URL) throws {
        let moved = workspace.deletingLastPathComponent().appendingPathComponent(
            ".khaos-bookmark-\(UUID().uuidString)",
            isDirectory: true
        )
        try FileManager.default.moveItem(at: workspace, to: moved)
        do {
            try FileManager.default.moveItem(at: moved, to: workspace)
        } catch {
            try? FileManager.default.moveItem(at: moved, to: workspace)
            throw error
        }
    }

    private static func requestKernelUnscopedRead(
        endpoint: NSXPCListenerEndpoint,
        path: String
    ) throws -> String {
        let connection = NSXPCConnection(listenerEndpoint: endpoint)
        connection.remoteObjectInterface = NSXPCInterface(with: KernelProbe.self)
        connection.resume()
        defer { connection.invalidate() }

        let proxy = connection.remoteObjectProxyWithErrorHandler { error in
            FileHandle.standardError.write(Data("kernel-unscoped-xpc-error: \(error)\n".utf8))
        } as? KernelProbe
        guard let proxy else {
            throw ProbeError.invalidProxy
        }

        let semaphore = DispatchSemaphore(value: 0)
        var result = "kernel-unscoped=no-response"
        proxy.readUnscopedInput(path) { value in
            result = value
            semaphore.signal()
        }
        guard semaphore.wait(timeout: .now() + 15) == .success else {
            throw ProbeError.xpcTimeout
        }
        return result
    }

    private static func runSpoofKernelClient(
        spoofEndpoint: NSXPCListenerEndpoint,
        kernelEndpoint: NSXPCListenerEndpoint,
        bookmark: Data
    ) throws -> String {
        let connection = NSXPCConnection(listenerEndpoint: spoofEndpoint)
        connection.remoteObjectInterface = NSXPCInterface(with: SpoofProbe.self)
        connection.resume()
        defer { connection.invalidate() }

        let proxy = connection.remoteObjectProxyWithErrorHandler { error in
            FileHandle.standardError.write(Data("spoof-kernel-xpc-error: \(error)\n".utf8))
        } as? SpoofProbe
        guard let proxy else {
            throw ProbeError.invalidProxy
        }

        let semaphore = DispatchSemaphore(value: 0)
        var result: String?
        proxy.attemptKernel(endpoint: kernelEndpoint, bookmark: bookmark) { value in
            result = value
            semaphore.signal()
        }
        guard semaphore.wait(timeout: .now() + 15) == .success,
              let result
        else {
            throw ProbeError.xpcTimeout
        }
        return result
    }

    private static func runSpoofKernelExecutionClient(
        spoofEndpoint: NSXPCListenerEndpoint,
        kernelEndpoint: NSXPCListenerEndpoint,
        workspace: URL,
        descriptorWorkspace: URL
    ) throws -> String {
        let connection = NSXPCConnection(listenerEndpoint: spoofEndpoint)
        connection.remoteObjectInterface = NSXPCInterface(with: SpoofProbe.self)
        connection.resume()
        defer { connection.invalidate() }

        let proxy = connection.remoteObjectProxyWithErrorHandler { error in
            FileHandle.standardError.write(
                Data("spoof-kernel-execution-xpc-error: \(error)\n".utf8)
            )
        } as? SpoofProbe
        guard let proxy else {
            throw ProbeError.invalidProxy
        }

        let root = try commonWorkspaceRoot(
            workspace: workspace,
            descriptorWorkspace: descriptorWorkspace
        )
        let workspaceBookmark = try root.bookmarkData(
            options: [], includingResourceValuesForKeys: nil, relativeTo: nil
        )
        let semaphore = DispatchSemaphore(value: 0)
        var result: String?
        proxy.attemptKernelExecution(
            endpoint: kernelEndpoint,
            bookmark: workspaceBookmark
        ) { value in
            result = value
            semaphore.signal()
        }
        guard semaphore.wait(timeout: .now() + 15) == .success,
              let result
        else {
            throw ProbeError.xpcTimeout
        }
        return result
    }

    private static func requestUnscopedPythonRunner(
        endpoint: NSXPCListenerEndpoint,
        snapshotPath: String,
        siblingPath: String,
        outsidePath: String,
        networkPort: Int
    ) throws -> String {
        let (connection, proxy) = try connectRunner(endpoint: endpoint)
        defer { connection.invalidate() }

        let semaphore = DispatchSemaphore(value: 0)
        var result = ""
        proxy.runUnscopedPythonRunner(
            snapshotPath: snapshotPath,
            siblingPath: siblingPath,
            outsidePath: outsidePath,
            networkPort: networkPort
        ) { value in
            result = value
            semaphore.signal()
        }
        guard semaphore.wait(timeout: .now() + 15) == .success else {
            throw ProbeError.xpcTimeout
        }
        return result
    }

    private static func connectRunner(
        endpoint: NSXPCListenerEndpoint
    ) throws -> (NSXPCConnection, RunnerProbe) {
        let connection = NSXPCConnection(listenerEndpoint: endpoint)
        connection.remoteObjectInterface = NSXPCInterface(with: RunnerProbe.self)
        connection.resume()
        guard let proxy = connection.remoteObjectProxyWithErrorHandler({ error in
            FileHandle.standardError.write(Data("runner-xpc-error: \(error)\n".utf8))
        }) as? RunnerProbe else {
            connection.invalidate()
            throw ProbeError.invalidProxy
        }
        return (connection, proxy)
    }

    private static func runnerEndpoint(
        serviceName: String
    ) throws -> NSXPCListenerEndpoint {
        let bootstrapConnection = NSXPCConnection(serviceName: serviceName)
        bootstrapConnection.remoteObjectInterface = NSXPCInterface(
            with: RunnerBootstrap.self
        )
        bootstrapConnection.resume()
        defer { bootstrapConnection.invalidate() }

        let bootstrap = bootstrapConnection.remoteObjectProxyWithErrorHandler { error in
            FileHandle.standardError.write(Data("bootstrap-xpc-error: \(error)\n".utf8))
        } as? RunnerBootstrap
        guard let bootstrap else {
            throw ProbeError.invalidProxy
        }

        let semaphore = DispatchSemaphore(value: 0)
        var endpoint: NSXPCListenerEndpoint?
        bootstrap.runnerEndpoint { value in
            endpoint = value
            semaphore.signal()
        }
        guard semaphore.wait(timeout: .now() + 15) == .success,
              let endpoint
        else {
            throw ProbeError.xpcTimeout
        }

        return endpoint
    }

    private static func spoofEndpoint(
        serviceName: String
    ) throws -> NSXPCListenerEndpoint {
        let connection = NSXPCConnection(serviceName: serviceName)
        connection.remoteObjectInterface = NSXPCInterface(
            with: SpoofBootstrap.self
        )
        connection.resume()
        defer { connection.invalidate() }

        let bootstrap = connection.remoteObjectProxyWithErrorHandler { error in
            FileHandle.standardError.write(
                Data("spoof-bootstrap-xpc-error: \(error)\n".utf8)
            )
        } as? SpoofBootstrap
        guard let bootstrap else {
            throw ProbeError.invalidProxy
        }
        let semaphore = DispatchSemaphore(value: 0)
        var endpoint: NSXPCListenerEndpoint?
        bootstrap.spoofEndpoint {
            endpoint = $0
            semaphore.signal()
        }
        guard semaphore.wait(timeout: .now() + 15) == .success,
              let endpoint
        else {
            throw ProbeError.xpcTimeout
        }
        return endpoint
    }

    private static func runSpoofClient(
        spoofEndpoint: NSXPCListenerEndpoint,
        runnerEndpoint: NSXPCListenerEndpoint,
        bookmark: Data,
        sibling: URL,
        outsidePath: String,
        networkPort: Int
    ) throws -> String {
        let connection = NSXPCConnection(listenerEndpoint: spoofEndpoint)
        connection.remoteObjectInterface = NSXPCInterface(with: SpoofProbe.self)
        connection.resume()
        defer { connection.invalidate() }

        let proxy = connection.remoteObjectProxyWithErrorHandler { error in
            FileHandle.standardError.write(Data("spoof-xpc-error: \(error)\n".utf8))
        } as? SpoofProbe
        guard let proxy else {
            throw ProbeError.invalidProxy
        }

        let semaphore = DispatchSemaphore(value: 0)
        var result: String?
        proxy.attempt(
            endpoint: runnerEndpoint,
            bookmark: bookmark,
            siblingPath: sibling.path,
            outsidePath: outsidePath,
            networkPort: networkPort
        ) { value in
            result = value
            semaphore.signal()
        }
        guard semaphore.wait(timeout: .now() + 15) == .success,
              let result
        else {
            throw ProbeError.xpcTimeout
        }
        return result
    }

    private static func statePath(from report: String) throws -> String {
        let prefix = "runner-container-state-path="
        guard let line = report.split(separator: "\n").first(where: {
            $0.hasPrefix(prefix)
        }) else {
            throw ProbeError.invalidStatePath
        }
        return String(line.dropFirst(prefix.count))
    }

    private static func read(_ url: URL) throws -> String {
        try String(contentsOf: url, encoding: .utf8)
    }
}

private enum ProbeError: Error {
    case invalidArguments
    case hostClientFailed(String)
    case invalidReport
    case invalidProxy
    case invalidStatePath
    case xpcTimeout
}
