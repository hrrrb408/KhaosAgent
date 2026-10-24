import { createHash } from 'node:crypto'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type { Context } from '@deepseek-ai/cordis'
import type { DshAgentTelemetry } from './dsh-agent-telemetry.ts'
import {
  KhaosProposalSession,
  type KhaosLauncherPort,
  type KhaosProposalCorrelation,
  type KhaosShellProposal,
  type KhaosToolResult,
} from './khaos-capability-adapter.ts'

const MAX_PATH_BYTES = 128
const MAX_TEXT_BYTES = 4 * 1024
const MAX_ALLOWED_OPERATIONS = 12
const MAX_ALLOWED_WRITES = 3
const MAX_ALLOWED_REPAIRS = 3
const READ_SCRIPT = 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"),end="")'
// Avoid directory discovery so the fixed test profile stays within file-scoped read authority.
const TEST_RESULT_MARKER = 'KHAOS_TEST_RESULT='
const TEST_SCRIPT = 'import json,pathlib,sys,types,unittest; module_name=sys.argv[1][:-3]; source=types.ModuleType(module_name); exec(compile(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"),sys.argv[1],"exec"),source.__dict__); sys.modules[module_name]=source; test=types.ModuleType("test_public"); exec(compile(pathlib.Path("test_public.py").read_text(encoding="utf-8"),"test_public.py","exec"),test.__dict__); result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(test)); successful=result.testsRun>0 and result.wasSuccessful(); print("KHAOS_TEST_RESULT="+json.dumps({"tests_run":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),"skipped":len(result.skipped),"successful":successful},sort_keys=True,separators=(",",":"))); raise SystemExit(0 if successful else 2 if result.testsRun==0 else 1)'
const TOOL_NAMES = ['read_file', 'replace_text', 'run_tests'] as const

export type SemanticToolName = typeof TOOL_NAMES[number]

interface SemanticToolResult extends KhaosToolResult {
  readonly remaining_budget: {
    readonly tool_operations: number
    readonly write_operations: number
    readonly repair_attempts: number
  }
  readonly test_result?: PublicTestVerification
  readonly public_test_completion_hint?: string
  readonly no_progress?: 'recovery_feedback' | 'final_only'
  readonly recovery_feedback?: string
}

export interface PublicTestVerification {
  readonly status: 'passed' | 'failed' | 'invalid' | 'unverified' | 'mismatch'
  readonly tests_run?: number
  readonly failures?: number
  readonly errors?: number
  readonly skipped?: number
  readonly error_code?: string
}

export interface KhaosCodingToolPolicy {
  readonly trialId: string
  readonly taskId: string
  readonly readFiles: readonly string[]
  readonly writeFiles: readonly string[]
  readonly fixedEditScript: string
  readonly maxToolOperations: number
  readonly maxWriteOperations: number
  readonly maxRepairAttempts: number
}

function bytes(value: string): number {
  return Buffer.byteLength(value, 'utf8')
}

function safeRelativePath(value: string): boolean {
  if (!value || bytes(value) > MAX_PATH_BYTES || value.startsWith('/') || value.includes('\\') || value.includes('\0')) {
    return false
  }
  if (/[\u0001-\u001f\u007f]/u.test(value)) return false
  const parts = value.split('/')
  return parts.length <= 64 && parts.every(part => part.length > 0 && part !== '.' && part !== '..')
}

function exactObject(value: unknown, expectedKeys: readonly string[], label: string): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error(`invalid_${label}`)
  const record = value as Record<string, unknown>
  if (Object.keys(record).sort().join(',') !== [...expectedKeys].sort().join(',')) throw new Error(`invalid_${label}`)
  return record
}

