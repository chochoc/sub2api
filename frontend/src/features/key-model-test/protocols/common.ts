import { limits, TEXT_PROMPT } from '../config'
import { gatewayError, TestError } from '../resultSanitizer'
import { record, str, type NormalizedUsage, type ParsedOutcome } from '../types'
import type { TestRequestSpec } from './types'

export function textRequest(path: string, body: Record<string, unknown>, stream: boolean, headers: Record<string, string> = {}): TestRequestSpec {
  return { path, body, headers, responseMode: stream ? 'sse' : 'json', timeoutMs: limits.textTimeoutMs, maxResponseBytes: limits.textBytes }
}
export const textMessages = () => [{ role: 'user', content: TEXT_PROMPT }]

export function checkError(body: Record<string, unknown>): void {
  if (body.error) {
    const error = record(body.error)
    throw new TestError('protocolError', str(error.code) || str(error.type) || str(error.status) || undefined, undefined, gatewayError(body, 200, '').stopQueue)
  }
}
export function usageOf(raw: unknown, kind: 'openai' | 'anthropic' | 'gemini' = 'openai'): NormalizedUsage | undefined {
  const u = record(raw)
  const result: NormalizedUsage = {}
  const put = (key: keyof NormalizedUsage, value: unknown) => {
    if (typeof value === 'number' && Number.isFinite(value) && value >= 0) result[key] = value
  }
  if (kind === 'gemini') {
    put('inputTokens', u.promptTokenCount); put('outputTokens', u.candidatesTokenCount)
    put('totalTokens', u.totalTokenCount); put('cachedInputTokens', u.cachedContentTokenCount)
  } else {
    put('inputTokens', u.input_tokens ?? u.prompt_tokens)
    put('outputTokens', u.output_tokens ?? u.completion_tokens)
    put('totalTokens', u.total_tokens)
    put('cachedInputTokens', kind === 'anthropic' ? u.cache_read_input_tokens : record(u.input_tokens_details ?? u.prompt_tokens_details).cached_tokens)
  }
  return Object.keys(result).length ? result : undefined
}
export function textOutcome(text: string, complete: boolean, abnormal = '', responseModel?: string, usage?: NormalizedUsage): ParsedOutcome {
  const output = text.slice(0, limits.previewChars)
  if (abnormal && !['length', 'max_tokens', 'MAX_TOKENS', 'incomplete'].includes(abnormal)) {
    return { status: 'failed', summary: 'unexpectedOutput', textPreview: output, partialOutput: !!text, responseModel, usage }
  }
  return {
    status: complete && !!text.trim() && !abnormal ? 'success' : (abnormal || !complete ? 'incomplete' : 'failed'),
    summary: abnormal || !complete ? 'incomplete' : (text.trim() ? 'completed' : 'emptyOutput'),
    textPreview: output, partialOutput: !!text && (!complete || !!abnormal), responseModel, usage
  }
}
