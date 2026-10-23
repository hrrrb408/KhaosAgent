import { createHash } from 'node:crypto'
import { describe, expect, it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import { type Agent } from '@deepseek-ai/dsh-agent'
import { createUserMessage, type ContextFormed } from '@deepseek-ai/dsh-llm'
import { SessionId } from '@deepseek-ai/dsh-session'
import AgentLoop from '@deepseek-ai/dsh-agent-loop'
import { mountAgentLoopTestDependencies } from '@deepseek-ai/dsh-agent-loop-testkit'
import { MockAdapter, textResponse, toolCallResponse } from '../mock-adapter.ts'
import { DshAgentTelemetry } from './dsh-agent-telemetry.ts'
import { lastToolResult } from './dsh-tool-result.ts'
import { semanticCodingResponses } from './dsh-semantic-fixture.ts'
import { localModelTestSupport } from './khaos-local-model.ts'
import {
  createKhaosSemanticToolsPlugin,
  semanticToolTestSupport,
  type KhaosCodingToolPolicy,
} from './khaos-semantic-tools.ts'
import type { KhaosLauncherPort, KhaosShellProposal, KhaosToolResult } from './khaos-capability-adapter.ts'

declare module '@deepseek-ai/dsh-llm' {
  interface MessageSourceMap {
    'khaos-semantic-tools-test': { kind: 'khaos-semantic-tools-test' } & ContextFormed
  }
}

function waitForIdle(ctx: Context, agent: Agent): Promise<void> {
  return new Promise(resolve => {
    const dispose = ctx.on('agent/status', ({ agent: current, status }) => {
      if (current === agent && status === 'idle') {
        dispose()
        resolve()
      }
    })
  })
}

async function createHarness(adapter: MockAdapter): Promise<Context> {
  const ctx = new Context()
  await mountAgentLoopTestDependencies(ctx)
  await ctx.plugin(AgentLoop, { agents: [], maxParallelToolCalls: 1 })
  ctx.llm.registerAdapter(['mock'], adapter)
  return ctx
}

async function startSemanticAgent(
  ctx: Context,
  policy: KhaosCodingToolPolicy,
  telemetry: DshAgentTelemetry,
  submitProposal: KhaosLauncherPort['submitProposal'],
): Promise<{ agent: Agent; pluginFiber: { dispose(): Promise<void> } }> {
  let setVisibleTools: (names: readonly ('read_file' | 'replace_text' | 'run_tests')[]) => void = () => undefined
  const pluginFiber = await ctx.plugin(createKhaosSemanticToolsPlugin(
    { submitProposal },
    policy,
    telemetry,
    names => setVisibleTools(names),
  ))
  const agent = await ctx.agentLoop.create(SessionId('semantic-' + policy.trialId), {
    provider: 'mock',
    model: 'mock',
  })
  let restriction: (() => void) | undefined
  const allTools = agent.ctx.tools.schemas().map(tool => tool.name).filter(name => name !== 'run_code')
  setVisibleTools = names => {
    restriction?.()
    restriction = names.length === 0
      ? agent.ctx.tools.restrict({ deny: allTools })
      : agent.ctx.tools.restrict({ allow: [...names] })
  }
  setVisibleTools(['read_file'])
  return { agent, pluginFiber }
}

const policy: KhaosCodingToolPolicy = {
  trialId: 'phase31-unit-a1',
  taskId: 'A',
  readFiles: ['fee.py', 'test_public.py'],
  writeFiles: ['fee.py'],
  fixedEditScript: 'exec("fixed-candidate-b-script")',
}

function toolNames(options: { tools?: readonly { name: string }[] }): string[] {
  return (options.tools ?? []).map(tool => tool.name)
}

describe('Khaos semantic Cordis tools', () => {
  it('continues the signed fixture when Launcher results omit optional return codes', async () => {
    const adapter = new MockAdapter(semanticCodingResponses())
    const ctx = await createHarness(adapter)
    const telemetry = new DshAgentTelemetry(policy.trialId, 'dsh-session-stage-a-fixture', 'A', () => undefined)
    const source = 'def calculate_fee(amount, rate=0.025):\n    return amount * rate\n'
    const submissions: KhaosShellProposal[] = []
    const results: KhaosToolResult[] = [
      { ok: true, canContinue: true, text: source },
      { ok: true, canContinue: true, text: 'def test_fee_is_rounded_to_cents(): pass' },
      { ok: true, canContinue: true, text: 'EDIT_APPLIED' },
      { ok: true, canContinue: true, text: 'Ran 1 test\\n\\nOK' },
    ]

    try {
      const { agent, pluginFiber } = await startSemanticAgent(ctx, policy, telemetry, async proposal => {
        submissions.push(proposal)
        const result = results.shift()
        if (!result) throw new Error('unexpected_tool_submission')
        return result
      })
      agent.followup(createUserMessage({
        content: [{ type: 'text', text: 'Read fee.py and test_public.py, then edit and run public tests.' }],
        source: { kind: 'khaos-semantic-tools-test' },
      }))
      await waitForIdle(ctx, agent)

      expect(submissions).toHaveLength(4)
      expect(submissions[3]?.argv).toEqual([
        'python3', '-I', '-B', '-c', semanticToolTestSupport.testScript,
      ])
      expect(adapter.requests.map(toolNames)).toEqual([
        ['read_file'], ['read_file'], ['replace_text'], ['run_tests'], [],
      ])
      expect(agent.session.deriveMessages().at(-1)?.content).toContainEqual({
        type: 'text', text: 'The actual public tests passed after the controlled edit.',
      })
      expect(results).toEqual([])
      await pluginFiber.dispose()
    } finally {
      await ctx.fiber.dispose()
    }
  })

  it('correlates the Launcher terminal result with DSH Session delivery without exposing trace fields', async () => {
    const adapter = new MockAdapter([
      toolCallResponse('trace-read', 'read_file', { path: 'fee.py' }),
      options => textResponse(`Observed ${lastToolResult(options.messages)}`),
    ])
    const ctx = await createHarness(adapter)
    const telemetryRecords: Readonly<Record<string, unknown>>[] = []
    const telemetry = new DshAgentTelemetry(
      'phase31-trace', 'dsh-session-trace', 'A', record => telemetryRecords.push(record),
    )
    try {
      const { agent, pluginFiber } = await startSemanticAgent(ctx, policy, telemetry, async (_proposal, _signal, correlation) => {
        if (!correlation) throw new Error('missing semantic correlation')
        return {
          ok: true,
          canContinue: true,
          returncode: 0,
          text: 'SOURCE_RESULT',
          launcherTrace: {
            trial_id: correlation.trialId,
            dsh_session_id: correlation.sessionId,
            benchmark_task_id: correlation.benchmarkTaskId,
            agent_turn_id: correlation.turn,
            agent_step_id: correlation.step,
            ...(correlation.modelCallId ? { model_call_id: correlation.modelCallId } : {}),
            tool_call_id: correlation.toolCallId,
            tool_name: correlation.toolName,
            operation_seq: correlation.operationSequence,
            invocation_sha256: correlation.invocationSHA256,
            launcher_task_id: 'khaos-task-123',
            launcher_request_id: 'khaos-request-456',
            launcher_approval_sha256: 'a'.repeat(64),
            approval_status: 'approved_ordinary',
            kernel_result: 'output',
            runner_status: 'completed',
            commit_status: 'committed',
            launcher_ok: true,
            can_continue: true,
            returncode: 0,
          },
        }
      })
      agent.followup(createUserMessage({
        content: [{ type: 'text', text: 'Read the fee source.' }],
        source: { kind: 'khaos-semantic-tools-test' },
      }))
      await waitForIdle(ctx, agent)

      const terminal = telemetryRecords.find(record => record.event === 'LAUNCHER_TERMINAL_RESULT_DELIVERED')
      expect(terminal).toMatchObject({
        trial_id: 'phase31-trace',
        dsh_session_id: 'dsh-session-trace',
        tool_call_id: 'trace-read',
        launcher_task_id: 'khaos-task-123',
        launcher_request_id: 'khaos-request-456',
        kernel_result: 'output',
        runner_status: 'completed',
        commit_status: 'committed',
        returncode: 0,
      })
      const toolMessage = agent.session.deriveMessages().find(message => message.role === 'tool')
      expect(JSON.stringify(toolMessage)).toContain('SOURCE_RESULT')
      expect(JSON.stringify(toolMessage)).not.toContain('khaos-request-456')
      await pluginFiber.dispose()
    } finally {
      await ctx.fiber.dispose()
    }
  })

  it('lowers Read → Edit → Test → Repair → Verify through the DSH Session', async () => {
    const feeSource = 'def calculate_fee(amount):\n    return amount * 0.025\n'
    const testSource = 'from fee import calculate_fee\n'
    const firstEdit = 'def calculate_fee(amount):\n    return round(amount * 0.025)\n'
    const replacement = 'def calculate_fee(amount):\n    return round(amount * 0.025, 2)\n'
    const observedFailure: string[] = []
    const adapter = new MockAdapter([
      toolCallResponse('semantic-read-fee', 'read_file', { path: 'fee.py' }),
      toolCallResponse('semantic-read-tests', 'read_file', { path: 'test_public.py' }),
      toolCallResponse('semantic-edit', 'replace_text', {
        path: 'fee.py', oldText: feeSource, newText: firstEdit,
      }),
      toolCallResponse('semantic-test-fail', 'run_tests', { profile: 'public' }),
      options => {
        const result = lastToolResult(options.messages)
        observedFailure.push(result)
        expect(JSON.parse(result)).toMatchObject({ ok: false })
        expect(JSON.parse(result).returncode).toBeUndefined()
        expect(result).toContain('Ran 1 test')
        expect(result).toContain('OK')
        return toolCallResponse('semantic-repair', 'replace_text', {
          path: 'fee.py', oldText: firstEdit, newText: replacement,
        })
      },
      toolCallResponse('semantic-test-pass', 'run_tests', { profile: 'public' }),
      options => {
        expect(JSON.parse(lastToolResult(options.messages))).toMatchObject({ ok: true })
        return textResponse('Public verification passed.')
      },
    ])
    const ctx = await createHarness(adapter)
    const telemetryRecords: Readonly<Record<string, unknown>>[] = []
    const telemetry = new DshAgentTelemetry(policy.trialId, 'dsh-session-semantic-test', policy.taskId, record => {
      telemetryRecords.push(record)
    })
    const submissions: KhaosShellProposal[] = []
    const portResults: KhaosToolResult[] = [
      { ok: true, canContinue: true, text: feeSource },
      { ok: true, canContinue: true, text: testSource },
      { ok: true, canContinue: true, text: 'EDIT_APPLIED' },
      { ok: false, canContinue: true, text: 'Runner return code=1\nRan 1 test\nOK' },
      { ok: true, canContinue: true, text: 'EDIT_APPLIED' },
      { ok: true, canContinue: true, text: 'Ran 1 test\nOK' },
    ]

    try {
      const { agent, pluginFiber } = await startSemanticAgent(ctx, policy, telemetry, async proposal => {
        submissions.push(proposal)
        const result = portResults.shift()
        if (!result) throw new Error('unexpected_tool_submission')
        return result
      })
      agent.followup(createUserMessage({
        content: [{ type: 'text', text: 'Fix the rounded fee implementation and test it.' }],
        source: { kind: 'khaos-semantic-tools-test' },
      }))
      await waitForIdle(ctx, agent)

      expect(adapter.requests).toHaveLength(7)
      expect(adapter.requests.map(toolNames)).toEqual([
        ['read_file'], ['read_file'], ['replace_text'], ['run_tests'],
        ['read_file', 'replace_text'], ['run_tests'], [],
      ])
      expect(submissions).toHaveLength(6)
      expect(submissions[0]).toEqual({
        argv: ['python3', '-I', '-B', '-c', semanticToolTestSupport.readScript, 'fee.py'],
        readScope: ['fee.py'], writeScope: [],
      })
      expect(submissions[1]?.readScope).toEqual(['test_public.py'])
      expect(submissions[2]?.argv.slice(0, 6)).toEqual([
        'python3', '-I', '-B', '-c', policy.fixedEditScript, 'fee.py',
      ])
      expect(JSON.parse(submissions[2]?.argv[6] ?? 'null')).toBe(feeSource)
      expect(JSON.parse(submissions[2]?.argv[7] ?? 'null')).toBe(firstEdit)
      expect(submissions[2]?.readScope).toEqual(['fee.py'])
      expect(submissions[2]?.writeScope).toEqual(['fee.py'])
      expect(submissions[3]).toEqual({
        argv: ['python3', '-I', '-B', '-c', semanticToolTestSupport.testScript],
        readScope: ['fee.py', 'test_public.py'], writeScope: [],
      })
      expect(semanticToolTestSupport.testScript).not.toMatch(/[\u0000-\u001f\u007f]/u)
      expect(observedFailure).toHaveLength(1)
      expect(portResults).toEqual([])
      expect(agent.session.deriveMessages().at(-1)?.content).toContainEqual({
        type: 'text', text: 'Public verification passed.',
      })
      expect(telemetryRecords.filter(record => record.event === 'TOOL_PROPOSAL_LOWERED')).toHaveLength(6)
      expect(telemetry.launcherResultDigest('semantic-read-fee'))
        .toBe(createHash('sha256').update(feeSource, 'utf8').digest('hex'))

      await pluginFiber.dispose()
      expect(ctx.tools.schemas().some(tool => tool.name === 'read_file')).toBe(false)
    } finally {
      await ctx.fiber.dispose()
    }
  })

  it('runs Task C public tests before the first repair', async () => {
    const taskC = { ...policy, trialId: 'phase31-unit-c1', taskId: 'C' as const,
      readFiles: ['progress.py', 'test_public.py'], writeFiles: ['progress.py'] }
    const source = 'def progress_percent(done, total):\n    return done * 100 // total\n'
    const fixed = 'def progress_percent(done, total):\n    return 0 if total <= 0 else min(max(done, 0), total) * 100 // total\n'
    const adapter = new MockAdapter([
      toolCallResponse('c-read-source', 'read_file', { path: 'progress.py' }),
      toolCallResponse('c-read-tests', 'read_file', { path: 'test_public.py' }),
      toolCallResponse('c-initial-test', 'run_tests', { profile: 'public' }),
      options => {
        expect(JSON.parse(lastToolResult(options.messages))).toMatchObject({ ok: false })
        expect(JSON.parse(lastToolResult(options.messages)).returncode).toBe(1)
        return toolCallResponse('c-repair', 'replace_text', {
          path: 'progress.py', oldText: source, newText: fixed,
        })
      },
      toolCallResponse('c-retest', 'run_tests', { profile: 'public' }),
      options => {
        expect(JSON.parse(lastToolResult(options.messages))).toMatchObject({ ok: true })
        return textResponse('Repaired after observing the failing tests.')
      },
    ])
    const ctx = await createHarness(adapter)
    const telemetry = new DshAgentTelemetry(taskC.trialId, 'dsh-session-task-c', taskC.taskId, () => undefined)
    const submissions: KhaosShellProposal[] = []
    const results: KhaosToolResult[] = [
      { ok: true, canContinue: true, text: source },
      { ok: true, canContinue: true, text: 'PUBLIC_TESTS' },
      { ok: false, canContinue: true, returncode: 1, text: 'Runner return code=1\nFAIL: ZeroTotal' },
      { ok: true, canContinue: true, text: 'EDIT_APPLIED' },
      { ok: true, canContinue: true, text: 'PASS' },
    ]
    try {
      const { agent, pluginFiber } = await startSemanticAgent(ctx, taskC, telemetry, async proposal => {
        submissions.push(proposal)
        const result = results.shift()
        if (!result) throw new Error('unexpected_tool_submission')
        return result
      })
      agent.followup(createUserMessage({
        content: [{ type: 'text', text: 'Inspect the failing tests, repair progress_percent, and verify.' }],
        source: { kind: 'khaos-semantic-tools-test' },
      }))
      await waitForIdle(ctx, agent)
      expect(adapter.requests.map(toolNames)).toEqual([
        ['read_file'], ['read_file'], ['run_tests'], ['read_file', 'replace_text'], ['run_tests'], [],
      ])
      expect(submissions.map(request => request.argv)).toEqual([
        ['python3', '-I', '-B', '-c', semanticToolTestSupport.readScript, 'progress.py'],
        ['python3', '-I', '-B', '-c', semanticToolTestSupport.readScript, 'test_public.py'],
        ['python3', '-I', '-B', '-c', semanticToolTestSupport.testScript],
        ['python3', '-I', '-B', '-c', taskC.fixedEditScript, 'progress.py',
          JSON.stringify(source), JSON.stringify(fixed)],
        ['python3', '-I', '-B', '-c', semanticToolTestSupport.testScript],
      ])
      expect(results).toEqual([])
      await pluginFiber.dispose()
    } finally {
      await ctx.fiber.dispose()
    }
  })

  it('unloads semantic tools without accepting or replaying a late Launcher result', async () => {
    const adapter = new MockAdapter([
      toolCallResponse('unload-read', 'read_file', { path: 'fee.py' }),
      textResponse('The pending operation ended with the unloaded tool.'),
    ])
    const ctx = await createHarness(adapter)
    const telemetry = new DshAgentTelemetry(
      'phase31-unload', 'dsh-session-unload', 'A', () => undefined,
    )
    let proposalStarted: (() => void) | undefined
    let completeProposal: ((result: KhaosToolResult) => void) | undefined
    const submitted = new Promise<void>(resolve => { proposalStarted = resolve })
    const submissions: KhaosShellProposal[] = []
    try {
      const { agent, pluginFiber } = await startSemanticAgent(ctx, policy, telemetry, proposal => {
        submissions.push(proposal)
        proposalStarted?.()
        return new Promise<KhaosToolResult>(resolve => { completeProposal = resolve })
      })
      agent.followup(createUserMessage({
        content: [{ type: 'text', text: 'Read the source.' }],
        source: { kind: 'khaos-semantic-tools-test' },
      }))
      await submitted
      await pluginFiber.dispose()
      expect(agent.ctx.tools.schemas().some(tool => tool.name === 'read_file')).toBe(false)
      completeProposal?.({ ok: true, canContinue: true, text: 'LATE_KERNEL_RESULT', returncode: 0 })
      await waitForIdle(ctx, agent)
      const toolResults = agent.session.deriveMessages().filter(message => message.role === 'tool')
      expect(JSON.stringify(toolResults)).not.toContain('LATE_KERNEL_RESULT')
      expect(submissions).toHaveLength(1)
      expect(adapter.requests.map(toolNames)).toEqual([['read_file'], []])
    } finally {
      await ctx.fiber.dispose()
    }
  })

  it('propagates Agent cancellation to the pending semantic Launcher operation', async () => {
    const adapter = new MockAdapter([
      toolCallResponse('cancel-read', 'read_file', { path: 'fee.py' }),
    ])
    const ctx = await createHarness(adapter)
    const telemetry = new DshAgentTelemetry(
      'phase31-cancel', 'dsh-session-cancel', 'A', () => undefined,
    )
    let proposalStarted: (() => void) | undefined
    let observedSignal: AbortSignal | undefined
    const submitted = new Promise<void>(resolve => { proposalStarted = resolve })
    const submissions: KhaosShellProposal[] = []
    try {
      const { agent, pluginFiber } = await startSemanticAgent(ctx, policy, telemetry, (proposal, signal) => {
        submissions.push(proposal)
        observedSignal = signal
        proposalStarted?.()
        return new Promise<KhaosToolResult>((_resolve, reject) => {
          signal.addEventListener('abort', () => reject(new Error('cancelled')), { once: true })
        })
      })
      agent.followup(createUserMessage({
        content: [{ type: 'text', text: 'Read the source.' }],
        source: { kind: 'khaos-semantic-tools-test' },
      }))
      await submitted
      agent.cancel({ kind: 'user' })
      await waitForIdle(ctx, agent)
      expect(observedSignal?.aborted).toBe(true)
      expect(submissions).toHaveLength(1)
      await pluginFiber.dispose()
    } finally {
      await ctx.fiber.dispose()
    }
  })

  it('rejects unlisted, absolute, traversal, long, and permission-shaped read arguments before Launcher', async () => {
    const untrustedPaths = [
      '../unscoped-canary.txt',
      '/etc/passwd',
      'nested/../fee.py',
      'unlisted.py',
      'link-to-fee.py',
      'x'.repeat(129),
    ]
    const adapter = new MockAdapter([
      ...untrustedPaths.map((path, index) => toolCallResponse(
        'bad-read-' + index,
        'read_file',
        { path },
      )),
      toolCallResponse('permission-shaped-read', 'read_file', {
        path: 'fee.py',
        readScope: ['unscoped-canary.txt'],
      }),
      textResponse('Rejected requests stayed outside the Launcher.'),
    ])
    const ctx = await createHarness(adapter)
    const records: Readonly<Record<string, unknown>>[] = []
    const telemetry = new DshAgentTelemetry(
      'phase31-read-attacks',
      'dsh-session-read-attacks',
      'A',
      record => records.push(record),
    )
    let submissions = 0

    try {
      const { agent, pluginFiber } = await startSemanticAgent(ctx, policy, telemetry, async () => {
        submissions += 1
        return { ok: true, canContinue: true, text: 'should not execute', returncode: 0 }
      })
      agent.followup(createUserMessage({
        content: [{ type: 'text', text: 'Read the allowlisted file.' }],
        source: { kind: 'khaos-semantic-tools-test' },
      }))
      await waitForIdle(ctx, agent)

      expect(submissions).toBe(0)
      expect(records.filter(record => record.event === 'TOOL_PROPOSAL_LOWERED')).toHaveLength(0)
      expect(records.filter(record => record.event === 'LAUNCHER_PROPOSAL_SUBMITTED')).toHaveLength(0)
      expect(adapter.requests.at(-1)?.messages.at(-1)?.role).toBe('tool')
      await pluginFiber.dispose()
    } finally {
      await ctx.fiber.dispose()
    }
  })

  it('rejects invalid edits and hidden test profiles before lowering them', async () => {
    const oneFilePolicy: KhaosCodingToolPolicy = {
      ...policy,
      trialId: 'phase31-edit-attacks',
      readFiles: ['fee.py'],
      writeFiles: ['fee.py'],
    }
    const source = 'def calculate_fee(amount):\n    return amount * 0.025\n'
    const validEdit = 'def calculate_fee(amount):\n    return round(amount * 0.025, 2)\n'
    const invalidEdits = [
      { path: 'secret.py', oldText: source, newText: validEdit },
      { path: 'fee.py', oldText: '', newText: validEdit },
      { path: 'fee.py', oldText: source, newText: source },
      { path: 'fee.py', oldText: 'x'.repeat(4_097), newText: validEdit },
      { path: 'fee.py', oldText: source, newText: 'x'.repeat(4_097) },
      { path: 'fee.py', oldText: '\ud800', newText: validEdit },
      { path: 'fee.py', oldText: source, newText: validEdit, writeScope: ['secret.py'] },
    ]
    const adapter = new MockAdapter([
      toolCallResponse('read-edit-attacks', 'read_file', { path: 'fee.py' }),
      ...invalidEdits.map((argumentsValue, index) => toolCallResponse(
        'bad-edit-' + index,
        'replace_text',
        argumentsValue,
      )),
      textResponse('Rejected invalid edits before Launcher submission.'),
    ])
    const ctx = await createHarness(adapter)
    const records: Readonly<Record<string, unknown>>[] = []
    const telemetry = new DshAgentTelemetry(
      oneFilePolicy.trialId,
      'dsh-session-edit-attacks',
      'A',
      record => records.push(record),
    )
    const submissions: KhaosShellProposal[] = []
    const results: KhaosToolResult[] = [
      { ok: true, canContinue: true, text: source, returncode: 0 },
    ]

    try {
      const { agent, pluginFiber } = await startSemanticAgent(
        ctx,
        oneFilePolicy,
        telemetry,
        async proposal => {
          submissions.push(proposal)
          const result = results.shift()
          if (!result) throw new Error('unexpected_tool_submission')
          return result
        },
      )
      agent.followup(createUserMessage({
        content: [{ type: 'text', text: 'Make one safe exact replacement.' }],
        source: { kind: 'khaos-semantic-tools-test' },
      }))
      await waitForIdle(ctx, agent)

      expect(submissions).toHaveLength(1)
      expect(submissions[0]?.writeScope).toEqual([])
      expect(records.filter(record => record.event === 'TOOL_PROPOSAL_LOWERED')).toHaveLength(1)
      expect(records.filter(record => record.event === 'TOOL_ARGUMENT_REJECTED').length).toBeGreaterThan(0)
      await pluginFiber.dispose()
    } finally {
      await ctx.fiber.dispose()
    }
  })

  it('does not turn an untrusted test profile into a command or hidden-test request', async () => {
    expect(semanticToolTestSupport.testScript).toContain('loadTestsFromModule(test_public)')
    expect(semanticToolTestSupport.testScript).not.toContain('.discover(')
    const oneFilePolicy: KhaosCodingToolPolicy = {
      ...policy,
      trialId: 'phase31-profile-attack',
      readFiles: ['fee.py'],
      writeFiles: ['fee.py'],
    }
    const source = 'def calculate_fee(amount):\n    return amount * 0.025\n'
    const replacement = 'def calculate_fee(amount):\n    return round(amount * 0.025, 2)\n'
    const adapter = new MockAdapter([
      toolCallResponse('profile-read', 'read_file', { path: 'fee.py' }),
      toolCallResponse('profile-edit', 'replace_text', {
        path: 'fee.py', oldText: source, newText: replacement,
      }),
      toolCallResponse('hidden-profile', 'run_tests', { profile: 'hidden' }),
      textResponse('The hidden profile was refused.'),
    ])
    const ctx = await createHarness(adapter)
    const records: Readonly<Record<string, unknown>>[] = []
    const telemetry = new DshAgentTelemetry(
      oneFilePolicy.trialId,
      'dsh-session-profile-attack',
      'A',
      record => records.push(record),
    )
    const submissions: KhaosShellProposal[] = []
    const results: KhaosToolResult[] = [
      { ok: true, canContinue: true, text: source, returncode: 0 },
      { ok: true, canContinue: true, text: 'EDIT_APPLIED', returncode: 0 },
    ]

    try {
      const { agent, pluginFiber } = await startSemanticAgent(
        ctx,
        oneFilePolicy,
        telemetry,
        async proposal => {
          submissions.push(proposal)
          const result = results.shift()
          if (!result) throw new Error('unexpected_tool_submission')
          return result
        },
      )
      agent.followup(createUserMessage({
        content: [{ type: 'text', text: 'Use the public tests after editing.' }],
        source: { kind: 'khaos-semantic-tools-test' },
      }))
      await waitForIdle(ctx, agent)

      expect(submissions).toHaveLength(2)
      expect(submissions.map(proposal => proposal.writeScope)).toEqual([[], ['fee.py']])
      expect(records.filter(record => record.event === 'TOOL_PROPOSAL_LOWERED')).toHaveLength(2)
      expect(adapter.requests.map(toolNames)).toEqual([
        ['read_file'], ['replace_text'], ['run_tests'], ['run_tests'],
      ])
      expect(adapter.requests[2]?.tools.find(tool => tool.name === 'run_tests')?.parameters)
        .toMatchObject({ properties: { profile: { enum: ['public'] } } })
      await pluginFiber.dispose()
    } finally {
      await ctx.fiber.dispose()
    }
  })

  it('uses Candidate B-compatible JSON strings and rejects malformed Unicode', () => {
    const canonical = semanticToolTestSupport.canonicalPythonJSONString
    expect(canonical('quote " slash \\ newline\n tab\t')).toBe(JSON.stringify('quote " slash \\ newline\n tab\t'))
    expect(canonical('é 😀')).toBe(String.raw`"\u00e9 \ud83d\ude00"`)
    expect(() => canonical('\ud800')).toThrow('invalid_unicode_text')
    expect(() => canonical('\udc00')).toThrow('invalid_unicode_text')
  })

  it('checks the exact delivered Session result before the next model turn', () => {
    const telemetry = new DshAgentTelemetry('trial-a', 'session-a', 'A', () => undefined)
    const result = [{ type: 'text', text: '{"returncode":1}' }]
    telemetry.markToolResultDelivered('call-a', result, false)
    expect(telemetry.matchesDeliveredToolResult('call-a', result, false)).toBe(true)
    expect(telemetry.matchesDeliveredToolResult('call-a', [{ type: 'text', text: 'changed' }], false)).toBe(false)
    expect(telemetry.matchesDeliveredToolResult('call-a', result, true)).toBe(false)
  })

  it('allows a final-only local-model response when the semantic tool registry is empty', () => {
    const request = localModelTestSupport.localPrompt({
      model: 'bundled-cpu',
      messages: [
        { role: 'system', content: 'Use only read_file, replace_text, and run_tests as they become visible.' },
        { role: 'user', content: 'The public tests passed.' },
      ],
      tools: [],
      max_tokens: 128,
      temperature: 0,
    })
    expect(request.hasTools).toBe(false)
    expect(request.grammar).toBe(localModelTestSupport.finalOnlyGrammar)
    expect(() => localModelTestSupport.normalizedModelOutput(
      { type: 'tool_call', name: 'run_tests', arguments: { profile: 'public' } },
      'call', true, false,
    )).toThrow('local_model_tool_call_without_visible_tools')
  })
})