function canonicalPythonJSONString(value: string): string {
  let result = '"'
  for (let index = 0; index < value.length; index++) {
    const first = value.charCodeAt(index)
    if (first >= 0xd800 && first <= 0xdbff) {
      const second = value.charCodeAt(index + 1)
      if (!(second >= 0xdc00 && second <= 0xdfff)) throw new Error('invalid_unicode_text')
    } else if (first >= 0xdc00 && first <= 0xdfff) {
      const previous = value.charCodeAt(index - 1)
      if (!(previous >= 0xd800 && previous <= 0xdbff)) throw new Error('invalid_unicode_text')
    }
  }
  for (const character of value) {
    const scalar = character.codePointAt(0) as number
    switch (scalar) {
      case 0x08: result += '\\b'; break
      case 0x09: result += '\\t'; break
      case 0x0a: result += '\\n'; break
      case 0x0c: result += '\\f'; break
      case 0x0d: result += '\\r'; break
      case 0x22: result += '\\"'; break
      case 0x5c: result += '\\\\'; break
      default:
        if (scalar <= 0x1f || (scalar >= 0x7f && scalar <= 0xffff)) {
          result += unicodeEscape(scalar)
        } else if (scalar <= 0x7e) {
          result += character
        } else if (scalar <= 0xffff) {
          result += unicodeEscape(scalar)
        } else {
          const offset = scalar - 0x10000
          result += unicodeEscape(0xd800 + (offset >> 10))
          result += unicodeEscape(0xdc00 + (offset & 0x3ff))
        }
    }
  }
  return `${result}"`
}

function unicodeEscape(value: number): string {
  return `\\u${value.toString(16).padStart(4, '0')}`
}

function sha256(value: string): string {
  return createHash('sha256').update(value, 'utf8').digest('hex')
}

function validatePolicy(policy: KhaosCodingToolPolicy): void {
  const idValid = /^[A-Za-z0-9_.:-]{1,128}$/u.test(policy.trialId)
  const taskIdValid = /^[A-Za-z0-9_.:-]{1,128}$/u.test(policy.taskId)
  const validList = (values: readonly string[]) => values.length > 0
    && values.length <= 8
    && new Set(values).size === values.length
    && values.every(safeRelativePath)
  if (!idValid || !taskIdValid
    || !validList(policy.readFiles) || !validList(policy.writeFiles)
    || !policy.writeFiles.every(path => policy.readFiles.includes(path))
    || !Number.isSafeInteger(policy.maxToolOperations) || policy.maxToolOperations < 1
    || policy.maxToolOperations > MAX_ALLOWED_OPERATIONS
    || !Number.isSafeInteger(policy.maxWriteOperations) || policy.maxWriteOperations < 0
    || policy.maxWriteOperations > MAX_ALLOWED_WRITES
    || !Number.isSafeInteger(policy.maxRepairAttempts) || policy.maxRepairAttempts < 0
    || policy.maxRepairAttempts > MAX_ALLOWED_REPAIRS
    || !policy.fixedEditScript.startsWith('exec(')
    || !policy.fixedEditScript.endsWith(')')
    || bytes(policy.fixedEditScript) > MAX_TEXT_BYTES) {
    throw new Error('invalid_semantic_tool_policy')
  }
}

function proposalDigest(proposal: KhaosShellProposal): string {
  return sha256(JSON.stringify({ argv: proposal.argv, readScope: proposal.readScope, writeScope: proposal.writeScope }))
}

function observationDigest(result: KhaosToolResult): string {
  return sha256(JSON.stringify({
    ok: result.ok,
    canContinue: result.canContinue,
    returncode: result.returncode ?? null,
    commitStatus: result.launcherTrace?.commit_status ?? null,
    text: result.text,
  }))
}

function outputSchema() {
  return {
    schema: {
      type: 'object',
      properties: {
        ok: { type: 'boolean', required: true },
        canContinue: { type: 'boolean', required: true },
        text: { type: 'string', required: true },
        returncode: { type: 'integer' },
        test_result: {
          type: 'object',
          properties: {
            status: { type: 'string', enum: ['passed', 'failed', 'invalid', 'unverified', 'mismatch'], required: true },
            tests_run: { type: 'integer' },
            failures: { type: 'integer' },
            errors: { type: 'integer' },
            skipped: { type: 'integer' },
            error_code: { type: 'string' },
          },
          additionalProperties: false,
        },
        public_test_completion_hint: { type: 'string' },
        no_progress: { type: 'string', enum: ['recovery_feedback', 'final_only'] },
        recovery_feedback: { type: 'string' },
        remaining_budget: {
          type: 'object',
          properties: {
            tool_operations: { type: 'integer', required: true },
            write_operations: { type: 'integer', required: true },
            repair_attempts: { type: 'integer', required: true },
          },
          additionalProperties: false,
          required: true,
        },
      },
      additionalProperties: false,
    },
    render: (_args: unknown, result: SemanticToolResult) => [{ type: 'text' as const, text: JSON.stringify(result) }],
  }
}

