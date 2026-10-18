# Oh My Pi editing review

## Source pin and scope

- Repository: [can1357/oh-my-pi](https://github.com/can1357/oh-my-pi)
- Reviewed commit: ba85aef0b343a25f3c90b4f86628a9bd92d8414d
- Scope: edit modes, Hashline prompt and anchoring, read/search output, diagnostics, edit staging and tests.
- This is pinned source review; no Oh My Pi build or upstream test suite was run.

## Tool surface and edit pipeline

The TypeScript EditTool exposes several modes: replace, patch, apply_patch, hashline, and sloppy. The current default is hashline in [settings.ts](https://github.com/can1357/oh-my-pi/blob/ba85aef0b343a25f3c90b4f86628a9bd92d8414d/packages/coding-agent/src/edit/settings.ts#L20-L47). The tool is essential and exclusive. Its approval decision scans the paths and move destinations in the parsed payload, then asks the session's internal URL router for the strictest required write tier. Approval details show the target paths; this is the project's own user/tool policy, not a Khaos Kernel boundary. See [EditTool metadata and approval](https://github.com/can1357/oh-my-pi/blob/ba85aef0b343a25f3c90b4f86628a9bd92d8414d/packages/coding-agent/src/edit/index.ts#L355-L435).

The edit execution path opens the Rust-backed EditSession, supplies policy and a URL resolver, parses/stages the request, then passes each resulting write request to the host callback. Success returns structured per-file details including diff, operation, changed line, and any LSP diagnostics. Failure text is returned as a tool error. See [EditTool.execute](https://github.com/can1357/oh-my-pi/blob/ba85aef0b343a25f3c90b4f86628a9bd92d8414d/packages/coding-agent/src/edit/index.ts#L493-L549) and [result assembly](https://github.com/can1357/oh-my-pi/blob/ba85aef0b343a25f3c90b4f86628a9bd92d8414d/packages/coding-agent/src/edit/index.ts#L226-L265).

## Hashline anchoring

The compact prompt documents a patch envelope with a file path and a four-hex snapshot tag, followed by line-anchored PUT, CUT, move, and clipboard operations. It says to anchor only lines visible in the latest read or search and to reread after every edit because tags and line numbers change. The source prompt is [hashline-compact.md](https://github.com/can1357/oh-my-pi/blob/ba85aef0b343a25f3c90b4f86628a9bd92d8414d/packages/coding-agent/src/edit/hashline-compact.md#L1-L24).

The read tool records a whole-file snapshot tag when hashline mode has enough complete, non-truncated source. Its source explains the tag is a content hash of the whole file; truncated or selected reads cannot pretend to prove lines that were not observed. See [read.ts snapshot tagging](https://github.com/can1357/oh-my-pi/blob/ba85aef0b343a25f3c90b4f86628a9bd92d8414d/packages/coding-agent/src/tools/read.ts#L2489-L2511). Read has inline path/range selectors, bounded output, truncation notices, and only emits editable hashline rows when it has complete lines. A regex grep tool searches paths and returns bounded line-oriented matches; see [grep.ts](https://github.com/can1357/oh-my-pi/blob/ba85aef0b343a25f3c90b4f86628a9bd92d8414d/packages/coding-agent/src/tools/grep.ts#L472-L525).

Native hashline staging checks the required snapshot tag, resolves each path, rejects duplicate sections that resolve to one canonical file, and applies edits against stored snapshots. The implementation describes staging all parsed sections before they are handed to the host writer. See [patcher.rs](https://github.com/can1357/oh-my-pi/blob/ba85aef0b343a25f3c90b4f86628a9bd92d8414d/crates/pi-edit/src/modes/hashline/patcher.rs#L591-L670).

Tests exercise stale line anchors, inserts and deletes after shifts, unseen lines, and repeated identical content. For example, [stale and duplicate anchor cases](https://github.com/can1357/oh-my-pi/blob/ba85aef0b343a25f3c90b4f86628a9bd92d8414d/crates/pi-edit/src/modes/hashline/patcher.rs#L915-L1063) reject edits that could silently hit the wrong occurrence and preserve the file on those failures.

## Read and post-edit feedback

Read accepts a path or an inline selector rather than a separate offset/limit object. Its formatting paths account for byte and line caps, identify omitted ranges, and only produce Hashline anchors for source that is completely visible. The model can use grep to move from a test identifier to implementation references without printing whole files.

Edit results carry per-file diffs and diagnostics. LSP results and patch warnings are merged into the EditTool result in [toPerFileResult](https://github.com/can1357/oh-my-pi/blob/ba85aef0b343a25f3c90b4f86628a9bd92d8414d/packages/coding-agent/src/edit/index.ts#L205-L265). Diagnostics improve the next model decision but do not authorize or enforce file access.

The host writer uses ordinary local file operations. Move writes the destination and then deletes the source; other operations use a writethrough helper. The host callback is visible at [EditTool.#write](https://github.com/can1357/oh-my-pi/blob/ba85aef0b343a25f3c90b4f86628a9bd92d8414d/packages/coding-agent/src/edit/index.ts#L674-L799). Staging validates the edit before that callback, but this review does not claim every multi-file physical write is an atomic transaction.

## Tradeoffs and relevance to Khaos

Hashline addresses a real model problem: a stale line number alone is not a trustworthy location. The whole-file tag, seen-line provenance and conservative rejection make stale edits easier to diagnose. It also costs a native edit engine, snapshot state, line-format rules, recovery logic, prompt conventions, search integration, and LSP plumbing. It is broader than the present Khaos Seed needs.

For M8.5.1, the relevant lesson is to bound an edit against observed content and return actionable failures. Hashline is a candidate for a later study only if a minimal exact-text edit proves insufficient. Its native parser and host write path are not portable Khaos security controls. Khaos must continue to route all model intent through its own Launcher approval, exact scopes, Runner and Kernel changeset validation.
