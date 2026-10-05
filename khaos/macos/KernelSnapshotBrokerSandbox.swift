import Darwin
import Foundation

enum KernelSnapshotBrokerSandboxError: Error {
    case invalidContainer
    case unavailable
    case policyRejected(Int32)
}

enum KernelSnapshotBrokerSandbox {
    static func kernelTemporaryRoot(identifier: String) throws -> URL {
        guard identifier == "org.khaos.Seed.KernelProduction" else {
            throw KernelSnapshotBrokerSandboxError.invalidContainer
        }
        return FileManager.default.temporaryDirectory
            .resolvingSymlinksInPath()
            .standardizedFileURL
    }

    static func apply(kernelIdentifier: String) throws {
        let home = FileManager.default.homeDirectoryForCurrentUser
            .standardizedFileURL
        let storageRoot = try kernelTemporaryRoot(identifier: kernelIdentifier)
            .appendingPathComponent(
                KernelSnapshotStoragePolicy.brokerDirectoryName,
                isDirectory: true
            )
            .standardizedFileURL
        guard storageRoot.path.hasPrefix("/var/folders/")
                || storageRoot.path.hasPrefix("/private/var/folders/") else {
            throw KernelSnapshotBrokerSandboxError.invalidContainer
        }

        // The Broker needs one private subtree, never peer accounts or /Users/Shared.
        let userRoot = home.path.hasPrefix("/Users/") ? "/Users" : home.path
        var protectedRoots = [userRoot]
        if userRoot == "/Users" {
            protectedRoots.append("/System/Volumes/Data/Users")
        }
        let userDataRules = protectedRoots.map { path in
            "(deny file-read-data (subpath \(sbplString(path))))"
        }.joined(separator: "\n")
        let userWriteRules = protectedRoots.map { path in
            "(deny file-read-xattr file-write* (subpath \(sbplString(path))))"
        }.joined(separator: "\n")
        let userMetadataRules = protectedRoots.map { path in
            "(deny file-read-metadata file-test-existence (subpath \(sbplString(path))))"
        }.joined(separator: "\n")
        // Package-manager trees may be user-writable but are not Broker storage.
        let packageManagerRoots = [
            "/opt/homebrew", "/usr/local",
            "/System/Volumes/Data/opt/homebrew",
            "/System/Volumes/Data/usr/local",
        ]
        let packageManagerWriteRules = packageManagerRoots.map { path in
            "(deny file-write* (subpath \(sbplString(path))))"
        }.joined(separator: "\n")
        let temporaryRoots = [
            "/private/var/folders", "/var/folders",
            "/private/tmp", "/tmp",
            "/private/var/tmp", "/var/tmp",
            "/System/Volumes/Data/private/var/folders",
            "/System/Volumes/Data/private/tmp",
            "/System/Volumes/Data/private/var/tmp",
        ]
        let restrictedExecutionRoots =
            protectedRoots + packageManagerRoots + temporaryRoots
        let restrictedExecutionRules = restrictedExecutionRoots.map { path in
            "(deny process-exec (subpath \(sbplString(path))))"
        }.joined(separator: "\n")
        let storagePaths = storageRoot.path.hasPrefix("/private/")
            ? [storageRoot.path, String(storageRoot.path.dropFirst("/private".count))]
            : [storageRoot.path, "/private\(storageRoot.path)"]
        let storageAliases = storagePaths.flatMap { path in
            path.hasPrefix("/private/")
                ? [path, "/System/Volumes/Data\(path)"]
                : [path]
        }
        let storageExceptions = storageAliases.map { path in
            """
            (require-not (subpath \(sbplString(path))))
            (require-not (path-ancestors \(sbplString(path))))
            """
        }.joined(separator: "\n")
        let temporaryRules = temporaryRoots.map { path in
            """
            (deny file-read-data file-read-metadata file-read-xattr
              file-test-existence file-write*
              (require-all
                (subpath \(sbplString(path)))
                \(storageExceptions)))
            """
        }.joined(separator: "\n")
        let profile = """
        (version 1)
        (allow default)
        (deny network*)
        (deny signal)
        (allow signal (target same-sandbox))
        \(userDataRules)
        \(userWriteRules)
        \(packageManagerWriteRules)
        \(userMetadataRules)
        \(restrictedExecutionRules)
        \(temporaryRules)
        (deny file-read-data file-read-xattr file-write*
          (subpath "/Volumes"))
        """

        try apply(profile)
    }

    private static func apply(_ profile: String) throws {
        guard let library = dlopen("/usr/lib/libsandbox.dylib", RTLD_NOW) else {
            throw KernelSnapshotBrokerSandboxError.unavailable
        }
        defer { dlclose(library) }

        guard let initializeSymbol = dlsym(library, "sandbox_init"),
              let freeErrorSymbol = dlsym(library, "sandbox_free_error") else {
            throw KernelSnapshotBrokerSandboxError.unavailable
        }
        typealias Initialize = @convention(c) (
            UnsafePointer<CChar>?,
            UInt64,
            UnsafeMutablePointer<UnsafeMutablePointer<CChar>?>?
        ) -> Int32
        typealias FreeError = @convention(c) (UnsafeMutablePointer<CChar>?) -> Void
        let initialize = unsafeBitCast(initializeSymbol, to: Initialize.self)
        let freeError = unsafeBitCast(freeErrorSymbol, to: FreeError.self)
        var errorBuffer: UnsafeMutablePointer<CChar>? = nil
        let status = profile.withCString {
            initialize($0, 0, &errorBuffer)
        }
        if let errorBuffer {
            freeError(errorBuffer)
        }
        guard status == 0 else {
            throw KernelSnapshotBrokerSandboxError.policyRejected(status)
        }
    }

    private static func sbplString(_ value: String) -> String {
        let escaped = value
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        return "\"\(escaped)\""
    }
}
