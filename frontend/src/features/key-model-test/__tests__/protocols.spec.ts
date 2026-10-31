import { describe, expect, it, vi } from 'vitest'
import { responsesAdapter } from '../protocols/responses'
import { chatAdapter } from '../protocols/chatCompletions'
import { messagesAdapter } from '../protocols/messages'
import { geminiAdapter } from '../protocols/gemini'
import { imagesAdapter } from '../protocols/images'
import { json, sse, signal, responsesOK, png } from './fixtures'
import type { ProtocolAdapter } from '../protocols/types'

const parse = (adapter: ProtocolAdapter, response: Response) => adapter.parseResponse(response, { signal: signal(), maxResponseBytes: 1024 * 1024, onText: vi.fn() })

describe('protocol results', () => {
  it('preserves zero usage and leaves missing values absent', async () => {
    const result = await parse(responsesAdapter, json(responsesOK))
    expect(result.status).toBe('success'); expect(result.usage?.cachedInputTokens).toBe(0)
    expect(result.usage?.totalTokens).toBeUndefined()
  })
  it.each([
    [{ ...responsesOK, status: 'incomplete' }, 'incomplete'],
    [{ ...responsesOK, output: [] }, 'failed'],
    [{ ...responsesOK, output: [{ type: 'function_call' }] }, 'failed']
  ])('does not accept incomplete, empty or tool output', async (body, status) => expect((await parse(responsesAdapter, json(body))).status).toBe(status))
  it('requires a Responses completed event, not just deltas', async () => {
    expect((await parse(responsesAdapter, sse([{ type: 'response.output_text.delta', delta: 'OK' }]))).status).toBe('incomplete')
    expect((await parse(responsesAdapter, sse([{ type: 'response.completed', response: responsesOK }]))).status).toBe('success')
  })
  it('accepts the gateway DONE sentinel only alongside a normal Responses terminal event', async () => {
    expect((await parse(responsesAdapter, sse([{ type: 'response.completed', response: responsesOK }, '[DONE]']))).status).toBe('success')
    expect((await parse(responsesAdapter, sse([{ type: 'response.output_text.delta', delta: 'OK' }, '[DONE]']))).status).toBe('incomplete')
    expect((await parse(responsesAdapter, sse([{ type: 'response.incomplete', response: { ...responsesOK, status: 'incomplete' } }, '[DONE]']))).status).toBe('incomplete')
  })
  it('rejects errors carried inside HTTP 200', async () => {
    await expect(parse(responsesAdapter, json({ error: { code: 'failed', message: 'secret' } }))).rejects.toThrow('protocolError')
  })
  it('requires Chat finish_reason and DONE', async () => {
    const event = { choices: [{ delta: { content: 'OK' }, finish_reason: 'stop' }] }
    expect((await parse(chatAdapter, sse([event]))).status).toBe('incomplete')
    expect((await parse(chatAdapter, sse([event, '[DONE]']))).status).toBe('success')
    expect((await parse(chatAdapter, json({ choices: [{ message: { content: 'Partial' }, finish_reason: 'length' }] }))).status).toBe('incomplete')
  })
  it('handles Anthropic message_stop and merges usage', async () => {
    const events = [
      { type: 'message_start', message: { model: 'claude', usage: { input_tokens: 3, cache_read_input_tokens: 0 } } },
      { type: 'content_block_delta', delta: { type: 'text_delta', text: 'OK' } },
      { type: 'message_delta', delta: { stop_reason: 'end_turn' }, usage: { output_tokens: 1 } }
    ]
    expect((await parse(messagesAdapter, sse(events))).status).toBe('incomplete')
    const result = await parse(messagesAdapter, sse([...events, { type: 'message_stop' }]))
    expect(result).toMatchObject({ status: 'success', usage: { inputTokens: 3, outputTokens: 1, cachedInputTokens: 0 } })
  })
  it('handles Gemini normal finish and safety blocks', async () => {
    const body = { candidates: [{ content: { parts: [{ text: 'OK' }] }, finishReason: 'STOP' }] }
    expect((await parse(geminiAdapter(false), json(body))).status).toBe('success')
    expect((await parse(geminiAdapter(false), sse([body]))).status).toBe('success')
    expect((await parse(geminiAdapter(false), json({ promptFeedback: { blockReason: 'SAFETY' } }))).status).toBe('failed')
  })
  it('requires real image data instead of text-only image replies', async () => {
    expect((await parse(imagesAdapter, json({ data: [{ b64_json: png }] }))).status).toBe('success')
    expect((await parse(imagesAdapter, json({ data: [{ b64_json: btoa('<svg/>') }] }))).status).toBe('failed')
    expect((await parse(geminiAdapter(true), json({ candidates: [{ content: { parts: [{ text: 'I cannot draw' }] }, finishReason: 'STOP' }] }))).status).toBe('failed')
    expect((await parse(geminiAdapter(true), json({ candidates: [{ content: { parts: [{ inlineData: { mimeType: 'image/png', data: png } }] }, finishReason: 'STOP' }] }))).status).toBe('success')
  })
  it('encodes Gemini model paths and disables image streaming', () => {
    expect(geminiAdapter(false).buildRequest('alias/a?b', true).path).toBe('/v1beta/models/alias%2Fa%3Fb:streamGenerateContent?alt=sse')
    expect(geminiAdapter(true).buildRequest('image', true).responseMode).toBe('json')
  })
  it('uses minimal payloads with no conflicting OpenAI token limit', () => {
    expect(responsesAdapter.buildRequest('model', false).body).toMatchObject({ store: false, stream: false, model: 'model' })
    expect(chatAdapter.buildRequest('model', true).body).not.toHaveProperty('max_tokens')
    expect(messagesAdapter.buildRequest('model', false).body).toHaveProperty('max_tokens', 256)
    expect(imagesAdapter.buildRequest('image', false).body).toMatchObject({ n: 1 })
  })
  it('accepts empty optional tool arrays but rejects actual tool calls', async () => {
    const body = (tool_calls: unknown[]) => ({ choices: [{ message: { content: 'OK', tool_calls }, finish_reason: 'stop' }] })
    expect((await parse(chatAdapter, json(body([])))).status).toBe('success')
    const toolResult = await parse(chatAdapter, json(body([{ id: 'call-1' }])))
    expect(toolResult.status).toBe('failed')
  })
})
