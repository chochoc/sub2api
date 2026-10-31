import { limits } from '../config'
import { array, record, str, type NormalizedUsage } from '../types'
import { checkError, textMessages, textOutcome, textRequest, usageOf } from './common'
import { eventJSON, readJSON, readSSE } from './sse'
import type { ProtocolAdapter } from './types'

export const chatAdapter: ProtocolAdapter = {
  buildRequest: (model, stream) => textRequest('/v1/chat/completions', { model, messages: textMessages(), stream }, stream),
  async parseResponse(response, context) {
    let text = '', finish = '', model = '', abnormal = '', done = false
    let usage: NormalizedUsage | undefined
    const accept = (raw: unknown, streaming: boolean) => {
      const body = record(raw); checkError(body)
      model = str(body.model) || model; usage = usageOf(body.usage) || usage
      const choices = array(body.choices)
      if (choices.length > 1) abnormal = 'unexpected'
      for (const rawChoice of choices) {
        const choice = record(rawChoice)
        const message = record(streaming ? choice.delta : choice.message)
        if (message.refusal || array(message.tool_calls).length || message.function_call || message.audio || (message.content != null && typeof message.content !== 'string')) abnormal = 'unexpected'
        text = (text + str(message.content)).slice(0, limits.previewChars)
        finish = str(choice.finish_reason) || finish
        context.onText(text)
      }
    }
    const streaming = /^text\/event-stream\b/i.test(response.headers.get('Content-Type') || '')
    if (streaming) await readSSE(response, context.signal, context.maxResponseBytes, event => {
      if (event.data === '[DONE]') { done = true; return }
      accept(eventJSON(event.data), true)
    })
    else { accept(await readJSON(response, context.signal, context.maxResponseBytes), false); done = true }
    return textOutcome(text, done && finish === 'stop', abnormal || (finish !== 'stop' ? finish : ''), model, usage)
  }
}
