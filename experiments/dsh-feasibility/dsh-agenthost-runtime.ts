import { randomUUID } from 'node:crypto'
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
import {
  createKhaosCapabilityPlugin,
  type KhaosProposalCorrelation,
  type KhaosShellProposal,
  type KhaosToolResult,
} from './khaos-capability-adapter.ts'
import { createKhaosSemanticToolsPlugin, type KhaosCodingToolPolicy, type SemanticToolName } from './khaos-semantic-tools.ts'
import { DshAgentTelemetry } from './dsh-agent-telemetry.ts'
import { runCapabilityLifecycleProbe } from './dsh-capability-lifecycle-probe.ts'
import {
  KhaosDshModelAdapter,
  type KhaosModelRequest,
  type KhaosModelResult,
} from './khaos-model-bridge.ts'
import { completeWithLocalModel } from './khaos-local-model.ts'
import { lastToolResult, lastToolResultText } from './dsh-tool-result.ts'
import {
  createMaliciousCordisPlugin,
  hostileProbePasses,
  type HostileProbeEvidence,
  type HostileProbePaths,
} from './malicious-cordis-plugin.ts'

interface HostInput {
  operation: 'user' | 'tool_result' | 'model_result' | 'stop'
  text?: string
  ok?: boolean
  can_continue?: boolean
  request_id?: string
  elapsed_ms?: number
  response?: unknown
  error?: { code?: unknown }
}

type PendingResult = (result: KhaosToolResult) => void
type PendingModelCall = {
  resolve(result: KhaosModelResult): void
  reject(error: Error): void
  signal?: AbortSignal
  onAbort?: () => void
}

let pendingResult: PendingResult | undefined
const pendingModelCalls = new Map<string, PendingModelCall>()
let currentAgent: Agent | undefined
let currentContext: Context | undefined
let currentPluginFiber: { dispose(): Promise<void> } | undefined
let crashOnNextToolResult = false

async function requestLocalModel(
  request: KhaosModelRequest,
  signal?: AbortSignal,
): Promise<KhaosModelResult> {
  try {
    const result = await completeWithLocalModel(request, undefined, undefined, signal)
    emit({ type: 'model_diagnostic', status: 'ok', elapsed_ms: result.elapsed_ms })
    return result
  } catch (error) {
    const value = error as Error & { elapsed_ms?: unknown }
    const elapsed = Number.isSafeInteger(value?.elapsed_ms) && (value.elapsed_ms as number) >= 0
      ? Math.min(value.elapsed_ms as number, 600_000)
      : 0
    const code = typeof value?.message === 'string'
      && /^local_model_[a-z0-9_]{1,64}$/u.test(value.message)
      ? value.message
      : 'local_model_failed'
    emit({ type: 'model_diagnostic', status: 'failed', code, elapsed_ms: elapsed })
    throw error
  }
}

function emit(value: object): void {
  process.stdout.write(`${JSON.stringify(value)}\n`)
}

function requestModel(
  request: KhaosModelRequest,
  signal?: AbortSignal,
): Promise<KhaosModelResult> {
  if (pendingModelCalls.size !== 0) return Promise.reject(new Error('a model request is already pending'))
  if (signal?.aborted) return Promise.reject(new Error('model request was cancelled'))
  return new Promise((resolve, reject) => {
    const pending: PendingModelCall = { resolve, reject, signal }
    pending.onAbort = () => {
      pendingModelCalls.delete(request.request_id)
      reject(new Error('model request was cancelled'))
    }
    pendingModelCalls.set(request.request_id, pending)
    signal?.addEventListener('abort', pending.onAbort, { once: true })
    emit({
      type: 'model_request',
      request_id: request.request_id,
      headers: request.headers,
      body: request.body,
    })
  })
}

function settleModelCall(input: HostInput): void {
  if (typeof input.request_id !== 'string') throw new Error('invalid model result id')
  const pending = pendingModelCalls.get(input.request_id)
  if (!pending) throw new Error('model result has no matching request')
  pendingModelCalls.delete(input.request_id)
  if (pending.onAbort) pending.signal?.removeEventListener('abort', pending.onAbort)
  if (input.ok === true) {
    if (!Number.isSafeInteger(input.elapsed_ms) || (input.elapsed_ms as number) < 0) {
      pending.reject(new Error('invalid model bridge timing'))
      return
    }
    pending.resolve({ completion: input.response, elapsed_ms: input.elapsed_ms as number })
    return
  }
  const code = input.error?.code
  const failure = new Error(
    typeof code === 'string' ? code.slice(0, 80) : 'model_provider_failed',
  ) as Error & { elapsed_ms?: number }
  if (Number.isSafeInteger(input.elapsed_ms) && (input.elapsed_ms as number) >= 0) {
    failure.elapsed_ms = input.elapsed_ms as number
  }
  pending.reject(failure)
}

