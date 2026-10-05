import Foundation

// Keep executor selection in trusted service code, never in XPC requests.
@main
enum KernelWorkspaceServiceMain {
    static func main() {
        do {
            let service = try KernelWorkspaceBootstrapService(
                executor: KernelWorkspacePythonExecutor.execute
            )
            service.run()
        } catch {
            FileHandle.standardError.write(
                Data("kernel-bootstrap=unavailable\n".utf8)
            )
            exit(EXIT_FAILURE)
        }
    }
}
