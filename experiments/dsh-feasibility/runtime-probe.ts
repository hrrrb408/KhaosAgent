import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFileSync, unlinkSync, writeFileSync } from 'node:fs'
import { connect } from 'node:net'
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

function fileReadAttempt(path: string): string {
  try {
    return `ALLOWED_${readFileSync(path).byteLength}`
  } catch (error) {
    return (error as NodeJS.ErrnoException).code ?? 'ERROR'
  }
}

function fileWriteAttempt(path: string): string {
  try {
    writeFileSync(path, 'untrusted DSH plugin write', { flag: 'wx' })
    unlinkSync(path)
    return 'ALLOWED'
  } catch (error) {
    return (error as NodeJS.ErrnoException).code ?? 'ERROR'
  }
}

function childProcessReadAttempt(path: string): string {
  try {
    const output = execFileSync('/bin/cat', [path], { encoding: 'utf8', stdio: 'pipe' })
    return `ALLOWED_${Buffer.byteLength(output)}`
  } catch (error) {
    return childProcessFailure(error)
  }
}

function childProcessWriteAttempt(path: string): string {
  try {
    execFileSync('/usr/bin/touch', [path], { encoding: 'utf8', stdio: 'pipe' })
    unlinkSync(path)
    return 'ALLOWED'
  } catch (error) {
    return childProcessFailure(error)
  }
}

function childProcessExecuteAttempt(): string {
  try {
    execFileSync('/usr/bin/true', [], { encoding: 'utf8', stdio: 'pipe' })
    return 'ALLOWED'
  } catch (error) {
    return childProcessFailure(error)
  }
}

function childProcessFailure(error: unknown): string {
  const failure = error as NodeJS.ErrnoException & { status?: number; stderr?: Buffer | string }
  const stderr = typeof failure.stderr === 'string'
    ? failure.stderr
    : failure.stderr?.toString('utf8') ?? ''
  if (['EPERM', 'EACCES'].includes(failure.code ?? '')
    || /operation not permitted|permission denied/i.test(stderr)) {
    return 'DENIED'
  }
  return `ERROR_${failure.code ?? failure.status ?? failure.name ?? 'UNKNOWN'}`
}

function networkAttempt(): Promise<string> {
  return new Promise((resolve) => {
    const socket = connect({ host: '1.1.1.1', port: 443 })
    let finished = false
    const finish = (result: string) => {
      if (finished) return
      finished = true
      socket.destroy()
      resolve(result)
    }
    socket.setTimeout(1500, () => finish('TIMEOUT'))
    socket.once('connect', () => finish('ALLOWED'))
    socket.once('error', error => finish((error as NodeJS.ErrnoException).code ?? 'ERROR'))
  })
}

async function main(): Promise<void> {
  const readPath = process.env.KHAOS_PROTECTED_READ_PATH
  const writePath = process.env.KHAOS_PROTECTED_WRITE_PATH
  assert.ok(readPath, 'missing protected-read fixture path')
  assert.ok(writePath, 'missing protected-write fixture path')

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

  const attackPlugin = async () => {
    // This Cordis Plugin is hostile fixture code running in the same Node
    // process as DSH. Its OS probes return status only; file contents stay local.
    const fileRead = fileReadAttempt(readPath)
    const fileWrite = fileWriteAttempt(writePath)
    const childProcessExecute = childProcessExecuteAttempt()
    const childProcessRead = childProcessReadAttempt(readPath)
    const childProcessWrite = childProcessWriteAttempt(writePath)
    const network = await networkAttempt()
    const credentialEnvironmentKeys = Object.keys(process.env)
      .filter(name => /(?:API_KEY|TOKEN|PASSWORD|SECRET)/i.test(name))
      .length

    const evidence = {
      fileRead,
      fileWrite,
      childProcessExecute,
      childProcessRead,
      childProcessWrite,
      network,
      credentialEnvironmentKeys,
    }
    console.log(JSON.stringify({
      signedRuntime: 'PASS',
      dshToolRoundTrip: 'PASS',
      runtimeRssBytes: process.memoryUsage().rss,
      hostilePlugin: evidence,
    }))
    if (!['EPERM', 'EACCES'].includes(fileRead)
      || !['EPERM', 'EACCES'].includes(fileWrite)
      || !['ALLOWED', 'EPERM', 'EACCES'].includes(childProcessExecute)
      || childProcessRead !== 'DENIED'
      || childProcessWrite !== 'DENIED'
      || !['EPERM', 'EACCES'].includes(network)
      || credentialEnvironmentKeys !== 0) {
      process.exitCode = 2
    }
  }

  const attackContext = new Context()
  await attackContext.plugin(attackPlugin)
  await attackContext.fiber.dispose()
}

await main()
