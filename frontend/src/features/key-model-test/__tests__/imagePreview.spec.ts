import { afterEach, describe, expect, it, vi } from 'vitest'
import { createPreviewStore, decodeImage, safeImageURL } from '../imagePreview'
import { png } from './fixtures'

afterEach(() => vi.restoreAllMocks())

describe('bounded image previews', () => {
  it('accepts PNG signatures and rejects HTML, SVG, malformed base64 and mismatched MIME', () => {
    expect(decodeImage({ base64: png })?.mime).toBe('image/png')
    expect(decodeImage({ base64: png, mime: 'image/jpeg' })).toBeNull()
    expect(decodeImage({ base64: btoa('<svg/>'), mime: 'image/svg+xml' })).toBeNull()
    expect(decodeImage({ base64: 'not-base64' })).toBeNull()
    expect(decodeImage({ base64: btoa('<html>') })).toBeNull()
  })
  it.each(['http://example.test/a', 'javascript:alert(1)', 'data:image/svg+xml,abc', 'https://user:password@example.test/a'])('rejects unsafe URL %s', url => expect(safeImageURL(url)).toBeNull())
  it('does not fetch remote URLs or attach credentials', () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
    const store = createPreviewStore()
    const id = store.add({ url: 'https://images.example.test/result.png' })!
    expect(store.previews.value[id]).toBe('https://images.example.test/result.png')
    expect(fetch).not.toHaveBeenCalled(); store.clear()
  })
  it('evicts old previews and revokes object URLs on replacement and close', () => {
    let id = 0
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => `blob:${++id}`) })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
    const store = createPreviewStore()
    const first = store.add({ base64: png })!
    store.add({ base64: png }); store.add({ base64: png }); store.add({ base64: png })
    expect(store.previews.value[first]).toBeUndefined()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:1')
    expect(Object.keys(store.previews.value)).toHaveLength(3)
    store.clear(); expect(URL.revokeObjectURL).toHaveBeenCalledTimes(4)
    expect(Object.keys(store.previews.value)).toHaveLength(0)
  })
})
