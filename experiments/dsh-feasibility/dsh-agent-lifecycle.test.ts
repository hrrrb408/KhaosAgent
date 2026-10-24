import assert from 'node:assert/strict'
import test from 'node:test'
import { classifyAgentTerminal, PendingToolResultSlot } from './dsh-agent-lifecycle.ts'

test('only a completed DSH turn with a final text message is completed', () => {
  assert.equal(classifyAgentTerminal({
    turnEndReason: { kind: 'completed' },
    lastMessageRole: 'assistant',
    lastMessageContent: [{ type: 'text', text: 'Done.' }],
    unresolvedKernelResult: false,
    agentErrorCount: 0,
    incompleteReason: 'no_progress_limit',
  }), 'incomplete')
  assert.equal(classifyAgentTerminal({
    turnEndReason: { kind: 'completed' },
    lastMessageRole: 'assistant',
    lastMessageContent: [{ type: 'text', text: 'Done.' }],
    unresolvedKernelResult: false,
    agentErrorCount: 0,
    incompleteReason: 'tool_budget_exhausted',
  }), 'incomplete')
  assert.equal(classifyAgentTerminal({
    turnEndReason: { kind: 'completed' },
    lastMessageRole: 'assistant',
    lastMessageContent: [{ type: 'text', text: 'Done.' }],
    unresolvedKernelResult: false,
    agentErrorCount: 0,
  }), 'completed')
  assert.equal(classifyAgentTerminal({
    turnEndReason: { kind: 'completed' },
    lastMessageRole: 'assistant',
    lastMessageContent: [{ type: 'tool-call', name: 'read_file' }],
    unresolvedKernelResult: false,
    agentErrorCount: 0,
  }), 'incomplete')
  assert.equal(classifyAgentTerminal({
    turnEndReason: { kind: 'aborted', reason: { kind: 'user' } },
    lastMessageRole: 'assistant',
    lastMessageContent: [{ type: 'text', text: 'Done.' }],
    unresolvedKernelResult: false,
    agentErrorCount: 0,
  }), 'cancelled')
  assert.equal(classifyAgentTerminal({
    turnEndReason: { kind: 'completed' },
    lastMessageRole: 'assistant',
    lastMessageContent: [{ type: 'text', text: 'Done.' }],
    unresolvedKernelResult: true,
    agentErrorCount: 0,
  }), 'result_unknown')
})

test('an aborted operation retains its correlation until its one late result is archived', async () => {
  const slot = new PendingToolResultSlot<string, string>()
  const controller = new AbortController()
  const pending = slot.begin('trial-A/call-1', controller.signal, () => undefined)
  controller.abort()
  await assert.rejects(pending, /kernel_operation_cancelled/u)
  assert.equal(slot.state, 'aborted')
  assert.throws(() => slot.begin('trial-B/call-1', new AbortController().signal, () => undefined),
    /kernel_operation_already_pending/u)
  assert.deepEqual(slot.complete('committed-result'), {
    delivery: 'discarded_after_abort',
    correlation: 'trial-A/call-1',
  })
  assert.equal(slot.occupied, false)
  const next = slot.begin('trial-B/call-1', new AbortController().signal, () => undefined)
  assert.deepEqual(slot.complete('new-result'), {
    delivery: 'delivered',
    correlation: 'trial-B/call-1',
  })
  assert.equal(await next, 'new-result')
})

test('a normal result is delivered once and clears the operation slot', async () => {
  const slot = new PendingToolResultSlot<number, { readonly taskId: string }>()
  const pending = slot.begin({ taskId: 'task-1' }, new AbortController().signal, () => undefined)
  assert.deepEqual(slot.complete(17), {
    delivery: 'delivered',
    correlation: { taskId: 'task-1' },
  })
  assert.equal(await pending, 17)
  assert.equal(slot.complete(18), undefined)
})
