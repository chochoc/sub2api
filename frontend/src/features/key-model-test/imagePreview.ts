import { shallowRef } from 'vue'
import { limits } from './config'
import type { ImageSource } from './types'

export function safeImageURL(raw: string): string | null {
  try {
    const url = new URL(raw)
    if (url.protocol !== 'https:' || url.username || url.password) return null
    return url.href
  } catch { return null }
}

export function decodeImage(source: ImageSource): { bytes: Uint8Array; mime: string } | null {
  if (!source.base64 || source.base64.length > Math.ceil(limits.imageBytes / 3) * 4 || !/^[A-Za-z0-9+/]*={0,2}$/.test(source.base64) || source.base64.length % 4 !== 0) return null
  try {
    const binary = atob(source.base64)
    if (!binary.length || binary.length > limits.imageBytes) return null
    const bytes = Uint8Array.from(binary, c => c.charCodeAt(0))
    const starts = (...prefix: number[]) => prefix.every((b, i) => bytes[i] === b)
    let mime = ''
    if (starts(137, 80, 78, 71, 13, 10, 26, 10)) mime = 'image/png'
    else if (starts(255, 216, 255)) mime = 'image/jpeg'
    else if (starts(82, 73, 70, 70) && bytes[8] === 87 && bytes[9] === 69 && bytes[10] === 66 && bytes[11] === 80) mime = 'image/webp'
    if (!mime || (source.mime && source.mime !== mime)) return null
    return { bytes, mime }
  } catch { return null }
}

export function validImage(source: ImageSource): boolean {
  return source.base64 ? !!decodeImage(source) : !!(source.url && safeImageURL(source.url))
}

export function createPreviewStore() {
  const previews = shallowRef<Record<string, string>>({})
  const entries = new Map<string, { url: string; bytes: number; blob: boolean }>()
  let sequence = 0
  const publish = () => { previews.value = Object.fromEntries([...entries].map(([id, value]) => [id, value.url])) }
  function remove(id?: string) {
    if (!id) return
    const entry = entries.get(id)
    if (entry?.blob) URL.revokeObjectURL(entry.url)
    entries.delete(id); publish()
  }
  function add(source: ImageSource): string | undefined {
    const decoded = source.base64 ? decodeImage(source) : null
    const remote = source.url ? safeImageURL(source.url) : null
    if (!decoded && !remote) return
    // Remote content size is unknown: reserve the per-image budget conservatively.
    const size = decoded?.bytes.byteLength ?? limits.imageBytes
    const total = () => [...entries.values()].reduce((sum, entry) => sum + entry.bytes, 0)
    while (entries.size >= limits.previewCount || total() + size > limits.previewBytes) remove(entries.keys().next().value)
    const id = `preview-${++sequence}`
    const url = decoded ? URL.createObjectURL(new Blob([decoded.bytes], { type: decoded.mime })) : remote!
    entries.set(id, { url, bytes: size, blob: !!decoded }); publish()
    return id
  }
  function clear() { for (const id of entries.keys()) remove(id) }
  return { previews, add, remove, clear }
}
