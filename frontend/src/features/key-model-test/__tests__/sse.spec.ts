import { describe, expect, it, vi } from 'vitest'
import { readSSE, readJSON } from '../protocols/sse'
import { signal } from './fixtures'
import { limits } from '../config'

describe('bounded SSE reader', () => {
  it('handles byte splits, UTF-8, BOM, CRLF, comments, multiline data and EOF', async () => {
    const bytes = new TextEncoder().encode('\ufeff: heartbeat\r\nevent: message\r\ndata: 你\r\ndata: 好\r\n\r\ndata: end')
    const body = new ReadableStream({ start(c) { for (const b of bytes) c.enqueue(new Uint8Array([b])); c.close() } })
    const events: unknown[] = []
    await readSSE(new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }), signal(), 2048, event => events.push(event))
    expect(events).toEqual([{ event: 'message', data: '你\n好' }, { event: '', data: 'end' }])
  })
  it('bounds a single unfinished event', async () => {
    const response = new Response(`data: ${'x'.repeat(limits.eventBytes + 1)}`, { headers: { 'Content-Type': 'text/event-stream' } })
    await expect(readSSE(response, signal(), limits.textBytes, () => undefined)).rejects.toThrow('responseLimit')
  })
  it('cancels the reader on a total size limit', async () => {
    const cancel = vi.fn()
    const body = new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode('data: 123456\n\n')) }, cancel })
    await expect(readSSE(new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }), signal(), 4, () => undefined)).rejects.toThrow('responseLimit')
    expect(cancel).toHaveBeenCalled()
  })
  it('aborts an idle stream and releases its lock', async () => {
    const cancel = vi.fn(), controller = new AbortController()
    const body = new ReadableStream({ cancel })
    const pending = readSSE(new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }), controller.signal, 100, () => undefined)
    controller.abort()
    await expect(pending).rejects.toThrow()
    expect(cancel).toHaveBeenCalled(); expect(body.locked).toBe(false)
  })
  it('does not parse HTML as a successful JSON response', async () => {
    await expect(readJSON(new Response('<html>oops</html>', { headers: { 'Content-Type': 'text/html' } }), signal(), 100)).rejects.toThrow('invalidResponse')
  })
})
