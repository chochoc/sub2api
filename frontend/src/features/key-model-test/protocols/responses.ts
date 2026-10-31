import { limits, TEXT_PROMPT } from '../config'
import { TestError } from '../resultSanitizer'
import { array, record, str } from '../types'
import { checkError, textOutcome, textRequest, usageOf } from './common'
import { eventJSON, readJSON, readSSE } from './sse'
import type { ProtocolAdapter } from './types'

function extract(body: Record<string, unknown>): { text: string; abnormal: string } {
  let text = ''
  let abnormal = ''
  for (const raw of array(body.output)) {
    const item = record(raw)
    if (item.type === 'reasoning') continue
    if (item.type !== 'message') { abnormal = 'unexpected'; continue }
    for (const part of array(item.content)) {
      const content = record(part)
      if (content.type === 'output_text') text += str(content.text)
      else abnormal = 'unexpected'
    }
  }
  return { text: text.slice(0, limits.previewChars), abnormal }
}

export const responsesAdapter: ProtocolAdapter = {
  buildRequest: (model, stream) => textRequest('/v1/responses', {
    model, instructions: 'This is a connectivity test. Reply briefly.',
    input: [{ role: 'user', content: [{ type: 'input_text', text: TEXT_PROMPT }] }], store: false, stream
  }, stream),
  async parseResponse(response, context) {
    if (!/^text\/event-stream\b/i.test(response.headers.get('Content-Type') || '')) {
      const body = record(await readJSON(response, context.signal, context.maxResponseBytes))
      checkError(body)
      const output = extract(body)
      context.onText(output.text)
      return textOutcome(output.text, body.status === 'completed', output.abnormal || (body.status === 'incomplete' ? 'incomplete' : body.status === 'failed' ? 'failed' : ''), str(body.model), usageOf(body.usage))
    }
    let text = '', abnormal = '', complete = false, model = ''
    let usage
    await readSSE(response, context.signal, context.maxResponseBytes, event => {
      // The gateway's Chat-to-Responses conversion appends this optional sentinel.
      // It does not substitute for response.completed and its normal status.
      if (event.data.trim() === '[DONE]') return
      const body = record(eventJSON(event.data))
      checkError(body)
      const type = str(body.type) || event.event
      if (type === 'error') throw new TestError('protocolError')
      if (type === 'response.output_text.delta') {
        text = (text + str(body.delta)).slice(0, limits.previewChars); context.onText(text)
      }
      if (/refusal|function_call|image_generation|audio/.test(type)) abnormal = 'unexpected'
      if (type === 'response.output_item.added' && !['message', 'reasoning'].includes(str(record(body.item).type))) abnormal = 'unexpected'
      if (['response.completed', 'response.incomplete', 'response.failed'].includes(type)) {
        const result = record(body.response)
        checkError(result)
        const output = extract(result)
        if (output.text) { text = output.text; context.onText(text) }
        model = str(result.model); usage = usageOf(result.usage)
        complete = type === 'response.completed' && result.status === 'completed'
        abnormal = abnormal || output.abnormal || (type === 'response.incomplete' ? 'incomplete' : type === 'response.failed' ? 'failed' : '')
      }
    })
    return textOutcome(text, complete, abnormal, model, usage)
  }
}
