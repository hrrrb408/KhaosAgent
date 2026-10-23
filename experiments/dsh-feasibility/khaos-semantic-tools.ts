import { createHash } from 'node:crypto'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type { Context } from '@deepseek-ai/cordis'
import type { DshAgentTelemetry } from './dsh-agent-telemetry.ts'
import {
  KhaosProposalSession,
  type KhaosLauncherPort,
  type KhaosProposalCorrelation,
  type KhaosShellProposal,
  type KhaosToolResult,
} from './khaos-capability-adapter.ts'

const MAX_PATH_BYTES = 128
const MAX_TEXT_BYTES = 4 * 1024
const MAX_OPERATIONS = 8
const MAX_WRITES = 3
const MAX_REPAIRS = 3
const READ_SCRIPT = 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"),end="")'
const TEST_SCRIPT = "import sys,unittest; sys.path.insert(0,'.'); r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('.',pattern='test_public.py')); raise SystemExit(not r.wasSuccessful())"
const TOOL_NAMES = ['read_file', 'replace_text', 'run_tests'] as const

export type SemanticToolName = typeof TOOL_NAMES[number]

export interface KhaosCodingToolPolicy {
  readonly trialId: string
  readonly taskId: string
  readonly readFiles: readonly string[]
  readonly writeFiles: readonly string[]
  readonly fixedEditScript: string
}

type Phase = 'read' | 'edit' | 'verify' | 'repair' | 'complete'

function bytes(value: string): number {
  return Buffer.byteLength(value, 'utf8')
}

function safeRelativePath(value: string): boolean {
  if (!value || bytes(value) > MAX_PATH_BYTES || value.startsWith('/') || value.includes('\\') || value.includes('\0')) {
    return false
  }
  if (/[\u0001-\u001f\u007f]/u.test(value)) return false
  const parts = value.split('/')
  return parts.length <= 64 && parts.every(part => part.length > 0 && part !== '.' && part !== '..')
}

function exactObject(value: unknown, expectedKeys: readonly string[], label: string): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error(`invalid_${label}`)
  const record = value as Record<string, unknown>
  if (Object.keys(record).sort().join(',') !== [...expectedKeys].sort().join(',')) throw new Error(`invalid_${label}`)
  return record
}

function canonicalPythonJSONString(value: string): string {
  let result = '"'
  for (let index = 0; index < value.length; index++) {
    const first = value.charCodeAt(index)
    if (first >= 0xd800 && first <= 0xdbff) {
      const second = value.charCodeAt(index + 1)
      if (!(second >= 0xdc00 && second <= 0xdfff)) throw new Error('invalid_unicode_text')
    } else if (first >= 0xdc00 && first <= 0xdfff) {
      const previous = value.charCodeAt(index - 1)
      if (!(previous >= 0xd800 && previous <= 0xdbff)) throw new Error('invalid_unicode_text')
    }
  }
  for (const character of value) {
    const scalar = character.codePointAt(0) as number
    switch (scalar) {
      case 0x08: result += '\\b'; break
      case 0x09: result += '\\t'; break
      case 0x0a: result += '\\n'; break
      case 0x0c: result += '\\f'; break
      case 0x0d: result += '\\r'; break
      case 0x22: result += '\\"'; break
      case 0x5c: result += '\\\\'; break
      default:
        if (scalar <= 0x1f || (scalar >= 0x7f && scalar <= 0xffff)) {
          result += unicodeEscape(scalar)
        } else if (scalar <= 0x7e) {
          result += character
        } else if (scalar <= 0xffff) {
          result += unicodeEscape(scalar)
        } else {
          const offset = scalar - 0x10000
          result += unicodeEscape(0xd800 + (offset >> 10))
          result += unicodeEscape(0xdc00 + (offset & 0x3ff))
        }
    }
  }
  return `${result}"`
}

function unicodeEscape(value: number): string {
  return `\\u${value.toString(16).padStart(4, '0')}`
}

function sha256(value: string): string {
  return createHash('sha256').update(value, 'utf8').digest('hex')
}

