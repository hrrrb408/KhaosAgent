import { createInterface } from 'node:readline'
import { Context } from '@deepseek-ai/cordis'
import AgentRegistry from '@deepseek-ai/dsh-agent'
import type { Agent } from '@deepseek-ai/dsh-agent'
import LlmRuntime, { createUserMessage } from '@deepseek-ai/dsh-llm'
import AgentLoop from '@deepseek-ai/dsh-agent-loop'
import SessionStore, { SessionId } from '@deepseek-ai/dsh-session'
import SessionProjectionRegistry from '@deepseek-ai/dsh-session-projection'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import { MockAdapter, textResponse, toolCallResponse } from '../mock-adapter.ts'
import { createKhaosCapabilityPlugin, type KhaosToolResult } from './khaos-capability-adapter.ts'

interface HostInput {
  operation: 'user' | 'tool_result' | 'stop'
  text?: string
  ok?: boolean
  can_continue?: boolean
  returncode?: number
}

type PendingResult = (result: KhaosToolResult) => void

let pendingResult: PendingResult | undefined
let currentAgent: Agent | undefined
let currentContext: Context | undefined
let currentPluginFiber: { dispose(): Promise<void> } | undefined
let sessionSequence = 0

function emit(value: object): void {
  process.stdout.write(`${JSON.stringify(value)}\n`)
}

function waitForIdle(ctx: Context, agent: Agent): Promise<void> {
  return new Promise((resolve) => {
    const dispose = ctx.on('agent/status', ({ agent: current, status }) => {
      if (current === agent && status === 'idle') {
        dispose()
        resolve()
      }
    })
  })
}

async function createTask(text: string): Promise<void> {
  if (currentAgent || pendingResult) throw new Error('task already active')
  const ctx = new Context()
  const adapter = new MockAdapter([
    toolCallResponse('khaos-dsh-acceptance-1', 'khaos_capability', {
      argv: [
        'python3', '-I', '-B', '-c',
        "from pathlib import Path; print(Path('fixture.txt').read_text())",
      ],
      readScope: ['fixture.txt'],
      writeScope: [],
    }),
    options => {
      const toolResult = [...options.messages].reverse().find(message => message.role === 'tool')
      const observed = JSON.stringify(toolResult?.content ?? null)
      return textResponse(`DSH observed the Khaos tool result: ${observed}`)
    },
  ])

  await ctx.plugin(LlmRuntime)
  await ctx.plugin(SessionStore)
  await ctx.plugin(SessionProjectionRegistry)
  await ctx.plugin(SystemPrompt, {})
  await ctx.plugin(ToolRuntime)
  await ctx.plugin(AgentRegistry)
  await ctx.plugin(AgentLoop, { agents: [] })
  ctx.llm.registerAdapter(['khaos-fixture'], adapter)
  const pluginFiber = await ctx.plugin(createKhaosCapabilityPlugin({
    submitProposal(proposal, signal) {
      if (pendingResult) throw new Error('one Khaos operation may be pending at a time')
      emit({ type: 'proposal', proposal })
      return new Promise((resolve, reject) => {
        let settled = false
        const finish = (result: KhaosToolResult) => {
          if (settled) return
          settled = true
          signal.removeEventListener('abort', onAbort)
          pendingResult = undefined
          resolve(result)
        }
        const onAbort = () => {
          if (settled) return
          settled = true
          pendingResult = undefined
          reject(new Error('Khaos Agent Host request was cancelled'))
        }
        pendingResult = finish
        if (signal.aborted) onAbort()
        else signal.addEventListener('abort', onAbort, { once: true })
      })
    },
  }))

  sessionSequence++
  const agent = await ctx.agentLoop.create(SessionId(`khaos-xpc-${sessionSequence}`), {
    provider: 'khaos-fixture',
    model: 'deterministic-acceptance',
  })
  currentAgent = agent
  currentContext = ctx
  currentPluginFiber = pluginFiber
  const idle = waitForIdle(ctx, agent)
  agent.followup(createUserMessage({
    content: [{ type: 'text', text }],
    source: { kind: 'user' },
  }))
  void idle.then(async () => {
    const assistant = [...agent.session.deriveMessages()].reverse()
      .find(message => message.role === 'assistant')
    const responseText = assistant?.content
      .filter(block => block.type === 'text')
      .map(block => block.text)
      .join('') ?? ''
    const toolResult = adapter.requests[1]?.messages
      .filter(message => message.role === 'tool')
      .map(message => message.content)
    emit({
      type: 'reply',
      text: responseText || 'DSH produced no final text response.',
      toolResultObserved: toolResult ?? [],
    })
    currentAgent = undefined
    currentContext = undefined
    currentPluginFiber = undefined
    await pluginFiber.dispose()
    await ctx.fiber.dispose()
  }).catch(error => {
    emit({ type: 'error', code: error instanceof Error ? 'dsh_agent_failed' : 'dsh_agent_error' })
  })
}

async function handle(input: HostInput): Promise<void> {
  if (input.operation === 'user') {
    if (typeof input.text !== 'string' || input.text.length === 0) {
      throw new Error('invalid user input')
    }
    await createTask(input.text)
    return
  }
  if (input.operation === 'tool_result') {
    if (!pendingResult
      || typeof input.ok !== 'boolean'
      || typeof input.can_continue !== 'boolean'
      || typeof input.text !== 'string'
      || (input.returncode !== undefined && !Number.isInteger(input.returncode))) {
      throw new Error('invalid Khaos tool result')
    }
    const resolve = pendingResult
    resolve({
      ok: input.ok,
      canContinue: input.can_continue,
      text: input.text,
      ...(input.returncode === undefined ? {} : { returncode: input.returncode }),
    })
    return
  }
  if (input.operation === 'stop') {
    currentAgent?.cancel({ kind: 'user' })
    pendingResult = undefined
    await currentPluginFiber?.dispose()
    await currentContext?.fiber.dispose()
    process.exit(0)
  }
  throw new Error('unknown host operation')
}

const lines = createInterface({ input: process.stdin, crlfDelay: Infinity })
lines.on('line', line => {
  if (Buffer.byteLength(line, 'utf8') > 64 * 1024) {
    emit({ type: 'error', code: 'host_frame_too_large' })
    process.exitCode = 1
    return
  }
  let input: HostInput
  try {
    input = JSON.parse(line) as HostInput
  } catch {
    emit({ type: 'error', code: 'host_frame_invalid' })
    process.exitCode = 1
    return
  }
  void handle(input).catch(() => {
    emit({ type: 'error', code: 'host_request_failed' })
    process.exitCode = 1
  })
})
