interface DshMessage {
  readonly role: string
  readonly content: unknown
}

function textContent(content: unknown): string {
  if (Array.isArray(content)) {
    const blocks = content.flatMap((value) => {
      if (value === null || typeof value !== 'object') return []
      const block = value as { type?: unknown; text?: unknown }
      return block.type === 'text' && typeof block.text === 'string' ? [block.text] : []
    })
    if (blocks.length > 0) return blocks.join('\n')
  }
  return typeof content === 'string' ? content : JSON.stringify(content ?? null)
}

/** Read the rendered content of the latest DSH tool message without re-encoding its blocks. */
export function lastToolResult(messages: readonly DshMessage[]): string {
  const message = [...messages].reverse().find(value => value.role === 'tool')
  return textContent(message?.content ?? null)
}

/** Unwrap the Launcher result's text field when a fixture needs its bounded command output. */
export function lastToolResultText(messages: readonly DshMessage[]): string {
  const rendered = lastToolResult(messages)
  try {
    const decoded = JSON.parse(rendered) as { text?: unknown } | null
    if (decoded && typeof decoded === 'object' && typeof decoded.text === 'string') {
      return decoded.text
    }
  } catch {
    // Some DSH tool adapters preserve plain text rather than JSON output.
  }
  return rendered
}

/** Read only the bounded budget metadata added by a semantic tool result. */
export function semanticToolBudget(content: unknown): {
  readonly toolOperations: number
  readonly writeOperations: number
  readonly repairAttempts: number
} | undefined {
  try {
    const parsed = JSON.parse(textContent(content)) as { remaining_budget?: unknown } | null
    const budget = parsed?.remaining_budget
    if (budget === null || typeof budget !== 'object' || Array.isArray(budget)) return undefined
    const value = budget as Record<string, unknown>
    if (!Number.isSafeInteger(value.tool_operations) || (value.tool_operations as number) < 0
      || !Number.isSafeInteger(value.write_operations) || (value.write_operations as number) < 0
      || !Number.isSafeInteger(value.repair_attempts) || (value.repair_attempts as number) < 0) {
      return undefined
    }
    return {
      toolOperations: value.tool_operations as number,
      writeOperations: value.write_operations as number,
      repairAttempts: value.repair_attempts as number,
    }
  } catch {
    return undefined
  }
}
