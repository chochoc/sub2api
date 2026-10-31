import { limits } from './config'
import { classifyModel } from './testProfiles'
import { record, str, type CatalogModel } from './types'
import { TestError } from './resultSanitizer'

export function parseCatalog(body: unknown, platform?: string): { models: CatalogModel[]; invalidCount: number } {
  const source = record(body).data
  if (source === null) return { models: [], invalidCount: 0 }
  if (!Array.isArray(source)) throw new TestError('invalidCatalog')
  if (source.length > limits.catalogItems) throw new TestError('catalogLimit')
  const seen = new Set<string>()
  const models: CatalogModel[] = []
  let invalidCount = 0
  for (const raw of source) {
    const item = record(raw)
    const id = str(item.id)
    if (!id.trim() || id.length > 1024 || Array.from(id).some(char => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)) { invalidCount++; continue }
    if (seen.has(id)) continue
    seen.add(id)
    models.push({ id, displayName: (str(item.display_name) || str(item.name) || id).slice(0, 1024), ...classifyModel(id, platform) })
  }
  return { models, invalidCount }
}
