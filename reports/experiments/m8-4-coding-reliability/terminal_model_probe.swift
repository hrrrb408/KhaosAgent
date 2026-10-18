import Darwin
import Foundation

// Deterministic preflight data source, excluded from formal model statistics.
if CommandLine.arguments.contains("--version") {
    print("M8.4 deterministic terminal model probe")
    exit(0)
}
let arguments = CommandLine.arguments
guard let index = arguments.firstIndex(of: "--file"), index + 1 < arguments.count,
      let data = try? Data(contentsOf: URL(fileURLWithPath: arguments[index + 1])),
      data.count <= 64 * 1024 else { exit(1) }
let completed = String(decoding: data, as: UTF8.self).contains("Trusted Launcher control for proposal #")
let action: [String: Any] = [
    "type": completed ? "text" : "shell",
    "text": completed ? "The preflight operation has returned; inspect the Launcher record." : "",
    "argv": completed ? [] : ["/usr/bin/true"],
    "readScope": [String](), "writeScope": [String](),
    "pluginID": "", "candidateDigest": "", "generation": 0,
    "pluginInput": "", "evolutionGoal": "",
]
let encoded = try JSONSerialization.data(withJSONObject: action, options: [.sortedKeys])
print("\n> " + String(decoding: encoded, as: UTF8.self))
