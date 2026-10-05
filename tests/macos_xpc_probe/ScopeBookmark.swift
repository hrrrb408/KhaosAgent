import Darwin
import Foundation

@main
struct ScopeBookmarkProbe {
    static func main() {
        switch CommandLine.arguments[1] {
        case "create":
            guard CommandLine.arguments.count == 3 else { exit(2) }
            createBookmark()
        case "consume":
            guard CommandLine.arguments.count == 4 else { exit(2) }
            consumeBookmark()
        default:
            exit(2)
        }
    }

    private static func createBookmark() {
        do {
            let workspace = URL(
                fileURLWithPath: CommandLine.arguments[2],
                isDirectory: true
            )
            let bookmark = try workspace.bookmarkData(
                options: [.withSecurityScope],
                includingResourceValuesForKeys: nil,
                relativeTo: nil
            )
            print(bookmark.base64EncodedString())
        } catch {
            fail(error)
        }
    }

    private static func consumeBookmark() {
        guard let bookmark = Data(base64Encoded: CommandLine.arguments[2]) else {
            exit(2)
        }
        do {
            let result = try KernelWorkspaceRoot.withScopedBookmark(bookmark) {
                _, rootDescriptor, _ in
                let descriptor = Darwin.openat(
                    rootDescriptor,
                    "canary.txt",
                    O_RDONLY | O_CLOEXEC | O_NOFOLLOW
                )
                guard descriptor >= 0 else {
                    throw NSError(
                        domain: NSPOSIXErrorDomain,
                        code: Int(errno)
                    )
                }
                _ = Darwin.close(descriptor)
                return true
            }
            if result.value { exit(3) }
        } catch KernelWorkspaceRootFailure.bookmarkAccessDenied,
                KernelWorkspaceRootFailure.workspaceAccessDenied {
            // The untrusted bookmark resolves, but the OS keeps its scope denied.
        } catch let error as NSError {
            fail(error)
        }

        let canary = URL(fileURLWithPath: CommandLine.arguments[3])
            .appendingPathComponent("canary.txt")
        let descriptor = Darwin.open(
            canary.path,
            O_RDONLY | O_CLOEXEC | O_NOFOLLOW
        )
        let openError = errno
        if descriptor >= 0 { _ = Darwin.close(descriptor) }
        guard descriptor < 0, openError == EPERM || openError == EACCES else {
            exit(3)
        }
        print("scope=denied open=denied:\(openError)")
    }

    private static func fail(_ error: Error) -> Never {
        FileHandle.standardError.write(Data("\(error)\n".utf8))
        exit(4)
    }
}
