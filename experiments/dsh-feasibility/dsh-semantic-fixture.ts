import { textResponse, toolCallResponse } from '../mock-adapter.ts'
import { lastToolResult, lastToolResultText } from './dsh-tool-result.ts'

export function semanticCodingResponses() {
  return [
    toolCallResponse('phase31-read-fee', 'read_file', { path: 'fee.py' }),
    options => {
      if (!lastToolResultText(options.messages).includes('return amount * rate')) {
        return textResponse('The actual fee.py read result did not contain the expected function.')
      }
      return toolCallResponse('phase31-read-tests', 'read_file', { path: 'test_public.py' })
    },
    options => {
      if (!lastToolResultText(options.messages).includes('test_fee_is_rounded_to_cents')) {
        return textResponse('The actual public test read result was incomplete.')
      }
      return toolCallResponse('phase31-edit-fee', 'replace_text', {
        path: 'fee.py',
        oldText: 'def calculate_fee(amount, rate=0.025):\n    return amount * rate\n',
        newText: 'def calculate_fee(amount, rate=0.025):\n    return round(amount * rate, 2)\n',
      })
    },
    options => {
      const edit = JSON.parse(lastToolResult(options.messages)) as { ok?: unknown }
      if (edit.ok !== true) return textResponse('The actual scoped edit did not complete successfully.')
      return toolCallResponse('phase322-read-fee-after-edit', 'read_file', { path: 'fee.py' })
    },
    options => {
      if (!lastToolResultText(options.messages).includes('return round(amount * rate, 2)')) {
        return textResponse('The actual post-edit fee.py read did not contain the approved edit.')
      }
      return toolCallResponse('phase31-test-fee', 'run_tests', { profile: 'public' })
    },
    options => {
      const test = JSON.parse(lastToolResult(options.messages)) as {
        ok?: unknown
        public_test_completion_hint?: unknown
      }
      return test.ok === true && typeof test.public_test_completion_hint === 'string'
        ? textResponse('The actual public tests passed after the controlled edit.')
        : textResponse('The actual public tests failed; no success is claimed.')
    },
  ]
}

export function semanticCrossWorkspaceReadResponses() {
  return [
    toolCallResponse('phase322-cross-workspace-read', 'read_file', { path: 'fee.py' }),
    options => {
      return crossWorkspaceResultResponse(options.messages)
    },
  ]
}

export function semanticCrossWorkspaceAfterReadResponses() {
  return [
    toolCallResponse('phase322-workspace-b-positive-read', 'read_file', { path: 'fee.py' }),
    options => lastToolResultText(options.messages).includes('return amount * rate')
      ? toolCallResponse('phase322-workspace-b-cross-read', 'read_file', { path: 'test_public.py' })
      : textResponse('KHAOS_DSH_CROSS_WORKSPACE_RESULT positive-not-proven'),
    options => crossWorkspaceResultResponse(options.messages),
  ]
}

function crossWorkspaceResultResponse(messages: Parameters<typeof lastToolResult>[0]) {
  const result = JSON.parse(lastToolResult(messages)) as {
    ok?: unknown
    returncode?: unknown
    text?: unknown
  }
  const text = typeof result.text === 'string' ? result.text : ''
  const leaked = text.includes('GATE_B0_CROSS_WORKSPACE_CANARY:')
  const kernelRejected = !result.ok && text.includes('workspace_rejected')
  const sandboxDiagnostic = /operation not permitted/iu.test(text)
    ? 'operation_not_permitted'
    : /permission denied/iu.test(text) ? 'permission_denied' : undefined
  const sandboxDenied = !result.ok && result.returncode === 1 && sandboxDiagnostic !== undefined
  const layer = kernelRejected
    ? 'kernel_workspace_rejected'
    : sandboxDenied ? 'os_sandbox_denied' : undefined
  const diagnostic = kernelRejected ? 'workspace_rejected' : sandboxDiagnostic
  if (leaked) return textResponse('KHAOS_DSH_CROSS_WORKSPACE_RESULT canary-disclosed')
  return layer
    ? textResponse(`KHAOS_DSH_CROSS_WORKSPACE_RESULT denied; layer=${layer}; observed=${diagnostic}`)
    : textResponse('KHAOS_DSH_CROSS_WORKSPACE_RESULT not-proven')
}

export type SemanticLoopFixtureCase =
  | 'coding'
  | 'repair'
  | 'repeated-read'
  | 'budget-exhaustion'
  | 'cross-workspace-read'
  | 'cross-workspace-after-read'

export type SemanticResultFixtureCase =
  | 'task-a-failure'
  | 'pass'
  | 'zero-tests'
  | 'fake-success'
  | 'import-error'
  | 'slow-cancel'

export type SemanticFixtureCase = SemanticLoopFixtureCase | SemanticResultFixtureCase

const RESULT_FIXTURE_CASES: readonly SemanticResultFixtureCase[] = [
  'task-a-failure', 'pass', 'zero-tests', 'fake-success', 'import-error', 'slow-cancel',
]
const LOOP_FIXTURE_CASES: readonly SemanticLoopFixtureCase[] = [
  'coding', 'repair', 'repeated-read', 'budget-exhaustion', 'cross-workspace-read',
  'cross-workspace-after-read',
]

export function isSemanticFixtureCase(value: unknown): value is SemanticFixtureCase {
  return typeof value === 'string' && [
    ...RESULT_FIXTURE_CASES, ...LOOP_FIXTURE_CASES,
  ].includes(value as SemanticFixtureCase)
}

