import { limits } from '../config'
import { array, record, str, type NormalizedUsage } from '../types'
import { checkError, textMessages, textOutcome, textRequest, usageOf } from './common'
import { eventJSON, readJSON, readSSE } from './sse'
import type { ProtocolAdapter } from './types'

export const messagesAdapter: ProtocolAdapter = {
  buildRequest: (model, stream) => textRequest('/v1/messages', { model, max_tokens: 256, messages: textMessages(), stream }, stream, { 'anthropic-version': '2023-06-01' }),
  async parseResponse(response, context) {
    let text = '', finish = '', abnormal = '', model = '', done = false
    let usage: NormalizedUsage | undefined
    const mergeUsage = (raw: unknown) => { const next = usageOf(raw, 'anthropic'); if (next) usage = { ...usage, ...next } }
    const block = (raw: unknown) => {
      const item = record(raw)
      if (item.type === 'text') text = (text + str(item.text)).slice(0, limits.previewChars)
      else if (!['thinking', 'redacted_thinking'].includes(str(item.type))) abnormal = 'unexpected'
      context.onText(text)
    }
    if (/^text\/event-stream\b/i.test(response.headers.get('Content-Type') || '')) {
      await readSSE(response, context.signal, context.maxResponseBytes, event => {
        const body = record(eventJSON(event.data)); checkError(body)
        const type = str(body.type) || event.event
        if (type === 'message_start') {
          const message = record(body.message); model = str(message.model); mergeUsage(message.usage)
        } else if (type === 'content_block_start') block(body.content_block)
        else if (type === 'content_block_delta') {
          const delta = record(body.delta)
          if (delta.type === 'text_delta') { text = (text + str(delta.text)).slice(0, limits.previewChars); context.onText(text) }
          else if (!['thinking_delta', 'signature_delta'].includes(str(delta.type))) abnormal = 'unexpected'
        } else if (type === 'message_delta') { finish = str(record(body.delta).stop_reason); mergeUsage(body.usage) }
        else if (type === 'message_stop') done = true
      })
    } else {
      const body = record(await readJSON(response, context.signal, context.maxResponseBytes)); checkError(body)
      array(body.content).forEach(block); model = str(body.model); finish = str(body.stop_reason); mergeUsage(body.usage); done = true
    }
    const normal = finish === 'end_turn' || finish === 'stop_sequence'
    return textOutcome(text, done && normal, abnormal || (!normal ? finish : ''), model, usage)
  }
}
