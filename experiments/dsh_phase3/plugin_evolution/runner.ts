import { createInterface } from 'node:readline'
import { pathToFileURL } from 'node:url'
import { Context } from '@deepseek-ai/cordis'
import LlmRuntime, { ToolCallId } from '@deepseek-ai/dsh-llm'
import SessionStore from '@deepseek-ai/dsh-session'
import SessionProjectionRegistry from '@deepseek-ai/dsh-session-projection'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'

const pluginPath = process.argv[2]
if (!pluginPath) throw new Error('candidate plugin path is required')

const loaded = await import(pathToFileURL(pluginPath).href) as { default: unknown }
const ctx = new Context()
await ctx.plugin(LlmRuntime)
await ctx.plugin(SessionStore)
await ctx.plugin(SessionProjectionRegistry)
await ctx.plugin(SystemPrompt, {})
await ctx.plugin(ToolRuntime)
await ctx.plugin(loaded.default as never)
const names = ctx.tools.schemas().map(tool => tool.name)
process.stdout.write(`${JSON.stringify({ ready: true, tool_names: names })}\n`)

const lines = createInterface({ input: process.stdin, crlfDelay: Infinity })
for await (const line of lines) {
  const request = JSON.parse(line) as { operation?: string; value?: unknown }
  if (request.operation === 'stop') break
  const toolName = request.operation === 'activation_probe' ? 'khaos_candidate_activate' : 'normalize_tags'
  const result = await ctx.tools.execute({
    callId: ToolCallId(`phase3-${Date.now()}`),
    name: toolName,
    arguments: request.operation === 'activation_probe' ? {} : { value: request.value },
    signal: new AbortController().signal,
  })
  process.stdout.write(`${JSON.stringify({ is_error: result.isError, content: result.content })}\n`)
}
await ctx.fiber.dispose()
