import Darwin
import Foundation

enum KernelWorkspaceRootFailure: Error {
    case invalidBookmark
    case bookmarkAccessDenied
    case workspaceAccessDenied
    case workspaceUnavailable
    case workspaceChanged

    var diagnosticCode: String {
        switch self {
        case .invalidBookmark: return "bookmark"
        case .bookmarkAccessDenied: return "bookmark-access"
        case .workspaceAccessDenied: return "workspace-access"
        case .workspaceUnavailable: return "workspace"
        case .workspaceChanged: return "workspace-changed"
        }
    }
}

enum KernelWorkspaceRoot {
    static func openChildDirectory(
        _ name: String,
        relativeTo parentDescriptor: Int32
    ) throws -> Int32 {
        guard !name.isEmpty, !name.contains("/"), name != ".", name != ".." else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(EINVAL))
        }
        let descriptor = Darwin.openat(
            parentDescriptor,
            name,
            O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC
        )
        guard descriptor >= 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }
        do {
            _ = try directoryIdentity(descriptor)
            return descriptor
        } catch {
            _ = Darwin.close(descriptor)
            throw error
        }
    }

    static func withScopedBookmark<Value>(
        _ bookmark: Data,
        operation: (URL, Int32, Data) throws -> Value
    ) throws -> (value: Value, stale: Bool, refreshed: Bool) {
        do {
            _ = try KernelWorkspaceXPC.boundedBookmarkLength(bookmark.count)
        } catch {
            throw KernelWorkspaceRootFailure.invalidBookmark
        }

        var stale = false
        let workspace: URL
        do {
            workspace = try URL(
                resolvingBookmarkData: bookmark,
                options: [],
                relativeTo: nil,
                bookmarkDataIsStale: &stale
            )
        } catch {
            throw KernelWorkspaceRootFailure.invalidBookmark
        }
        guard workspace.startAccessingSecurityScopedResource() else {
            throw KernelWorkspaceRootFailure.bookmarkAccessDenied
        }
        // Keep bookmark scope active for every operation using its descriptors.
        defer { workspace.stopAccessingSecurityScopedResource() }

        let root = try openWorkspaceDirectory(workspace)
        defer { _ = Darwin.close(root.descriptor) }
        guard stale else {
            return (try operation(workspace, root.descriptor, bookmark), false, false)
        }

        let refreshedBookmark: Data
        do {
            refreshedBookmark = try workspace.bookmarkData(
                options: [],
                includingResourceValuesForKeys: nil,
                relativeTo: nil
            )
            _ = try KernelWorkspaceXPC.boundedBookmarkLength(refreshedBookmark.count)
        } catch {
            throw KernelWorkspaceRootFailure.invalidBookmark
        }

        var refreshedBookmarkIsStale = false
        let refreshedWorkspace: URL
        do {
            refreshedWorkspace = try URL(
                resolvingBookmarkData: refreshedBookmark,
                options: [],
                relativeTo: nil,
                bookmarkDataIsStale: &refreshedBookmarkIsStale
            )
        } catch {
            throw KernelWorkspaceRootFailure.invalidBookmark
        }
        guard !refreshedBookmarkIsStale else {
            throw KernelWorkspaceRootFailure.invalidBookmark
        }
        guard refreshedWorkspace.startAccessingSecurityScopedResource() else {
            throw KernelWorkspaceRootFailure.bookmarkAccessDenied
        }
        defer { refreshedWorkspace.stopAccessingSecurityScopedResource() }

        let refreshedRoot = try openWorkspaceDirectory(refreshedWorkspace)
        defer { _ = Darwin.close(refreshedRoot.descriptor) }
        guard root.identity.0 == refreshedRoot.identity.0,
              root.identity.1 == refreshedRoot.identity.1
        else {
            throw KernelWorkspaceRootFailure.workspaceChanged
        }
        return (
            try operation(
                refreshedWorkspace,
                refreshedRoot.descriptor,
                refreshedBookmark
            ),
            true,
            true
        )
    }

    private static func openWorkspaceDirectory(
        _ workspace: URL
    ) throws -> (descriptor: Int32, identity: (dev_t, ino_t)) {
        let descriptor = Darwin.open(
            workspace.path,
            O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC
        )
        guard descriptor >= 0 else {
            throw workspaceFailure(
                for: NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
            )
        }
        do {
            return (descriptor, try directoryIdentity(descriptor))
        } catch {
            _ = Darwin.close(descriptor)
            throw workspaceFailure(for: error)
        }
    }

    private static func directoryIdentity(_ descriptor: Int32) throws -> (dev_t, ino_t) {
        var info = stat()
        guard Darwin.fstat(descriptor, &info) == 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }
        guard (info.st_mode & S_IFMT) == S_IFDIR else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(ENOTDIR))
        }
        return (info.st_dev, info.st_ino)
    }

    private static func workspaceFailure(for error: Error) -> KernelWorkspaceRootFailure {
        let failure = error as NSError
        if failure.domain == NSPOSIXErrorDomain,
           (failure.code == Int(EPERM) || failure.code == Int(EACCES)) {
            return .workspaceAccessDenied
        }
        return .workspaceUnavailable
    }
}
