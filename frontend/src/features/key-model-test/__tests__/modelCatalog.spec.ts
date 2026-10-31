import { describe, expect, it } from 'vitest'
import { parseCatalog } from '../modelCatalog'
import { limits } from '../config'

describe('key model catalog', () => {
  it('preserves exact public IDs, order, names and unknown aliases', () => {
    const catalog = parseCatalog({ data: [{ id: 'My-Alias', display_name: 'Alias' }, { id: 'gpt-image-2' }, { id: 'My-Alias' }, { id: '__proto__' }, {}, null] })
    expect(catalog.models.map(m => m.id)).toEqual(['My-Alias', 'gpt-image-2', '__proto__'])
    expect(catalog.models[0]).toMatchObject({ displayName: 'Alias', resolution: 'manual_required' })
    expect(catalog.invalidCount).toBe(2)
  })
  it.each([[], null])('accepts empty/null data without static fallback', data => expect(parseCatalog({ data }).models).toEqual([]))
  it.each([{}, { models: [] }, { data: {} }, { data: '' }])('rejects a malformed envelope', data => expect(() => parseCatalog(data)).toThrow('invalidCatalog'))
  it('fails rather than silently truncates a large catalog', () => expect(() => parseCatalog({ data: Array(limits.catalogItems + 1).fill({ id: 'x' }) })).toThrow('catalogLimit'))
})
