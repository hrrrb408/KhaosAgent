import { randomUUID } from 'node:crypto'
import { createInterface } from 'node:readline'
import { Context } from '@deepseek-ai/cordis'
import AgentRegistry from '@deepseek-ai/dsh-agent'
import type { Agent } from '@deepseek-ai/dsh-agent'
import LlmRuntime, { createUserMessage, ReasoningEffortId } from '@deepseek-ai/dsh-llm'
import AgentLoop from '@deepseek-ai/dsh-agent-loop'
import SessionStore, { SessionId } from '@deepseek-ai/dsh-session'
import SessionProjectionRegistry from '@deepseek-ai/dsh-session-projection'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import { MockAdapter, textResponse, toolCallResponse } from '../mock-adapter.ts'
import { createKhaosCapabilityPlugin, type KhaosToolResult } from './khaos-capability-adapter.ts'
import { runCapabilityLifecycleProbe } from './dsh-capability-lifecycle-probe.ts'
import {
  KhaosModelBridgeAdapter,
  type KhaosModelBridgeRequest,
  type KhaosModelBridgeResult,
} from './khaos-model-bridge.ts'
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
  resolve(result: KhaosModelBridgeResult): void
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

function emit(value: object): void {
  process.stdout.write(`${JSON.stringify(value)}\n`)
}

function requestModel(
  request: KhaosModelBridgeRequest,
  signal?: AbortSignal,
): Promise<KhaosModelBridgeResult> {
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
  const localPort = Number(process.env.KHAOS_DSH_LOCAL_PORT)
  const agentHostPid = Number(process.env.KHAOS_DSH_AGENTHOST_PID)
  if (!workspaceRead || !workspaceWrite || !credential || !kernelBinary
    || !Number.isInteger(localPort) || localPort < 1 || localPort > 65_535
    || !Number.isSafeInteger(agentHostPid) || agentHostPid <= 0) {
    return undefined
  }
  return { workspaceRead, workspaceWrite, credential, kernelBinary, localPort, agentHostPid }
}

async function createTask(text: string): Promise<void> {
  if (currentAgent || pendingResult) throw new Error('task already active')
  const realModelPrefix = 'KHAOS_DSH_REAL_MODEL_CODING\n'
  const realModelMode = text.startsWith(realModelPrefix)
  const taskText = realModelMode ? text.slice(realModelPrefix.length) : text
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
    ? new KhaosModelBridgeAdapter(requestModel)
    : undefined
  const provider = realModelMode ? 'khaos-bigmodel' : 'khaos-fixture'
  const model = realModelMode ? 'glm-5.3' : 'deterministic-acceptance'

  await ctx.plugin(LlmRuntime)
  await ctx.plugin(SessionStore)
  await ctx.plugin(SessionProjectionRegistry)
  await ctx.plugin(SystemPrompt, {})
  await ctx.plugin(ToolRuntime)
  await ctx.plugin(AgentRegistry)
  await ctx.plugin(AgentLoop, { agents: [], maxParallelToolCalls: 1 })
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
  const pluginFiber = await ctx.plugin(createKhaosCapabilityPlugin({
    reportRejectedProposal() {
      rejectedProposalCount += 1
    },
    submitProposal(proposalValue, signal) {
      if (pendingResult) throw new Error('one Khaos operation may be pending at a time')
      emit({ type: 'proposal', proposal: proposalValue })
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

  const agent = await ctx.agentLoop.create(SessionId(`khaos-xpc-${randomUUID()}`), {
    provider,
    model,
    ...(realModelMode ? { maxTokens: 2_048, reasoningEffort: ReasoningEffortId('high') } : {}),
  })
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
    emit({
      type: 'reply',
      text: responseText || `DSH produced no final text response. diagnostics=${JSON.stringify(diagnostics)}`,
      toolResults,
      diagnostics,
      ...(modelAdapter === undefined ? {} : { model_stats: modelAdapter.usage() }),
    })
    disposeAgentErrorListener()
    currentAgent = undefined
    currentContext = undefined
    currentPluginFiber = undefined
    await pluginFiber.dispose()
    await ctx.fiber.dispose()
  }).catch(() => {
    disposeAgentErrorListener()
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
