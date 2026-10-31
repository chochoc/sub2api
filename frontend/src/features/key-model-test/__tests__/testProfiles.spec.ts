import { describe, expect, it } from 'vitest'
import { classifyModel, resolveProfile } from '../testProfiles'
import { parseCatalog } from '../modelCatalog'

describe('test protocol suggestions', () => {
  it.each([
    ['gpt-image-2', 'images'], ['dall-e-3', 'images'], ['gemini-3.1-flash-image', 'gemini_image'],
    ['grok-imagine', 'images'], ['claude-sonnet-4', 'messages'], ['gemini-2.5-pro', 'gemini_text'],
    ['gpt-6', 'responses'], ['codex-auto-review', 'responses'], ['o3', 'responses'], ['deepseek-chat', 'chat_completions']
  ])('%s suggests %s without probing', (id, profile) => expect(classifyModel(id).suggestedProfile).toBe(profile))
  it.each(['gpt-audio', 'grok-imagine-video', 'text-embedding-3', 'veo-3', 'whisper-1', 'gpt-realtime'])('excludes %s before broad text prefixes', id => expect(classifyModel(id).kind).toBe('unsupported'))
  it('requires manual selection for aliases', () => expect(classifyModel('our-model').resolution).toBe('manual_required'))
  it('checks global modality but permits deliberate row overrides', () => {
    const model = parseCatalog({ data: [{ id: 'gpt-image-2' }] }).models[0]
    expect(resolveProfile(model, 'responses')).toEqual({ profile: null, reason: 'profileMismatch' })
    expect(resolveProfile(model, 'images', 'responses')).toEqual({ profile: 'responses' })
  })
})