function rejectPendingModelCalls(reason: string): void {
  for (const [requestId, pending] of pendingModelCalls) {
    pendingModelCalls.delete(requestId)
    if (pending.onAbort) pending.signal?.removeEventListener('abort', pending.onAbort)
    pending.reject(new Error(reason))
  }
}

function proposal(argv: string[], readScope: string[], writeScope: string[]) {
  return { argv, readScope, writeScope }
}

function codingResponses() {
  return [
    toolCallResponse('dsh-read-example', 'khaos_capability', proposal(
      [
        'python3', '-I', '-B', '-c',
        "from pathlib import Path; print(Path('example.py').read_text()); print(Path('test_example.py').read_text())",
      ],
      ['example.py', 'test_example.py'],
      [],
    )),
    options => {
      const observed = lastToolResult(options.messages)
      if (!observed.includes('return 100') || !observed.includes('test_answer')) {
        return textResponse(`The actual read result was incomplete: ${observed}`)
      }
      return toolCallResponse('dsh-edit-example', 'khaos_capability', proposal(
        [
          'python3', '-I', '-B', '-c',
          "from pathlib import Path; p=Path('example.py'); s=p.read_text(); old='def answer():\\n    return 100\\n'; new='def answer():\\n    return 200\\n'; assert s==old; p.write_text(new)",
        ],
        ['example.py'],
        ['example.py'],
      ))
    },
    options => {
      const observed = lastToolResult(options.messages)
      if (!observed.includes('"ok":true')) {
        return textResponse(`The edit result was not successful: ${observed}`)
      }
      return toolCallResponse('dsh-test-example', 'khaos_capability', proposal(
        [
          'python3', '-I', '-B', '-c',
          "import importlib.util,sys,unittest; s=importlib.util.spec_from_file_location('example','example.py'); m=importlib.util.module_from_spec(s); sys.modules['example']=m; s.loader.exec_module(m); s=importlib.util.spec_from_file_location('test_example','test_example.py'); t=importlib.util.module_from_spec(s); sys.modules['test_example']=t; s.loader.exec_module(t); unittest.main(module=t,argv=['test_example'],verbosity=1)",
        ],
        ['example.py', 'test_example.py'],
        [],
      ))
    },
    options => {
      const observed = lastToolResult(options.messages)
      if (observed.includes('"ok":true') && observed.includes('Ran 1 test') && observed.includes('OK')) {
        return textResponse(`DSH consumed the actual passing test result: ${observed}`)
      }
      return textResponse(`DSH consumed the actual non-passing test result: ${observed}`)
    },
  ]
}

function semanticCodingResponses() {
  return [
    toolCallResponse('phase31-read-fee', 'read_file', { path: 'fee.py' }),
    options => {
      if (!lastToolResultText(options.messages).includes('return amount * rate')) {
        return textResponse('The actual fee.py read result did not contain the expected function.')
      }
      return toolCallResponse('phase31-read-tests', 'read_file', { path: 'test_public.py' })
    },
    options => {
      if (!lastToolResultText(options.messages).includes('test_fee_is_rounded_to_cents')) {
        return textResponse('The actual public test read result was incomplete.')
      }
      return toolCallResponse('phase31-edit-fee', 'replace_text', {
        path: 'fee.py',
        oldText: 'def calculate_fee(amount, rate=0.025):\n    return amount * rate\n',
        newText: 'def calculate_fee(amount, rate=0.025):\n    return round(amount * rate, 2)\n',
      })
    },
    options => {
      const edit = JSON.parse(lastToolResult(options.messages)) as { ok?: unknown; returncode?: unknown }
      if (edit.ok !== true || edit.returncode !== 0) return textResponse('The actual scoped edit did not complete successfully.')
      return toolCallResponse('phase31-test-fee', 'run_tests', { profile: 'public' })
    },
    options => {
      const test = JSON.parse(lastToolResult(options.messages)) as { returncode?: unknown }
      return test.returncode === 0
        ? textResponse('The actual public tests passed after the controlled edit.')
        : textResponse('The actual public tests failed; no success is claimed.')
    },
  ]
}

interface Phase31TaskInput {
  readonly trial_id: string
  readonly task_id: string
  readonly prompt: string
  readonly read_scope: readonly string[]
  readonly write_scope: readonly string[]
}

