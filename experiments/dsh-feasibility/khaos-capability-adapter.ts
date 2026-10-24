import { defineTool } from '@deepseek-ai/dsh-tools'
import type { Context } from '@deepseek-ai/cordis'

const MAX_PROPOSAL_BYTES = 48 * 1024
const MAX_ARGUMENTS = 32
const MAX_SCOPE_PATHS = 8
const MAX_ARGUMENT_BYTES = 4 * 1024
const MAX_SCOPE_PATH_BYTES = 128
const MAX_RESULT_BYTES = 4 * 1024

export interface KhaosShellProposal {
  readonly argv: readonly string[]
  readonly readScope: readonly string[]
  readonly writeScope: readonly string[]
}

export interface KhaosToolResult {
  readonly ok: boolean
  readonly canContinue: boolean
  readonly text: string
  readonly returncode?: number
  readonly launcherTrace?: LauncherOperationTrace
}

export interface LauncherOperationTrace {
  readonly trial_id: string
  readonly dsh_session_id: string
  readonly benchmark_task_id: string
  readonly agent_turn_id: number
  readonly agent_step_id: number
  readonly model_call_id?: string
  readonly tool_call_id: string
  readonly tool_name: string
  readonly operation_seq: number
  readonly invocation_sha256: string
  readonly launcher_task_id: string
  readonly launcher_request_id: string
  readonly launcher_approval_sha256: string
  readonly approval_status: string
  readonly kernel_result: string
  readonly runner_status: string
  readonly commit_status: string
  readonly launcher_ok: boolean
  readonly can_continue: boolean
  readonly returncode?: number
}

export interface KhaosProposalCorrelation {
  readonly trialId: string
  readonly sessionId: string
  readonly benchmarkTaskId: string
  readonly turn: number
  readonly step: number
  readonly modelCallId?: string
  readonly toolCallId: string
  readonly operationSequence: number
  readonly toolName: string
  readonly invocationSHA256: string
}

/**
 * Untrusted DSH-to-Host bridge. It only proposes an action; the existing
 * Trusted Launcher still performs review, approval, Kernel submission, and
 * result accounting. The bridge is scoped to one DSH Agent/task instance.
 */
export interface KhaosLauncherPort {
  submitProposal(
    proposal: KhaosShellProposal,
    signal: AbortSignal,
    correlation?: KhaosProposalCorrelation,
  ): Promise<KhaosToolResult>
  reportRejectedProposal?(): void
}

function utf8Bytes(value: string): number {
  return new TextEncoder().encode(value).byteLength
}

function boundedStringArray(
  value: unknown,
  maximumItems: number,
  maximumItemBytes: number,
  field: string,
  allowEmpty: boolean,
): string[] {
  if (!Array.isArray(value) || value.length > maximumItems) {
    throw new Error(`invalid ${field}`)
  }
  const result: string[] = []
  for (const item of value) {
    if (typeof item !== 'string'
      || (!allowEmpty && item.length === 0)
      || item.includes('\0')
      || utf8Bytes(item) > maximumItemBytes) {
      throw new Error(`invalid ${field}`)
    }
    result.push(item)
  }
  return result
}

function parseProposal(args: unknown): KhaosShellProposal {
  if (args === null || typeof args !== 'object' || Array.isArray(args)) {
    throw new Error('invalid capability proposal')
  }
  const record = args as Record<string, unknown>
  const keys = Object.keys(record).sort()
  if (keys.join(',') !== 'argv,readScope,writeScope') {
    throw new Error('invalid capability proposal')
  }

  const argv = boundedStringArray(record.argv, MAX_ARGUMENTS, MAX_ARGUMENT_BYTES, 'argv', true)
  const readScope = boundedStringArray(record.readScope, MAX_SCOPE_PATHS, MAX_SCOPE_PATH_BYTES, 'readScope', false)
  const writeScope = boundedStringArray(record.writeScope, MAX_SCOPE_PATHS, MAX_SCOPE_PATH_BYTES, 'writeScope', false)
  if (argv.length === 0) throw new Error('invalid capability proposal')

  const proposal = { argv, readScope, writeScope }
  if (utf8Bytes(JSON.stringify(proposal)) > MAX_PROPOSAL_BYTES) {
    throw new Error('capability proposal too large')
  }
  return proposal
}

function parseResult(value: unknown): KhaosToolResult {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('invalid Launcher result')
  }
  const record = value as Record<string, unknown>
  if (typeof record.ok !== 'boolean'
    || typeof record.canContinue !== 'boolean'
    || typeof record.text !== 'string'
    || utf8Bytes(record.text) > MAX_RESULT_BYTES
    || (record.returncode !== undefined
      && (!Number.isInteger(record.returncode) || Math.abs(record.returncode as number) > 2_147_483_647))) {
    throw new Error('invalid Launcher result')
  }
  const launcherTrace = record.launcherTrace === undefined
    ? undefined : parseLauncherTrace(record.launcherTrace)
  return {
    ok: record.ok,
    canContinue: record.canContinue,
    text: record.text,
    ...(record.returncode === undefined ? {} : { returncode: record.returncode as number }),
    ...(launcherTrace === undefined ? {} : { launcherTrace }),
  }
}

