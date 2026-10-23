import AppKit
import Foundation

@main
enum LaunchSignedRuntimeProbe {
    static func main() {
        guard CommandLine.arguments.count == 2 else {
            fputs("expected app path\n", stderr)
            exit(64)
        }

        let appURL = URL(fileURLWithPath: CommandLine.arguments[1])
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = false
        configuration.createsNewApplicationInstance = true
        configuration.arguments = []

        let completed = DispatchSemaphore(value: 0)
        var runningApplication: NSRunningApplication?
        var launchError: Error?
        NSWorkspace.shared.openApplication(at: appURL, configuration: configuration) { application, error in
            runningApplication = application
            launchError = error
            completed.signal()
        }
        guard completed.wait(timeout: .now() + 20) == .success else {
            fputs("launch_services_timeout\n", stderr)
            exit(70)
        }
        guard let application = runningApplication, launchError == nil else {
            fputs("launch_services_failed\n", stderr)
            exit(71)
        }

        let deadline = Date().addingTimeInterval(45)
        while !application.isTerminated && Date() < deadline {
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        }
        guard application.isTerminated else {
            application.forceTerminate()
            fputs("signed_app_timeout\n", stderr)
            exit(72)
        }

        print("signed_app_terminated=true")
    }
}
