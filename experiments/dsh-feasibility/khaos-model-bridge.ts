import { randomUUID } from 'node:crypto'
import {
  LlmAdapter,
  LlmError,
  ToolCallId,
  attributionHeaders,
} from '@deepseek-ai/dsh-llm'
import type {
  ContentBlock,
  GenerateOptions,
  LlmResolvedModelInfo,
  StreamChunk,
  ToolSchema,
} from '@deepseek-ai/dsh-llm'
import type { DshAgentTelemetry } from './dsh-agent-telemetry.ts'

const MAX_REQUEST_BYTES = 56 * 1024
const MAX_RESPONSE_TEXT_BYTES = 48 * 1024
const MAX_ARGUMENT_BYTES = 32 * 1024
const MAX_COMPLETION_TOKENS = 2_048
const MAX_MODEL_CALLS_PER_TASK = 12
const SEMANTIC_TOOL_NAMES = ['read_file', 'replace_text', 'run_tests'] as const

export interface KhaosModelRequest {
  readonly request_id: string
  readonly headers: Readonly<Record<string, string>>
  readonly body: Readonly<Record<string, unknown>>
}

export interface KhaosModelResult {
  readonly completion: unknown
  readonly elapsed_ms: number
}

export type KhaosModelCall = (
  request: KhaosModelRequest,
  signal?: AbortSignal,
) => Promise<KhaosModelResult>

export interface KhaosModelRoute {
  readonly provider: string
  readonly model: string
  readonly name: string
  readonly contextWindow: number
  readonly complete: KhaosModelCall
}

export interface KhaosModelUsage {
  readonly calls: number
  readonly input_tokens: number | null
  readonly output_tokens: number | null
  readonly elapsed_ms: number
}

function fail(message: string, code = 'MALFORMED_RESPONSE'): never {
  throw new LlmError(`Khaos DSH model adapter: ${message}`, code)
}

function utf8Bytes(value: string): number {
  return Buffer.byteLength(value, 'utf8')
}

function modelText(blocks: readonly ContentBlock[]): string {
  const result: string[] = []
  for (const block of blocks) {
    if (block.type === 'text') result.push(block.text)
    else if (block.type === 'tool-addition' || block.type === 'tool-removal') continue
    else fail(`unsupported request block ${block.type}`, 'UNSUPPORTED_CONTENT')
  }
  return result.join('')
}

function toolSchema(tool: ToolSchema): Record<string, unknown> {
  return {
    type: 'function',
    function: {
      name: tool.name,
      description: tool.description,
      parameters: tool.parameters,
    },
  }
}

function requestMessage(message: GenerateOptions['messages'][number]): Record<string, unknown> {
  if (message.role === 'assistant') {
    const calls = message.content.filter(block => block.type === 'tool-call')
    const text = message.content
      .filter(block => block.type === 'text')
      .map(block => block.text)
      .join('')
    const toolCalls = calls.map(block => ({
      id: block.id,
      type: 'function',
      function: { name: block.name, arguments: block.arguments },
    }))
    for (const block of message.content) {
      if (block.type !== 'tool-call' && block.type !== 'text') {
        fail(`unsupported assistant block ${block.type}`, 'UNSUPPORTED_CONTENT')
      }
    }
    return {
      role: 'assistant',
      content: text || null,
      ...(toolCalls.length > 0 ? { tool_calls: toolCalls } : {}),
    }
  }
  if (message.role === 'tool') {
    return {
      role: 'tool',
      tool_call_id: message.toolCallId,
      content: modelText(message.content),
    }
  }
  const content = modelText(message.content)
  return {
    role: message.role === 'developer' ? 'system' : message.role,
    content,
  }
}

