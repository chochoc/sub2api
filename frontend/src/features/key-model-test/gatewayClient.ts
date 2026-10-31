import { buildGatewayUrl } from '@/api/url'
import { limits } from './config'
import { parseCatalog } from './modelCatalog'
import { gatewayError, sanitize, TestError } from './resultSanitizer'
import { responsesAdapter } from './protocols/responses'
import { chatAdapter } from './protocols/chatCompletions'
import { messagesAdapter } from './protocols/messages'
import { imagesAdapter } from './protocols/images'
import { geminiAdapter } from './protocols/gemini'
import { readJSON } from './protocols/sse'
import type { ProtocolAdapter } from './protocols/types'
import type { ImageSource, ModelTestResult, TestProfile, TestSelection } from './types'

const adapters: Record<TestProfile, ProtocolAdapter> = {
  responses: responsesAdapter, chat_completions: chatAdapter, messages: messagesAdapter,
  gemini_text: geminiAdapter(false), images: imagesAdapter, gemini_image: geminiAdapter(true)
}

function deadline(parent: AbortSignal, timeoutMs: number) {
  const controller = new AbortController()
  let timedOut = false
  const abort = () => controller.abort()
  parent.addEventListener('abort', abort, { once: true })
  if (parent.aborted) abort()
  const timer = setTimeout(() => { timedOut = true; controller.abort() }, timeoutMs)
  return {
    signal: controller.signal, timedOut: () => timedOut,
    dispose: () => { clearTimeout(timer); parent.removeEventListener('abort', abort) }
  }
}

async function send(key: string, path: string, signal: AbortSignal, body?: unknown, extraHeaders: Record<string, string> = {}, stream = false): Promise<Response> {
  // Exact allowlist; model is percent-encoded before interpolation. No caller URL.
  if (!/^\/v1\/(models|responses|chat\/completions|messages|images\/generations)$/.test(path) &&
      !/^\/v1beta\/models\/[^/?#:]+:(generateContent|streamGenerateContent\?alt=sse)$/.test(path)) throw new TestError('invalidEndpoint')
  const headers: Record<string, string> = { Authorization: `Bearer ${key}`, Accept: stream ? 'text/event-stream' : 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (extraHeaders['anthropic-version']) headers['anthropic-version'] = extraHeaders['anthropic-version']
  signal.throwIfAborted()
  const response = await fetch(buildGatewayUrl(path), {
    method: body === undefined ? 'GET' : 'POST', headers, body: body === undefined ? undefined : JSON.stringify(body),
    signal, credentials: 'omit', cache: 'no-store', redirect: 'error'
  })
  return response
}

async function checkHTTP(response: Response, signal: AbortSignal, secret: string): Promise<void> {
  if (response.ok) return
  let body: unknown
  try { body = await readJSON(response, signal, 64 * 1024) } catch { signal.throwIfAborted() }
  throw gatewayError(body, response.status, secret)
}

export async function discoverModels(key: string, signal: AbortSignal, platform?: string) {
  const scope = deadline(signal, limits.catalogTimeoutMs)
  let response: Response | undefined
  try {
    response = await send(key, '/v1/models', scope.signal)
    await checkHTTP(response, scope.signal, key)
    return parseCatalog(await readJSON(response, scope.signal, limits.catalogBytes), platform)
  } catch (error) {
    if (scope.timedOut()) throw new TestError('timeout')
    if (signal.aborted) throw new TestError('cancelled')
    if (error instanceof TestError) throw error
    throw new TestError('networkError', undefined, undefined, true)
  } finally {
    scope.dispose()
    await response?.body?.cancel().catch(() => undefined)
  }
}

export interface TestExecution { result: ModelTestResult; images: ImageSource[]; stopQueue: boolean }

export async function executeTest(key: string, selection: TestSelection, signal: AbortSignal, onProgress: (text: string) => void = () => undefined): Promise<TestExecution> {
  const adapter = adapters[selection.profile]
  const request = adapter.buildRequest(selection.modelId, selection.stream)
  const scope = deadline(signal, request.timeoutMs)
  const start = performance.now()
  const result: ModelTestResult = {
    ...selection, status: 'running', startedAt: new Date().toISOString(), durationMs: 0, summary: 'running', partialOutput: false
  }
  let text = '', lastProgress = -Infinity
  let response: Response | undefined
  let stopQueue = false
  let images: ImageSource[] = []
  try {
    response = await send(key, request.path, scope.signal, request.body, request.headers, request.responseMode === 'sse')
    result.httpStatus = response.status
    result.gatewayRequestId = sanitize(response.headers.get('X-Client-Request-ID') || '', key, 128) || undefined
    await checkHTTP(response, scope.signal, key)
    const contentType = response.headers.get('Content-Type') || ''
    if (request.responseMode === 'sse' && !/^text\/event-stream\b/i.test(contentType)) throw new TestError('invalidResponse')
    if (request.responseMode === 'json' && !/\bapplication\/(?:[\w.+-]*\+)?json\b/i.test(contentType)) throw new TestError('invalidResponse')
    const parsed = await adapter.parseResponse(response, {
      signal: scope.signal, maxResponseBytes: request.maxResponseBytes,
      onText(value) {
        if (scope.signal.aborted) return
        text = sanitize(value, key, limits.previewChars)
        if (text.trim() && result.firstContentMs === undefined) result.firstContentMs = Math.round(performance.now() - start)
        if (performance.now() - lastProgress >= 100) { lastProgress = performance.now(); onProgress(text) }
      }
    })
    scope.signal.throwIfAborted()
    images = parsed.images || []
    Object.assign(result, {
      status: parsed.status, summary: parsed.summary, textPreview: sanitize(parsed.textPreview || text, key, limits.previewChars),
      responseModel: sanitize(parsed.responseModel || '', key, 1024) || undefined,
      usage: parsed.usage, imageCount: images.length || undefined, partialOutput: parsed.partialOutput ?? false,
      errorCode: sanitize(parsed.errorCode || '', key, 100) || undefined
    })
  } catch (error) {
    const known = error instanceof TestError ? error : undefined
    result.status = scope.timedOut() ? 'timeout' : signal.aborted ? 'cancelled' : text && !known ? 'incomplete' : 'failed'
    result.summary = scope.timedOut() ? 'timeout' : signal.aborted ? 'cancelled' : known?.reason || (text ? 'incomplete' : 'networkError')
    result.errorCode = known?.code ? sanitize(known.code, key, 100) : undefined
    result.errorMessage = known?.detail ? sanitize(known.detail, key) : undefined
    result.errorCategory = result.summary
    result.textPreview = text || undefined
    result.partialOutput = !!text
    stopQueue = !!known?.stopQueue || (!known && !scope.timedOut()) || signal.aborted
  } finally {
    result.durationMs = Math.round(performance.now() - start)
    scope.dispose()
    await response?.body?.cancel().catch(() => undefined)
  }
  return { result, images, stopQueue }
}
