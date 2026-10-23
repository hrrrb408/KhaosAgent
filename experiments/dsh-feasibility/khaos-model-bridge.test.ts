import assert from 'node:assert/strict'
import test from 'node:test'
import { KhaosModelBridgeAdapter } from './khaos-model-bridge.ts'
import type { GenerateOptions } from '@deepseek-ai/dsh-llm'

const completion = (message: Record<string, unknown>, finishReason: unknown = 'stop') => ({
  choices: [{ message, finish_reason: finishReason }],
  usage: { prompt_tokens: 12, completion_tokens: 7 },
})

function options(overrides: Partial<GenerateOptions> = {}): GenerateOptions {
  return {
    model: 'glm-5.3',
    messages: [{ role: 'user', content: [{ type: 'text', text: 'synthetic task' }] }],
    tools: [{
      name: 'khaos_capability',
      description: 'bounded test fixture',
      parameters: { type: 'object', properties: {} },
    }],
    maxTokens: 2_048,
    ...overrides,
  } as GenerateOptions
}

async function chunks(adapter: KhaosModelBridgeAdapter, request: GenerateOptions): Promise<unknown[]> {
  const result: unknown[] = []
  for await (const item of adapter.stream(request)) result.push(item)
  return result
}

test('uses the DSH route, fixed model, bounded output, and one Khaos tool', async () => {
  let captured: Record<string, unknown> | undefined
  const adapter = new KhaosModelBridgeAdapter(async request => {
    captured = request as unknown as Record<string, unknown>
    return {
      completion: completion({
        role: 'assistant',
        content: null,
        tool_calls: [{
          id: 'call-1',
          type: 'function',
          function: { name: 'khaos_capability', arguments: '{"argv":["python3"]}' },
        }],
      }, 'tool_calls'),
      elapsed_ms: 23,
    }
  })

  const result = await chunks(adapter, options())
  assert.ok(captured)
  assert.deepEqual(captured.headers, {
    'user-agent': 'deepseek-harness/0.2.1-rc.2 (+https://github.com/deepseek-ai/deepseek-harness)',
  })
  assert.deepEqual(captured.body, {
    model: 'glm-5.3',
    messages: [{ role: 'user', content: 'synthetic task' }],
    tools: [{
      type: 'function',
      function: {
        name: 'khaos_capability',
        description: 'bounded test fixture',
        parameters: { type: 'object', properties: {} },
      },
    }],
    tool_choice: 'auto',
    max_tokens: 2_048,
    temperature: 0.2,
    thinking: { type: 'enabled', clear_thinking: false },
    stream: false,
  })
  assert.ok(result.some(item => (item as { type?: string }).type === 'tool-call-delta'))
  assert.deepEqual(adapter.usage(), {
    calls: 1,
    input_tokens: 12,
    output_tokens: 7,
    elapsed_ms: 23,
  })
})

test('rejects unsupported models, completion budgets, request sizes, and tools before transport', async () => {
  let calls = 0
  const adapter = new KhaosModelBridgeAdapter(async () => {
    calls += 1
    return { completion: completion({ role: 'assistant', content: 'unused' }), elapsed_ms: 1 }
  })
  await assert.rejects(adapter.resolveModel('other', 'glm-5.3'))
  await assert.rejects(chunks(adapter, options({ model: 'other' })))
  await assert.rejects(chunks(adapter, options({ maxTokens: 2_049 })))
  await assert.rejects(chunks(adapter, options({
    tools: [{ name: 'arbitrary-network', description: '', parameters: {} }],
  })))
  await assert.rejects(chunks(adapter, options({
    messages: [{ role: 'user', content: [{ type: 'text', text: 'x'.repeat(57 * 1_024) }] }],
  })))
  assert.equal(calls, 0)
})

test('rejects malformed and oversized provider responses', async () => {
  const invalidResponses = [
    {},
    { choices: [] },
    completion({ role: 'assistant', content: 'ok' }, 'content_filter'),
    completion({
      role: 'assistant',
      content: null,
      tool_calls: [
        { id: 'call-1', type: 'function', function: { name: 'khaos_capability', arguments: '{}' } },
        { id: 'call-2', type: 'function', function: { name: 'khaos_capability', arguments: '{}' } },
      ],
    }, 'tool_calls'),
    completion({
      role: 'assistant',
      content: null,
      tool_calls: [{
        id: 'call-unknown',
        type: 'function',
        function: { name: 'not_registered', arguments: '{}' },
      }],
    }, 'tool_calls'),
    completion({
      role: 'assistant',
      content: null,
      tool_calls: [{
        id: 'call-invalid-json',
        type: 'function',
        function: { name: 'khaos_capability', arguments: '{' },
      }],
    }, 'tool_calls'),
    completion({
      role: 'assistant',
      content: null,
      tool_calls: [{
        id: 'call-invalid-shape',
        type: 'function',
        function: { name: 'khaos_capability', arguments: '[]' },
      }],
    }, 'tool_calls'),
    completion({ role: 'assistant', content: 'x'.repeat(49 * 1_024) }),
    completion({
      role: 'assistant',
      content: null,
      tool_calls: [{
        id: 'call-1',
        type: 'function',
        function: { name: 'khaos_capability', arguments: 'x'.repeat(33 * 1_024) },
      }],
    }, 'tool_calls'),
  ]
  for (const response of invalidResponses) {
    const adapter = new KhaosModelBridgeAdapter(async () => ({ completion: response, elapsed_ms: 1 }))
    await assert.rejects(chunks(adapter, options()))
  }
})

test('sanitizes provider errors while retaining bounded timing', async () => {
  const adapter = new KhaosModelBridgeAdapter(async () => {
    throw Object.assign(new Error('model_provider_auth_failed with secret response'), { elapsed_ms: 31 })
  })
  await assert.rejects(chunks(adapter, options()), error => {
    assert.match((error as Error).message, /model_provider_failed/u)
    assert.doesNotMatch((error as Error).message, /secret response/u)
    return true
  })
  assert.deepEqual(adapter.usage(), {
    calls: 1,
    input_tokens: null,
    output_tokens: null,
    elapsed_ms: 31,
  })
})

test('does not submit a pre-cancelled request', async () => {
  let calls = 0
  const adapter = new KhaosModelBridgeAdapter(async () => {
    calls += 1
    return { completion: completion({ role: 'assistant', content: 'unused' }), elapsed_ms: 1 }
  })
  const controller = new AbortController()
  controller.abort()
  await assert.rejects(chunks(adapter, options({ signal: controller.signal })))
  assert.equal(calls, 0)
})