const PHASE31_REAL_PREFIX = 'KHAOS_DSH_PHASE3_1_REAL: '
const PHASE31_FIXTURE_PREFIX = 'KHAOS_DSH_PHASE3_1_FIXTURE: '

function parsePhase31Input(text: string): { input: Phase31TaskInput; realModel: boolean } | undefined {
  const prefix = text.startsWith(PHASE31_REAL_PREFIX) ? PHASE31_REAL_PREFIX
    : text.startsWith(PHASE31_FIXTURE_PREFIX) ? PHASE31_FIXTURE_PREFIX : undefined
  if (!prefix) return undefined
  let value: unknown
  try { value = JSON.parse(text.slice(prefix.length)) } catch { throw new Error('invalid_phase31_task_input') }
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error('invalid_phase31_task_input')
  const input = value as Record<string, unknown>
  const keys = Object.keys(input).sort().join(',')
  if (keys !== 'prompt,read_scope,task_id,trial_id,write_scope'
    || typeof input.trial_id !== 'string' || !/^[A-Za-z0-9_.:-]{1,128}$/u.test(input.trial_id)
    || typeof input.task_id !== 'string' || !['A', 'B', 'C', 'D'].includes(input.task_id)
    || typeof input.prompt !== 'string' || input.prompt.length === 0
    || !Array.isArray(input.read_scope) || input.read_scope.length === 0 || input.read_scope.length > 8
    || !Array.isArray(input.write_scope) || input.write_scope.length === 0 || input.write_scope.length > 8
    || ![...input.read_scope, ...input.write_scope].every(path => typeof path === 'string'
      && path.length > 0 && Buffer.byteLength(path, 'utf8') <= 128 && !path.startsWith('/')
      && !path.includes('\\') && !path.split('/').some(part => part === '' || part === '.' || part === '..'))
    || new Set(input.read_scope).size !== input.read_scope.length
    || new Set(input.write_scope).size !== input.write_scope.length
    || !input.write_scope.every(path => input.read_scope.includes(path))) {
    throw new Error('invalid_phase31_task_input')
  }
  return { input: input as unknown as Phase31TaskInput, realModel: prefix === PHASE31_REAL_PREFIX }
}

function scopeAttackResponses() {
  return [
    toolCallResponse('dsh-scope-escape', 'khaos_capability', proposal(
      ['python3', '-I', '-B', '-c', "from pathlib import Path; print(Path('../unscoped-canary.txt').read_text())"],
      ['../unscoped-canary.txt'],
      [],
    )),
    toolCallResponse('dsh-after-terminal', 'khaos_capability', proposal(
      ['python3', '-I', '-B', '-c', 'print("must not reach Launcher")'],
      [],
      [],
    )),
    options => textResponse(`DSH observed terminal scope denial: ${lastToolResult(options.messages)}`),
  ]
}

function oversizedScopeProposal() {
  return toolCallResponse('dsh-oversized-scope', 'khaos_capability', proposal(
    ['python3', '-I', '-B', '-c', 'print("must not reach the Launcher")'],
    Array.from({ length: 9 }, (_, index) => `scope-${index}.txt`),
    [],
  ))
}

function oversizedScopeResponses() {
  return [
    oversizedScopeProposal(),
    options => {
      const observed = lastToolResult(options.messages)
      const blocked = observed.includes('invalid readScope')
      return textResponse(`KHAOS_DSH_OVERSIZED_SCOPE_RESULT ${JSON.stringify({ blocked, observed })}`)
    },
  ]
}

function fakeResultResponses() {
  return [
    toolCallResponse('dsh-fake-success-output', 'khaos_capability', proposal(
      [
        'python3', '-I', '-B', '-c',
        "print('Ran 1 test\\nOK'); raise SystemExit(1)",
      ],
      [],
      [],
    )),
    options => {
      const observed = lastToolResult(options.messages)
      const actualFailure = observed.includes('"ok":false')
      const fakeSuccessOutput = observed.includes('Ran 1 test') && observed.includes('OK')
      return textResponse(`KHAOS_DSH_FAKE_RESULT_CHECK ${JSON.stringify({
        status: actualFailure && fakeSuccessOutput ? 'PASS' : 'FAIL',
        actualFailure,
        fakeSuccessOutput,
      })}`)
    },
  ]
}

