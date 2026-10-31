import type { ParsedOutcome } from '../types'

export interface TestRequestSpec {
  path: string
  headers: Record<string, string>
  body: unknown
  responseMode: 'json' | 'sse'
  timeoutMs: number
  maxResponseBytes: number
}
export interface ParseContext {
  signal: AbortSignal
  maxResponseBytes: number
  onText: (text: string) => void
}
export interface ProtocolAdapter {
  buildRequest(modelId: string, stream: boolean): TestRequestSpec
  parseResponse(response: Response, context: ParseContext): Promise<ParsedOutcome>
}
