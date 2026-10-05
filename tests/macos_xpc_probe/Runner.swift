import Darwin
import Foundation

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

final class Service: NSObject, RunnerProbe {
    @objc func runUnscopedPythonRunner(
        snapshotPath: String,
        siblingPath: String,
        outsidePath: String,
        networkPort: Int,
        withReply reply: @escaping (String) -> Void
    ) {
        reply(runKhaosRunnerProbe(
            snapshotPath: snapshotPath,
            siblingPath: siblingPath,
            outsidePath: outsidePath,
            networkPort: networkPort
        ))
    }

    @objc func run(
        _ bookmark: Data,
        siblingPath: String,
        outsidePath: String,
        otherRunnerStatePath: String,
        networkPort: Int,
        pluginID: String,
        withReply reply: @escaping (String) -> Void
    ) {
        do {
            var stale = false
            let snapshot = try URL(
                resolvingBookmarkData: bookmark,
                options: [],
                relativeTo: nil,
                bookmarkDataIsStale: &stale
            )
            let started = snapshot.startAccessingSecurityScopedResource()
            defer {
                if started {
                    snapshot.stopAccessingSecurityScopedResource()
                }
            }

            var results = [
                "runner-bookmark-stale=\(stale)",
                "runner-snapshot-access-started=\(started)",
            ]
            results.append(contentsOf: runBundledPython(
                snapshot: snapshot,
                siblingPath: siblingPath,
                outsidePath: outsidePath,
                networkPort: networkPort
            ))
            let output = snapshot.appendingPathComponent("runner-output.txt")
            try Data("runner".utf8).write(to: output)
            results.append("runner-snapshot-write=allowed")
            results.append(attemptRead(siblingPath, label: "runner-sibling-read"))
            results.append(attemptWrite(siblingPath, label: "runner-sibling-write"))
            results.append(attemptRead(outsidePath, label: "runner-outside-read"))
            results.append(attemptWrite(outsidePath + ".runner-write", label: "runner-outside-write"))
            results.append(attemptRead(
                otherRunnerStatePath,
                label: "runner-other-container-read"
            ))

            let suffix = UUID().uuidString
            let siblingLink = snapshot.appendingPathComponent("link-to-sibling-\(suffix)")
            let outsideLink = snapshot.appendingPathComponent("link-to-outside-\(suffix)")
            let traversalPath = snapshot.appendingPathComponent("../sibling-secret.txt")
            try FileManager.default.createSymbolicLink(
                atPath: siblingLink.path,
                withDestinationPath: siblingPath
            )
            try FileManager.default.createSymbolicLink(
                atPath: outsideLink.path,
                withDestinationPath: outsidePath
            )
            results.append(attemptRead(siblingLink.path, label: "runner-symlink-sibling-read"))
            results.append(attemptWrite(siblingLink.path, label: "runner-symlink-sibling-write"))
            results.append(attemptRead(outsideLink.path, label: "runner-symlink-outside-read"))
            results.append(attemptWrite(outsideLink.path, label: "runner-symlink-outside-write"))
            results.append(attemptRead(traversalPath.path, label: "runner-traversal-read"))
            results.append(attemptWrite(traversalPath.path, label: "runner-traversal-write"))

            let hardLink = siblingPath + ".runner-hardlink-\(suffix)"
            let linkResult = Darwin.link(output.path, hardLink)
            let linkStatus = linkResult == 0 ? "allowed" : "denied:\(errno)"
            results.append("runner-hardlink=\(linkStatus)")

            let sourceData = try String(contentsOf: snapshot.appendingPathComponent("input.txt"), encoding: .utf8)
            let runnerState = FileManager.default.urls(
                for: .applicationSupportDirectory,
                in: .userDomainMask
            )[0].appendingPathComponent("khaos-runner-state.txt")
            results.append("runner-container-state-path=\(runnerState.path)")
            if pluginID == "plugin-a" {
                try Data(sourceData.utf8).write(to: runnerState)
                results.append("runner-container-state=stored")
            } else {
                results.append("runner-container-state=\((try? String(contentsOf: runnerState, encoding: .utf8)) ?? "missing")")
                try? FileManager.default.removeItem(at: runnerState)
            }

            results.append("runner-network=\(loopbackStatus(port: networkPort))")
            let child = try runShell(
                snapshot: snapshot,
                output: output,
                siblingPath: siblingPath,
                outsidePath: outsidePath,
                siblingLink: siblingLink.path,
                outsideLink: outsideLink.path,
                traversalPath: traversalPath.path,
                networkPort: networkPort
            )
            results.append(contentsOf: child)
            reply(results.joined(separator: "\n"))
        } catch {
            reply("runner-error: \(error)")
        }
    }

