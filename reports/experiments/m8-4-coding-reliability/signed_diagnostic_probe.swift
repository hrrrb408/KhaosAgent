import Darwin
import Foundation

// Disposable preflight client, never included in a formal A/C product.
// No API key, user turn, workspace request, or model completion is sent.
@main
enum SignedDiagnosticProbe {
    static func main() {
        do {
            let client = AgentHostClient()
            let reply = try client.sendToolResult(
                ok: false, canContinue: false,
                text: "M84_SYNTHETIC_PRIVATE_CANARY", activePlugin: nil
            )
            guard case .failure("invalid_request") = reply else { exit(2) }
            print("signed-host-diagnostic=invalid_request")
        } catch { exit(3) }
    }
}
