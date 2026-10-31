import { IMAGE_PROMPT, limits } from '../config'
import { validImage } from '../imagePreview'
import { array, record, str, type ImageSource, type ParsedOutcome } from '../types'
import { checkError, usageOf } from './common'
import { readJSON } from './sse'
import type { ProtocolAdapter } from './types'

export function imageOutcome(images: ImageSource[]): ParsedOutcome {
  const valid = images.filter(validImage)
  return { status: valid.length ? 'success' : 'failed', summary: valid.length ? 'imageCompleted' : 'noImage', images: valid }
}

export const imagesAdapter: ProtocolAdapter = {
  buildRequest: model => ({ path: '/v1/images/generations', headers: {}, body: { model, prompt: IMAGE_PROMPT, n: 1 }, responseMode: 'json', timeoutMs: limits.imageTimeoutMs, maxResponseBytes: limits.imageResponseBytes }),
  async parseResponse(response, context) {
    const body = record(await readJSON(response, context.signal, context.maxResponseBytes)); checkError(body)
    const images = array(body.data).map(raw => {
      const item = record(raw)
      return { base64: str(item.b64_json) || undefined, url: str(item.url) || undefined, mime: str(item.mime_type) || undefined }
    })
    return { ...imageOutcome(images), usage: usageOf(body.usage), responseModel: str(body.model) }
  }
}