    private func attemptRead(_ path: String, label: String) -> String {
        let descriptor = Darwin.open(path, O_RDONLY)
        guard descriptor >= 0 else { return "\(label)=denied:\(errno)" }
        _ = Darwin.close(descriptor)
        return "\(label)=allowed"
    }

    private func runKhaosRunnerProbe(
        snapshotPath: String,
        siblingPath: String,
        outsidePath: String,
        networkPort: Int
    ) -> String {
        guard let version = Bundle.main.object(
            forInfoDictionaryKey: "KhaosPythonVersion"
        ) as? String else {
            return "python-skip=no-supported-runtime"
        }
        let contents = Bundle.main.bundleURL.appendingPathComponent("Contents")
        let pythonHome = contents
            .appendingPathComponent("Frameworks/Python.framework/Versions/\(version)")
        let executable = pythonHome
            .appendingPathComponent("bin/python\(version)")
        let harness = contents
            .appendingPathComponent("Resources/kernel_runner_probe.py")
        let process = Process()
        process.executableURL = executable
        process.arguments = ["-S", harness.path]
        process.environment = [
            "PATH": "/usr/bin:/bin",
            "PYTHONHOME": pythonHome.path,
            "PYTHONDONTWRITEBYTECODE": "1",
            "TMPDIR": NSTemporaryDirectory(),
            "KHAOS_PROBE_SNAPSHOT_PATH": snapshotPath,
            "KHAOS_PROBE_SIBLING_PATH": siblingPath,
            "KHAOS_PROBE_OUTSIDE_PATH": outsidePath,
            "KHAOS_PROBE_NETWORK_PORT": String(networkPort),
        ]
        let output = Pipe()
        process.standardOutput = output
        process.standardError = output
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            return "kernel-probe-error=\(error)"
        }
        let text = String(
            data: output.fileHandleForReading.readDataToEndOfFile(),
            encoding: .utf8
        ) ?? ""
        guard process.terminationStatus == 0 else {
            return "kernel-probe-error=\(process.terminationStatus):\(text)"
        }
        return text
    }

    private func runBundledPython(
        snapshot: URL,
        siblingPath: String,
        outsidePath: String,
        networkPort: Int
    ) -> [String] {
        guard let version = Bundle.main.object(
            forInfoDictionaryKey: "KhaosPythonVersion"
        ) as? String else {
            return ["python-skip=no-supported-runtime"]
        }
        let contents = Bundle.main.bundleURL.appendingPathComponent("Contents")
        let pythonHome = contents
            .appendingPathComponent("Frameworks/Python.framework/Versions/\(version)")
        let executable = pythonHome
            .appendingPathComponent("bin/python\(version)")
        let packageRoot = contents.appendingPathComponent("Resources")
        let script = """
        import errno
        import socket
        import sys
        from pathlib import Path

        sys.path.insert(0, sys.argv[1])
        from khaos.kernel.workspace_changes import WorkspaceChangeSet

        def must_be_denied(path, label):
            try:
                Path(path).read_text(encoding="utf-8")
            except OSError as error:
                if error.errno in (errno.EPERM, errno.EACCES):
                    print(f"{label}=denied")
                    return
                raise
            raise SystemExit(f"{label}=allowed")

        Path(sys.argv[2], "python-child.txt").write_text("bundled", encoding="utf-8")
        print(f"python-version={sys.version_info.major}.{sys.version_info.minor}")
        print(f"python-khaos-import={WorkspaceChangeSet.__name__}")
        print("python-snapshot-write=allowed")
        must_be_denied(sys.argv[3], "python-sibling-read")
        must_be_denied(sys.argv[4], "python-outside-read")
        try:
            socket.create_connection(("127.0.0.1", int(sys.argv[5])), timeout=1)
        except OSError as error:
            if error.errno not in (errno.EPERM, errno.EACCES):
                raise
            print("python-network=denied")
        else:
            raise SystemExit("python-network=allowed")
        """
        let process = Process()
        process.executableURL = executable
        process.arguments = [
            "-S", "-c", script,
            packageRoot.path,
            snapshot.path,
            siblingPath,
            outsidePath,
            String(networkPort),
        ]
        process.environment = [
            "PATH": "/usr/bin:/bin",
            "PYTHONHOME": pythonHome.path,
            "PYTHONDONTWRITEBYTECODE": "1",
        ]
        let output = Pipe()
        process.standardOutput = output
        process.standardError = output
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            return ["python-error=\(error)"]
        }
        let text = String(
            data: output.fileHandleForReading.readDataToEndOfFile(),
            encoding: .utf8
        ) ?? ""
        guard process.terminationStatus == 0 else {
            return ["python-error=\(process.terminationStatus):\(text)"]
        }
        return text.split(whereSeparator: \.isNewline).map(String.init)
    }

    private func attemptWrite(_ path: String, label: String) -> String {
        let descriptor = Darwin.open(path, O_WRONLY | O_CREAT | O_TRUNC, mode_t(0o600))
        guard descriptor >= 0 else { return "\(label)=denied:\(errno)" }
        _ = Darwin.close(descriptor)
        return "\(label)=allowed"
    }

    private func runShell(
        snapshot: URL,
        output: URL,
        siblingPath: String,
        outsidePath: String,
        siblingLink: String,
        outsideLink: String,
        traversalPath: String,
        networkPort: Int
    ) throws -> [String] {
        let siblingCopy = snapshot.appendingPathComponent("sibling-copy.txt").path
        let outsideCopy = snapshot.appendingPathComponent("outside-copy.txt").path
        let script = """
        printf child > "$1"
        cat "$2" > "$1.sibling-copy" 2>/dev/null
        cat "$3" > "$1.outside-copy" 2>/dev/null
        printf blocked > "$4" 2>/dev/null
        printf blocked > "$5" 2>/dev/null
        printf blocked > "$6" 2>/dev/null
        printf blocked > "$7" 2>/dev/null
        printf blocked > "$8" 2>/dev/null
        if /usr/bin/nc -z -w 1 127.0.0.1 \(networkPort) >/dev/null 2>&1; then
            printf 'KHAOS_CHILD_NETWORK=allowed'
        else
            printf 'KHAOS_CHILD_NETWORK=denied'
        fi
        """
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/sh")
        process.arguments = [
            "-c", script, "probe", output.path, siblingPath, outsidePath,
            siblingLink, outsideLink, traversalPath, siblingCopy, outsideCopy,
        ]
        process.environment = ["PATH": "/usr/bin:/bin", "HOME": NSHomeDirectory()]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        try process.run()
        process.waitUntilExit()
        let text = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        let outputValue = (try? String(contentsOf: output, encoding: .utf8)) ?? ""
        let siblingCopyValue = (try? String(contentsOfFile: siblingCopy, encoding: .utf8)) ?? ""
        let outsideCopyValue = (try? String(contentsOfFile: outsideCopy, encoding: .utf8)) ?? ""
        return [
            "child-snapshot-write=\(outputValue == "child" ? "allowed" : "denied")",
            "child-sibling-read=\(siblingCopyValue == "sibling-secret" ? "allowed" : "denied")",
            "child-outside-read=\(outsideCopyValue == "outside-secret" ? "allowed" : "denied")",
            "child-network=\(text.contains("KHAOS_CHILD_NETWORK=allowed") ? "allowed" : "denied")",
        ]
    }

    private func loopbackStatus(port: Int) -> String {
        let descriptor = Darwin.socket(AF_INET, SOCK_STREAM, 0)
        guard descriptor >= 0 else { return "denied:\(errno)" }
        defer { _ = Darwin.close(descriptor) }

        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = in_port_t(port).bigEndian
        let parsed = "127.0.0.1".withCString {
            Darwin.inet_pton(AF_INET, $0, &address.sin_addr)
        }
        guard parsed == 1 else { return "invalid_address" }
        let result = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.connect(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        return result == 0 ? "allowed" : "denied:\(errno)"
    }
}