function requestBody(options: GenerateOptions, model: string): Record<string, unknown> {
  if (options.model !== model) fail('only the configured model is supported', 'INVALID_MODEL')
  const maxTokens = options.maxTokens ?? MAX_COMPLETION_TOKENS
  if (!Number.isSafeInteger(maxTokens) || maxTokens < 1 || maxTokens > MAX_COMPLETION_TOKENS) {
    fail('completion token limit is outside the experimental bound', 'INVALID_REQUEST')
  }
  const messages = options.messages.map(requestMessage)
  if (messages.length < 1 || messages.length > 64) {
    fail('message count is outside the experimental bound', 'INVALID_REQUEST')
  }
  if (options.system !== undefined && options.system.length > 0) {
    messages.unshift({ role: 'system', content: options.system })
  }
  const tools = options.tools?.map(toolSchema)
  if (tools !== undefined) {
    const names = options.tools?.map(tool => tool.name) ?? []
    const noToolMode = names.length === 0
    const rawToolMode = names.length === 1 && names[0] === 'khaos_capability'
    const semanticToolMode = names.length > 0 && names.length <= SEMANTIC_TOOL_NAMES.length
      && new Set(names).size === names.length
      && names.every(name => SEMANTIC_TOOL_NAMES.includes(name as typeof SEMANTIC_TOOL_NAMES[number]))
    if (!noToolMode && !rawToolMode && !semanticToolMode) {
      fail('model tool set is outside the registered Khaos experiment interface', 'INVALID_REQUEST')
    }
  }
  const temperature = options.temperature ?? 0.2
  if (!Number.isFinite(temperature) || temperature < 0 || temperature > 2) {
    fail('invalid temperature', 'INVALID_REQUEST')
  }
  const reasoningEffort = options.reasoningEffort
  if (reasoningEffort !== undefined && !['low', 'medium', 'high', 'max'].includes(reasoningEffort)) {
    fail('invalid reasoning effort', 'INVALID_REQUEST')
  }
  if (options.stop !== undefined && (
    !Array.isArray(options.stop)
    || options.stop.length > 4
    || options.stop.some(value => typeof value !== 'string' || utf8Bytes(value) > 256)
  )) {
    fail('invalid stop sequence', 'INVALID_REQUEST')
  }
  const body = {
    model,
    messages,
    ...(tools && tools.length > 0 ? { tools, tool_choice: 'auto' } : {}),
    max_tokens: maxTokens,
    temperature,
    ...(reasoningEffort === undefined ? {} : { reasoning_effort: reasoningEffort }),
    thinking: { type: 'enabled', clear_thinking: false },
    stream: false,
    ...(options.stop === undefined ? {} : { stop: options.stop }),
  }
  const encoded = JSON.stringify(body)
  if (utf8Bytes(encoded) > MAX_REQUEST_BYTES) fail('model request is too large', 'REQUEST_TOO_LARGE')
  return body
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    fail(`invalid ${label}`)
  }
  return value as Record<string, unknown>
}

function boundedTokenCount(value: unknown): number | undefined {
  return Number.isSafeInteger(value) && (value as number) >= 0 && (value as number) <= 1_000_000
    ? value as number
    : undefined
}

function textChunks(text: string, index: number): StreamChunk[] {
  return [
    { type: 'block-start', index, blockType: 'text' },
    ...(text.length === 0 ? [] : [{ type: 'text-delta' as const, index, text }]),
    { type: 'block-end', index, block: { type: 'text', text } },
  ]
}

function completionChunks(
  value: unknown,
  permittedTools: ReadonlySet<string>,
): {
  chunks: StreamChunk[]
  usage?: { inputTokens: number; outputTokens: number }
  toolCalls: { id: string; name: string; argumentBytes: number }[]
} {
  const completion = object(value, 'completion')
  if (!Array.isArray(completion.choices) || completion.choices.length !== 1) {
    fail('expected one completion choice')
  }
  const choice = object(completion.choices[0], 'choice')
  const message = object(choice.message, 'assistant message')
  const content = message.content
  if (content !== null && typeof content !== 'string') fail('invalid assistant content')
  if (typeof content === 'string' && utf8Bytes(content) > MAX_RESPONSE_TEXT_BYTES) {
    fail('assistant content is too large', 'RESPONSE_TOO_LARGE')
  }
  const calls = message.tool_calls === undefined ? [] : message.tool_calls
  if (!Array.isArray(calls) || calls.length > 1) {
    fail('a response may contain at most one Khaos operation', 'TOOL_CALL_LIMIT_EXCEEDED')
  }

  const chunks: StreamChunk[] = []
  const toolCalls: { id: string; name: string; argumentBytes: number }[] = []
  let index = 0
  if (typeof content === 'string' && content.length > 0) {
    chunks.push(...textChunks(content, index++))
  }
  for (const item of calls) {
    const call = object(item, 'tool call')
    const fn = object(call.function, 'tool function')
    if (call.type !== 'function'
      || typeof call.id !== 'string' || call.id.length === 0 || utf8Bytes(call.id) > 128
      || /[\u0000-\u001f\u007f]/u.test(call.id)
      || typeof fn.name !== 'string' || fn.name.length === 0 || utf8Bytes(fn.name) > 128
      || typeof fn.arguments !== 'string' || utf8Bytes(fn.arguments) > MAX_ARGUMENT_BYTES) {
      fail('invalid tool call')
    }
    if (!permittedTools.has(fn.name)) fail('model requested an unregistered tool', 'UNKNOWN_TOOL')
    let argumentsValue: unknown
    try {
      argumentsValue = JSON.parse(fn.arguments)
    } catch {
      fail('model returned invalid tool argument JSON', 'INVALID_TOOL_ARGUMENTS')
    }
    if (argumentsValue === null || typeof argumentsValue !== 'object' || Array.isArray(argumentsValue)) {
      fail('model returned a non-object tool argument', 'INVALID_TOOL_ARGUMENTS')
    }
    const id = ToolCallId(call.id)
    toolCalls.push({ id: call.id, name: fn.name, argumentBytes: utf8Bytes(fn.arguments) })
    chunks.push(
      { type: 'block-start', index, blockType: 'tool-call' },
      { type: 'tool-call-delta', index, id, name: fn.name, argumentsDelta: fn.arguments },
      {
        type: 'block-end',
        index,
        block: { type: 'tool-call', id, name: fn.name, arguments: fn.arguments },
      },
    )
    index += 1
  }
  if (chunks.length === 0) fail('empty completion', 'EMPTY_RESPONSE')

  const reason = choice.finish_reason
  const finish = calls.length > 0
    ? { kind: 'tool-calls' as const }
    : reason === 'length'
      ? { kind: 'max-tokens' as const }
      : reason === 'stop' || reason === null
        ? { kind: 'stop' as const }
        : undefined
  if (finish === undefined) fail('unsupported finish reason')

  const rawUsage = completion.usage === undefined ? undefined : object(completion.usage, 'usage')
  const inputTokens = boundedTokenCount(rawUsage?.prompt_tokens)
  const outputTokens = boundedTokenCount(rawUsage?.completion_tokens)
  const usage = inputTokens === undefined || outputTokens === undefined
    ? undefined
    : { inputTokens, outputTokens }
  return {
    chunks: [
      ...chunks,
      ...(usage === undefined ? [] : [{ type: 'usage' as const, usage }]),
      { type: 'finish', reason: finish },
    ],
    toolCalls,
    ...(usage === undefined ? {} : { usage }),
  }
}

