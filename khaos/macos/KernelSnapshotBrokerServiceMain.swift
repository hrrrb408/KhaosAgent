import Foundation
import OSLog

@main
enum KernelSnapshotBrokerServiceMain {
    private static let logger = Logger(
        subsystem: "org.khaos.Seed.KernelSnapshotBroker",
        category: "startup"
    )

    static func main() {
        do {
            guard let launcherRequirement = XPCPeerIdentity.codeSigningRequirement(
                forInfoKey: "KhaosLauncherCallerRequirement"
            ),
            let kernelRequirement = XPCPeerIdentity.codeSigningRequirement(
                forInfoKey: "KhaosKernelCallerRequirement"
            ),
            let identifier = Bundle.main.object(
                forInfoDictionaryKey: "KhaosKernelContainerIdentifier"
            ) as? String else {
                throw SnapshotBrokerConfigurationError.invalid
            }
            let service = try KernelSnapshotBrokerService(
                launcherRequirement: launcherRequirement,
                kernelRequirement: kernelRequirement,
                kernelIdentifier: identifier
            )
            logger.notice("startup=configured")
            try withExtendedLifetime(service) { try service.run() }
        } catch {
            if let sandboxError = error as? KernelSnapshotBrokerSandboxError {
                switch sandboxError {
                case .invalidContainer:
                    logger.error("startup=unavailable stage=container")
                case .unavailable:
                    logger.error("startup=unavailable stage=sandbox-runtime")
                case .policyRejected(let status):
                    logger.error("startup=unavailable stage=sandbox-policy status=\(status)")
                }
            }
            let failure = error as NSError
            logger.error(
                "startup=unavailable domain=\(failure.domain, privacy: .public) code=\(failure.code)"
            )
            FileHandle.standardError.write(
                Data("snapshot-broker=unavailable\n".utf8)
            )
            exit(EXIT_FAILURE)
        }
    }
}

private enum SnapshotBrokerConfigurationError: Error {
    case invalid
}
