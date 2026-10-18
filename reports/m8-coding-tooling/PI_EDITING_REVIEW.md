# Pi coding tools review

## Repository identity and source pin

- Requested project: badlogic/pi-mono.
- Current official repository: [earendil-works/pi](https://github.com/earendil-works/pi). GitHub's repository API resolves the former badlogic/pi-mono identity to this non-archived repository.
- Reviewed commit: 482c1381a00d8d00bc81697e4a980c593db6803e.
- The local checkout remote remains earendil-works/pi-mono.git; source links below use the canonical repository and exact reviewed commit.
- This is pinned source review; no Pi build or upstream test suite was run.

## Minimal tool set and loop

The coding-agent registers read, bash, edit and write definitions from [core/tools/index.ts](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/src/core/tools/index.ts#L112-L173). Their responsibilities stay separate:

- read(path, offset?, limit?) reads text or images. Text output is bounded by line and byte limits and carries a continuation hint when truncated. See [read.ts](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/src/core/tools/read.ts#L14-L23) and [execution/truncation](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/src/core/tools/read.ts#L153-L204).
- edit(path, edits[]) targets exact oldText/newText replacements in one file. Each oldText must be unique in the original content, and edits must not overlap.
- write(path, content) creates or overwrites a complete file and creates parent directories.
- bash(command, timeout?) runs a command and returns output, truncation metadata, and exit code.
- The agent loop executes tool calls, appends toolResult messages to context, and then makes the next model turn. See [agent-loop.ts](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/agent/src/agent-loop.ts#L261-L287).

The small surface is useful because each tool has a direct model job: inspect, locate, make a precise edit, create or rewrite a file, and verify by running a command. Pi still relies on the model to decide the order and meaning of the work.

## Edit semantics and feedback

The edit schema is defined in [edit.ts](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/src/core/tools/edit.ts#L21-L50). Input is a path plus one or more replacement objects. The prompt asks for exact, small, unique oldText and explains that all edits are matched against the same original file.

The executor resolves the path relative to cwd, serializes same-file mutations with a per-file queue, checks existence and access, reads UTF-8, preserves BOM and line-ending style, applies all replacements in memory, then writes and returns a diff, unified patch, and first changed line. See [execution](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/src/core/tools/edit.ts#L143-L212). The algorithm rejects empty, missing, duplicated, overlapping, or no-change edits with text that tells the model what to fix. Matching logic is in [edit-diff.ts](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/src/core/tools/edit-diff.ts#L247-L361).

This removes the need to write Python or shell quoting for an ordinary replacement. It also lets one call make several disjoint edits to one file. It does not support creating or deleting a file; those operations use the distinct write tool or other tooling. Pi offers legacy-input normalization in [prepareEditArguments](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/src/core/tools/edit.ts#L103-L134), which improves compatibility but adds a second accepted input shape.

## Read, write, bash, and verification

Read supports an explicit line offset and limit, bounded default output, and actionable continuation text. Write takes a complete content string, creates parent directories, and overwrites the target; it is intentionally distinct from a small edit. See [write.ts](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/src/core/tools/write.ts#L11-L19) and [write execution](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/src/core/tools/write.ts#L44-L93).

Bash has a command and optional timeout. The output schema includes an exit code and truncation flag; the tool returns bounded output and records where full output was saved when truncation occurs. See [bash.ts](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/src/core/tools/bash.ts#L40-L69) and [result formatting](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/src/core/tools/bash.ts#L338-L370). Tool results become new agent context before the following model response, so a failed test can drive a later edit without a separate planner framework.

## Tests and limits

Focused tests include successful replacement, missing target errors, disjoint edits, overlap rejection, all-or-nothing validation for multiple edits before the write, duplicate detection, legacy argument shapes, same-file mutation queuing, and queue safety while an aborted write is still in flight. Examples: [tools.test.ts](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/test/tools.test.ts#L282-L435), [duplicate/fuzzy tests](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/test/tools.test.ts#L1255-L1300), and [mutation queue tests](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/test/file-mutation-queue.test.ts#L37-L145).

The default file operations are direct local fs access and fs write calls. The tool's exact-match rules and mutation queue are application behavior; they do not prove path confinement, user approval, symlink defense, hardlink defense, race safety, or sandboxing. Do not port those as Khaos authority controls.

## Khaos implications

Pi's strongest minimal lesson is to move exact string matching and duplicate detection out of the model's hand-written script. For Khaos, the smallest compatible experiment is one existing file and one unique oldText replacement, translated by untrusted AgentHost code to the existing explicitly approved shell operation. Khaos must retain its own exact workspace scopes and Kernel checks. A Pi-style direct file write would not be an acceptable security implementation for Khaos.