function cancellationResponses() {
  const fixedScript = process.env.KHAOS_DSH_CANDIDATE_B_FIXED_SCRIPT
  if (!fixedScript || !fixedScript.startsWith('exec(') || !fixedScript.endsWith(')')) {
    throw new Error('trusted Candidate B fixed script is unavailable')
  }
  const oldText = 'def parse_tags(value):\n    return value.split(",")\n'
  const newText = 'def parse_tags(value):\n    return [part.strip() for part in value.split(",") if part.strip()]\n'
  const argv = [
    'python3', '-I', '-B', '-c', fixedScript, 'tags.py',
    JSON.stringify(oldText), JSON.stringify(newText),
  ]
  return [
    toolCallResponse('dsh-cancellation-candidate-b', 'khaos_capability', proposal(
      argv,
      ['tags.py'],
      ['tags.py'],
    )),
    options => textResponse(
      `CANCELLATION_RECEIPT_BASE64 ${Buffer.from(lastToolResultText(options.messages), 'utf8').toString('base64')}`,
    ),
  ]
}

function xpcCrashResponses() {
  const oldText = 'def parse_tags(value):\n    return value.split(",")\n'
  const newText = 'def parse_tags(value):\n    return [part.strip() for part in value.split(",") if part.strip()]\n'
  return [
    toolCallResponse('dsh-xpc-crash-edit', 'khaos_capability', proposal(
      [
        'python3', '-I', '-B', '-c',
        "from pathlib import Path; p=Path('tags.py'); old='def parse_tags(value):\\n    return value.split(\\\",\\\")\\n'; new='def parse_tags(value):\\n    return [part.strip() for part in value.split(\\\",\\\") if part.strip()]\\n'; assert p.read_text()==old; p.write_text(new)",
      ],
      ['tags.py'],
      ['tags.py'],
    )),
    options => textResponse(`KHAOS_DSH_XPC_CRASH_TASK_RESULT ${lastToolResult(options.messages)}`),
  ]
}

function xpcRecoveryResponses() {
  return [
    toolCallResponse('dsh-xpc-recovery-read', 'khaos_capability', proposal(
      [
        'python3', '-I', '-B', '-c',
        "from pathlib import Path; print(Path('tags.py').read_text())",
      ],
      ['tags.py'],
      [],
    )),
    options => textResponse(`KHAOS_DSH_XPC_RECOVERY_TASK_RESULT ${lastToolResult(options.messages)}`),
  ]
}

function probePaths(): HostileProbePaths | undefined {
  const workspaceRead = process.env.KHAOS_DSH_WORKSPACE_READ_PATH
  const workspaceWrite = process.env.KHAOS_DSH_WORKSPACE_WRITE_PATH
  const credential = process.env.KHAOS_DSH_CREDENTIAL_PATH
  const kernelBinary = process.env.KHAOS_DSH_KERNEL_PATH
  const nodeBinary = process.env.KHAOS_DSH_NODE_PATH
  const modelBridgeProbe = process.env.KHAOS_DSH_MODEL_BRIDGE_PROBE_PATH
  const localPort = Number(process.env.KHAOS_DSH_LOCAL_PORT)
  const agentHostPid = Number(process.env.KHAOS_DSH_AGENTHOST_PID)
  if (!workspaceRead || !workspaceWrite || !credential || !kernelBinary || !nodeBinary
    || !Number.isInteger(localPort) || localPort < 1 || localPort > 65_535
    || !Number.isSafeInteger(agentHostPid) || agentHostPid <= 0) {
    return undefined
  }
  return {
    workspaceRead,
    workspaceWrite,
    credential,
    kernelBinary,
    nodeBinary,
    ...(modelBridgeProbe ? { modelBridgeProbe } : {}),
    localPort,
    agentHostPid,
  }
}

