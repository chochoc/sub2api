import type { CatalogModel, ProfileChoice, TestProfile } from './types'

export function isImageProfile(profile: TestProfile): boolean {
  return profile === 'images' || profile === 'gemini_image'
}

// Suggestions select a request template, never advertise or rewrite a model.
export function classifyModel(id: string, platform?: string): Pick<CatalogModel, 'kind' | 'suggestedProfile' | 'resolution'> {
  const name = id.toLowerCase()
  let profile: TestProfile | null = null
  if (/(?:audio|realtime|embedding|whisper|tts|video|veo|sora|seedance|moderation|systemone)/.test(name)) {
    return { kind: 'unsupported', suggestedProfile: null, resolution: 'unsupported' }
  }
  if (/^(gpt-image-|dall-e-)/.test(name) || /^grok-imagine(?:$|-image(?:-|$))/.test(name)) profile = 'images'
  else if (/^gemini-.*(?:-image)(?:-|$)/.test(name)) profile = 'gemini_image'
  else if (/^claude-/.test(name)) profile = 'messages'
  else if (/^gemini-/.test(name)) profile = 'gemini_text'
  else if (/^(gpt-|codex(?:-|$)|o[1-9](?:-|$))/.test(name)) profile = 'responses'
  else if (/^(grok-|deepseek-|kimi-|glm-|minimax-|qwen-)/.test(name)) profile = 'chat_completions'
  // A known text family on a native Anthropic group is best tested with Messages.
  if (profile && !isImageProfile(profile) && platform === 'anthropic') profile = 'messages'
  return {
    kind: profile ? (isImageProfile(profile) ? 'image' : 'text') : 'unknown',
    suggestedProfile: profile,
    resolution: profile ? 'suggested' : 'manual_required'
  }
}

export function resolveProfile(model: CatalogModel, global: ProfileChoice, override?: ProfileChoice): { profile: TestProfile | null; reason?: string } {
  if (override && override !== 'auto') return { profile: override }
  if (model.kind === 'unsupported') return { profile: null, reason: 'unsupported' }
  const selected = global === 'auto' ? model.suggestedProfile : global
  if (!selected) return { profile: null, reason: 'manualRequired' }
  if ((model.kind === 'image' && !isImageProfile(selected)) || (model.kind === 'text' && isImageProfile(selected))) {
    return { profile: null, reason: 'profileMismatch' }
  }
  return { profile: selected }
}