function operationSucceeded(result: KhaosToolResult): boolean {
  return result.ok && (result.returncode === undefined || result.returncode === 0)
}

function validatePolicy(policy: KhaosCodingToolPolicy): void {
  const idValid = /^[A-Za-z0-9_.:-]{1,128}$/u.test(policy.trialId)
  const validList = (values: readonly string[]) => values.length > 0
    && values.length <= 8
    && new Set(values).size === values.length
    && values.every(safeRelativePath)
  if (!idValid || !/^[A-D]$/u.test(policy.taskId)
    || !validList(policy.readFiles) || !validList(policy.writeFiles)
    || !policy.writeFiles.every(path => policy.readFiles.includes(path))
    || !policy.fixedEditScript.startsWith('exec(')
    || !policy.fixedEditScript.endsWith(')')
    || bytes(policy.fixedEditScript) > MAX_TEXT_BYTES) {
    throw new Error('invalid_semantic_tool_policy')
  }
}

function proposalDigest(proposal: KhaosShellProposal): string {
  return sha256(JSON.stringify({ argv: proposal.argv, readScope: proposal.readScope, writeScope: proposal.writeScope }))
}

function outputSchema() {
  return {
    schema: {
      type: 'object',
      properties: {
        ok: { type: 'boolean', required: true },
        canContinue: { type: 'boolean', required: true },
        text: { type: 'string', required: true },
        returncode: { type: 'integer' },
      },
      additionalProperties: false,
    },
    render: (_args: unknown, result: KhaosToolResult) => [{ type: 'text' as const, text: JSON.stringify(result) }],
  }
}

function semanticEvent(
  telemetry: DshAgentTelemetry,
  event: string,
  toolName: SemanticToolName,
  callId: string,
  extra: Readonly<Record<string, string | number | boolean>> = {},
): void {
  const position = telemetry.position()
  telemetry.emit(event, {
    agent_turn_id: position.turn,
    agent_step_id: position.step,
    ...(position.modelCallId ? { model_call_id: position.modelCallId } : {}),
    tool_call_id: callId,
    tool_name: toolName,
    ...extra,
  })
}

