import assert from 'node:assert/strict'
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
import { createKhaosCapabilityPlugin } from './khaos-capability-adapter.ts'

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

async function main(): Promise<void> {
  const adapter = new MockAdapter([
    toolCallResponse('signed-dsh-1', 'khaos_capability', {
      argv: ['python3', '-c', 'print("signed-dsh-result")'],
      readScope: ['fixture.py'],
      writeScope: [],
    }),
    textResponse('The Launcher result was returned to the DSH Agent Loop.'),
  ])
  const ctx = new Context()
  await ctx.plugin(LlmRuntime)
  await ctx.plugin(SessionStore)
  await ctx.plugin(SessionProjectionRegistry)
  await ctx.plugin(SystemPrompt, {})
  await ctx.plugin(ToolRuntime)
  await ctx.plugin(AgentRegistry)
  await ctx.plugin(AgentLoop, { agents: [] })
  ctx.llm.registerAdapter(['mock'], adapter)
  let submitted = 0
  const capabilityFiber = await ctx.plugin(createKhaosCapabilityPlugin({
    async submitProposal(_proposal, signal) {
      assert.equal(signal.aborted, false)
      submitted++
      return { ok: true, canContinue: true, text: 'returncode=0\nsigned-dsh-result', returncode: 0 }
    },
  }))
  const agent = await ctx.agentLoop.create(SessionId('signed-dsh-runtime'), {
    provider: 'mock',
    model: 'mock',
  })
  agent.followup(createUserMessage({
    content: [{ type: 'text', text: 'Run the deterministic signed-runtime fixture.' }],
    source: { kind: 'user' },
  }))
  await waitForIdle(ctx, agent)

  assert.equal(submitted, 1)
  assert.equal(adapter.requests.length, 2)
  assert.ok(adapter.requests[0]?.tools?.some(tool => tool.name === 'khaos_capability'))
  assert.equal(adapter.requests[1]?.messages.find(message => message.role === 'tool')?.isError, false)
  assert.ok(JSON.stringify(agent.session.deriveMessages()).includes('The Launcher result was returned to the DSH Agent Loop.'))
  await capabilityFiber.dispose()
  assert.equal(ctx.tools.schemas().some(tool => tool.name === 'khaos_capability'), false)
  await ctx.fiber.dispose()

  console.log(JSON.stringify({
    signedRuntime: 'PASS',
    dshToolRoundTrip: 'PASS',
    runtimeRssBytes: process.memoryUsage().rss,
  }))
}

await main()
