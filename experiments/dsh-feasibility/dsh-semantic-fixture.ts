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

export type SemanticResultFixtureCase =
  | 'task-a-failure'
  | 'pass'
  | 'zero-tests'
  | 'fake-success'
  | 'import-error'
  | 'slow-cancel'

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
