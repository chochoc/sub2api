import { limits } from './config'
import { record, str, type ModelTestResult } from './types'

export class TestError extends Error {
  constructor(public readonly reason: string, public readonly code?: string, public readonly status?: number, public readonly stopQueue = false, public readonly detail?: string) {
    super(reason)
    this.name = 'KeyModelTestError'
  }
}

export function sanitize(value: string, secret = '', max: number = limits.errorChars): string {
  let text = secret ? value.split(secret).join('[redacted]') : value
  text = text
    .replace(/https?:\/\/[^\s<>"']+/gi, '[url]')
    .replace(/\b(?:Bearer\s+|sk-|sess-|adm_sc_)[^\s,"'<>]+/gi, '[redacted]')
    .replace(/\b(?:authorization|cookie|api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\b["']?\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\s,;]+)/gi, '[redacted]')
    .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, '[redacted]')
  text = Array.from(text).filter(char => { const code = char.charCodeAt(0); return code >= 32 && code !== 127 || [9, 10, 13].includes(code) }).join('')
  return text.slice(0, max)
}

export function gatewayError(body: unknown, status: number, secret: string): TestError {
  const root = record(body)
  const error = record(root.error)
  const code = sanitize(str(error.code) || str(error.type) || str(error.status) || str(root.code), secret, 100)
  const detail = sanitize(str(error.message) || str(root.message), secret)
  const modelOnly = /^(model_not_found|model_not_allowed|unsupported_model|unsupported_endpoint)$/i.test(code)
  const stop = status === 401 || status === 402 || status === 429 || (status === 403 && !modelOnly) || /API_KEY_|SUBSCRIPTION_|INSUFFICIENT_BALANCE|ACCESS_DENIED|USER_INACTIVE/.test(code)
  return new TestError('gatewayError', code || undefined, status, stop, detail || undefined)
}

export function diagnosticSummary(result: ModelTestResult): string {
  // Deliberate whitelist: no reply, upstream message, image URL, or request object.
  const { modelId, profile, stream, status, startedAt, durationMs, firstContentMs, httpStatus, gatewayRequestId, responseModel, usage, imageCount, errorCode } = result
  return JSON.stringify({ modelId, profile, stream, status, startedAt, durationMs, firstContentMs, httpStatus, gatewayRequestId, responseModel, usage, imageCount, errorCode }, null, 2)
}
