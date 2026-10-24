export type PendingResultState = 'pending' | 'aborted'
export type ResultDelivery = 'delivered' | 'discarded_after_abort'

interface PendingOperation<T, C> {
  readonly correlation: C
  readonly signal: AbortSignal
  readonly resolve: (result: T) => void
  readonly reject: (error: Error) => void
  readonly notifyAbort: () => void
  readonly onAbort: () => void
  state: PendingResultState
}

/** Keeps one Launcher operation correlated until its original result arrives. */
export class PendingToolResultSlot<T, C> {
  private operation: PendingOperation<T, C> | undefined

  get occupied(): boolean {
    return this.operation !== undefined
  }

  get state(): PendingResultState | undefined {
    return this.operation?.state
  }

  get correlation(): C | undefined {
    return this.operation?.correlation
  }

  begin(correlation: C, signal: AbortSignal, onAbort: () => void): Promise<T> {
    if (this.occupied) throw new Error('kernel_operation_already_pending')
    if (signal.aborted) throw new Error('kernel_operation_cancelled_before_submission')
    return new Promise<T>((resolve, reject) => {
      let operation: PendingOperation<T, C>
      const abort = (): void => {
        if (operation.state !== 'pending') return
        operation.state = 'aborted'
        signal.removeEventListener('abort', operation.onAbort)
        try {
          onAbort()
        } finally {
          reject(new Error('kernel_operation_cancelled'))
        }
      }
      operation = {
        correlation,
        signal,
        resolve,
        reject,
        notifyAbort: onAbort,
        onAbort: abort,
        state: 'pending',
      }
      this.operation = operation
      signal.addEventListener('abort', operation.onAbort, { once: true })
      if (signal.aborted) abort()
    })
  }

  abort(reason: string): void {
    const operation = this.operation
    if (!operation || operation.state !== 'pending') return
    operation.state = 'aborted'
    operation.signal.removeEventListener('abort', operation.onAbort)
    try {
      operation.notifyAbort()
    } finally {
      operation.reject(new Error(reason))
    }
  }

  complete(result: T): { readonly delivery: ResultDelivery; readonly correlation: C } | undefined {
    const operation = this.operation
    if (!operation) return undefined
    this.operation = undefined
    operation.signal.removeEventListener('abort', operation.onAbort)
    if (operation.state === 'aborted') {
      return { delivery: 'discarded_after_abort', correlation: operation.correlation }
    }
    operation.resolve(result)
    return { delivery: 'delivered', correlation: operation.correlation }
  }
}

export interface AgentTerminalInput {
  readonly turnEndReason: unknown
  readonly lastMessageRole: unknown
  readonly lastMessageContent: unknown
  readonly unresolvedKernelResult: boolean
  readonly agentErrorCount: number
  readonly incompleteReason?: 'no_progress_limit'
}

export type AgentTerminalStatus = 'completed' | 'incomplete' | 'result_unknown' | 'cancelled' | 'failed'

/** Classifies DSH's recorded turn end; idle/quiescent is deliberately not success. */
export function classifyAgentTerminal(input: AgentTerminalInput): AgentTerminalStatus {
  if (input.unresolvedKernelResult) return 'result_unknown'
  const reason = input.turnEndReason
  const reasonKind = reason !== null && typeof reason === 'object'
    ? (reason as { kind?: unknown }).kind : undefined
  if (reasonKind === 'aborted') return 'cancelled'
  if (reasonKind === 'error' || input.agentErrorCount > 0) return 'failed'
  if (input.incompleteReason === 'no_progress_limit') return 'incomplete'
  if (reasonKind !== 'completed' || input.lastMessageRole !== 'assistant') return 'incomplete'
  if (!Array.isArray(input.lastMessageContent) || input.lastMessageContent.length === 0) return 'incomplete'
  const finalText = input.lastMessageContent.every(block =>
    block !== null && typeof block === 'object'
      && (block as { type?: unknown }).type === 'text'
      && typeof (block as { text?: unknown }).text === 'string'
      && (block as { text: string }).text.trim().length > 0)
  return finalText ? 'completed' : 'incomplete'
}
