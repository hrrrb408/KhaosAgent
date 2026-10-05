import CoreFoundation
import Foundation

enum AgentHostReply {
    case text(String)
    case tool(AgentToolProposal)
    case failure(String)
}

struct AgentToolProposal {
    let argv: [String]
    let readScope: [String]
    let writeScope: [String]
}

@objc protocol AgentHostSessionEndpoint {
    func handle(
        _ frame: NSData,
        withReply reply: @escaping (NSData?) -> Void
    )
}

enum AgentHostProtocol {
    static let version = 1
    static let maximumFrameBytes = 64 * 1024
    static let maximumTextBytes = 16 * 1024
    static let maximumArguments = 32
    static let maximumScopePaths = 8
    static let maximumArgumentBytes = 4096

    static func userTurn(_ text: String) throws -> Data {
        guard boundedBytes(text, maximum: maximumTextBytes), !text.isEmpty else {
            throw AgentHostProtocolError.invalidRequest
        }
        return try encode([
            "version": version,
            "operation": "user",
            "text": text,
        ])
    }

    static func toolResult(ok: Bool, text: String) throws -> Data {
        guard boundedBytes(text, maximum: maximumTextBytes) else {
            throw AgentHostProtocolError.invalidRequest
        }
        return try encode([
            "version": version,
            "operation": "tool_result",
            "ok": ok,
            "text": text,
        ])
    }

    static func stop() throws -> Data {
        try encode(["version": version, "operation": "stop"])
    }

    static func decodeReply(_ data: Data) -> AgentHostReply? {
        guard let object = decodeObject(data),
              integer(object["version"]) == version,
              let type = object["type"] as? String
        else {
            return nil
        }
        switch type {
        case "text":
            guard Set(object.keys) == ["version", "type", "text"],
                  let text = object["text"] as? String,
                  boundedBytes(text, maximum: maximumTextBytes) else {
                return nil
            }
            return .text(text)
        case "tool":
            guard Set(object.keys) == [
                "version", "type", "argv", "read_scope", "write_scope"
            ],
                let argv = strings(
                    object["argv"], maximum: maximumArguments,
                    maximumItemBytes: maximumArgumentBytes
                ),
                let readScope = strings(
                    object["read_scope"], maximum: maximumScopePaths,
                    maximumItemBytes: 128
                ),
                let writeScope = strings(
                    object["write_scope"], maximum: maximumScopePaths,
                    maximumItemBytes: 128
                ),
                !argv.isEmpty,
                readScope.count + writeScope.count <= maximumScopePaths,
                Set(readScope).count == readScope.count,
                Set(writeScope).count == writeScope.count,
                (readScope + writeScope).allSatisfy(reviewable),
                argv.allSatisfy(reviewable) else {
                return nil
            }
            return .tool(AgentToolProposal(
                argv: argv,
                readScope: readScope,
                writeScope: writeScope
            ))
        case "error":
            guard Set(object.keys) == ["version", "type", "code"],
                  let code = object["code"] as? String,
                  code.utf8.count <= 64,
                  !code.isEmpty,
                  code.utf8.allSatisfy({
                    (0x61...0x7a).contains($0)
                        || (0x30...0x39).contains($0)
                        || $0 == 0x5f
                  }) else {
                return nil
            }
            return .failure(code)
        default:
            return nil
        }
    }

    static func decodeInput(_ data: Data) -> [String: Any]? {
        guard let object = decodeObject(data),
              integer(object["version"]) == version,
              let operation = object["operation"] as? String else {
            return nil
        }
        switch operation {
        case "user":
            guard Set(object.keys) == ["version", "operation", "text"],
                  let text = object["text"] as? String,
                  !text.isEmpty, boundedBytes(text, maximum: maximumTextBytes) else {
                return nil
            }
        case "tool_result":
            guard Set(object.keys) == ["version", "operation", "ok", "text"],
                  let ok = object["ok"] as? Bool,
                  let text = object["text"] as? String,
                  boundedBytes(text, maximum: maximumTextBytes) else {
                return nil
            }
            // JSON booleans and numeric 0/1 must not be interchangeable on the wire.
            guard let number = object["ok"] as? NSNumber,
                  CFGetTypeID(number) == CFBooleanGetTypeID(),
                  number.boolValue == ok else {
                return nil
            }
        case "stop":
            guard Set(object.keys) == ["version", "operation"] else {
                return nil
            }
        default:
            return nil
        }
        return object
    }

    static func encodeReply(_ reply: AgentHostReply) throws -> Data {
        switch reply {
        case let .text(text):
            guard boundedBytes(text, maximum: maximumTextBytes) else {
                throw AgentHostProtocolError.invalidResponse
            }
            return try encode(["version": version, "type": "text", "text": text])
        case let .tool(proposal):
            return try encode([
                "version": version,
                "type": "tool",
                "argv": proposal.argv,
                "read_scope": proposal.readScope,
                "write_scope": proposal.writeScope,
            ])
        case let .failure(code):
            return try encode(["version": version, "type": "error", "code": code])
        }
    }

    private static func encode(_ value: [String: Any]) throws -> Data {
        let data = try JSONSerialization.data(
            withJSONObject: value,
            options: [.sortedKeys, .withoutEscapingSlashes]
        )
        guard data.count <= maximumFrameBytes,
              isJSONNestingWithinLimit(data) else {
            throw AgentHostProtocolError.frameTooLarge
        }
        return data
    }

    private static func decodeObject(_ data: Data) -> [String: Any]? {
        guard !data.isEmpty, data.count <= maximumFrameBytes,
              isJSONNestingWithinLimit(data),
              let object = try? JSONSerialization.jsonObject(with: data),
              let dictionary = object as? [String: Any],
              let canonical = try? JSONSerialization.data(
                withJSONObject: dictionary,
                options: [.sortedKeys, .withoutEscapingSlashes]
              ),
              canonical == data else {
            return nil
        }
        return dictionary
    }

    private static func integer(_ value: Any?) -> Int? {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.stringValue == "1" else {
            return nil
        }
        return 1
    }

    private static func strings(
        _ value: Any?,
        maximum: Int,
        maximumItemBytes: Int
    ) -> [String]? {
        guard let values = value as? [String], values.count <= maximum,
              values.allSatisfy({
                !$0.isEmpty && boundedBytes($0, maximum: maximumItemBytes)
              }) else {
            return nil
        }
        return values
    }

    private static func boundedBytes(_ value: String, maximum: Int) -> Bool {
        value.utf8.count <= maximum
    }

    private static func reviewable(_ value: String) -> Bool {
        value.unicodeScalars.allSatisfy { scalar in
            !CharacterSet.controlCharacters.contains(scalar)
                && scalar.properties.generalCategory != .format
        }
    }

    private static func isJSONNestingWithinLimit(_ data: Data) -> Bool {
        var depth = 0
        var inString = false
        var escaped = false
        for byte in data {
            if inString {
                if escaped {
                    escaped = false
                } else if byte == 0x5c {
                    escaped = true
                } else if byte == 0x22 {
                    inString = false
                }
                continue
            }
            switch byte {
            case 0x22: inString = true
            case 0x7b, 0x5b:
                depth += 1
                if depth > 8 { return false }
            case 0x7d, 0x5d:
                depth -= 1
                if depth < 0 { return false }
            default: break
            }
        }
        return depth == 0 && !inString && !escaped
    }
}

enum AgentHostProtocolError: Error {
    case invalidRequest
    case invalidResponse
    case frameTooLarge
}
