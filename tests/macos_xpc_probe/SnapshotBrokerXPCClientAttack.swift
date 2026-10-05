import Foundation

@main
struct SnapshotBrokerXPCClientAttack {
    static func main() {
        guard CommandLine.arguments.count == 2,
              !CommandLine.arguments[1].isEmpty else {
            exit(2)
        }
        let result = SnapshotBrokerPeerProbe.status(
            serviceName: CommandLine.arguments[1]
        )
        FileHandle.standardOutput.write(Data("\(result)\n".utf8))
        if result == "peer=accepted" { exit(1) }
    }
}