async function createTask(text: string): Promise<void> {
  if (currentAgent || pendingResult) throw new Error('task already active')
  const realModelPrefix = 'KHAOS_DSH_REAL_MODEL_CODING: '
  const phase31 = parsePhase31Input(text)
  const semanticMode = phase31 !== undefined
  const realModelMode = phase31?.realModel ?? text.startsWith(realModelPrefix)
  const taskText = phase31?.input.prompt ?? (realModelMode ? text.slice(realModelPrefix.length) : text)
  if (realModelMode && taskText.length === 0) throw new Error('real-model task text is empty')
  const pluginLifecycleMode = text.includes('KHAOS_DSH_PLUGIN_LIFECYCLE')
  const attackMode = text.includes('KHAOS_DSH_XPC_ATTACK')
  const scopeAttack = text.includes('KHAOS_DSH_SCOPE_ATTACK')
  const oversizedScope = text.includes('KHAOS_DSH_OVERSIZED_SCOPE')
  const codingMode = text.includes('KHAOS_DSH_CODING_LOOP')
  const fakeResultMode = text.includes('KHAOS_DSH_FAKE_RESULT')
  const cancellationMode = text.includes('KHAOS_DSH_CANCELLATION_')
  const xpcCrashMode = text.includes('KHAOS_DSH_AGENTHOST_CRASH_ON_TOOL_RESULT')
  const xpcRecoveryMode = text.includes('KHAOS_DSH_XPC_RECOVERY_NEW_TASK')
  crashOnNextToolResult = text.includes('KHAOS_DSH_NODE_CRASH_ON_RESULT')
  const recoveryMode = text.includes('KHAOS_DSH_RECOVERY_NEW_TASK')
  const ctx = new Context()
  const dshSessionId = semanticMode ? `khaos-phase31-${randomUUID()}` : `khaos-xpc-${randomUUID()}`
  const telemetry = phase31 === undefined ? undefined : new DshAgentTelemetry(
    phase31.input.trial_id,
    dshSessionId,
    phase31.input.task_id,
    record => emit({ type: 'telemetry', record }),
  )
  let hostileEvidence: HostileProbeEvidence | undefined

  if (attackMode) {
    const paths = probePaths()
    if (!paths) throw new Error('signed XPC attack probe configuration is incomplete')
    await ctx.plugin(createMaliciousCordisPlugin(paths, evidence => {
      hostileEvidence = evidence
    }))
  }

  const mockAdapter = new MockAdapter(attackMode
    ? [oversizedScopeProposal(), options => {
      const evidence = hostileEvidence
      const oversizedScopeBlocked = lastToolResult(options.messages).includes('invalid readScope')
      const result = evidence ? {
        status: hostileProbePasses(evidence) && oversizedScopeBlocked ? 'PASS' : 'FAIL',
        oversizedScopeBlocked,
        ...evidence,
      } : { status: 'FAIL', oversizedScopeBlocked, reason: 'probe did not produce evidence' }
      return textResponse(`KHAOS_DSH_XPC_ATTACK_RESULT ${JSON.stringify(result)}`)
    }]
    : semanticMode && !realModelMode
      ? semanticCodingResponses()
    : codingMode
      ? codingResponses()
      : fakeResultMode
        ? fakeResultResponses()
      : cancellationMode
        ? cancellationResponses()
      : xpcCrashMode
        ? xpcCrashResponses()
      : recoveryMode
        ? [
          toolCallResponse('dsh-recovery-read', 'khaos_capability', proposal(
            [
              'python3', '-I', '-B', '-c',
              "from pathlib import Path; print(Path('fixture.txt').read_text())",
            ],
            ['fixture.txt'],
            [],
          )),
          options => textResponse(`KHAOS_DSH_RECOVERY_TASK_RESULT ${lastToolResult(options.messages)}`),
        ]
      : xpcRecoveryMode
        ? xpcRecoveryResponses()
      : scopeAttack
        ? scopeAttackResponses()
        : oversizedScope
          ? oversizedScopeResponses()
        : [
          toolCallResponse('khaos-dsh-acceptance-1', 'khaos_capability', proposal(
            [
              'python3', '-I', '-B', '-c',
              "from pathlib import Path; print(Path('fixture.txt').read_text())",
            ],
            ['fixture.txt'],
            [],
          )),
          options => textResponse(`DSH observed the actual Khaos tool result: ${lastToolResult(options.messages)}`),
        ])
  const modelAdapter = realModelMode
    ? new KhaosDshModelAdapter(
      process.env.KHAOS_DSH_LOCAL_MODEL_EXECUTABLE
        ? {
          provider: 'khaos-local',
          model: 'bundled-cpu',
          name: 'Khaos bundled CPU model',
          contextWindow: 8_192,
          complete: requestLocalModel,
        }
        : {
          provider: 'khaos-bigmodel',
          model: 'glm-5.3',
          name: 'GLM-5.3',
          contextWindow: 32_768,
          complete: requestModel,
        },
        telemetry,
    )
    : undefined
  const localModelMode = realModelMode && Boolean(process.env.KHAOS_DSH_LOCAL_MODEL_EXECUTABLE)
  const provider = realModelMode ? (localModelMode ? 'khaos-local' : 'khaos-bigmodel') : 'khaos-fixture'
  const model = realModelMode ? (localModelMode ? 'bundled-cpu' : 'glm-5.3') : 'deterministic-acceptance'

  await ctx.plugin(LlmRuntime)
  await ctx.plugin(SessionStore)
  await ctx.plugin(SessionProjectionRegistry)
  await ctx.plugin(SystemPrompt, {})
  await ctx.plugin(ToolRuntime)
  await ctx.plugin(AgentRegistry)
  await ctx.plugin(AgentLoop, { agents: [], maxParallelToolCalls: 1 })
  const disposeSemanticPrompt = semanticMode
    ? ctx.systemPrompt.section({
      name: 'khaos-phase3-1-semantic-tools',
      order: 9_900,
      text: 'For this coding task use only the semantic tools shown in the tool registry: read_file, replace_text, and run_tests with profile public. The task text may describe the public test command; that command is executed only through run_tests. Never generate shell commands, argv, scopes, working directories, environment values, or paths outside the displayed tool schemas. The registry exposes only the next allowed operation. Read every permitted public file before editing. Never access hidden tests. Maximum 8 tool operations, 3 writes, 3 repairs, and 600 seconds.',
    })
    : undefined
  ctx.llm.registerAdapter(
    [provider],
    modelAdapter ?? mockAdapter,
  )
  if (pluginLifecycleMode) {
    await ctx.agentLoop.create(SessionId(`khaos-lifecycle-${randomUUID()}`), {
      provider: 'khaos-fixture',
      model: 'deterministic-lifecycle-probe',
    })
    const evidence = await runCapabilityLifecycleProbe(ctx)
    emit({
      type: 'reply',
      text: `KHAOS_DSH_PLUGIN_LIFECYCLE_RESULT ${JSON.stringify({ ...evidence, nodePid: process.pid })}`,
    })
    await ctx.fiber.dispose()
    return
  }
  let rejectedProposalCount = 0
  const submitProposal = (
    proposalValue: KhaosShellProposal,
    signal: AbortSignal,
    correlation?: KhaosProposalCorrelation,
  ): Promise<KhaosToolResult> => {
    if (pendingResult) throw new Error('one Khaos operation may be pending at a time')
    if (correlation && telemetry) {
      telemetry.emit('LAUNCHER_PROPOSAL_SUBMITTED', {
        agent_turn_id: correlation.turn,
        agent_step_id: correlation.step,
        ...(correlation.modelCallId ? { model_call_id: correlation.modelCallId } : {}),
        tool_call_id: correlation.toolCallId,
        tool_name: correlation.toolName,
        operation_seq: correlation.operationSequence,
        invocation_sha256: correlation.invocationSHA256,
      })
    }
    emit({
      type: 'proposal',
      proposal: proposalValue,
      ...(correlation === undefined ? {} : {
        correlation: {
          trial_id: correlation.trialId,
          dsh_session_id: correlation.sessionId,
          benchmark_task_id: correlation.benchmarkTaskId,
          agent_turn_id: correlation.turn,
          agent_step_id: correlation.step,
          ...(correlation.modelCallId ? { model_call_id: correlation.modelCallId } : {}),
          tool_call_id: correlation.toolCallId,
          operation_seq: correlation.operationSequence,
          tool_name: correlation.toolName,
          invocation_sha256: correlation.invocationSHA256,
        },
      }),
    })
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
  }

  const agent = await ctx.agentLoop.create(SessionId(dshSessionId), {
    provider,
    model,
    ...(realModelMode ? { maxTokens: 2_048 } : {}),
  })
  let visibleToolDisposer: (() => void) | undefined
  let allAgentTools: string[] = []
  const setVisibleTools = (names: readonly SemanticToolName[]) => {
    visibleToolDisposer?.()
    visibleToolDisposer = names.length === 0
      ? agent.ctx.tools.restrict({ deny: allAgentTools })
      : agent.ctx.tools.restrict({ allow: [...names] })
  }
  const pluginFiber = semanticMode
    ? await ctx.plugin(createKhaosSemanticToolsPlugin(
      { submitProposal },
      {
        trialId: phase31.input.trial_id,
        taskId: phase31.input.task_id,
        readFiles: phase31.input.read_scope,
        writeFiles: phase31.input.write_scope,
        fixedEditScript: process.env.KHAOS_DSH_CANDIDATE_B_FIXED_SCRIPT ?? '',
      },
      telemetry as DshAgentTelemetry,
      setVisibleTools,
    ))
    : await ctx.plugin(createKhaosCapabilityPlugin({
      reportRejectedProposal() {
        rejectedProposalCount += 1
      },
      submitProposal,
    }))
  allAgentTools = agent.ctx.tools.schemas()
    .map(tool => tool.name)
    .filter(name => name !== 'run_code')
  if (semanticMode) setVisibleTools(['read_file'])
  currentAgent = agent
  currentContext = ctx
  currentPluginFiber = pluginFiber
  const agentErrors: { name: string; code?: string; message: string }[] = []
  const disposeAgentErrorListener = ctx.on('agent/error', ({ agent: failedAgent, error }) => {
    if (failedAgent !== agent || agentErrors.length >= 4) return
    const record = error as { code?: unknown }
    agentErrors.push({
      name: error instanceof Error ? error.name : typeof error,
      ...(typeof record?.code === 'string' ? { code: record.code.slice(0, 80) } : {}),
      message: error instanceof Error ? error.message.slice(0, 240) : String(error).slice(0, 240),
    })
  })
  const disposeSessionTelemetry = telemetry === undefined ? undefined : ctx.on('session/event', (session, event) => {
    if (session.id !== agent.session.id) return
    const data = event.data as Record<string, unknown>
    if (event.type === 'turn/start') telemetry.setPosition(data.turn as number, 0)
    if (event.type === 'step/start') {
      telemetry.setPosition(data.turn as number, data.step as number)
      if (phase31 && !phase31.realModel) {
        const position = telemetry.position()
        const modelCallId = `${phase31.input.trial_id}:fixture:${position.turn}:${position.step}`
        telemetry.beginModelCall(modelCallId)
        telemetry.emit('MODEL_REQUEST_STARTED', {
          agent_turn_id: position.turn,
          agent_step_id: position.step,
          model_call_id: modelCallId,
          model_provider: 'khaos-fixture',
          model_id: 'deterministic-semantic-fixture',
        })
      }
    }
    if (event.type === 'assistant/message') {
      const position = telemetry.position()
      telemetry.emit('DSH_ASSISTANT_MESSAGE_COMMITTED', {
        agent_turn_id: data.turn as number,
        agent_step_id: data.step as number,
        ...(position.modelCallId ? { model_call_id: position.modelCallId } : {}),
        status: 'session_committed',
        dsh_event_seq: event.seq,
      })
      if (phase31 && !phase31.realModel) {
        telemetry.emit('MODEL_RESPONSE_RECEIVED', {
          agent_turn_id: data.turn as number,
          agent_step_id: data.step as number,
          ...(position.modelCallId ? { model_call_id: position.modelCallId } : {}),
          status: 'fixture_received',
          duration_ms: 0,
        })
      }
    }
    if (event.type === 'tool/call') {
      const position = telemetry.position()
      const callId = String(data.callId ?? '')
      const name = String(data.name ?? '')
      const args = typeof data.arguments === 'string' ? data.arguments : ''
      if (!/^[A-Za-z0-9_.:-]{1,128}$/u.test(callId)
        || !['read_file', 'replace_text', 'run_tests'].includes(name)) return
      telemetry.emit('TOOL_CALL_PARSED', {
        agent_turn_id: data.turn as number,
        agent_step_id: data.step as number,
        ...(position.modelCallId ? { model_call_id: position.modelCallId } : {}),
        tool_call_id: callId,
        tool_name: name,
        argument_bytes: Buffer.byteLength(args, 'utf8'),
        dsh_event_seq: event.seq,
      })
    }
    if (event.type === 'tool/result') {
      const position = telemetry.position()
      const message = data.message as { toolCallId?: unknown; content?: unknown; isError?: unknown }
      const callId = typeof message.toolCallId === 'string' ? message.toolCallId : ''
      if (!/^[A-Za-z0-9_.:-]{1,128}$/u.test(callId)) return
      const contentJSON = JSON.stringify(message.content ?? null)
      telemetry.markToolResultDelivered(callId, message.content ?? null, message.isError === true)
      telemetry.emit('TOOL_RESULT_DELIVERED', {
        agent_turn_id: data.turn as number,
        agent_step_id: data.step as number,
        ...(position.modelCallId ? { model_call_id: position.modelCallId } : {}),
        tool_call_id: callId,
        ...(telemetry.operationSequence(callId) === undefined
          ? {} : { operation_seq: telemetry.operationSequence(callId) as number }),
        result_bytes: Buffer.byteLength(contentJSON, 'utf8'),
        result_sha256: telemetry.resultDigest(message.content ?? null),
        ...(telemetry.launcherResultDigest(callId) === undefined ? {} : {
          launcher_result_sha256: telemetry.launcherResultDigest(callId) as string,
        }),
        status: message.isError === true ? 'error' : 'ok',
        dsh_event_seq: event.seq,
      })
    }
  })
  telemetry?.emit('SESSION_STARTED', {
    agent_turn_id: 0,
    agent_step_id: 0,
    status: 'started',
    model_provider: provider,
    model_id: model,
  })
  agent.followup(createUserMessage({
    content: [{ type: 'text', text: taskText }],
    source: { kind: 'user' },
  }))
  void agent.whenIdle().then(async () => {
    const messages = [...agent.session.deriveMessages()]
    const assistantMessages = messages
      .filter(message => message.role === 'assistant')
    const assistant = assistantMessages.at(-1)
    const responseText = assistant?.content
      .filter(block => block.type === 'text')
      .map(block => block.text)
      .join('') ?? ''
    const toolResults = messages
      .filter(message => message.role === 'tool')
      .map(message => message.content)
    const diagnostics = {
      adapterRequestCount: modelAdapter?.usage().calls ?? mockAdapter.requests.length,
      assistantMessageCount: assistantMessages.length,
      lastAssistantBlockTypes: assistant?.content.map(block => block.type) ?? [],
      toolResultCount: toolResults.length,
      lastMessageRole: messages.at(-1)?.role ?? null,
      lastMessageBlockTypes: messages.at(-1)?.content.map(block => block.type) ?? [],
      adapterRejectedProposalCount: rejectedProposalCount,
      agentErrors,
    }
    if (telemetry) {
      const position = telemetry.position()
      telemetry.emit('AGENT_TERMINATED', {
        agent_turn_id: position.turn,
        agent_step_id: position.step,
        ...(position.modelCallId ? { model_call_id: position.modelCallId } : {}),
        status: 'idle',
      })
    }
    emit({
      type: 'reply',
      text: responseText || `DSH produced no final text response. diagnostics=${JSON.stringify(diagnostics)}`,
      toolResults,
      diagnostics,
      ...(modelAdapter === undefined ? {} : { model_stats: modelAdapter.usage() }),
    })
    disposeAgentErrorListener()
    disposeSessionTelemetry?.()
    disposeSemanticPrompt?.()
    visibleToolDisposer?.()
    currentAgent = undefined
    currentContext = undefined
    currentPluginFiber = undefined
    await pluginFiber.dispose()
    await ctx.fiber.dispose()
  }).catch(async () => {
    try {
      if (telemetry) {
        const position = telemetry.position()
        telemetry.emit('AGENT_TERMINATED', {
          agent_turn_id: position.turn,
          agent_step_id: position.step,
          ...(position.modelCallId ? { model_call_id: position.modelCallId } : {}),
          status: 'failed',
          error_code: 'dsh_agent_failed',
        })
      }
    } catch {
      // Trace exhaustion must not keep the failed experimental session alive.
    }
    disposeAgentErrorListener()
    disposeSessionTelemetry?.()
    disposeSemanticPrompt?.()
    visibleToolDisposer?.()
    currentAgent = undefined
    currentContext = undefined
    currentPluginFiber = undefined
    await pluginFiber.dispose().catch(() => undefined)
    await ctx.fiber.dispose().catch(() => undefined)
    emit({ type: 'error', code: 'dsh_agent_failed' })
  })
}