/** Cordis tools lower intent into the existing bounded Launcher proposal port. */
export function createKhaosSemanticToolsPlugin(
  port: KhaosLauncherPort,
  policy: KhaosCodingToolPolicy,
  telemetry: DshAgentTelemetry,
  setVisibleTools: (names: readonly SemanticToolName[]) => void,
) {
  validatePolicy(policy)
  const session = new KhaosProposalSession(port, () => undefined)
  const readFiles = new Set(policy.readFiles)
  const seenCallIds = new Set<string>()
  const completedReads = new Set<string>()
  let phase: Phase = 'read'
  let operationSequence = 0
  let writeOperations = 0
  let repairAttempts = 0
  let testRuns = 0
  let closed = false

  const visibleTools = (): readonly SemanticToolName[] => {
    if (closed || phase === 'complete') return []
    if (phase === 'read') return ['read_file']
    if (phase === 'edit') return ['replace_text']
    if (phase === 'verify') return ['run_tests']
    return ['read_file', 'replace_text']
  }

  const execute = async (
    toolName: SemanticToolName,
    args: unknown,
    callId: string,
    signal: AbortSignal,
  ): Promise<KhaosToolResult> => {
    if (closed || session.isClosed) throw new Error('semantic_tool_session_closed')
    if (!/^[A-Za-z0-9_.:-]{1,128}$/u.test(callId) || seenCallIds.has(callId)) {
      if (/^[A-Za-z0-9_.:-]{1,128}$/u.test(callId)) {
        semanticEvent(telemetry, 'TOOL_ARGUMENT_REJECTED', toolName, callId, { error_code: 'duplicate_tool_call_id' })
      }
      throw new Error('duplicate_or_invalid_tool_call_id')
    }
    if (seenCallIds.size >= MAX_OPERATIONS) throw new Error('semantic_operation_limit_exceeded')
    seenCallIds.add(callId)
    if (!visibleTools().includes(toolName)) {
      semanticEvent(telemetry, 'TOOL_ARGUMENT_REJECTED', toolName, callId, { error_code: 'tool_not_allowed_in_current_phase' })
      throw new Error('tool_not_allowed_in_current_phase')
    }
    if (signal.aborted) throw new Error('semantic_tool_cancelled_before_submission')

    let argsBytes = 0
    let pathCount = 0
    let proposal: KhaosShellProposal
    let correlation: KhaosProposalCorrelation
    let readPath: string | undefined
    let testProfile = false
    try {
      if (toolName === 'read_file') {
        const record = exactObject(args, ['path'], 'read_file_arguments')
        if (typeof record.path !== 'string' || !safeRelativePath(record.path)
          || !readFiles.has(record.path)
          || (phase === 'read' && completedReads.has(record.path))) {
          throw new Error('path_not_in_read_scope')
        }
        readPath = record.path
        argsBytes = bytes(record.path)
        pathCount = 1
        proposal = {
          argv: ['python3', '-I', '-B', '-c', READ_SCRIPT, record.path],
          readScope: [record.path],
          writeScope: [],
        }
      } else if (toolName === 'replace_text') {
        const record = exactObject(args, ['path', 'oldText', 'newText'], 'replace_text_arguments')
        if (typeof record.path !== 'string' || !safeRelativePath(record.path)
          || !policy.writeFiles.includes(record.path)) throw new Error('path_not_in_write_scope')
        if (typeof record.oldText !== 'string' || typeof record.newText !== 'string'
          || !record.oldText || record.oldText === record.newText
          || bytes(record.oldText) > MAX_TEXT_BYTES || bytes(record.newText) > MAX_TEXT_BYTES) {
          throw new Error('invalid_replacement_text')
        }
        const oldText = canonicalPythonJSONString(record.oldText)
        const newText = canonicalPythonJSONString(record.newText)
        if (bytes(oldText) > MAX_TEXT_BYTES || bytes(newText) > MAX_TEXT_BYTES) {
          throw new Error('replacement_encoding_too_large')
        }
        proposal = {
          argv: ['python3', '-I', '-B', '-c', policy.fixedEditScript, record.path, oldText, newText],
          readScope: [record.path],
          writeScope: [record.path],
        }
        argsBytes = bytes(record.path) + bytes(record.oldText) + bytes(record.newText)
        pathCount = 1
      } else {
        const record = exactObject(args, ['profile'], 'run_tests_arguments')
        if (record.profile !== 'public') throw new Error('test_profile_not_allowed')
        proposal = {
          argv: ['python3', '-I', '-B', '-c', TEST_SCRIPT],
          readScope: [...policy.readFiles],
          writeScope: [],
        }
        argsBytes = bytes('public')
        pathCount = policy.readFiles.length
        testProfile = true
      }
      const nextSequence = operationSequence + 1
      const digest = proposalDigest(proposal)
      if (operationSequence >= MAX_OPERATIONS) throw new Error('semantic_operation_limit_exceeded')
      if (toolName === 'replace_text') {
        if (writeOperations >= MAX_WRITES) throw new Error('semantic_write_limit_exceeded')
        if (testRuns > 0 && repairAttempts >= MAX_REPAIRS) throw new Error('semantic_repair_limit_exceeded')
      }
      if (toolName === 'run_tests' && testRuns >= MAX_OPERATIONS) throw new Error('semantic_test_limit_exceeded')
      semanticEvent(telemetry, 'TOOL_ARGUMENT_VALIDATED', toolName, callId, {
        argument_bytes: argsBytes,
        file_count: pathCount,
      })
      semanticEvent(telemetry, 'TOOL_PROPOSAL_LOWERED', toolName, callId, {
        operation_seq: nextSequence,
        invocation_sha256: digest,
        argument_bytes: argsBytes,
        file_count: pathCount,
        write_operation: toolName === 'replace_text',
      })
      operationSequence = nextSequence
      if (toolName === 'replace_text') {
        writeOperations += 1
        if (testRuns > 0) repairAttempts += 1
      }
      if (testProfile) testRuns += 1
      telemetry.bindToolCall(callId, nextSequence)
      const position = telemetry.position()
      correlation = {
        trialId: telemetry.trialId,
        sessionId: telemetry.sessionId,
        benchmarkTaskId: policy.taskId,
        turn: position.turn,
        step: position.step,
        ...(position.modelCallId ? { modelCallId: position.modelCallId } : {}),
        toolCallId: callId,
        operationSequence: nextSequence,
        toolName,
        invocationSHA256: digest,
      }
    } catch (error) {
      semanticEvent(telemetry, 'TOOL_ARGUMENT_REJECTED', toolName, callId, {
        error_code: error instanceof Error && /^[a-z0-9_]{1,80}$/u.test(error.message)
          ? error.message : 'semantic_tool_rejected',
      })
      throw error
    }

    let result: KhaosToolResult
    try {
      result = await session.submit(proposal, callId, signal, correlation)
    } catch (error) {
      closed = true
      setVisibleTools([])
      semanticEvent(telemetry, 'TOOL_SUBMISSION_FAILED', toolName, callId, {
        operation_seq: operationSequence,
        invocation_sha256: proposalDigest(proposal),
        error_code: error instanceof Error && /^[a-z0-9_]{1,80}$/u.test(error.message)
          ? error.message : 'launcher_submission_failed',
      })
      throw error
    }
    telemetry.markLauncherResultReceived(callId, result.text)
    const succeeded = operationSucceeded(result)
    if (toolName === 'read_file' && succeeded && readPath) completedReads.add(readPath)
    if (toolName === 'replace_text') {
      phase = succeeded ? 'verify' : (testRuns > 0 ? 'repair' : 'edit')
    } else if (toolName === 'run_tests') {
      phase = succeeded ? 'complete' : 'repair'
    } else if (phase === 'read' && policy.readFiles.every(path => completedReads.has(path))) {
      // Task C requires observing the intentionally failing public suite before its first repair.
      phase = policy.taskId === 'C' ? 'verify' : 'edit'
    }
    if (!result.canContinue) closed = true
    setVisibleTools(visibleTools())
    return result
  }

  const plugin = (ctx: Context): void => {
    const disposers = [
      ctx.tools.register(defineTool({
        name: 'read_file',
        description: `Read one exact allowlisted source or public test file. Allowed paths: ${policy.readFiles.join(', ')}.`,
        parameters: { path: { type: 'string', enum: [...policy.readFiles], required: true } },
        output: outputSchema(),
        execute: (args, exec) => execute('read_file', args, String(exec.callId), exec.signal),
      })),
      ctx.tools.register(defineTool({
        name: 'replace_text',
        description: `Replace one exact, unique, non-empty text span in one existing allowlisted source file. Allowed paths: ${policy.writeFiles.join(', ')}.`,
        parameters: {
          path: { type: 'string', enum: [...policy.writeFiles], required: true },
          oldText: { type: 'string', required: true },
          newText: { type: 'string', required: true },
        },
        output: outputSchema(),
        execute: (args, exec) => execute('replace_text', args, String(exec.callId), exec.signal),
      })),
      ctx.tools.register(defineTool({
        name: 'run_tests',
        description: 'Run only the fixed public unittest profile. Hidden acceptance tests are never available to this tool.',
        parameters: { profile: { type: 'string', enum: ['public'], required: true } },
        output: outputSchema(),
        execute: (args, exec) => execute('run_tests', args, String(exec.callId), exec.signal),
      })),
    ]
    ctx.effect(() => () => {
      closed = true
      session.close()
      setVisibleTools([])
      for (const dispose of disposers.reverse()) dispose()
    })
  }

  return Object.assign(plugin, { inject: ['tools'] as const })
}

export const semanticToolTestSupport = {
  canonicalPythonJSONString,
  proposalDigest,
  readScript: READ_SCRIPT,
  testScript: TEST_SCRIPT,
  toolNames: TOOL_NAMES,
}
