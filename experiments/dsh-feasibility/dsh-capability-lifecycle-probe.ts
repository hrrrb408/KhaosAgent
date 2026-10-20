import { Context } from '@deepseek-ai/cordis'
import { ToolCallId } from '@deepseek-ai/dsh-llm'
import { createKhaosCapabilityPlugin, type KhaosToolResult } from './khaos-capability-adapter.ts'

const proposal = {
  argv: ['python3', '-c', 'print("lifecycle probe")'],
  readScope: [],
  writeScope: [],
}

function toolCount(ctx: Context): number {
  return ctx.tools.schemas().filter(tool => tool.name === 'khaos_capability').length
}

function execute(ctx: Context, callId: string) {
  return ctx.tools.execute({
    callId: ToolCallId(callId),
    name: 'khaos_capability',
    arguments: proposal,
    signal: new AbortController().signal,
  })
}

export interface CapabilityLifecycleEvidence {
  readonly status: 'PASS' | 'FAIL'
  readonly registeredOnce: boolean
  readonly duplicateRegistrationRejected: boolean
  readonly duplicateDidNotAddTool: boolean
  readonly unloadRemovedTool: boolean
  readonly inFlightLateResultRejected: boolean
  readonly postUnloadCallRejected: boolean
  readonly terminalTaskCallRejected: boolean
  readonly probePortCalls: number
}

export async function runCapabilityLifecycleProbe(ctx: Context): Promise<CapabilityLifecycleEvidence> {
  const firstFiber = await ctx.plugin(createKhaosCapabilityPlugin({
    async submitProposal() {
      return { ok: true, canContinue: true, text: 'unexpected duplicate-path submission' }
    },
  }))
  const registeredOnce = toolCount(ctx) === 1

  let duplicateRegistrationRejected = false
  const duplicateFiber = ctx.plugin(createKhaosCapabilityPlugin({
    async submitProposal() {
      throw new Error('duplicate capability registration must not execute')
    },
  }))
  try {
    await duplicateFiber
  } catch (error) {
    duplicateRegistrationRejected = error instanceof Error
      && error.message.includes('khaos_capability')
  }
  await duplicateFiber.dispose()
  const duplicateDidNotAddTool = toolCount(ctx) === 1
  await firstFiber.dispose()
  const unloadRemovedTool = toolCount(ctx) === 0

  let proposalsSubmitted = 0
  const entered = Promise.withResolvers<void>()
  const lateResult = Promise.withResolvers<KhaosToolResult>()
  const pendingFiber = await ctx.plugin(createKhaosCapabilityPlugin({
    submitProposal() {
      proposalsSubmitted += 1
      entered.resolve()
      return lateResult.promise
    },
  }))
  const inFlight = execute(ctx, 'khaos-lifecycle-in-flight')
  await entered.promise
  await pendingFiber.dispose()
  lateResult.resolve({ ok: true, canContinue: true, text: 'stale result after unload' })
  const inFlightLateResultRejected = (await inFlight).isError
  const postUnloadCallRejected = (await execute(
    ctx,
    'khaos-lifecycle-after-unload',
  )).isError && proposalsSubmitted === 1

  let terminalSubmissions = 0
  const terminalFiber = await ctx.plugin(createKhaosCapabilityPlugin({
    async submitProposal() {
      terminalSubmissions += 1
      return { ok: false, canContinue: false, text: 'terminal Launcher result' }
    },
  }))
  const firstTerminalCall = await execute(ctx, 'khaos-lifecycle-terminal-1')
  const terminalTaskCallRejected = !firstTerminalCall.isError
    && (await execute(ctx, 'khaos-lifecycle-terminal-2')).isError
    && terminalSubmissions === 1
  await terminalFiber.dispose()

  const checks = [
    registeredOnce,
    duplicateRegistrationRejected,
    duplicateDidNotAddTool,
    unloadRemovedTool,
    inFlightLateResultRejected,
    postUnloadCallRejected,
    terminalTaskCallRejected,
  ]
  return {
    status: checks.every(Boolean) ? 'PASS' : 'FAIL',
    registeredOnce,
    duplicateRegistrationRejected,
    duplicateDidNotAddTool,
    unloadRemovedTool,
    inFlightLateResultRejected,
    postUnloadCallRejected,
    terminalTaskCallRejected,
    probePortCalls: proposalsSubmitted + terminalSubmissions,
  }
}
