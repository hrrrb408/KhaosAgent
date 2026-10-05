import Darwin
import Foundation

@main
struct KernelSnapshotBrokerToolRunnerProbe {
    static func main() {
        guard CommandLine.arguments.count == 3 else {
            exit(2)
        }
        let mode = CommandLine.arguments[1]
        let pidFile = CommandLine.arguments[2]
        guard mode == "cancelled" || mode == "timed-out" || mode == "inventory"
                || mode == "orphaned" || mode == "wait-error" else {
            exit(2)
        }

        if mode == "inventory" {
            do {
                let output = try KernelSnapshotBrokerToolRunner.run(
                    executable: "/usr/bin/hdiutil",
                    arguments: ["info", "-plist"],
                    environment: ["PATH": "/usr/bin:/bin"],
                    currentDirectory: URL(fileURLWithPath: "/tmp", isDirectory: true),
                    timeout: 10,
                    outputLimit: 1_048_576,
                    isCancelled: { false },
                    processStarted: { _ in },
                    processFinished: { _ in }
                )
                guard (try? PropertyListSerialization.propertyList(
                    from: output,
                    options: [],
                    format: nil
                )) != nil else {
                    exit(7)
                }
                print("broker-tool-inventory=valid-plist bytes=\(output.count)")
                return
            } catch {
                fputs("broker-tool-inventory=failed\n", stderr)
                exit(8)
            }
        }

        let script = mode == "orphaned"
                || mode == "wait-error"
            ? "sleep 60 >/dev/null 2>&1 & child=$!; printf '%s' \"$child\" > \"$1\""
            : "sleep 60 & child=$!; printf '%s' \"$child\" > \"$1\"; wait \"$child\""
        if mode == "wait-error" {
            _ = Darwin.signal(SIGCHLD, SIG_IGN)
        }
        var processFinished = false
        do {
            _ = try KernelSnapshotBrokerToolRunner.run(
                executable: "/bin/sh",
                arguments: ["-c", script, "broker-probe", pidFile],
                environment: ["PATH": "/usr/bin:/bin"],
                currentDirectory: URL(fileURLWithPath: "/tmp", isDirectory: true),
                timeout: mode == "timed-out" ? 0.5 : 10,
                outputLimit: 1024,
                isCancelled: {
                    mode == "cancelled"
                        && FileManager.default.fileExists(atPath: pidFile)
                },
                processStarted: { _ in },
                processFinished: { _ in processFinished = true }
            )
            if mode == "orphaned" {
                print("broker-tool-process-group=orphaned-child-stopped")
                return
            }
            exit(3)
        } catch KernelSnapshotBrokerToolFailure.cancelled {
            guard mode == "cancelled" else { exit(4) }
            print("broker-tool-process-group=cancelled")
        } catch KernelSnapshotBrokerToolFailure.timedOut {
            guard mode == "timed-out" else { exit(5) }
            print("broker-tool-process-group=timed-out")
        } catch KernelSnapshotBrokerToolFailure.waitFailed(let code) {
            guard mode == "wait-error", code == ECHILD, processFinished else {
                exit(10)
            }
            print("broker-tool-process-group=wait-error-child-stopped")
        } catch {
            exit(6)
        }
    }
}
