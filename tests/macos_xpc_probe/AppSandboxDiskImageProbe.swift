import Darwin
import Foundation

@_silgen_name("flock")
private func flockDescriptor(_ descriptor: Int32, _ operation: Int32) -> Int32


private func runTool(
    _ executable: String,
    _ arguments: [String]
) throws -> (Int32, Data, Data) {
    let process = Process()
    let output = Pipe()
    let errorOutput = Pipe()
    process.executableURL = URL(fileURLWithPath: executable)
    process.arguments = arguments
    process.standardOutput = output
    process.standardError = errorOutput
    try process.run()
    process.waitUntilExit()
    return (
        process.terminationStatus,
        output.fileHandleForReading.readDataToEndOfFile(),
        errorOutput.fileHandleForReading.readDataToEndOfFile()
    )
}

private func attachedAPFSVolumeDevice(for image: URL) throws -> String? {
    let (status, output, errorOutput) = try runTool(
        "/usr/bin/hdiutil",
        ["info", "-plist"]
    )
    guard status == 0 else {
        throw NSError(
            domain: "AppSandboxDiskImageProbe",
            code: 7,
            userInfo: [
                NSLocalizedDescriptionKey: String(
                    decoding: errorOutput,
                    as: UTF8.self
                )
            ]
        )
    }
    guard let info = try PropertyListSerialization.propertyList(
            from: output,
            options: [],
            format: nil
          ) as? [String: Any],
          let images = info["images"] as? [[String: Any]] else {
        throw NSError(domain: "AppSandboxDiskImageProbe", code: 8)
    }
    guard let attached = images.first(where: {
        ($0["image-path"] as? String) == image.path
    }) else { return nil }
    guard let entities = attached["system-entities"] as? [[String: Any]] else {
        throw NSError(domain: "AppSandboxDiskImageProbe", code: 9)
    }

    let apfsVolumeHint = "41504653-0000-11AA-AA11-00306543ECAC"
    return entities.first(where: {
        ($0["content-hint"] as? String)?.uppercased() == apfsVolumeHint
    }).flatMap { entity in
        guard let device = entity["dev-entry"] as? String,
              device.range(
                of: #"^/dev/disk[0-9]+s[0-9]+$"#,
                options: .regularExpression
              ) != nil else {
            return nil
        }
        return device
    }
}

private func runProbe() throws {
    let temporary = FileManager.default.temporaryDirectory
        .appendingPathComponent("khaos-app-sandbox-image-\(UUID().uuidString)", isDirectory: true)
    try FileManager.default.createDirectory(at: temporary, withIntermediateDirectories: false)
    defer { try? FileManager.default.removeItem(at: temporary) }

    let canary = temporary.appendingPathComponent("sandbox-write-canary")
    try Data("temporary-write-allowed".utf8).write(to: canary, options: .atomic)
    print("sandbox-temporary-write=allowed")

    let (nestedSandboxStatus, _, nestedSandboxError) = try runTool(
        "/usr/bin/sandbox-exec",
        ["-p", "(version 1) (allow default)", "/usr/bin/true"]
    )
    print("sandbox-nested-seatbelt-status=\(nestedSandboxStatus)")
    print(
        "sandbox-nested-seatbelt-apply-denied="
            + String(
                String(decoding: nestedSandboxError, as: UTF8.self)
                    .contains("sandbox_apply: Operation not permitted")
            )
    )

    let createdImage = temporary.appendingPathComponent("sandbox-created.sparsebundle")
    let (createStatus, _, _) = try runTool(
        "/usr/bin/hdiutil",
        [
            "create",
            "-type",
            "SPARSEBUNDLE",
            "-sectors",
            "131072",
            "-layout",
            "NONE",
            "-fs",
            "APFS",
            "-volname",
            "KhaosWork",
            "-nospotlight",
            createdImage.path,
        ]
    )
    print("sandbox-hdiutil-create-status=\(createStatus)")
    print(
        "sandbox-hdiutil-create-output-exists="
            + String(FileManager.default.fileExists(atPath: createdImage.path))
    )

    guard let resources = Bundle.main.resourceURL else {
        throw NSError(domain: "AppSandboxDiskImageProbe", code: 1)
    }
    let bundledImage = resources.appendingPathComponent(
        "workspace.sparsebundle",
        isDirectory: true
    )
    let hdiutilImage = temporary.appendingPathComponent(
        "hdiutil-workspace.sparsebundle",
        isDirectory: true
    )
    try FileManager.default.copyItem(at: bundledImage, to: hdiutilImage)
    let hdiutilMount = temporary.appendingPathComponent("hdiutil-mount", isDirectory: true)
    try FileManager.default.createDirectory(
        at: hdiutilMount,
        withIntermediateDirectories: false
    )
    print("sandbox-hdiutil-image-path=\(hdiutilImage.path)")
    print("sandbox-hdiutil-mount-point=\(hdiutilMount.path)")
    let (hdiutilAttachStatus, _, _) = try runTool(
        "/usr/bin/hdiutil",
        [
            "attach",
            "-plist",
            "-nobrowse",
            "-mountpoint",
            hdiutilMount.path,
            hdiutilImage.path,
        ]
    )
    print("sandbox-hdiutil-attach-status=\(hdiutilAttachStatus)")

    let diskutilImage = temporary.appendingPathComponent(
        "diskutil-workspace.sparsebundle",
        isDirectory: true
    )
    try FileManager.default.copyItem(at: bundledImage, to: diskutilImage)
    let diskutilMount = temporary.appendingPathComponent("diskutil-mount", isDirectory: true)
    try FileManager.default.createDirectory(
        at: diskutilMount,
        withIntermediateDirectories: false
    )
    print("sandbox-diskutil-image-path=\(diskutilImage.path)")
    print("sandbox-diskutil-mount-point=\(diskutilMount.path)")
    let (diskutilAttachStatus, diskutilAttachOutput, diskutilAttachError) = try runTool(
        "/usr/sbin/diskutil",
        [
            "image",
            "attach",
            "--plist",
            "--nobrowse",
            "--mountPoint",
            diskutilMount.path,
            diskutilImage.path,
        ]
    )
    print("sandbox-diskutil-attach-status=\(diskutilAttachStatus)")
    print(
        "sandbox-diskutil-attach-output="
            + String(decoding: diskutilAttachOutput, as: UTF8.self)
            + String(decoding: diskutilAttachError, as: UTF8.self),
        terminator: ""
    )
    if let volumeDevice = try attachedAPFSVolumeDevice(for: diskutilImage) {
        let (mountStatus, mountOutput, mountError) = try runTool(
            "/usr/sbin/diskutil",
            ["mount", "-mountPoint", diskutilMount.path, volumeDevice]
        )
        print("sandbox-diskutil-mount-status=\(mountStatus)")
        print(
            "sandbox-diskutil-mount-output="
                + String(decoding: mountOutput, as: UTF8.self)
                + String(decoding: mountError, as: UTF8.self),
            terminator: ""
        )
    } else {
        print("sandbox-diskutil-mount-status=not-attempted")
    }
}

