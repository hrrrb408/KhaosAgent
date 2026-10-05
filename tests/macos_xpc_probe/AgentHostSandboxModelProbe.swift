import Darwin
import Foundation

if CommandLine.arguments.dropFirst().first == "--version" {
    print("llama.cpp sandbox probe")
    exit(EXIT_SUCCESS)
}

let arguments = Array(CommandLine.arguments.dropFirst())
guard let fileOption = arguments.firstIndex(of: "--file"),
      fileOption + 1 < arguments.count else {
    exit(EXIT_FAILURE)
}
let promptURL = URL(fileURLWithPath: arguments[fileOption + 1])
let input = (try? Data(contentsOf: promptURL)) ?? Data()
guard input.count <= 64 * 1024,
      let prompt = String(data: input, encoding: .utf8),
      let marker = prompt.range(of: "CANARY_PATH=") else {
    exit(EXIT_FAILURE)
}
let path = String(prompt[marker.upperBound...])
    .components(separatedBy: .newlines)[0]
guard !path.isEmpty else { exit(EXIT_FAILURE) }

func denied(_ flags: Int32) -> Bool {
    let descriptor = Darwin.open(path, flags | O_CLOEXEC | O_NOFOLLOW, 0o600)
    if descriptor >= 0 {
        Darwin.close(descriptor)
        return false
    }
    return errno == EPERM || errno == EACCES
}

let readDenied = denied(O_RDONLY)
let writeDenied = denied(O_WRONLY | O_APPEND)
print("\n> {\"type\":\"text\",\"text\":\"read-denied=\(readDenied) write-denied=\(writeDenied)\",\"argv\":[],\"readScope\":[],\"writeScope\":[]}")
