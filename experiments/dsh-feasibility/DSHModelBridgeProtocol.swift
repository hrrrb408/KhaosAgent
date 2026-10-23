import Foundation

enum DSHModelBridgeLimits {
    static let maximumRequestBytes = 56 * 1_024
    static let maximumResponseBytes = 56 * 1_024
    static let maximumCompletionTokens = 2_048
    static let maximumModelCallsPerTask = 16
    static let maximumTaskSeconds = 600
    static let serviceName = "org.khaos.Seed.DSHModelBridge"
    static let hostRequirementInfoKey = "KhaosAgentHostRequirement"
    static let bridgeRequirementInfoKey = "KhaosDSHModelBridgeRequirement"
}

@objc protocol DSHModelBridgeEndpoint {
    func complete(
        _ body: NSData,
        headers: NSData,
        apiKey: NSString,
        timeoutSeconds: NSNumber,
        withReply reply: @escaping (NSData?, NSString?, NSNumber) -> Void
    )
}
