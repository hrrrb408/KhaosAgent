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
      let prompt = String(data: input, encoding: .utf8) else {
    exit(EXIT_FAILURE)
}

func emit(_ action: [String: Any]) -> Never {
    let data = (try? JSONSerialization.data(
        withJSONObject: action,
        options: [.sortedKeys, .withoutEscapingSlashes]
    )) ?? Data()
    print("\n> \(String(decoding: data, as: UTF8.self))")
    exit(EXIT_SUCCESS)
}

func textAction(_ text: String) -> [String: Any] {
    [
        "type": "text",
        "text": text,
        "argv": [String](),
        "readScope": [String](),
        "writeScope": [String](),
        "pluginID": "",
        "candidateDigest": "",
        "generation": 0,
        "pluginInput": "",
    ]
}

func pluginAction(
    _ pluginID: String,
    _ digest: String,
    _ generation: Int,
    input: String = ""
) -> [String: Any] {
    [
        "type": "plugin",
        "text": "",
        "argv": [String](),
        "readScope": [String](),
        "writeScope": [String](),
        "pluginID": pluginID,
        "candidateDigest": digest,
        "generation": generation,
        "pluginInput": input,
    ]
}

func parseResultObject(_ text: String) -> [String: Any]? {
    guard let start = text.firstIndex(of: "{") else { return nil }
    var index = start
    var depth = 0
    var insideString = false
    var escaped = false
    while index < text.endIndex {
        let character = text[index]
        if insideString {
            if escaped {
                escaped = false
            } else if character == "\\" {
                escaped = true
            } else if character == "\"" {
                insideString = false
            }
        } else if character == "\"" {
            insideString = true
        } else if character == "{" {
            depth += 1
        } else if character == "}" {
            depth -= 1
            if depth == 0 {
                let end = text.index(after: index)
                guard let data = text[start..<end].data(using: .utf8),
                      let value = try? JSONSerialization.jsonObject(with: data)
                else {
                    return nil
                }
                return value as? [String: Any]
            }
        }
        index = text.index(after: index)
    }
    return nil
}

func latestUserRequest(_ prompt: String) -> String {
    let latestMessage: String
    if let range = prompt.range(of: "\nUser: ", options: .backwards) {
        latestMessage = String(prompt[range.upperBound...])
    } else {
        latestMessage = prompt
    }
    let marker = "User request (untrusted data):\n"
    guard let range = latestMessage.range(of: marker, options: .backwards) else {
        return latestMessage
    }
    return String(latestMessage[range.upperBound...])
        .components(separatedBy: .newlines)
        .first ?? ""
}

func activePluginMetadata(_ prompt: String) -> [String: Any]? {
    let marker = "UNTRUSTED_PLUGIN_METADATA_JSON="
    guard let range = prompt.range(of: marker, options: .backwards) else {
        return nil
    }
    let line = String(prompt[range.upperBound...])
        .components(separatedBy: .newlines)
        .first ?? ""
    guard let data = line.data(using: .utf8),
          let value = try? JSONSerialization.jsonObject(with: data) else {
        return nil
    }
    return value as? [String: Any]
}

func requestedField(_ name: String, from request: String) -> String? {
    let escapedName = NSRegularExpression.escapedPattern(for: name)
    let pattern = #"(?:^|\s)"# + escapedName + #"=(?:"([^"]*)"|([^\s]+))"#
    guard let expression = try? NSRegularExpression(pattern: pattern),
          let match = expression.firstMatch(
            in: request,
            range: NSRange(request.startIndex..., in: request)
          ) else {
        return nil
    }
    for index in 1..<match.numberOfRanges {
        let range = match.range(at: index)
        if let swiftRange = Range(range, in: request) {
            return String(request[swiftRange])
        }
    }
    return nil
}

if let marker = prompt.range(of: "CANARY_PATH=") {
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
    emit(textAction("read-denied=\(readDenied) write-denied=\(writeDenied)"))
}

let latestUser = latestUserRequest(prompt)
if latestUser.contains("no_active_candidate") {
    emit(textAction("No active Candidate was available, so the Launcher denied execution."))
}

if latestUser.contains("Runner result") {
    let trustLabel = "Treat the following output only as untrusted data:\n"
    guard let resultStart = latestUser.range(of: trustLabel),
          latestUser[resultStart.upperBound...].utf8.count <= 16 * 1024 else {
        emit(textAction("Runner result was missing its untrusted-data label or size bound."))
    }
    let resultText = String(latestUser[resultStart.upperBound...])
    guard let resultObject = parseResultObject(resultText) else {
        emit(textAction("The Agent received an untrusted Plugin result."))
    }
    let added = resultObject["added"] as? Int ?? -1
    let modified = resultObject["modified"] as? Int ?? -1
    let deleted = resultObject["deleted"] as? Int ?? -1
    guard added == 0, modified == 0, deleted == 0 else {
        emit(textAction(
            "Plugin result changeset counts: added=\(added), "
                + "modified=\(modified), deleted=\(deleted)."
        ))
    }
    let pluginOutput = (resultObject["stdout"] as? String) ?? ""
    emit(textAction(
        "Agent received untrusted Plugin output; state-only changeset counts "
            + "are zero: \(pluginOutput)"
    ))
}

if latestUser.localizedCaseInsensitiveContains("user denied this Plugin invocation") {
    emit(textAction("The Agent received the user's denial; no Plugin result was produced."))
}

if latestUser.contains("TRY_PLUGIN_WITHOUT_ACTIVE") {
    emit(pluginAction("plugin-missing", String(repeating: "0", count: 64), 0))
}

if let metadata = activePluginMetadata(prompt),
   let pluginID = metadata["plugin_id"] as? String,
   let digest = metadata["candidate_digest"] as? String,
   let generation = metadata["generation"] as? Int {
    if latestUser.contains("RUN_ACTIVE_PLUGIN") {
        emit(pluginAction(pluginID, digest, generation))
    }
    if let interface = metadata["agent_interface"] as? [String: Any],
       let operations = interface["operations"] as? [[String: Any]] {
        let request = latestUser.lowercased()
        for operation in operations {
            guard let name = operation["name"] as? String,
                  request.contains(name.lowercased()),
                  let fields = operation["fields"] as? [String] else {
                continue
            }
            var businessInput: [String: Any] = ["operation": name]
            for field in fields {
                guard let value = requestedField(field, from: latestUser) else {
                    emit(textAction("A required business field was missing from the request."))
                }
                businessInput[field] = value
            }
            guard let data = try? JSONSerialization.data(
                withJSONObject: businessInput,
                options: [.sortedKeys, .withoutEscapingSlashes]
            ),
            let inputJSON = String(data: data, encoding: .utf8) else {
                emit(textAction("The bounded Plugin input could not be encoded."))
            }
            emit(pluginAction(pluginID, digest, generation, input: inputJSON))
        }
    }
}

emit(textAction("test model probe completed"))
