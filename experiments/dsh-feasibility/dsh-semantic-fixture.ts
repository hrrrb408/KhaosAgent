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
      const test = JSON.parse(lastToolResult(options.messages)) as { ok?: unknown }
      return test.ok === true
        ? textResponse('The actual public tests passed after the controlled edit.')
        : textResponse('The actual public tests failed; no success is claimed.')
    },
  ]
}
