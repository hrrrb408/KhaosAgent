import { createHash } from 'node:crypto'

export interface AgentTracePosition {
  readonly turn: number
  readonly step: number
  readonly modelCallId?: string
}

export interface AgentTraceFields {
  readonly [key: string]: string | number | boolean
}

const EVENTS = new Set([
  'SESSION_STARTED',
  'MODEL_REQUEST_STARTED',
  'MODEL_RESPONSE_RECEIVED',
  'MODEL_TOOL_CALL_OUTPUT_ACCEPTED',
  'DSH_ASSISTANT_MESSAGE_COMMITTED',
  'MODEL_REQUEST_FAILED',
  'MODEL_OUTPUT_REJECTED',
  'TOOL_CALL_PARSED',
  'TOOL_ARGUMENT_VALIDATED',
  'TOOL_ARGUMENT_REJECTED',
  'TOOL_SUBMISSION_FAILED',
  'TOOL_PROPOSAL_LOWERED',
  'LAUNCHER_PROPOSAL_SUBMITTED',
  'APPROVAL_ACCEPTED',
  'APPROVAL_DENIED',
  'KERNEL_OPERATION_STARTED',
  'KERNEL_OPERATION_COMPLETED',
  'LAUNCHER_TERMINAL_RESULT_DELIVERED',
  'PUBLIC_TEST_RESULT_VERIFIED',
  'TOOL_RESULT_DELIVERED',
  'TOOL_OPERATION_ABORTED',
  'TOOL_RESULT_DISCARDED',
  'NO_PROGRESS_DETECTED',
  'TURN_END_OBSERVED',
  'AGENT_NEXT_TURN_STARTED',
  'SESSION_CONTINUITY_CHECK',
  'AGENT_TERMINATED',
])

const FIELDS = new Set([
  'agent_turn_id', 'agent_step_id', 'model_call_id', 'tool_call_id', 'tool_name',
  'operation_seq', 'invocation_sha256', 'argument_bytes', 'file_count',
  'write_operation', 'duration_ms', 'status', 'error_code', 'returncode',
  'tool_operations_remaining', 'write_operations_remaining', 'repair_attempts_remaining',
  'can_continue', 'result_bytes', 'result_sha256', 'observed_tool_result',
  'launcher_result_sha256', 'dsh_event_seq', 'token_input', 'token_output', 'model_provider', 'model_id',
  'launcher_task_id', 'launcher_request_id', 'launcher_approval_sha256', 'approval_status',
  'runtime_trial_id',
  'kernel_result', 'runner_status', 'commit_status', 'launcher_ok',
  'turn_end_sequence', 'assistant_message_count', 'tool_result_count', 'turn_end_reason',
  'last_message_role', 'last_message_text_only', 'unresolved_kernel_result',
  'tests_run', 'failures', 'errors', 'skipped',
])

function safeId(value: string): boolean {
  return /^[A-Za-z0-9_.:-]{1,128}$/u.test(value)
}

/** Bounded, payload-free records for one experimental DSH task. */
export class DshAgentTelemetry {
  private sequence = 0
  private turn = 0
  private step = 0
  private modelCallId: string | undefined
  private readonly toolOperationSequences = new Map<string, number>()
  private readonly deliveredToolResults = new Map<string, { digest: string; isError: boolean }>()
  private readonly pendingContinuityChecks: string[] = []
  private readonly launcherResults = new Map<string, string>()

  constructor(
    readonly trialId: string,
    readonly sessionId: string,
    readonly benchmarkTaskId: string,
    private readonly sink: (record: Readonly<Record<string, unknown>>) => void,
  ) {
    if (!safeId(trialId) || !safeId(sessionId) || !safeId(benchmarkTaskId)) {
      throw new Error('invalid_telemetry_identity')
    }
  }

  setPosition(turn: number, step: number): void {
    if (!Number.isSafeInteger(turn) || turn < 0 || !Number.isSafeInteger(step) || step < 0) {
      throw new Error('invalid_telemetry_position')
    }
    this.turn = turn
    this.step = step
  }

  beginModelCall(modelCallId: string): void {
    if (!safeId(modelCallId)) throw new Error('invalid_model_call_id')
    this.modelCallId = modelCallId
  }

  position(): AgentTracePosition {
    return {
      turn: this.turn,
      step: this.step,
      ...(this.modelCallId ? { modelCallId: this.modelCallId } : {}),
    }
  }

  bindToolCall(callId: string, operationSequence: number): void {
    if (!safeId(callId) || !Number.isSafeInteger(operationSequence) || operationSequence < 1) {
      throw new Error('invalid_tool_correlation')
    }
    this.toolOperationSequences.set(callId, operationSequence)
  }

  operationSequence(callId: string): number | undefined {
    return this.toolOperationSequences.get(callId)
  }

  markLauncherResultReceived(callId: string, text: string): void {
    if (!safeId(callId) || !this.toolOperationSequences.has(callId) || this.launcherResults.has(callId)) {
      throw new Error('invalid_launcher_result_correlation')
    }
    this.launcherResults.set(callId, createHash('sha256').update(text, 'utf8').digest('hex'))
  }

  launcherResultDigest(callId: string): string | undefined {
    return this.launcherResults.get(callId)
  }

  markToolResultDelivered(callId: string, content: unknown, isError: boolean): void {
    if (!safeId(callId) || this.deliveredToolResults.has(callId)) {
      throw new Error('invalid_tool_result_correlation')
    }
    this.deliveredToolResults.set(callId, { digest: this.resultDigest(content), isError })
    this.pendingContinuityChecks.push(callId)
  }

  matchesDeliveredToolResult(callId: string, content: unknown, isError: boolean): boolean {
    const expected = this.deliveredToolResults.get(callId)
    return expected !== undefined
      && expected.isError === isError
      && expected.digest === this.resultDigest(content)
  }

  nextPendingContinuityCheck(): string | undefined {
    return this.pendingContinuityChecks[0]
  }

  completeContinuityCheck(callId: string): void {
    if (this.pendingContinuityChecks[0] !== callId) {
      throw new Error('invalid_tool_result_continuity_order')
    }
    this.pendingContinuityChecks.shift()
  }

  resultDigest(value: unknown): string {
    return createHash('sha256').update(JSON.stringify(value), 'utf8').digest('hex')
  }

  emit(event: string, fields: AgentTraceFields = {}): void {
    if (!EVENTS.has(event)) throw new Error('unknown_telemetry_event')
    if (this.sequence >= 256) throw new Error('telemetry_event_limit_exceeded')
    for (const [key, value] of Object.entries(fields)) {
      if (!FIELDS.has(key)
        || (typeof value === 'string' && (value.length > 256 || /[\u0000-\u001f\u007f]/u.test(value)))
        || (typeof value !== 'string' && typeof value !== 'number' && typeof value !== 'boolean')) {
        throw new Error('invalid_telemetry_field')
      }
      if (key.endsWith('_sha256') && (typeof value !== 'string' || !/^[0-9a-f]{64}$/u.test(value))) {
        throw new Error('invalid_telemetry_digest')
      }
    }
    this.sequence += 1
    this.sink({
      event,
      event_seq: this.sequence,
      timestamp_utc: new Date().toISOString(),
      trial_id: this.trialId,
      dsh_session_id: this.sessionId,
      benchmark_task_id: this.benchmarkTaskId,
      ...fields,
    })
  }
}
