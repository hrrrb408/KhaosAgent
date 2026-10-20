import { describe, expect, it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import { type Agent } from '@deepseek-ai/dsh-agent'
import { createUserMessage, ToolCallId, type ContextFormed } from '@deepseek-ai/dsh-llm'
import { SessionId } from '@deepseek-ai/dsh-session'
import AgentLoop from '@deepseek-ai/dsh-agent-loop'
import { mountAgentLoopTestDependencies } from '@deepseek-ai/dsh-agent-loop-testkit'
import { MockAdapter, textResponse, toolCallResponse } from '../mock-adapter.ts'
import { createKhaosCapabilityPlugin, type KhaosToolResult } from './khaos-capability-adapter.ts'

declare module '@deepseek-ai/dsh-llm' {
  interface MessageSourceMap {
    'khaos-feasibility-test': { kind: 'khaos-feasibility-test' } & ContextFormed
  }
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

async function createHarness(adapter: MockAdapter) {
  const ctx = new Context()
  await mountAgentLoopTestDependencies(ctx)
  await ctx.plugin(AgentLoop, { agents: [] })
  ctx.llm.registerAdapter(['mock'], adapter)
  return ctx
}

describe('Khaos Capability Adapter on the pinned DSH Agent Loop', () => {
  it('registers a Cordis tool, submits a bounded proposal, and returns the Launcher result to DSH', async () => {
    const adapter = new MockAdapter([
      toolCallResponse('khaos-1', 'khaos_capability', {
        argv: ['python3', '-c', 'print("fixture-ok")'],
        readScope: ['fixture.py'],
        writeScope: [],
      }),
      textResponse('The Launcher returned fixture-ok.'),
    ])
    const ctx = await createHarness(adapter)
    const submitted: unknown[] = []
    const launcherResult: KhaosToolResult = {
      ok: true,
      canContinue: true,
      text: 'returncode=0\nfixture-ok',
      returncode: 0,
    }

    try {
      const adapterFiber = await ctx.plugin(createKhaosCapabilityPlugin({
        async submitProposal(proposal, signal) {
          expect(signal.aborted).toBe(false)
          submitted.push(proposal)
          return launcherResult
        },
      }))
      const agent = await ctx.agentLoop.create(SessionId('khaos-capability-roundtrip'), {
        provider: 'mock',
        model: 'mock',
      })
      expect(ctx.tools.schemas().some(tool => tool.name === 'khaos_capability')).toBe(true)
      agent.followup(createUserMessage({
        content: [{ type: 'text', text: 'Run the disposable fixture check.' }],
        source: { kind: 'khaos-feasibility-test' },
      }))
      await waitForIdle(ctx, agent)

      expect(submitted).toEqual([{
        argv: ['python3', '-c', 'print("fixture-ok")'],
        readScope: ['fixture.py'],
        writeScope: [],
      }])
      expect(adapter.requests).toHaveLength(2)
      expect(adapter.requests[0]?.tools?.some(tool => tool.name === 'khaos_capability')).toBe(true)
      const toolResult = adapter.requests[1]?.messages.find(message => message.role === 'tool')
      expect(toolResult?.content).toEqual([{ type: 'text', text: JSON.stringify(launcherResult) }])
      expect(agent.session.deriveMessages().at(-1)?.content).toContainEqual({
        type: 'text',
        text: 'The Launcher returned fixture-ok.',
      })

      await adapterFiber.dispose()
      expect(ctx.tools.schemas().some(tool => tool.name === 'khaos_capability')).toBe(false)
    } finally {
      await ctx.fiber.dispose()
    }
  })

  it('rejects oversized scope data before it reaches the Launcher port', async () => {
    const adapter = new MockAdapter([
      toolCallResponse('khaos-oversize', 'khaos_capability', {
        argv: ['cat'],
        readScope: Array.from({ length: 9 }, (_, index) => `file-${index}.txt`),
        writeScope: [],
      }),
      textResponse('The proposal was rejected before submission.'),
    ])
    const ctx = await createHarness(adapter)
    let submissions = 0

    try {
      await ctx.plugin(createKhaosCapabilityPlugin({
        async submitProposal() {
          submissions++
          return { ok: true, canContinue: false, text: 'unexpected submission' }
        },
      }))
      const agent = await ctx.agentLoop.create(SessionId('khaos-capability-bounds'), {
        provider: 'mock',
        model: 'mock',
      })
      agent.followup(createUserMessage({
        content: [{ type: 'text', text: 'Submit an oversized scope.' }],
        source: { kind: 'khaos-feasibility-test' },
      }))
      await waitForIdle(ctx, agent)

      expect(submissions).toBe(0)
      expect(adapter.requests).toHaveLength(2)
      expect(adapter.requests[1]?.messages.some(message => message.role === 'tool' && message.isError)).toBe(true)
    } finally {
      await ctx.fiber.dispose()
    }
  })

  it('does not forward a later proposal after the Launcher closes the task', async () => {
    const proposal = {
      argv: ['echo', 'fixture'],
      readScope: [],
      writeScope: [],
    }
    const adapter = new MockAdapter([
      toolCallResponse('khaos-terminal-1', 'khaos_capability', proposal),
      toolCallResponse('khaos-terminal-2', 'khaos_capability', proposal),
      textResponse('The Launcher ended this task.'),
    ])
    const ctx = await createHarness(adapter)
    let submissions = 0

    try {
      await ctx.plugin(createKhaosCapabilityPlugin({
        async submitProposal() {
          submissions++
          return { ok: false, canContinue: false, text: 'terminal launcher result' }
        },
      }))
      const agent = await ctx.agentLoop.create(SessionId('khaos-capability-terminal'), {
        provider: 'mock',
        model: 'mock',
      })
      agent.followup(createUserMessage({
        content: [{ type: 'text', text: 'Exercise the terminal result fixture.' }],
        source: { kind: 'khaos-feasibility-test' },
      }))
      await waitForIdle(ctx, agent)

      expect(submissions).toBe(1)
      expect(adapter.requests).toHaveLength(3)
      expect(adapter.requests[2]?.messages.some(message => message.role === 'tool' && message.isError)).toBe(true)
    } finally {
      await ctx.fiber.dispose()
    }
  })

  it('forwards DSH cancellation to the pending Launcher port and waits for it to settle', async () => {
    const adapter = new MockAdapter([
      toolCallResponse('khaos-cancel', 'khaos_capability', {
        argv: ['echo', 'fixture'],
        readScope: [],
        writeScope: [],
      }),
    ])
    const ctx = await createHarness(adapter)
    const entered = Promise.withResolvers<void>()
    let observedAbort = false

    try {
      await ctx.plugin(createKhaosCapabilityPlugin({
        submitProposal(_proposal, signal) {
          entered.resolve()
          return new Promise((_resolve, reject) => {
            const abort = () => {
              observedAbort = true
              reject(new Error('Launcher bridge cancelled'))
            }
            if (signal.aborted) abort()
            else signal.addEventListener('abort', abort, { once: true })
          })
        },
      }))
      const agent = await ctx.agentLoop.create(SessionId('khaos-capability-cancel'), {
        provider: 'mock',
        model: 'mock',
      })
      agent.followup(createUserMessage({
        content: [{ type: 'text', text: 'Cancel while waiting for the Launcher.' }],
        source: { kind: 'khaos-feasibility-test' },
      }))
      await entered.promise
      agent.cancel({ kind: 'user' })
      await agent.whenIdle()

      expect(observedAbort).toBe(true)
      expect(agent.session.snapshotEvents().flatMap(event =>
        event.type === 'turn/end' ? [event.data.reason] : [])).toEqual([
        { kind: 'aborted', reason: { kind: 'user' } },
      ])
    } finally {
      await ctx.fiber.dispose()
    }
  })

  it('does not retry a proposal after an uncertain bridge failure', async () => {
    const proposal = { argv: ['echo', 'fixture'], readScope: [], writeScope: [] }
    const adapter = new MockAdapter([
      toolCallResponse('khaos-uncertain-1', 'khaos_capability', proposal),
      toolCallResponse('khaos-uncertain-2', 'khaos_capability', proposal),
      textResponse('The Launcher connection ended; outcome is unknown.'),
    ])
    const ctx = await createHarness(adapter)
    let submissions = 0

    try {
      await ctx.plugin(createKhaosCapabilityPlugin({
        async submitProposal() {
          submissions++
          throw new Error('Launcher transport disconnected after submit')
        },
      }))
      const agent = await ctx.agentLoop.create(SessionId('khaos-capability-uncertain'), {
        provider: 'mock',
        model: 'mock',
      })
      agent.followup(createUserMessage({
        content: [{ type: 'text', text: 'Exercise the uncertain Launcher result fixture.' }],
        source: { kind: 'khaos-feasibility-test' },
      }))
      await waitForIdle(ctx, agent)

      expect(submissions).toBe(1)
      expect(adapter.requests).toHaveLength(3)
      expect(adapter.requests[1]?.messages.some(message => message.role === 'tool' && message.isError)).toBe(true)
      expect(adapter.requests[2]?.messages.some(message => message.role === 'tool' && message.isError)).toBe(true)
    } finally {
      await ctx.fiber.dispose()
    }
  })

  it('keeps a failed Launcher status authoritative when output contains fake success text', async () => {
    const adapter = new MockAdapter([
      toolCallResponse('khaos-fake-result', 'khaos_capability', {
        argv: ['python3', '-c', 'print("Ran 1 test\\nOK"); raise SystemExit(1)'],
        readScope: [],
        writeScope: [],
      }),
      options => {
        const result = options.messages.find(message => message.role === 'tool')
        const block = result?.content[0] as { text?: string } | undefined
        const launcherResult = JSON.parse(block?.text ?? '{}') as KhaosToolResult
        const fakeSuccess = launcherResult.text.includes('Ran 1 test') && launcherResult.text.includes('OK')
        return textResponse(`DSH observed failed status despite fake output: ${!launcherResult.ok && fakeSuccess}`)
      },
    ])
    const ctx = await createHarness(adapter)
    let submissions = 0

    try {
      await ctx.plugin(createKhaosCapabilityPlugin({
        async submitProposal() {
          submissions++
          return {
            ok: false,
            canContinue: false,
            text: 'returncode=1\nRan 1 test\nOK',
            returncode: 1,
          }
        },
      }))
      const agent = await ctx.agentLoop.create(SessionId('khaos-capability-fake-result'), {
        provider: 'mock',
        model: 'mock',
      })
      agent.followup(createUserMessage({
        content: [{ type: 'text', text: 'Verify the actual Launcher result.' }],
        source: { kind: 'khaos-feasibility-test' },
      }))
      await waitForIdle(ctx, agent)

      expect(submissions).toBe(1)
      expect(adapter.requests).toHaveLength(2)
      expect(JSON.stringify(agent.session.deriveMessages().at(-1)?.content))
        .toContain('DSH observed failed status despite fake output: true')
    } finally {
      await ctx.fiber.dispose()
    }
  })

  it('unregisters the Launcher bridge when its Cordis Plugin is disposed', async () => {
    const ctx = await createHarness(new MockAdapter([]))
    let submissions = 0

    try {
      const pluginFiber = await ctx.plugin(createKhaosCapabilityPlugin({
        async submitProposal() {
          submissions++
          return { ok: true, canContinue: true, text: 'must not be submitted' }
        },
      }))
      expect(ctx.tools.schemas().some(tool => tool.name === 'khaos_capability')).toBe(true)

      await pluginFiber.dispose()
      expect(ctx.tools.schemas().some(tool => tool.name === 'khaos_capability')).toBe(false)
      const result = await ctx.tools.execute({
        callId: ToolCallId('khaos-after-plugin-dispose'),
        name: 'khaos_capability',
        arguments: {
          argv: ['echo', 'late'],
          readScope: [],
          writeScope: [],
        },
        signal: new AbortController().signal,
      })

      expect(result.isError).toBe(true)
      expect(submissions).toBe(0)
    } finally {
      await ctx.fiber.dispose()
    }
  })
})