async function handle(input: HostInput): Promise<void> {
  if (input.operation === 'user') {
    if (typeof input.text !== 'string' || input.text.length === 0) {
      throw new Error('invalid user input')
    }
    if (input.text.includes('KHAOS_DSH_NODE_CRASH_BEFORE_TASK')) process.exit(86)
    await createTask(input.text)
    return
  }
  if (input.operation === 'model_result') {
    settleModelCall(input)
    return
  }
  if (input.operation === 'tool_result') {
    if (!pendingResult
      || typeof input.ok !== 'boolean'
      || typeof input.can_continue !== 'boolean'
      || typeof input.text !== 'string') {
      throw new Error('invalid Khaos tool result')
    }
    if (crashOnNextToolResult) process.exit(86)
    const resolve = pendingResult
    resolve({
      ok: input.ok,
      canContinue: input.can_continue,
      text: input.text,
    })
    return
  }
  if (input.operation === 'stop') {
    currentAgent?.cancel({ kind: 'user' })
    pendingResult = undefined
    rejectPendingModelCalls('agent host stopped')
    await currentPluginFiber?.dispose()
    await currentContext?.fiber.dispose()
    process.exit(0)
  }
  throw new Error('unknown host operation')
}

const lines = createInterface({ input: process.stdin, crlfDelay: Infinity })
lines.on('close', () => {
  const agent = currentAgent
  agent?.cancel({ kind: 'user' })
  pendingResult = undefined
  rejectPendingModelCalls('agent host input closed')
  void (async () => {
    await agent?.whenIdle()
    await currentPluginFiber?.dispose()
    await currentContext?.fiber.dispose()
  })().then(
    () => process.exit(0),
    () => process.exit(1),
  )
})
lines.on('line', line => {
  if (Buffer.byteLength(line, 'utf8') > 768 * 1024) {
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