function exactResultRecord(value: unknown, expectedKeys: readonly string[]): Record<string, unknown> | undefined {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return undefined
  const record = value as Record<string, unknown>
  return Object.keys(record).sort().join(',') === [...expectedKeys].sort().join(',')
    ? record : undefined
}

function verifyPublicTestResult(result: KhaosToolResult): PublicTestVerification {
  if (!Number.isSafeInteger(result.returncode)) {
    return { status: 'unverified', error_code: 'runner_result_unknown' }
  }
  let output: Record<string, unknown> | undefined
  try {
    output = exactResultRecord(JSON.parse(result.text), [
      'added', 'deleted', 'modified', 'returncode', 'stderr', 'stderr_truncated', 'stdout', 'stdout_truncated',
    ])
  } catch {
    output = undefined
  }
  if (!output || output.returncode !== result.returncode
    || typeof output.stdout !== 'string' || typeof output.stderr !== 'string'
    || typeof output.stdout_truncated !== 'boolean' || typeof output.stderr_truncated !== 'boolean'
    || !['added', 'modified', 'deleted'].every(key =>
      Number.isSafeInteger(output?.[key]) && (output?.[key] as number) >= 0)) {
    return { status: 'unverified', error_code: 'runner_result_unverified' }
  }
  if (output.stdout_truncated || output.stderr_truncated) {
    return { status: 'unverified', error_code: 'runner_output_truncated' }
  }
  const marker = (output.stdout as string).split(/\r?\n/u)
    .filter(line => line.startsWith(TEST_RESULT_MARKER)).at(-1)
  if (!marker) return { status: 'unverified', error_code: 'test_summary_missing' }
  let summary: Record<string, unknown> | undefined
  try {
    summary = exactResultRecord(JSON.parse(marker.slice(TEST_RESULT_MARKER.length)), [
      'errors', 'failures', 'skipped', 'successful', 'tests_run',
    ])
  } catch {
    summary = undefined
  }
  if (!summary
    || !['tests_run', 'failures', 'errors', 'skipped'].every(key =>
      Number.isSafeInteger(summary?.[key]) && (summary?.[key] as number) >= 0)
    || typeof summary.successful !== 'boolean') {
    return { status: 'unverified', error_code: 'test_summary_invalid' }
  }
  const testsRun = summary.tests_run as number
  const failures = summary.failures as number
  const errors = summary.errors as number
  const skipped = summary.skipped as number
  if (skipped > testsRun || failures + errors + skipped > testsRun) {
    return { status: 'unverified', error_code: 'test_summary_invalid' }
  }
  if (testsRun === 0 || testsRun === skipped) {
    return { status: 'invalid', tests_run: testsRun, failures, errors, skipped, error_code: 'zero_tests_executed' }
  }
  const summaryPassed = summary.successful === true && failures === 0 && errors === 0
  const launcherPassed = result.returncode === 0 && result.ok
  const summaryFailed = summary.successful === false && (failures > 0 || errors > 0)
  const launcherFailed = result.returncode !== 0 && !result.ok
  if ((summary.successful === false && !summaryFailed)
    || summaryPassed !== launcherPassed || summaryFailed !== launcherFailed
    || summaryPassed === summaryFailed) {
    return { status: 'mismatch', tests_run: testsRun, failures, errors, skipped, error_code: 'test_result_mismatch' }
  }
  return {
    status: summaryPassed ? 'passed' : 'failed',
    tests_run: testsRun,
    failures,
    errors,
    skipped,
  }
}

function semanticEvent(
  telemetry: DshAgentTelemetry,
  event: string,
  toolName: SemanticToolName,
  callId: string,
  extra: Readonly<Record<string, string | number | boolean>> = {},
): void {
  const position = telemetry.position()
  telemetry.emit(event, {
    agent_turn_id: position.turn,
    agent_step_id: position.step,
    ...(position.modelCallId ? { model_call_id: position.modelCallId } : {}),
    tool_call_id: callId,
    tool_name: toolName,
    ...extra,
  })
}