private func mountProbeRoot(_ token: String) throws -> URL {
    guard let applicationSupport = FileManager.default.urls(
        for: .applicationSupportDirectory,
        in: .userDomainMask
    ).first else {
        throw NSError(domain: "AppSandboxDiskImageProbe", code: 6)
    }
    return applicationSupport
        .appendingPathComponent("KhaosMountedImageProbe", isDirectory: true)
        .appendingPathComponent("khaos-mounted-image-\(token)", isDirectory: true)
}

private func prepareMountProbe(_ token: String) throws {
    let root = try mountProbeRoot(token)
    let mountPoint = root.appendingPathComponent("mount", isDirectory: true)
    try FileManager.default.createDirectory(
        at: mountPoint,
        withIntermediateDirectories: true
    )
    let applicationSupport = root
        .deletingLastPathComponent()
        .deletingLastPathComponent()
    print("sandbox-application-support=\(applicationSupport.path)")
    print("sandbox-mount-probe-root=\(root.path)")
    print("sandbox-mount-point=\(mountPoint.path)")
}

private func reportAccess<T>(_ operation: String, _ body: () throws -> T) -> T? {
    do {
        let value = try body()
        print("sandbox-mounted-volume-\(operation)=allowed")
        return value
    } catch {
        let failure = error as NSError
        print(
            "sandbox-mounted-volume-\(operation)=denied:\(failure.domain):\(failure.code)"
        )
        return nil
    }
}

