import Darwin
import Foundation

@main
struct KernelContainerCanaryProbe {
    private static let directoryPrefix = "khaos-runner-container-probe-"
    private static let fileName = "kernel-container-secret.txt"
    private static let contents = Data("kernel-container-only-secret".utf8)

    static func main() {
        guard CommandLine.arguments.count == 4,
              let operation = Operation(rawValue: CommandLine.arguments[1]),
              let identifier = UUID(uuidString: CommandLine.arguments[2]) else {
            fail("invalid_arguments")
        }
        do {
            let root = try validatedTemporaryRoot()
            let directory = root.appendingPathComponent(
                directoryPrefix + identifier.uuidString.lowercased(),
                isDirectory: true
            )
            let file = directory.appendingPathComponent(fileName)
            switch operation {
            case .create:
                try create(directory: directory, file: file)
                print("kernel-container-canary=created")
            case .verify:
                try verify(directory: directory, file: file)
                print("kernel-container-canary=verified")
            case .cleanup:
                try cleanup(directory: directory, file: file)
                print("kernel-container-canary=removed")
            }
        } catch {
            fail("operation_failed")
        }
    }

    private enum Operation: String {
        case create
        case verify
        case cleanup
    }

    private static func validatedTemporaryRoot() throws -> URL {
        let root = URL(fileURLWithPath: NSTemporaryDirectory(), isDirectory: true)
            .standardizedFileURL.resolvingSymlinksInPath()
        let expected = URL(
            fileURLWithPath: CommandLine.arguments[3].hasPrefix("/")
                ? CommandLine.arguments[3]
                : "/invalid",
            isDirectory: true
        ).standardizedFileURL.resolvingSymlinksInPath()
        guard root == expected else { throw ProbeFailure.invalidRoot }
        return root
    }

    private static func create(directory: URL, file: URL) throws {
        guard Darwin.mkdir(directory.path, 0o700) == 0 else {
            throw ProbeFailure.operationFailed
        }
        let descriptor = Darwin.open(
            file.path,
            O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW,
            0o600
        )
        guard descriptor >= 0 else { throw ProbeFailure.operationFailed }
        defer { _ = Darwin.close(descriptor) }
        try write(contents, to: descriptor)
        try verify(directory: directory, file: file)
        let result: [String: String] = ["path": file.path]
        let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
        guard let line = String(data: data, encoding: .utf8) else {
            throw ProbeFailure.operationFailed
        }
        print(line)
    }

    private static func verify(directory: URL, file: URL) throws {
        try validateDirectory(directory)
        let descriptor = Darwin.open(file.path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW)
        guard descriptor >= 0 else { throw ProbeFailure.operationFailed }
        defer { _ = Darwin.close(descriptor) }
        var info = stat()
        guard Darwin.fstat(descriptor, &info) == 0,
              (info.st_mode & S_IFMT) == S_IFREG,
              info.st_uid == geteuid(),
              info.st_nlink == 1,
              (info.st_mode & 0o777) == 0o600,
              try read(descriptor) == contents else {
            throw ProbeFailure.operationFailed
        }
    }

    private static func cleanup(directory: URL, file: URL) throws {
        try validateDirectory(directory)
        var info = stat()
        guard Darwin.lstat(file.path, &info) == 0,
              (info.st_mode & S_IFMT) == S_IFREG,
              info.st_uid == geteuid(),
              info.st_nlink == 1 else {
            throw ProbeFailure.operationFailed
        }
        guard Darwin.unlink(file.path) == 0,
              Darwin.rmdir(directory.path) == 0 else {
            throw ProbeFailure.operationFailed
        }
    }

    private static func validateDirectory(_ directory: URL) throws {
        var info = stat()
        guard Darwin.lstat(directory.path, &info) == 0,
              (info.st_mode & S_IFMT) == S_IFDIR,
              info.st_uid == geteuid(),
              (info.st_mode & 0o777) == 0o700,
              directory.resolvingSymlinksInPath().standardizedFileURL == directory
        else {
            throw ProbeFailure.operationFailed
        }
    }

    private static func write(_ data: Data, to descriptor: Int32) throws {
        try data.withUnsafeBytes { bytes in
            guard let base = bytes.baseAddress else { throw ProbeFailure.operationFailed }
            var offset = 0
            while offset < bytes.count {
                let result = Darwin.write(
                    descriptor,
                    base.advanced(by: offset),
                    bytes.count - offset
                )
                if result < 0 && errno == EINTR { continue }
                guard result > 0 else { throw ProbeFailure.operationFailed }
                offset += result
            }
        }
    }

    private static func read(_ descriptor: Int32) throws -> Data {
        var result = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while true {
            let count = buffer.withUnsafeMutableBytes { storage in
                Darwin.read(descriptor, storage.baseAddress, storage.count)
            }
            if count < 0 && errno == EINTR { continue }
            guard count >= 0 else { throw ProbeFailure.operationFailed }
            if count == 0 { return result }
            result.append(contentsOf: buffer.prefix(count))
            guard result.count <= contents.count else {
                throw ProbeFailure.operationFailed
            }
        }
    }

    private static func fail(_ code: String) -> Never {
        fputs("kernel-container-canary=failed code=\(code)\n", stderr)
        exit(EXIT_FAILURE)
    }
}

private enum ProbeFailure: Error {
    case invalidRoot
    case operationFailed
}