/** Shared DSH adapter for model routes that return bounded OpenAI-style completions. */
export class KhaosDshModelAdapter extends LlmAdapter {
  private calls = 0
  private inputTokens = 0
  private outputTokens = 0
  private usageKnown = true
  private elapsedMilliseconds = 0
  private readonly usedToolCallIds = new Set<string>()
  private awaitingToolResultId: string | undefined

  constructor(
    private readonly route: KhaosModelRoute,
    private readonly telemetry?: DshAgentTelemetry,
  ) {
    super()
  }

  override async resolveModel(provider: string, model: string): Promise<LlmResolvedModelInfo> {
    if (provider !== this.route.provider || model !== this.route.model) {
      fail('unsupported model route', 'INVALID_MODEL')
    }
    return {
      provider,
      id: this.route.model,
      name: this.route.name,
      contextWindow: this.route.contextWindow,
    }
  }

  usage(): KhaosModelUsage {
    return {
      calls: this.calls,
      input_tokens: this.usageKnown ? this.inputTokens : null,
      output_tokens: this.usageKnown ? this.outputTokens : null,
      elapsed_ms: this.elapsedMilliseconds,
    }
  }

  async *stream(options: GenerateOptions): AsyncIterable<StreamChunk> {
    if (options.signal?.aborted) throw new LlmError('model call was cancelled', 'ABORTED')
    if (this.calls >= MAX_MODEL_CALLS_PER_TASK) {
      fail('model call budget exceeded', 'MODEL_CALL_BUDGET_EXCEEDED')
    }
    const body = requestBody(options, this.route.model)
    const requestId = randomUUID()
    const position = this.telemetry?.position()
    if (this.awaitingToolResultId !== undefined && this.telemetry) {
      const toolCallId = this.awaitingToolResultId
      const toolMessage = options.messages.find(message =>
        message.role === 'tool' && message.toolCallId === toolCallId)
      const observed = toolMessage !== undefined
        && this.telemetry.matchesDeliveredToolResult(
          toolCallId,
          toolMessage.content,
          toolMessage.isError === true,
        )
      const operationSequence = this.telemetry.operationSequence(toolCallId)
      const correlation = {
        agent_turn_id: position?.turn ?? 0,
        agent_step_id: position?.step ?? 0,
        model_call_id: requestId,
        tool_call_id: toolCallId,
        ...(operationSequence === undefined ? {} : { operation_seq: operationSequence }),
        observed_tool_result: observed,
      }
      this.telemetry.emit('SESSION_CONTINUITY_CHECK', correlation)
      if (!observed) {
        this.telemetry.emit('MODEL_REQUEST_FAILED', {
          agent_turn_id: position?.turn ?? 0,
          agent_step_id: position?.step ?? 0,
          model_call_id: requestId,
          duration_ms: 0,
          error_code: 'session_continuity_missing',
        })
        this.awaitingToolResultId = undefined
        throw new LlmError('DSH Session did not contain the delivered Khaos tool result', 'SESSION_CONTINUITY_MISSING')
      }
      this.telemetry.emit('AGENT_NEXT_TURN_STARTED', correlation)
      this.awaitingToolResultId = undefined
    }
    this.telemetry?.beginModelCall(requestId)
    this.telemetry?.emit('MODEL_REQUEST_STARTED', {
      agent_turn_id: position?.turn ?? 0,
      agent_step_id: position?.step ?? 0,
      model_call_id: requestId,
      model_provider: this.route.provider,
      model_id: this.route.model,
    })
    const request: KhaosModelRequest = {
      request_id: requestId,
      headers: attributionHeaders(),
      body,
    }
    this.calls += 1
    let result: KhaosModelResult
    try {
      result = await this.route.complete(request, options.signal)
    } catch (error) {
      this.usageKnown = false
      if (options.signal?.aborted) throw new LlmError('model call was cancelled', 'ABORTED')
      const value = error instanceof Error ? error.message : ''
      const code = /^[a-z][a-z0-9_]{0,79}$/u.test(value) ? value : 'model_provider_failed'
      const elapsed = (error as Error & { elapsed_ms?: unknown })?.elapsed_ms
      this.telemetry?.emit('MODEL_REQUEST_FAILED', {
        agent_turn_id: position?.turn ?? 0,
        agent_step_id: position?.step ?? 0,
        model_call_id: requestId,
        duration_ms: Number.isSafeInteger(elapsed) && (elapsed as number) >= 0
          ? Math.min(elapsed as number, 600_000) : 0,
        error_code: code,
      })
      if (Number.isSafeInteger(elapsed) && (elapsed as number) >= 0) {
        this.elapsedMilliseconds += elapsed as number
      }
      throw new LlmError(`Khaos model request failed (${code})`, code.toUpperCase())
    }
    if (!Number.isSafeInteger(result.elapsed_ms) || result.elapsed_ms < 0) {
      fail('invalid bridge timing')
    }
    if (utf8Bytes(JSON.stringify(result.completion)) > 56 * 1024) {
      fail('provider completion exceeds the XPC frame budget', 'RESPONSE_TOO_LARGE')
    }
    this.telemetry?.emit('MODEL_RESPONSE_RECEIVED', {
      agent_turn_id: position?.turn ?? 0,
      agent_step_id: position?.step ?? 0,
      model_call_id: requestId,
      duration_ms: result.elapsed_ms,
      status: 'received',
    })
    let translated: ReturnType<typeof completionChunks>
    try {
      translated = completionChunks(result.completion, new Set(options.tools?.map(tool => tool.name) ?? []))
      for (const call of translated.toolCalls) {
        if (this.usedToolCallIds.has(call.id)) fail('duplicate tool call id in one DSH task', 'DUPLICATE_TOOL_CALL_ID')
        if (this.usedToolCallIds.size >= 16) fail('tool call id limit exceeded', 'TOOL_CALL_LIMIT_EXCEEDED')
        this.usedToolCallIds.add(call.id)
      }
    } catch (error) {
      this.usageKnown = false
      const rawCode = error instanceof LlmError ? error.code.toLowerCase() : 'invalid_model_output'
      const code = /^[a-z0-9_]{1,80}$/u.test(rawCode) ? rawCode : 'invalid_model_output'
      this.telemetry?.emit('MODEL_OUTPUT_REJECTED', {
        agent_turn_id: position?.turn ?? 0,
        agent_step_id: position?.step ?? 0,
        model_call_id: requestId,
        duration_ms: result.elapsed_ms,
        error_code: code,
      })
      throw error
    }
    for (const call of translated.toolCalls) {
      this.telemetry?.emit('MODEL_TOOL_CALL_OUTPUT_ACCEPTED', {
        agent_turn_id: position?.turn ?? 0,
        agent_step_id: position?.step ?? 0,
        model_call_id: requestId,
        tool_call_id: call.id,
        tool_name: call.name,
        argument_bytes: call.argumentBytes,
      })
    }
    for (const call of translated.toolCalls) {
      this.awaitingToolResultId = call.id
    }
    this.elapsedMilliseconds += result.elapsed_ms
    if (translated.usage === undefined) {
      this.usageKnown = false
    } else {
      this.inputTokens += translated.usage.inputTokens
      this.outputTokens += translated.usage.outputTokens
    }
    yield* translated.chunks
  }
}