private func reportDirectoryMetadata(_ path: URL, label: String) {
    let descriptor = Darwin.open(
        path.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC
    )
    guard descriptor >= 0 else {
        print("sandbox-directory-\(label)-open=denied:\(errno)")
        return
    }
    defer { _ = Darwin.close(descriptor) }
    print("sandbox-directory-\(label)-open=allowed")
    if label == "data-volume" {
        let lockStatus = flockDescriptor(descriptor, LOCK_EX | LOCK_NB)
        print(
            "sandbox-directory-data-volume-lock="
                + (lockStatus == 0 ? "allowed" : "denied:\(errno)")
        )
        if lockStatus == 0 { _ = flockDescriptor(descriptor, LOCK_UN) }
    }

    var fullPathAttributes = attrlist()
    fullPathAttributes.bitmapcount = UInt16(ATTR_BIT_MAP_COUNT)
    fullPathAttributes.commonattr = attrgroup_t(ATTR_CMN_FULLPATH)
    var fullPathResult = [UInt8](repeating: 0, count: 4096)
    let fullPathStatus = fullPathResult.withUnsafeMutableBytes { bytes in
        Darwin.fgetattrlist(
            descriptor, &fullPathAttributes, bytes.baseAddress, bytes.count, 0
        )
    }
    if fullPathStatus == 0 {
        let pathMatches = fullPathResult.withUnsafeBytes { bytes -> Bool in
            let reference = bytes.loadUnaligned(
                fromByteOffset: 4, as: attrreference_t.self
            )
            let start = 4 + Int(reference.attr_dataoffset)
            let end = start + Int(reference.attr_length)
            guard start >= 12, end <= bytes.count, end > start else {
                return false
            }
            let content = bytes[start..<end]
            return content.dropLast().elementsEqual(path.path.utf8)
                && content.last == 0
        }
        print(
            "sandbox-directory-\(label)-fullpath="
                + (pathMatches ? "matches" : "differs")
        )
    } else {
        print("sandbox-directory-\(label)-fullpath=denied:\(errno)")
    }

    var attributes = attrlist()
    attributes.bitmapcount = UInt16(ATTR_BIT_MAP_COUNT)
    attributes.volattr = attrgroup_t(ATTR_VOL_INFO) | attrgroup_t(ATTR_VOL_MOUNTPOINT)
    var result = [UInt8](repeating: 0, count: 4096)
    let mountStatus = result.withUnsafeMutableBytes { bytes in
        Darwin.fgetattrlist(
            descriptor, &attributes, bytes.baseAddress, bytes.count, 0
        )
    }
    print(
        "sandbox-directory-\(label)-mountpoint="
            + (mountStatus == 0 ? "allowed" : "denied:\(errno)")
    )

    attributes.volattr = 0
    attributes.dirattr = attrgroup_t(ATTR_DIR_MOUNTSTATUS)
    let directoryStatus = result.withUnsafeMutableBytes { bytes in
        Darwin.fgetattrlist(
            descriptor, &attributes, bytes.baseAddress, bytes.count, 0
        )
    }
    print(
        "sandbox-directory-\(label)-mount-status="
            + (directoryStatus == 0 ? "allowed" : "denied:\(errno)")
    )
}

private func accessMountedVolume(_ token: String) throws {
    let mountPoint = try mountProbeRoot(token)
        .appendingPathComponent("mount", isDirectory: true)
    reportDirectoryMetadata(URL(fileURLWithPath: "/Users"), label: "users")
    reportDirectoryMetadata(
        URL(fileURLWithPath: "/System/Volumes/Data"), label: "data-volume"
    )
    reportDirectoryMetadata(
        mountPoint.deletingLastPathComponent(), label: "source"
    )
    reportDirectoryMetadata(mountPoint, label: "mounted")
    let hostCanary = mountPoint.appendingPathComponent("host-canary")
    if let data = reportAccess("read", { try Data(contentsOf: hostCanary) }) {
        guard data == Data("host-mounted-volume-canary".utf8) else {
            throw NSError(domain: "AppSandboxDiskImageProbe", code: 3)
        }
    }

    let writeback = mountPoint.appendingPathComponent("sandbox-writeback")
    let expected = Data("sandbox-mounted-volume-write".utf8)
    guard reportAccess("write", {
        try expected.write(to: writeback, options: .atomic)
    }) != nil else {
        return
    }
    guard let written = reportAccess("write-readback", {
        try Data(contentsOf: writeback)
    }) else {
        return
    }
    guard written == expected else {
        throw NSError(domain: "AppSandboxDiskImageProbe", code: 4)
    }
}

private func cleanupMountProbe(_ token: String) throws {
    let root = try mountProbeRoot(token)
    if FileManager.default.fileExists(atPath: root.path) {
        try FileManager.default.removeItem(at: root)
    }
    let probeDirectory = root.deletingLastPathComponent()
    if let children = try? FileManager.default.contentsOfDirectory(atPath: probeDirectory.path),
       children.isEmpty {
        try FileManager.default.removeItem(at: probeDirectory)
    }
}

@main
private struct AppSandboxDiskImageProbe {
    static func main() {
        do {
            let arguments = Array(CommandLine.arguments.dropFirst())
            if arguments.isEmpty {
                try runProbe()
            } else if arguments.count == 2 {
                let token = arguments[1]
                switch arguments[0] {
                case "prepare":
                    try prepareMountProbe(token)
                case "access":
                    try accessMountedVolume(token)
                case "cleanup":
                    try cleanupMountProbe(token)
                default:
                    throw NSError(domain: "AppSandboxDiskImageProbe", code: 5)
                }
            } else {
                throw NSError(domain: "AppSandboxDiskImageProbe", code: 5)
            }
        } catch {
            fputs("App-Sandboxed disk image probe failed: \(error)\n", stderr)
            exit(1)
        }
    }
}
