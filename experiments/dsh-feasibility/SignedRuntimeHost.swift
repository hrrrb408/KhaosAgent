import Foundation
import OSLog

@main
enum SignedRuntimeHost {
    struct ChildResult {
        let status: Int32
        let termination: String
        let stdout: String
        let stderrBytes: Int
    }

    static let logger = Logger(
        subsystem: Bundle.main.bundleIdentifier ?? "com.khaos.dsh-feasibility-probe",
        category: "runtime"
    )

    static func persistEvidence(_ value: [String: Any]) {
        let evidencePath = URL(fileURLWithPath: NSHomeDirectory())
            .appendingPathComponent("dsh-probe-result.json")
        do {
            let data = try JSONSerialization.data(withJSONObject: value)
            try data.write(to: evidencePath, options: .atomic)
            logger.notice("KHAOS_DSH_EVIDENCE \(String(decoding: data, as: UTF8.self), privacy: .public)")
        } catch {
            fputs("evidence_write_failed\n", stderr)
            exit(71)
        }
    }

    static func statusValue(_ value: Any?) -> Any {
        guard let value = value as? String,
              value.utf8.count <= 64,
              value.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || "_-:".contains($0)) }) else {
            return "INVALID"
        }
        return value
    }

    static func sanitizedProbeEvidence(_ stdout: String) -> [String: Any] {
        let payloads = stdout.split(separator: "\n").compactMap { line -> [String: Any]? in
            guard let data = line.data(using: .utf8),
                  let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  value["signedRuntime"] as? String == "PASS" else {
                return nil
            }
            return value
        }
        guard payloads.count == 1,
              let hostile = payloads[0]["hostilePlugin"] as? [String: Any] else {
            return ["evidenceDecode": "FAILED"]
        }
        let credentialCount = hostile["credentialEnvironmentKeys"] as? Int ?? -1
        let rssBytes = payloads[0]["runtimeRssBytes"] as? Int ?? -1
        return [
            "dshToolRoundTrip": statusValue(payloads[0]["dshToolRoundTrip"]),
            "nodeRssBytes": rssBytes,
            "hostilePlugin": [
                "fileRead": statusValue(hostile["fileRead"]),
                "fileWrite": statusValue(hostile["fileWrite"]),
                "childProcessExecute": statusValue(hostile["childProcessExecute"]),
                "childProcessRead": statusValue(hostile["childProcessRead"]),
                "childProcessWrite": statusValue(hostile["childProcessWrite"]),
                "network": statusValue(hostile["network"]),
                "credentialEnvironmentKeys": credentialCount,
            ],
        ]
    }

    static func runChild(
        node: URL,
        script: URL,
        arguments: [String] = [],
        environment: [String: String]
    ) throws -> ChildResult {
        let child = Process()
        child.executableURL = node
        child.arguments = [script.path] + arguments
        child.environment = environment
        let output = Pipe()
        let errors = Pipe()
        child.standardOutput = output
        child.standardError = errors
        try child.run()
        child.waitUntilExit()
        let stdout = output.fileHandleForReading.readDataToEndOfFile()
        let stderr = errors.fileHandleForReading.readDataToEndOfFile()
        return ChildResult(
            status: child.terminationStatus,
            termination: child.terminationReason == .exit ? "exit" : "signal",
            stdout: String(data: stdout.prefix(8192), encoding: .utf8) ?? "",
            stderrBytes: stderr.count
        )
    }

    static func main() {
        guard CommandLine.arguments.count == 3 else {
            fputs("expected protected read and write paths\n", stderr)
            exit(64)
        }

        let resources = Bundle.main.bundleURL.appendingPathComponent("Contents/Resources", isDirectory: true)
        let node = resources.appendingPathComponent("node", isDirectory: false)
        let script = resources.appendingPathComponent("dsh/runtime-probe.mjs", isDirectory: false)
        let crashScript = resources.appendingPathComponent("dsh/crash-probe.mjs", isDirectory: false)
        let environment = [
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": NSHomeDirectory(),
            "TMPDIR": NSTemporaryDirectory(),
            "KHAOS_PROTECTED_READ_PATH": CommandLine.arguments[1],
            "KHAOS_PROTECTED_WRITE_PATH": CommandLine.arguments[2],
        ]
        do {
            let crashedChild = try runChild(
                node: node,
                script: crashScript,
                environment: environment
            )
            let runtimeChild = try runChild(
                node: node,
                script: script,
                environment: environment
            )
            let crashIsolation = crashedChild.termination == "signal"
                && crashedChild.status == 15
            let probe = sanitizedProbeEvidence(runtimeChild.stdout)
            let evidence = [
                "firstChildTermination": crashedChild.termination,
                "firstChildStatus": crashedChild.status,
                "childRestartAfterCrash": crashIsolation ? "PASS" : "FAILED",
                "childExitStatus": runtimeChild.status,
                "childTerminationReason": runtimeChild.termination,
                "childStderrBytes": runtimeChild.stderrBytes,
            ] as [String: Any]
            persistEvidence(evidence.merging(probe) { _, new in new })
            guard crashIsolation,
                  runtimeChild.termination == "exit",
                  runtimeChild.status == 0 else {
                exit(2)
            }
            exit(0)
        } catch {
            persistEvidence(["hostError": "node_launch_failed", "errorType": String(describing: type(of: error))])
            exit(70)
        }
    }
}
