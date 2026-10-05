import AppKit
import Foundation

enum TrustedWorkspacePickerError: Error {
    case cancelled
}

struct TrustedWorkspaceSelection {
    let scopeURL: URL
    let bookmark: Data
}

enum TrustedWorkspacePicker {
    static func selectPluginPackage() throws -> URL {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = false
        panel.title = "Choose Khaos Plugin Package"
        panel.message = "Choose a folder containing canonical manifest.json and plugin.py."
        guard panel.runModal() == .OK, let selectedURL = panel.url else {
            throw TrustedWorkspacePickerError.cancelled
        }
        return selectedURL
    }

    static func selectWorkspace(
        initialDirectory: URL? = nil,
        message: String
    ) throws -> TrustedWorkspaceSelection {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = false
        panel.directoryURL = initialDirectory
        panel.title = "Choose Khaos Workspace"
        panel.message = message

        guard panel.runModal() == .OK, let selectedURL = panel.url else {
            throw TrustedWorkspacePickerError.cancelled
        }
        // Keep the panel's implicit scope in the bookmark passed across XPC.
        let bookmark = try selectedURL.bookmarkData(
            options: [],
            includingResourceValuesForKeys: nil,
            relativeTo: nil
        )
        return TrustedWorkspaceSelection(
            scopeURL: selectedURL,
            bookmark: bookmark
        )
    }
}
