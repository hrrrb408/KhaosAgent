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

const MAX_REQUEST_BYTES = 56 * 1024
const MAX_RESPONSE_TEXT_BYTES = 48 * 1024
const MAX_ARGUMENT_BYTES = 32 * 1024
const MAX_COMPLETION_TOKENS = 2_048
const MODEL = 'glm-5.3'

export interface KhaosModelBridgeRequest {
  readonly request_id: string
  readonly headers: Readonly<Record<string, string>>
  readonly body: Readonly<Record<string, unknown>>
}

export interface KhaosModelBridgeResult {
  readonly completion: unknown
  readonly elapsed_ms: number
}

export type KhaosModelBridgeCall = (
  request: KhaosModelBridgeRequest,
  signal?: AbortSignal,
) => Promise<KhaosModelBridgeResult>

export interface KhaosModelUsage {
  readonly calls: number
  readonly input_tokens: number | null
  readonly output_tokens: number | null
  readonly elapsed_ms: number
}

function fail(message: string, code = 'MALFORMED_RESPONSE'): never {
  throw new LlmError(`Khaos BigModel adapter: ${message}`, code)
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

function requestBody(options: GenerateOptions): Record<string, unknown> {
  if (options.model !== MODEL) fail('only the configured model is supported', 'INVALID_MODEL')
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
  if (tools !== undefined && (tools.length !== 1 || options.tools?.[0]?.name !== 'khaos_capability')) {
    fail('only the Khaos capability tool may be sent to the model', 'INVALID_REQUEST')
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
    model: MODEL,
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

function completionChunks(value: unknown): { chunks: StreamChunk[]; usage?: { inputTokens: number; outputTokens: number } } {
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
    if (fn.name !== 'khaos_capability') fail('model requested an unregistered tool', 'UNKNOWN_TOOL')
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
    ...(usage === undefined ? {} : { usage }),
  }
}

/** DSH-native provider route whose network request is proxied by the signed Swift XPC host. */
export class KhaosModelBridgeAdapter extends LlmAdapter {
  private calls = 0
  private inputTokens = 0
  private outputTokens = 0
  private usageKnown = true
  private elapsedMilliseconds = 0

  constructor(private readonly complete: KhaosModelBridgeCall) {
    super()
  }

  override async resolveModel(provider: string, model: string): Promise<LlmResolvedModelInfo> {
    if (provider !== 'khaos-bigmodel' || model !== MODEL) fail('unsupported model route', 'INVALID_MODEL')
    return { provider, id: MODEL, name: 'GLM-5.3', contextWindow: 32_768 }
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
    const request: KhaosModelBridgeRequest = {
      request_id: randomUUID(),
      headers: attributionHeaders(),
      body: requestBody(options),
    }
    this.calls += 1
    let result: KhaosModelBridgeResult
    try {
      result = await this.complete(request, options.signal)
    } catch (error) {
      this.usageKnown = false
      if (options.signal?.aborted) throw new LlmError('model call was cancelled', 'ABORTED')
      const value = error instanceof Error ? error.message : ''
      const code = /^[a-z][a-z0-9_]{0,79}$/u.test(value) ? value : 'model_provider_failed'
      const elapsed = (error as Error & { elapsed_ms?: unknown })?.elapsed_ms
      if (Number.isSafeInteger(elapsed) && (elapsed as number) >= 0) {
        this.elapsedMilliseconds += elapsed as number
      }
      throw new LlmError(`Khaos BigModel request failed (${code})`, code.toUpperCase())
    }
    if (!Number.isSafeInteger(result.elapsed_ms) || result.elapsed_ms < 0) {
      fail('invalid bridge timing')
    }
    if (utf8Bytes(JSON.stringify(result.completion)) > 56 * 1024) {
      fail('provider completion exceeds the XPC frame budget', 'RESPONSE_TOO_LARGE')
    }
    let translated: ReturnType<typeof completionChunks>
    try {
      translated = completionChunks(result.completion)
    } catch (error) {
      this.usageKnown = false
      throw error
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