/** Cordis tools lower intent into the existing bounded Launcher proposal port. */
export function createKhaosSemanticToolsPlugin(
  port: KhaosLauncherPort,
  policy: KhaosCodingToolPolicy,
  telemetry: DshAgentTelemetry,
  setVisibleTools: (names: readonly SemanticToolName[]) => void,
  onNoProgressLimit?: () => void,
  onToolBudgetExhausted?: () => void,
) {
  validatePolicy(policy)
  const session = new KhaosProposalSession(port, () => undefined)
  const seenCallIds = new Set<string>()
  let toolCallCount = 0
  let operationSequence = 0
  let writeOperations = 0
  let repairAttempts = 0
  let testRuns = 0
  let workspaceRevision = 0
  let lastObservation: {
    readonly invocationSHA256: string
    readonly resultSHA256: string
    readonly workspaceRevision: number
    readonly repeatedResultObserved: boolean
  } | undefined
  let finalOnly = false
  let closed = false

  const toolAllowedByPolicy = (name: SemanticToolName): boolean => name !== 'replace_text'
    || (writeOperations < policy.maxWriteOperations
      && (testRuns === 0 || repairAttempts < policy.maxRepairAttempts))

  const visibleTools = (): readonly SemanticToolName[] => {
    if (closed || finalOnly || toolCallCount >= policy.maxToolOperations) return []
    return TOOL_NAMES.filter(toolAllowedByPolicy)
  }

  const execute = async (
    toolName: SemanticToolName,
    args: unknown,
    callId: string,
    signal: AbortSignal,
  ): Promise<SemanticToolResult> => {
    if (closed || session.isClosed) throw new Error('semantic_tool_session_closed')
    if (toolCallCount >= policy.maxToolOperations) throw new Error('semantic_operation_limit_exceeded')
    toolCallCount += 1
    setVisibleTools(visibleTools())
    if (!/^[A-Za-z0-9_.:-]{1,128}$/u.test(callId) || seenCallIds.has(callId)) {
      if (/^[A-Za-z0-9_.:-]{1,128}$/u.test(callId)) {
        semanticEvent(telemetry, 'TOOL_ARGUMENT_REJECTED', toolName, callId, { error_code: 'duplicate_tool_call_id' })
      }
      throw new Error('duplicate_or_invalid_tool_call_id')
    }
    seenCallIds.add(callId)
    if (!toolAllowedByPolicy(toolName)) {
      semanticEvent(telemetry, 'TOOL_ARGUMENT_REJECTED', toolName, callId, { error_code: 'tool_unavailable_or_budget_exhausted' })
      throw new Error('tool_unavailable_or_budget_exhausted')
    }
    if (signal.aborted) throw new Error('semantic_tool_cancelled_before_submission')

    let argsBytes = 0
    let pathCount = 0
    let proposal: KhaosShellProposal
    let correlation: KhaosProposalCorrelation
    let testProfile = false
    try {
      if (toolName === 'read_file') {
        const record = exactObject(args, ['path'], 'read_file_arguments')
        if (typeof record.path !== 'string' || !safeRelativePath(record.path)
          || !policy.readFiles.includes(record.path)) {
          throw new Error('path_not_in_read_scope')
        }
        argsBytes = bytes(record.path)
        pathCount = 1
        proposal = {
          argv: ['python3', '-I', '-B', '-c', READ_SCRIPT, record.path],
          readScope: [record.path],
          writeScope: [],
        }
      } else if (toolName === 'replace_text') {
        const record = exactObject(args, ['path', 'oldText', 'newText'], 'replace_text_arguments')
        if (typeof record.path !== 'string' || !safeRelativePath(record.path)
          || !policy.writeFiles.includes(record.path)) throw new Error('path_not_in_write_scope')
        if (typeof record.oldText !== 'string' || typeof record.newText !== 'string'
          || !record.oldText || record.oldText === record.newText
          || bytes(record.oldText) > MAX_TEXT_BYTES || bytes(record.newText) > MAX_TEXT_BYTES) {
          throw new Error('invalid_replacement_text')
        }
        const oldText = canonicalPythonJSONString(record.oldText)
        const newText = canonicalPythonJSONString(record.newText)
        if (bytes(oldText) > MAX_TEXT_BYTES || bytes(newText) > MAX_TEXT_BYTES) {
          throw new Error('replacement_encoding_too_large')
        }
        proposal = {
          argv: ['python3', '-I', '-B', '-c', policy.fixedEditScript, record.path, oldText, newText],
          readScope: [record.path],
          writeScope: [record.path],
        }
        argsBytes = bytes(record.path) + bytes(record.oldText) + bytes(record.newText)
        pathCount = 1
      } else {
        const record = exactObject(args, ['profile'], 'run_tests_arguments')
        if (record.profile !== 'public') throw new Error('test_profile_not_allowed')
        const [sourcePath] = policy.writeFiles
        if (policy.writeFiles.length !== 1 || typeof sourcePath !== 'string'
          || !/^[A-Za-z_][A-Za-z0-9_]*\.py$/u.test(sourcePath)
          || !policy.readFiles.includes(sourcePath)
          || !policy.readFiles.includes('test_public.py')) {
          throw new Error('public_test_scope_invalid')
        }
        proposal = {
          argv: ['python3', '-I', '-B', '-c', TEST_SCRIPT, sourcePath],
          readScope: [sourcePath, 'test_public.py'],
          writeScope: [],
        }
        argsBytes = bytes('public')
        pathCount = policy.readFiles.length
        testProfile = true
      }
      const digest = proposalDigest(proposal)
      const repeatedResult = lastObservation?.invocationSHA256 === digest
        && lastObservation.workspaceRevision === workspaceRevision
        && lastObservation.repeatedResultObserved
      if (repeatedResult) {
        finalOnly = true
        onNoProgressLimit?.()
        semanticEvent(telemetry, 'NO_PROGRESS_DETECTED', toolName, callId, {
          invocation_sha256: digest,
          result_sha256: lastObservation?.resultSHA256 as string,
          status: 'final_only',
        })
        setVisibleTools([])
        return {
          ok: false,
          canContinue: true,
          text: 'The same operation already returned the same result twice without a workspace change. It was not submitted again. Give a concise final response; do not claim unverified success.',
          no_progress: 'final_only',
          remaining_budget: {
            tool_operations: Math.max(0, policy.maxToolOperations - toolCallCount),
            write_operations: Math.max(0, policy.maxWriteOperations - writeOperations),
            repair_attempts: Math.max(0, policy.maxRepairAttempts - repairAttempts),
          },
        }
      }
      if (lastObservation?.invocationSHA256 !== digest
        || lastObservation.workspaceRevision !== workspaceRevision) {
        lastObservation = undefined
      }
      const nextSequence = operationSequence + 1
      if (nextSequence > policy.maxToolOperations) throw new Error('semantic_operation_limit_exceeded')
      if (toolName === 'replace_text') {
        if (writeOperations >= policy.maxWriteOperations) throw new Error('semantic_write_limit_exceeded')
        if (testRuns > 0 && repairAttempts >= policy.maxRepairAttempts) throw new Error('semantic_repair_limit_exceeded')
      }
      semanticEvent(telemetry, 'TOOL_ARGUMENT_VALIDATED', toolName, callId, {
        argument_bytes: argsBytes,
        file_count: pathCount,
      })
      semanticEvent(telemetry, 'TOOL_PROPOSAL_LOWERED', toolName, callId, {
        operation_seq: nextSequence,
        invocation_sha256: digest,
        argument_bytes: argsBytes,
        file_count: pathCount,
        write_operation: toolName === 'replace_text',
      })
      operationSequence = nextSequence
      if (toolName === 'replace_text') {
        writeOperations += 1
        if (testRuns > 0) repairAttempts += 1
      }
      if (testProfile) testRuns += 1
      telemetry.bindToolCall(callId, nextSequence)
      const position = telemetry.position()
      correlation = {
        trialId: telemetry.trialId,
        sessionId: telemetry.sessionId,
        benchmarkTaskId: policy.taskId,
        turn: position.turn,
        step: position.step,
        ...(position.modelCallId ? { modelCallId: position.modelCallId } : {}),
        toolCallId: callId,
        operationSequence: nextSequence,
        toolName,
        invocationSHA256: digest,
      }
    } catch (error) {
      semanticEvent(telemetry, 'TOOL_ARGUMENT_REJECTED', toolName, callId, {
        error_code: error instanceof Error && /^[a-z0-9_]{1,80}$/u.test(error.message)
          ? error.message : 'semantic_tool_rejected',
      })
      setVisibleTools(visibleTools())
      throw error
    }

    let result: KhaosToolResult
    const invocationSHA256 = proposalDigest(proposal)
    try {
      result = await session.submit(proposal, callId, signal, correlation)
    } catch (error) {
      closed = true
      setVisibleTools([])
      semanticEvent(telemetry, 'TOOL_SUBMISSION_FAILED', toolName, callId, {
        operation_seq: operationSequence,
        invocation_sha256: proposalDigest(proposal),
        error_code: error instanceof Error && /^[a-z0-9_]{1,80}$/u.test(error.message)
          ? error.message : 'launcher_submission_failed',
      })
      throw error
    }
    const commitStatus = result.launcherTrace?.commit_status
    if (toolName === 'replace_text' && commitStatus === 'committed') workspaceRevision += 1
    const resultSHA256 = observationDigest(result)
    const sameObservation = lastObservation?.invocationSHA256 === invocationSHA256
      && lastObservation.workspaceRevision === workspaceRevision
      && lastObservation.resultSHA256 === resultSHA256
    const noProgress = sameObservation ? 'recovery_feedback' : undefined
    if (noProgress) {
      semanticEvent(telemetry, 'NO_PROGRESS_DETECTED', toolName, callId, {
        invocation_sha256: invocationSHA256,
        result_sha256: resultSHA256,
        status: noProgress,
      })
    }
    lastObservation = {
      invocationSHA256,
      resultSHA256,
      workspaceRevision,
      repeatedResultObserved: sameObservation,
    }
    telemetry.markLauncherResultReceived(callId, result.text)
    const launcherTrace = result.launcherTrace
    if (launcherTrace) {
      const matchesProposal = launcherTrace.trial_id === telemetry.trialId
        && launcherTrace.dsh_session_id === telemetry.sessionId
        && launcherTrace.benchmark_task_id === policy.taskId
        && launcherTrace.agent_turn_id === correlation?.turn
        && launcherTrace.agent_step_id === correlation?.step
        && launcherTrace.model_call_id === correlation?.modelCallId
        && launcherTrace.tool_call_id === callId
        && launcherTrace.tool_name === toolName
        && launcherTrace.operation_seq === operationSequence
        && launcherTrace.invocation_sha256 === proposalDigest(proposal)
        && launcherTrace.launcher_ok === result.ok
        && launcherTrace.can_continue === result.canContinue
        && launcherTrace.returncode === result.returncode
      if (!matchesProposal) throw new Error('launcher_trace_mismatch')
      telemetry.emit('LAUNCHER_TERMINAL_RESULT_DELIVERED', {
        agent_turn_id: launcherTrace.agent_turn_id,
        agent_step_id: launcherTrace.agent_step_id,
        ...(launcherTrace.model_call_id ? { model_call_id: launcherTrace.model_call_id } : {}),
        tool_call_id: launcherTrace.tool_call_id,
        tool_name: launcherTrace.tool_name,
        operation_seq: launcherTrace.operation_seq,
        invocation_sha256: launcherTrace.invocation_sha256,
        launcher_task_id: launcherTrace.launcher_task_id,
        launcher_request_id: launcherTrace.launcher_request_id,
        launcher_approval_sha256: launcherTrace.launcher_approval_sha256,
        approval_status: launcherTrace.approval_status,
        kernel_result: launcherTrace.kernel_result,
        runner_status: launcherTrace.runner_status,
        commit_status: launcherTrace.commit_status,
        launcher_ok: launcherTrace.launcher_ok,
        can_continue: launcherTrace.can_continue,
        ...(launcherTrace.returncode === undefined ? {} : { returncode: launcherTrace.returncode }),
        result_bytes: bytes(result.text),
        result_sha256: telemetry.resultDigest(result.text),
        launcher_result_sha256: telemetry.launcherResultDigest(callId) as string,
      })
    }
    let effectiveOk = result.ok
    let effectiveCanContinue = result.canContinue
    let testResult: PublicTestVerification | undefined
    if (toolName === 'run_tests') {
      testResult = verifyPublicTestResult(result)
      semanticEvent(telemetry, 'PUBLIC_TEST_RESULT_VERIFIED', toolName, callId, {
        status: testResult.status,
        ...(testResult.tests_run === undefined ? {} : { tests_run: testResult.tests_run }),
        ...(testResult.failures === undefined ? {} : { failures: testResult.failures }),
        ...(testResult.errors === undefined ? {} : { errors: testResult.errors }),
        ...(testResult.skipped === undefined ? {} : { skipped: testResult.skipped }),
        ...(testResult.error_code === undefined ? {} : { error_code: testResult.error_code }),
      })
      if (testResult.status === 'passed') {
        effectiveOk = true
      } else {
        effectiveOk = false
        const recoverableRunnerFailure = testResult.status === 'failed'
          || (testResult.status === 'unverified'
            && testResult.error_code === 'test_summary_missing'
            && Number.isSafeInteger(result.returncode)
            && result.returncode !== 0
            && !result.ok)
        if (!recoverableRunnerFailure) effectiveCanContinue = false
      }
    }
    if (!effectiveCanContinue) {
      closed = true
      session.close()
    }
    if (toolCallCount >= policy.maxToolOperations
      && !(toolName === 'run_tests' && testResult?.status === 'passed')) {
      onToolBudgetExhausted?.()
    }
    setVisibleTools(visibleTools())
    return {
      ok: effectiveOk,
      canContinue: effectiveCanContinue,
      text: result.text,
      ...(result.returncode === undefined ? {} : { returncode: result.returncode }),
      ...(testResult === undefined ? {} : { test_result: testResult }),
      ...(testResult?.status === 'passed' ? {
        public_test_completion_hint: 'The public tests passed. Decide whether more authorized work is useful; if complete, give a final response. This does not verify hidden tests.',
      } : {}),
      ...(noProgress === undefined ? {} : {
        no_progress: noProgress,
        recovery_feedback: 'This identical request returned the same result without a workspace change. Use this result to choose one different useful operation or finish; do not repeat it unchanged.',
      }),
      remaining_budget: {
        tool_operations: Math.max(0, policy.maxToolOperations - toolCallCount),
        write_operations: Math.max(0, policy.maxWriteOperations - writeOperations),
        repair_attempts: Math.max(0, policy.maxRepairAttempts - repairAttempts),
      },
    }
  }

  const plugin = (ctx: Context): void => {
    const disposers = [
      ctx.tools.register(defineTool({
        name: 'read_file',
        description: `Read one exact allowlisted source or public test file. Allowed paths: ${policy.readFiles.join(', ')}.`,
        parameters: { path: { type: 'string', enum: [...policy.readFiles], required: true } },
        output: outputSchema(),
        execute: (args, exec) => execute('read_file', args, String(exec.callId), exec.signal),
      })),
      ctx.tools.register(defineTool({
        name: 'replace_text',
        description: `Replace one exact, unique, non-empty text span in one existing allowlisted source file. Allowed paths: ${policy.writeFiles.join(', ')}.`,
        parameters: {
          path: { type: 'string', enum: [...policy.writeFiles], required: true },
          oldText: { type: 'string', required: true },
          newText: { type: 'string', required: true },
        },
        output: outputSchema(),
        execute: (args, exec) => execute('replace_text', args, String(exec.callId), exec.signal),
      })),
      ctx.tools.register(defineTool({
        name: 'run_tests',
        description: 'Run only the fixed public unittest profile. Hidden acceptance tests are never available to this tool.',
        parameters: { profile: { type: 'string', enum: ['public'], required: true } },
        output: outputSchema(),
        execute: (args, exec) => execute('run_tests', args, String(exec.callId), exec.signal),
      })),
    ]
    setVisibleTools(visibleTools())
    ctx.effect(() => () => {
      closed = true
      session.close()
      setVisibleTools([])
      for (const dispose of disposers.reverse()) dispose()
    })
  }

  return Object.assign(plugin, { inject: ['tools'] as const })
}

export const semanticToolTestSupport = {
  canonicalPythonJSONString,
  proposalDigest,
  readScript: READ_SCRIPT,
  testScript: TEST_SCRIPT,
  verifyPublicTestResult,
  toolNames: TOOL_NAMES,
}
