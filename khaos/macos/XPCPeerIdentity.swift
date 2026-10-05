import Foundation

enum XPCPeerIdentity {
    static func codeSigningRequirement(forInfoKey requirementKey: String) -> String? {
        guard let requirement = Bundle.main.object(
            forInfoDictionaryKey: requirementKey
        ) as? String,
        !requirement.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else {
            return nil
        }
        return requirement
    }

    static func requirePeerIdentity(
        _ connection: NSXPCConnection,
        requirementKey: String
    ) -> Bool {
        guard let requirement = codeSigningRequirement(forInfoKey: requirementKey)
        else {
            return false
        }

        // Require macOS to authenticate the remote peer before either side resumes.
        connection.setCodeSigningRequirement(requirement)
        return true
    }
}
