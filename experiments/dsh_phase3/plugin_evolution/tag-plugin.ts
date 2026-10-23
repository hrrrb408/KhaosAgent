import { defineTool } from '@deepseek-ai/dsh-tools'
import type { Context } from '@deepseek-ai/cordis'

export type TagNormalizer = (value: string) => string[]

export function createTagPlugin(normalize: TagNormalizer) {
  const plugin = (ctx: Context): void => {
    const unregister = ctx.tools.register(defineTool({
      name: 'normalize_tags',
      description: 'Normalize a comma-separated tag string.',
      parameters: { value: { type: 'string', required: true } },
      output: {
        schema: {
          type: 'object',
          properties: { tags: { type: 'array', items: { type: 'string' }, required: true } },
          additionalProperties: false,
        },
        render: (_args, result) => [{ type: 'text', text: JSON.stringify(result) }],
      },
      execute(args) {
        const value = (args as { value?: unknown }).value
        if (typeof value !== 'string' || Buffer.byteLength(value, 'utf8') > 1_024) {
          throw new Error('invalid tag input')
        }
        return { tags: normalize(value) }
      },
    }))
    ctx.effect(() => () => unregister())
  }

  return Object.assign(plugin, { inject: ['tools'] as const })
}
