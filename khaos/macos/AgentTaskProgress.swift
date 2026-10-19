import AppKit
import Foundation

struct AgentTaskProgressResult<Value> {
    let result: Result<Value, Error>
    let cancellationRequested: Bool
}

final class AgentTaskProgress<Value>: NSObject {
    private let panel = NSPanel(
        contentRect: NSRect(x: 0, y: 0, width: 560, height: 180),
        styleMask: [.titled],
        backing: .buffered,
        defer: false
    )
    private let status = NSTextField(wrappingLabelWithString: "")
    private let cancelButton = NSButton(title: "Cancel task", target: nil, action: nil)
    private var result: Result<Value, Error>?
    private var cancellationRequested = false
    private var cancelAction: (() -> Void)?
    private let cancelCompletesImmediately: Bool

    init(
        taskID: UUID,
        title: String,
        message: String,
        cancelCompletesImmediately: Bool = false
    ) {
        self.cancelCompletesImmediately = cancelCompletesImmediately
        super.init()
        panel.title = "Khaos Agent Task \(taskID.uuidString.prefix(8).lowercased())"
        panel.isReleasedWhenClosed = false
        panel.standardWindowButton(.closeButton)?.isEnabled = false

        let content = NSView(frame: NSRect(x: 0, y: 0, width: 560, height: 180))
        status.stringValue = "\(title)\n\(message)"
        status.frame = NSRect(x: 24, y: 74, width: 512, height: 78)
        status.lineBreakMode = .byWordWrapping
        cancelButton.frame = NSRect(x: 394, y: 22, width: 142, height: 32)
        cancelButton.target = self
        cancelButton.action = #selector(cancelTask(_:))
        content.addSubview(status)
        content.addSubview(cancelButton)
        panel.contentView = content
    }

    func wait(
        start: @escaping (@escaping (Result<Value, Error>) -> Void) -> Void,
        cancel: @escaping () -> Void
    ) -> AgentTaskProgressResult<Value> {
        cancelAction = cancel
        panel.center()
        panel.makeKeyAndOrderFront(nil)
        NSApplication.shared.activate(ignoringOtherApps: true)
        start { [weak self] result in
            DispatchQueue.main.async {
                self?.finish(result)
            }
        }
        _ = NSApplication.shared.runModal(for: panel)
        panel.orderOut(nil)
        let finalResult = result ?? .failure(AgentTaskProgressError.resultUnavailable)
        return AgentTaskProgressResult(
            result: finalResult,
            cancellationRequested: cancellationRequested
        )
    }

    func updateStatus(_ message: String) {
        let update = { [weak self] in
            guard let self, self.result == nil else { return }
            self.status.stringValue = message
        }
        if Thread.isMainThread {
            update()
        } else {
            DispatchQueue.main.async(execute: update)
        }
    }

    private func finish(_ value: Result<Value, Error>) {
        guard result == nil else { return }
        result = value
        cancelButton.isEnabled = false
        if cancellationRequested && !cancelCompletesImmediately {
            status.stringValue = "The request returned a final result. Khaos is recording that result before ending this task."
        } else if cancellationRequested {
            status.stringValue = "This task was cancelled. Late Agent Host replies will be discarded."
        } else {
            status.stringValue = "The request returned a final result."
        }
        NSApplication.shared.stopModal(withCode: .OK)
    }

    @objc private func cancelTask(_ sender: Any?) {
        guard !cancellationRequested, result == nil else { return }
        cancellationRequested = true
        cancelButton.isEnabled = false
        status.stringValue = "Cancellation requested. Waiting for the active request's actual result."
        if cancelCompletesImmediately {
            finish(.failure(AgentTaskProgressError.cancelled))
        }
        cancelAction?()
    }
}

enum AgentTaskProgressError: Error {
    case resultUnavailable
    case cancelled
}
