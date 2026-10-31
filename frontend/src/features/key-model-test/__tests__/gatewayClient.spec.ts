import { afterEach, describe, expect, it, vi } from 'vitest'
import { discoverModels, executeTest } from '../gatewayClient'
import { limits } from '../config'
import { diagnosticSummary, sanitize } from '../resultSanitizer'
import { json, responsesOK, signal, sse } from './fixtures'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

describe('key-authenticated gateway client', () => {
  it('uses only the selected key and no cookies, JWT, query key or redirects', async () => {
    localStorage.setItem('auth_token', 'panel-jwt')
    const fetch = vi.fn().mockResolvedValue(json({ data: [{ id: 'gpt-6' }] }))
    vi.stubGlobal('fetch', fetch)
    await discoverModels('sk-selected', signal())
    const [url, init] = fetch.mock.calls[0]
    expect(url).toMatch(/\/v1\/models$/); expect(url).not.toContain('key='); expect(url).not.toContain('client_version')
    expect(init).toMatchObject({ method: 'GET', credentials: 'omit', redirect: 'error', cache: 'no-store', headers: { Authorization: 'Bearer sk-selected' } })
    expect(JSON.stringify(init)).not.toContain('panel-jwt')
    localStorage.removeItem('auth_token')
  })
  it('executes once, preserves correlation and zero usage, does not retry', async () => {
    const fetch = vi.fn().mockResolvedValue(json(responsesOK)); vi.stubGlobal('fetch', fetch)
    const value = await executeTest('sk-selected', { modelId: 'gpt-6', profile: 'responses', stream: false }, signal())
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(value.result).toMatchObject({ status: 'success', gatewayRequestId: 'request-123', usage: { cachedInputTokens: 0 } })
  })
  it.each([401, 402, 403, 429])('stops batch on status %d and redacts diagnostics', async status => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ error: { code: 'ACCESS_DENIED', message: 'Bearer sk-selected https://upstream.test/path?key=hidden' } }, status)))
    const result = await executeTest('sk-selected', { modelId: 'alias', profile: 'responses', stream: false }, signal())
    expect(result.stopQueue).toBe(true); expect(result.result.status).toBe('failed')
    expect(JSON.stringify(result)).not.toContain('sk-selected'); expect(JSON.stringify(result)).not.toContain('hidden')
  })
  it('continues after a model-specific rejection or 503', async () => {
    for (const response of [json({ error: { code: 'model_not_allowed' } }, 403), json({ error: { message: 'Unavailable' } }, 503)]) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
      expect((await executeTest('test', { modelId: 'alias', profile: 'responses', stream: false }, signal())).stopQueue).toBe(false)
    }
  })
  it('retains partial output on connection failure and stops the queue', async () => {
    let controller: ReadableStreamDefaultController<Uint8Array>
    const body = new ReadableStream<Uint8Array>({ start(c) { controller = c; c.enqueue(new TextEncoder().encode('data: {"type":"response.output_text.delta","delta":"partial"}\n\n')) } })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, { headers: { 'Content-Type': 'text/event-stream' } })))
    const progress = vi.fn(() => controller.error(new TypeError('connection reset')))
    const result = await executeTest('test', { modelId: 'gpt-6', profile: 'responses', stream: true }, signal(), progress)
    expect(result).toMatchObject({ stopQueue: true, result: { status: 'incomplete', partialOutput: true, textPreview: 'partial' } })
  })
  it('uses an absolute timeout even on an idle stream and releases resources', async () => {
    vi.useFakeTimers()
    const cancel = vi.fn()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new ReadableStream({ cancel }), { headers: { 'Content-Type': 'text/event-stream' } })))
    const pending = executeTest('test', { modelId: 'gpt-6', profile: 'responses', stream: true }, signal())
    await vi.advanceTimersByTimeAsync(limits.textTimeoutMs)
    expect((await pending).result.status).toBe('timeout'); expect(cancel).toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
  })
  it('rejects JSON instead of the requested SSE, and errors in a 200 stream', async () => {
    for (const response of [json(responsesOK), sse([{ error: { type: 'overloaded_error' } }])]) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
      expect((await executeTest('test', { modelId: 'gpt-6', profile: 'responses', stream: true }, signal())).result.status).toBe('failed')
    }
  })
  it('keeps diagnostics to a safe whitelist', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(responsesOK)))
    const { result } = await executeTest('selected', { modelId: 'gpt-6', profile: 'responses', stream: false }, signal())
    result.textPreview = 'private reply'; result.errorMessage = 'private error'
    const output = diagnosticSummary(result)
    expect(output).not.toContain('private'); expect(output).not.toContain('textPreview')
    expect(sanitize('api_key="private" https://user:password@example.test/a?token=secret Bearer abc')).not.toMatch(/private|password|secret|abc/)
  })
})
