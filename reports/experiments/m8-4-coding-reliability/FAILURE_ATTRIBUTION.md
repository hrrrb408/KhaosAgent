# M8.4 failure attribution

No formal model failure has occurred because no formal attempt has started.

Preflight zero-tool case: the deterministic local model returned text. The existing Launcher prints neither Task Status nor Task Record when toolCalls is zero. Its stdout joins the interactive You: prefix with the model-text marker. The observer consequently retains terminal_outcome_not_captured despite waiter exit 0. This is an existing terminal-evidence limitation, not failure to consume stdin, not a model protocol failure, and not task success. The initial capture is preserved as terminal-preflight-zero-tool.json. No Launcher or success definition is changed.

The replacement preflight uses one explicitly reviewed no-op tool to reach the existing Task Record path. Formal zero-tool outcomes will remain incomplete if no independent terminal exists. M8.2's historical missing-text attribution remains PARTIALLY_PROVEN and is background only; those attempts are excluded from M8.4 denominators.
