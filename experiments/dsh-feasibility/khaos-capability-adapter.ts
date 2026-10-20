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
  ): Promise<KhaosToolResult>
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
  return {
    ok: record.ok,
    canContinue: record.canContinue,
    text: record.text,
    ...(record.returncode === undefined ? {} : { returncode: record.returncode as number }),
  }
}

/** Create a Cordis Plugin that adds one bounded, untrusted Launcher proposal tool. */
export function createKhaosCapabilityPlugin(port: KhaosLauncherPort) {
  let closed = false
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
        if (closed) throw new Error('Launcher ended this capability session')
        const proposal = parseProposal(args)
        try {
          const value = await port.submitProposal(proposal, execution.signal)
          if (closed) throw new Error('Launcher ended this capability session')
          const result = parseResult(value)
          if (!result.canContinue) closed = true
          return result
        } catch (error) {
          closed = true
          throw error
        }
      },
    }))
    ctx.effect(() => () => {
      closed = true
      unregister()
    })
  }

  return Object.assign(plugin, { inject: ['tools'] as const })
}
