export const profiles = ['responses', 'chat_completions', 'messages', 'gemini_text', 'images', 'gemini_image'] as const
export type TestProfile = typeof profiles[number]
export type ProfileChoice = TestProfile | 'auto'
export type ModelKind = 'text' | 'image' | 'unsupported' | 'unknown'
export type TestStatus = 'untested' | 'queued' | 'running' | 'success' | 'failed' | 'incomplete' | 'timeout' | 'cancelled' | 'skipped'

export interface CatalogModel {
  id: string
  displayName: string
  kind: ModelKind
  suggestedProfile: TestProfile | null
  resolution: 'suggested' | 'manual_required' | 'unsupported'
}
export interface TestSelection { modelId: string; profile: TestProfile; stream: boolean }
export interface TestPlan { selections: TestSelection[]; skipped: Array<{ modelId: string; reason: string }>; imageCount: number }
export interface NormalizedUsage { inputTokens?: number; outputTokens?: number; totalTokens?: number; cachedInputTokens?: number }
export interface ModelTestResult {
  modelId: string
  profile?: TestProfile
  stream: boolean
  status: TestStatus
  startedAt: string
  durationMs: number
  firstContentMs?: number
  httpStatus?: number
  gatewayRequestId?: string
  responseModel?: string
  summary: string // keyModelTest.messages translation key; never a raw payload
  textPreview?: string
  usage?: NormalizedUsage
  imageCount?: number
  previewId?: string
  errorCategory?: string
  errorCode?: string
  errorMessage?: string
  partialOutput: boolean
}
export interface ImageSource { base64?: string; mime?: string; url?: string }
export interface ParsedOutcome {
  status: 'success' | 'failed' | 'incomplete'
  summary: string
  textPreview?: string
  responseModel?: string
  usage?: NormalizedUsage
  images?: ImageSource[]
  errorCode?: string
  partialOutput?: boolean
}
export function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}
export function array(value: unknown): unknown[] { return Array.isArray(value) ? value : [] }
export function str(value: unknown): string { return typeof value === 'string' ? value : '' }