final class Delegate: NSObject, NSXPCListenerDelegate {
    private let service = Service()

    func listener(
        _ listener: NSXPCListener,
        shouldAcceptNewConnection connection: NSXPCConnection
    ) -> Bool {
        connection.exportedInterface = NSXPCInterface(with: RunnerProbe.self)
        connection.exportedObject = service
        connection.resume()
        return true
    }
}

final class Bootstrap: NSObject, RunnerBootstrap {
    private let listener: NSXPCListener
    private let runnerDelegate = Delegate()

    override init() {
        guard let requirement = Bundle.main.object(
            forInfoDictionaryKey: "KhaosPeerRequirement"
        ) as? String else {
            fatalError("missing peer code requirement")
        }
        listener = NSXPCListener.anonymous()
        super.init()
        listener.setConnectionCodeSigningRequirement(requirement)
        listener.delegate = runnerDelegate
        listener.resume()
    }

    func runnerEndpoint(withReply reply: @escaping (NSXPCListenerEndpoint) -> Void) {
        reply(listener.endpoint)
    }
}

final class BootstrapDelegate: NSObject, NSXPCListenerDelegate {
    private let bootstrap = Bootstrap()

    func listener(
        _ listener: NSXPCListener,
        shouldAcceptNewConnection connection: NSXPCConnection
    ) -> Bool {
        connection.exportedInterface = NSXPCInterface(with: RunnerBootstrap.self)
        connection.exportedObject = bootstrap
        connection.resume()
        return true
    }
}

let delegate = BootstrapDelegate()
let listener = NSXPCListener.service()
listener.delegate = delegate
listener.resume()
RunLoop.main.run()