function parseLauncherTrace(value: unknown): LauncherOperationTrace {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('invalid Launcher trace')
  }
  const record = value as Record<string, unknown>
  const required = [
    'trial_id', 'dsh_session_id', 'benchmark_task_id', 'agent_turn_id', 'agent_step_id',
    'tool_call_id', 'tool_name', 'operation_seq', 'invocation_sha256',
    'launcher_task_id', 'launcher_request_id', 'launcher_approval_sha256', 'approval_status',
    'kernel_result', 'runner_status', 'commit_status', 'launcher_ok', 'can_continue',
  ]
  const optional = ['model_call_id', 'returncode']
  if (required.some(key => !(key in record))
    || Object.keys(record).some(key => !required.includes(key) && !optional.includes(key))) {
    throw new Error('invalid Launcher trace')
  }
  const ids = [
    record.trial_id, record.dsh_session_id, record.benchmark_task_id, record.tool_call_id,
    record.launcher_task_id, record.launcher_request_id,
  ]
  if (!ids.every(item => typeof item === 'string' && /^[A-Za-z0-9_.:-]{1,128}$/u.test(item))
    || !['read_file', 'replace_text', 'run_tests'].includes(record.tool_name as string)
    || !Number.isSafeInteger(record.agent_turn_id) || (record.agent_turn_id as number) < 0
    || !Number.isSafeInteger(record.agent_step_id) || (record.agent_step_id as number) < 0
    || !Number.isSafeInteger(record.operation_seq) || (record.operation_seq as number) < 1
    || typeof record.invocation_sha256 !== 'string' || !/^[0-9a-f]{64}$/u.test(record.invocation_sha256)
    || typeof record.launcher_approval_sha256 !== 'string' || !/^[0-9a-f]{64}$/u.test(record.launcher_approval_sha256)
    || !['ordinary', 'candidate_b_preview', 'denied', 'preview_incomplete'].some(status =>
      record.approval_status === status || record.approval_status === `approved_${status}`)
    || typeof record.kernel_result !== 'string' || !/^[a-z0-9_.:-]{1,128}$/u.test(record.kernel_result)
    || typeof record.runner_status !== 'string' || !/^[a-z0-9_.:-]{1,128}$/u.test(record.runner_status)
    || typeof record.commit_status !== 'string' || !/^[a-z0-9_.:-]{1,128}$/u.test(record.commit_status)
    || typeof record.launcher_ok !== 'boolean' || typeof record.can_continue !== 'boolean'
    || (record.model_call_id !== undefined
      && (typeof record.model_call_id !== 'string' || !/^[A-Za-z0-9_.:-]{1,128}$/u.test(record.model_call_id)))
    || (record.returncode !== undefined
      && (!Number.isInteger(record.returncode) || Math.abs(record.returncode as number) > 2_147_483_647))) {
    throw new Error('invalid Launcher trace')
  }
  return record as unknown as LauncherOperationTrace
}

/** One bounded proposal lifecycle shared by raw and semantic Cordis tools. */
export class KhaosProposalSession {
  private closed = false
  private closeVersion = 0
  private inFlight = false
  private readonly seenCallIds = new Set<string>()

  constructor(
    private readonly port: KhaosLauncherPort,
    private readonly onRejected?: () => void,
  ) {}

  async submit(
    args: unknown,
    callId: string,
    signal: AbortSignal,
    correlation?: KhaosProposalCorrelation,
  ): Promise<KhaosToolResult> {
    if (this.closed) throw new Error('Launcher ended this capability session')
    if (!callId || callId.length > 128 || this.seenCallIds.has(callId)) {
      this.onRejected?.()
      throw new Error('duplicate or invalid tool call id')
    }
    if (this.seenCallIds.size >= MAX_SCOPE_PATHS * 2) {
      this.close()
      throw new Error('tool call limit exceeded')
    }
    this.seenCallIds.add(callId)
    if (this.inFlight) {
      this.onRejected?.()
      throw new Error('a Khaos operation is already pending')
    }
    let proposal: KhaosShellProposal
    try {
      proposal = parseProposal(args)
    } catch (error) {
      this.onRejected?.()
      throw error
    }
    if (signal.aborted) throw new Error('Khaos operation was cancelled before submission')

    this.inFlight = true
    const closeVersion = this.closeVersion
    try {
      const rawResult = await this.port.submitProposal(proposal, signal, correlation)
      if (this.closeVersion !== closeVersion) throw new Error('Launcher ended this capability session')
      const result = parseResult(rawResult)
      if (!result.canContinue) this.close()
      return result
    } catch (error) {
      this.close()
      throw error
    } finally {
      this.inFlight = false
    }
  }

  close(): void {
    if (this.closed) return
    this.closed = true
    this.closeVersion += 1
  }

  get isClosed(): boolean {
    return this.closed
  }
}

/** Create a Cordis Plugin that adds one bounded, untrusted Launcher proposal tool. */
export function createKhaosCapabilityPlugin(port: KhaosLauncherPort) {
  const session = new KhaosProposalSession(port, () => port.reportRejectedProposal?.())
  const plugin = (ctx: Context): void => {
    const unregister = ctx.tools.register(defineTool({
      name: 'khaos_capability',
      description: 'Propose one bounded shell action to the Khaos Trusted Launcher for independent review.',
      parameters: {
        argv: { type: 'array', items: { type: 'string' }, required: true },
        readScope: { type: 'array', items: { type: 'string' }, required: true },
        writeScope: { type: 'array', items: { type: 'string' }, required: true },
      },
      output: {
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
        render: (_args, result) => [{ type: 'text', text: JSON.stringify(result) }],
      },
      async execute(args, execution) {
        return session.submit(args, String(execution.callId), execution.signal)
      },
    }))
    ctx.effect(() => () => {
      session.close()
      unregister()
    })
  }

  return Object.assign(plugin, { inject: ['tools'] as const })
}
