import { limits } from '../config'
import { TestError } from '../resultSanitizer'

export async function readChunks(response: Response, signal: AbortSignal, maxBytes: number, consume: (text: string) => void): Promise<void> {
  if (!response.body) throw new TestError('invalidResponse')
  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8', { fatal: true })
  let total = 0
  const cancel = () => { void reader.cancel().catch(() => undefined) }
  signal.addEventListener('abort', cancel, { once: true })
  try {
    signal.throwIfAborted()
    while (true) {
      const { done, value } = await reader.read()
      signal.throwIfAborted()
      if (done) break
      total += value.byteLength
      if (total > maxBytes) throw new TestError('responseLimit')
      consume(decoder.decode(value, { stream: true }))
    }
    consume(decoder.decode())
  } finally {
    signal.removeEventListener('abort', cancel)
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}

export async function readJSON(response: Response, signal: AbortSignal, maxBytes: number): Promise<unknown> {
  if (!/\bapplication\/(?:[\w.+-]*\+)?json\b/i.test(response.headers.get('Content-Type') || '')) throw new TestError('invalidResponse')
  let text = ''
  await readChunks(response, signal, maxBytes, chunk => { text += chunk })
  try { return JSON.parse(text) as unknown } catch { throw new TestError('invalidResponse') }
}

export interface SSEEvent { event: string; data: string }

export async function readSSE(response: Response, signal: AbortSignal, maxBytes: number, consume: (event: SSEEvent) => void): Promise<void> {
  if (!/^text\/event-stream\b/i.test(response.headers.get('Content-Type') || '')) throw new TestError('invalidResponse')
  let buffer = ''
  let event = ''
  let data: string[] = []
  let eventBytes = 0
  const encoder = new TextEncoder()
  const dispatch = () => {
    if (data.length) consume({ event, data: data.join('\n') })
    event = ''; data = []; eventBytes = 0
  }
  const line = (raw: string) => {
    if (!raw) { dispatch(); return }
    if (raw.startsWith(':')) return
    eventBytes += encoder.encode(raw).length
    if (eventBytes > limits.eventBytes) throw new TestError('responseLimit')
    const colon = raw.indexOf(':')
    const field = colon < 0 ? raw : raw.slice(0, colon)
    const value = colon < 0 ? '' : raw.slice(colon + 1).replace(/^ /, '')
    if (field === 'event') event = value
    if (field === 'data') data.push(value)
  }
  await readChunks(response, signal, maxBytes, chunk => {
    buffer += chunk
    let end: number
    while ((end = buffer.indexOf('\n')) >= 0) {
      line(buffer.slice(0, end).replace(/\r$/, ''))
      buffer = buffer.slice(end + 1)
    }
    if (encoder.encode(buffer).length > limits.eventBytes) throw new TestError('responseLimit')
  })
  if (buffer) line(buffer.replace(/\r$/, ''))
  dispatch()
}

export function eventJSON(data: string): unknown {
  try { return JSON.parse(data) as unknown } catch { throw new TestError('invalidResponse') }
}
