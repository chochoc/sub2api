import { IMAGE_PROMPT, TEXT_PROMPT, limits } from '../config'
import { array, record, str, type ImageSource, type NormalizedUsage } from '../types'
import { checkError, textOutcome, usageOf } from './common'
import { imageOutcome } from './images'
import { eventJSON, readJSON, readSSE } from './sse'
import type { ProtocolAdapter } from './types'

export function geminiAdapter(image: boolean): ProtocolAdapter {
  return {
    buildRequest(model, stream) {
      const streaming = stream && !image
      const action = streaming ? 'streamGenerateContent?alt=sse' : 'generateContent'
      return {
        path: `/v1beta/models/${encodeURIComponent(model)}:${action}`, headers: {},
        body: { contents: [{ role: 'user', parts: [{ text: image ? IMAGE_PROMPT : TEXT_PROMPT }] }],
          ...(image ? { generationConfig: { responseModalities: ['TEXT', 'IMAGE'], imageConfig: { aspectRatio: '1:1' } } } : {}) },
        responseMode: streaming ? 'sse' : 'json', timeoutMs: image ? limits.imageTimeoutMs : limits.textTimeoutMs,
        maxResponseBytes: image ? limits.imageResponseBytes : limits.textBytes
      }
    },
    async parseResponse(response, context) {
      let text = '', finish = '', abnormal = '', model = ''
      let usage: NormalizedUsage | undefined
      const images: ImageSource[] = []
      const accept = (raw: unknown) => {
        const body = record(raw); checkError(body)
        if (record(body.promptFeedback).blockReason) abnormal = 'blocked'
        model = str(body.modelVersion) || model; usage = usageOf(body.usageMetadata, 'gemini') || usage
        const candidates = array(body.candidates)
        if (!image && candidates.length > 1) abnormal = 'unexpected'
        for (const rawCandidate of candidates) {
          const candidate = record(rawCandidate)
          finish = str(candidate.finishReason) || finish
          for (const rawPart of array(record(candidate.content).parts)) {
            const part = record(rawPart)
            if (part.thought === true) continue
            if (typeof part.text === 'string') { text = (text + part.text).slice(0, limits.previewChars); context.onText(text) }
            else if (image && (part.inlineData || part.inline_data)) {
              const data = record(part.inlineData || part.inline_data)
              images.push({ base64: str(data.data), mime: str(data.mimeType || data.mime_type) })
            } else abnormal = 'unexpected'
          }
        }
      }
      if (!image && /^text\/event-stream\b/i.test(response.headers.get('Content-Type') || '')) {
        await readSSE(response, context.signal, context.maxResponseBytes, event => accept(eventJSON(event.data)))
      } else accept(await readJSON(response, context.signal, context.maxResponseBytes))
      if (image) {
        if (abnormal || (finish && finish !== 'STOP')) return { status: 'failed', summary: 'unexpectedOutput' }
        return { ...imageOutcome(images), responseModel: model, usage }
      }
      return textOutcome(text, finish === 'STOP', abnormal || (finish !== 'STOP' ? finish : ''), model, usage)
    }
  }
}
