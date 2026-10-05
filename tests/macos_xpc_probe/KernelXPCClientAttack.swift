import Foundation

@main
struct KernelXPCClientAttack {
    static func main() {
        guard CommandLine.arguments.count == 2,
              !CommandLine.arguments[1].isEmpty
        else {
            exit(2)
        }

        let result = KernelBootstrapPeerProbe.status(
            serviceName: CommandLine.arguments[1]
        )
        FileHandle.standardOutput.write(Data("\(result)\n".utf8))
        if result == "peer=accepted" {
            exit(1)
        }
    }
}