export function isSemanticResultFixtureCase(
  value: SemanticFixtureCase | undefined,
): value is SemanticResultFixtureCase {
  return value !== undefined && RESULT_FIXTURE_CASES.includes(value as SemanticResultFixtureCase)
}

function semanticRepairResponses() {
  return [
    toolCallResponse('phase322-repair-test-before', 'run_tests', { profile: 'public' }),
    options => {
      const result = JSON.parse(lastToolResult(options.messages)) as {
        ok?: unknown
        returncode?: unknown
        test_result?: { status?: unknown }
      }
      return result.ok === false && result.returncode === 1 && result.test_result?.status === 'failed'
        ? toolCallResponse('phase322-repair-read-fee', 'read_file', { path: 'fee.py' })
        : textResponse('The initial public test failure was not observed; no repair is claimed.')
    },
    options => lastToolResultText(options.messages).includes('return amount * rate')
      ? toolCallResponse('phase322-repair-edit-fee', 'replace_text', {
        path: 'fee.py',
        oldText: 'def calculate_fee(amount, rate=0.025):\n    return amount * rate\n',
        newText: 'def calculate_fee(amount, rate=0.025):\n    return round(amount * rate, 2)\n',
      })
      : textResponse('The source read did not match the failing implementation; no repair is claimed.'),
    options => {
      const edit = JSON.parse(lastToolResult(options.messages)) as { ok?: unknown }
      return edit.ok === true
        ? toolCallResponse('phase322-repair-test-after', 'run_tests', { profile: 'public' })
        : textResponse('The controlled edit did not complete; no test pass is claimed.')
    },
    options => {
      const result = JSON.parse(lastToolResult(options.messages)) as {
        ok?: unknown
        test_result?: { status?: unknown }
      }
      return result.ok === true && result.test_result?.status === 'passed'
        ? textResponse('The initial public test failure was repaired and the public tests passed.')
        : textResponse('The repaired public tests did not pass; no success is claimed.')
    },
  ]
}

function repeatedReadResponses() {
  return [
    toolCallResponse('phase322-repeat-read-1', 'read_file', { path: 'fee.py' }),
    options => lastToolResultText(options.messages).includes('return amount * rate')
      ? toolCallResponse('phase322-repeat-read-2', 'read_file', { path: 'fee.py' })
      : textResponse('The first source observation was unexpected; task remains incomplete.'),
    options => {
      const result = JSON.parse(lastToolResult(options.messages)) as { no_progress?: unknown }
      return result.no_progress === 'recovery_feedback'
        ? toolCallResponse('phase322-repeat-read-3', 'read_file', { path: 'fee.py' })
        : textResponse('The repeated observation did not produce recovery feedback; task remains incomplete.')
    },
    options => {
      const result = JSON.parse(lastToolResult(options.messages)) as { no_progress?: unknown }
      return result.no_progress === 'final_only'
        ? textResponse('Repeated identical observations did not verify the coding task; it remains incomplete.')
        : textResponse('The repeated observation was not closed safely; task remains incomplete.')
    },
  ]
}

function budgetExhaustionResponses() {
  return [
    toolCallResponse('phase322-budget-read', 'read_file', { path: 'fee.py' }),
    options => {
      const result = JSON.parse(lastToolResult(options.messages)) as {
        remaining_budget?: { tool_operations?: unknown }
      }
      return result.remaining_budget?.tool_operations === 0
        ? textResponse('The tool-operation budget is exhausted before verification; task remains incomplete.')
        : textResponse('The operation budget was not exhausted; no completion is claimed.')
    },
  ]
}

export function semanticFixtureResponses(testCase: SemanticFixtureCase) {
  if (isSemanticResultFixtureCase(testCase)) return semanticTestResultResponses(testCase)
  switch (testCase) {
    case 'repair': return semanticRepairResponses()
    case 'repeated-read': return repeatedReadResponses()
    case 'budget-exhaustion': return budgetExhaustionResponses()
    case 'cross-workspace-read': return semanticCrossWorkspaceReadResponses()
    case 'cross-workspace-after-read': return semanticCrossWorkspaceAfterReadResponses()
    case 'coding': return semanticCodingResponses()
  }
}

export function semanticTestResultResponses(testCase: SemanticResultFixtureCase) {
  return [
    toolCallResponse(`phase321-run-${testCase}`, 'run_tests', { profile: 'public' }),
    options => {
      const value = JSON.parse(lastToolResult(options.messages)) as {
        ok?: unknown
        canContinue?: unknown
        returncode?: unknown
        test_result?: {
          status?: unknown
          tests_run?: unknown
          failures?: unknown
          errors?: unknown
          skipped?: unknown
          error_code?: unknown
        }
      }
      const test = value.test_result ?? {}
      return textResponse(`KHAOS_DSH_TEST_RESULT_OBSERVED ${JSON.stringify({
        test_case: testCase,
        ok: value.ok === true,
        can_continue: value.canContinue === true,
        returncode: Number.isSafeInteger(value.returncode) ? value.returncode : null,
        status: typeof test.status === 'string' ? test.status : 'missing',
        tests_run: Number.isSafeInteger(test.tests_run) ? test.tests_run : null,
        failures: Number.isSafeInteger(test.failures) ? test.failures : null,
        errors: Number.isSafeInteger(test.errors) ? test.errors : null,
        skipped: Number.isSafeInteger(test.skipped) ? test.skipped : null,
        error_code: typeof test.error_code === 'string' ? test.error_code : null,
      })}`)
    },
  ]
}
