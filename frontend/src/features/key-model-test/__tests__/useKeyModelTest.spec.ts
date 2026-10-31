import { effectScope } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { useKeyModelTest } from '../useKeyModelTest'
import { keysAPI } from '@/api/keys'
import { discoverModels, executeTest } from '../gatewayClient'
import { parseCatalog } from '../modelCatalog'
import type { TestExecution } from '../gatewayClient'

vi.mock('@/api/keys', () => ({ keysAPI: { getById: vi.fn() } }))
vi.mock('../gatewayClient', () => ({ discoverModels: vi.fn(), executeTest: vi.fn() }))
const key = { id: 1, key: 'sk-private-key', name: 'key', group_id: 1, group: { name: 'group', platform: 'openai', updated_at: 'a' }, status: 'active', updated_at: 'a', expires_at: null }
const scopes: ReturnType<typeof effectScope>[] = []
const setup = () => { const scope = effectScope(); scopes.push(scope); return scope.run(() => useKeyModelTest())! }
const deferred = <T>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r }); return { promise, resolve } }
const ok = (modelId: string): TestExecution => ({ result: { modelId, status: 'success', stream: false, startedAt: '', durationMs: 1, summary: 'completed', partialOutput: false }, images: [], stopQueue: false })
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(keysAPI.getById).mockResolvedValue(key as never)
  vi.mocked(discoverModels).mockResolvedValue(parseCatalog({ data: [{ id: 'gpt-6' }, { id: 'gpt-5' }, { id: 'gpt-image-2' }, { id: 'alias' }] }))
  vi.mocked(executeTest).mockImplementation(async (_key, selection) => ok(selection.modelId))
})
afterEach(() => { scopes.splice(0).forEach(s => s.stop()) })

describe('key model testing lifecycle', () => {
  it('opens without any paid request and never exposes the secret in UI state', async () => {
    const state = setup(); await state.open(1)
    expect(executeTest).not.toHaveBeenCalled()
    expect(JSON.stringify(state.keyInfo.value)).not.toContain(key.key)
    expect(state.models.value).toHaveLength(4)
  })
  it('keeps a frozen serial queue and ignores duplicate starts', async () => {
    const state = setup(); await state.open(1)
    const first = deferred<TestExecution>()
    vi.mocked(executeTest).mockImplementationOnce(() => first.promise)
    const plan = state.plan(['gpt-6', 'gpt-5'], 'auto', {}, false, false)
    const running = state.start(plan); await flushPromises()
    await state.start(plan)
    plan.selections.splice(1)
    expect(executeTest).toHaveBeenCalledTimes(1)
    first.resolve(ok('gpt-6')); await running
    expect(executeTest).toHaveBeenCalledTimes(2)
    expect(state.results.value['gpt-5'].status).toBe('success')
  })
  it('skips unknown and excluded image models without requests', async () => {
    const state = setup(); await state.open(1)
    const plan = state.plan(state.models.value.map(m => m.id), 'auto', {}, false, false)
    expect(plan.skipped).toEqual([{ modelId: 'gpt-image-2', reason: 'imageExcluded' }, { modelId: 'alias', reason: 'manualRequired' }])
    expect(plan.selections).toHaveLength(2)
  })
  it('stops queued models and prevents a late result from overwriting cancellation', async () => {
    const state = setup(); await state.open(1)
    const first = deferred<TestExecution>(); vi.mocked(executeTest).mockReturnValueOnce(first.promise)
    const pending = state.start(state.plan(['gpt-6', 'gpt-5'], 'auto', {}, false, false)); await flushPromises()
    const requestSignal = vi.mocked(executeTest).mock.calls[0][2]
    state.stop(); expect(requestSignal.aborted).toBe(true)
    first.resolve(ok('gpt-6')); await pending
    expect(state.results.value['gpt-6'].status).toBe('cancelled')
    expect(state.results.value['gpt-5'].status).toBe('skipped'); expect(executeTest).toHaveBeenCalledTimes(1)
  })
  it('stops the batch after key/rate failures', async () => {
    const state = setup(); await state.open(1)
    vi.mocked(executeTest).mockResolvedValueOnce({ ...ok('gpt-6'), stopQueue: true, result: { ...ok('gpt-6').result, status: 'failed' } })
    await state.start(state.plan(['gpt-6', 'gpt-5'], 'auto', {}, false, false))
    expect(executeTest).toHaveBeenCalledTimes(1); expect(state.results.value['gpt-5'].status).toBe('skipped')
  })
  it('reloads on group changes and requires a new user action', async () => {
    const state = setup(); await state.open(1)
    vi.mocked(keysAPI.getById).mockResolvedValue({ ...key, group_id: 2 } as never)
    await state.start(state.plan(['gpt-6'], 'auto', {}, false, false))
    expect(executeTest).not.toHaveBeenCalled(); expect(discoverModels).toHaveBeenCalledTimes(2)
    expect(state.notice.value).toBe('keyChanged')
  })
  it('does not execute after failed ownership refresh', async () => {
    const state = setup(); await state.open(1)
    vi.mocked(keysAPI.getById).mockRejectedValue(new Error('404'))
    await state.start(state.plan(['gpt-6'], 'auto', {}, false, false))
    expect(executeTest).not.toHaveBeenCalled(); expect(state.error.value).toBe('keyUnavailable')
  })
  it('allows discovery and earlier calls to update activity timestamps and quota usage', async () => {
    const state = setup(); await state.open(1)
    vi.mocked(keysAPI.getById).mockResolvedValue({ ...key, updated_at: 'b', last_used_at: 'b', quota_used: 0.01, usage_5h: 0.01 } as never)
    await state.start(state.plan(['gpt-6'], 'auto', {}, false, false))
    vi.mocked(keysAPI.getById).mockResolvedValue({ ...key, updated_at: 'c', last_used_at: 'c', quota_used: 0.02, usage_5h: 0.02 } as never)
    await state.start(state.plan(['gpt-5'], 'auto', {}, false, false))
    expect(executeTest).toHaveBeenCalledTimes(2); expect(discoverModels).toHaveBeenCalledTimes(1)
    expect(state.results.value['gpt-6'].status).toBe('success')
    expect(state.results.value['gpt-5'].status).toBe('success')
  })
  it.each([{ ip_whitelist: ['127.0.0.1'] }, { ip_blacklist: ['127.0.0.1'] }, { quota: 5 }, { rate_limit_5h: 1 }])('reloads when key policy changes: %j', async change => {
    const state = setup(); await state.open(1)
    vi.mocked(keysAPI.getById).mockResolvedValue({ ...key, ...change } as never)
    await state.start(state.plan(['gpt-6'], 'auto', {}, false, false))
    expect(executeTest).not.toHaveBeenCalled(); expect(state.notice.value).toBe('keyChanged')
    expect(discoverModels).toHaveBeenCalledTimes(2)
  })
  it('preserves other row results across single tests', async () => {
    const state = setup(); await state.open(1)
    await state.start(state.plan(['gpt-6'], 'auto', {}, false, false))
    await state.start(state.plan(['gpt-5'], 'auto', {}, false, false))
    expect(state.results.value['gpt-6'].status).toBe('success'); expect(state.results.value['gpt-5'].status).toBe('success')
    expect(state.counts.value.total).toBe(1)
  })
  it('cannot publish a stale key read after closing', async () => {
    const state = setup(), read = deferred<never>()
    vi.mocked(keysAPI.getById).mockReturnValue(read.promise)
    const pending = state.open(1); state.close(); read.resolve(key as never); await pending
    expect(state.keyInfo.value).toBeUndefined(); expect(discoverModels).not.toHaveBeenCalled()
  })
  it('does not discover or run an inactive key', async () => {
    vi.mocked(keysAPI.getById).mockResolvedValue({ ...key, status: 'inactive' } as never)
    const state = setup(); await state.open(1)
    expect(state.notice.value).toBe('inactiveKey'); expect(discoverModels).not.toHaveBeenCalled()
  })
  it('treats a malformed panel response as a read failure, not an inactive key', async () => {
    vi.mocked(keysAPI.getById).mockResolvedValue('<html>proxy failure</html>' as never)
    const state = setup(); await state.open(1)
    expect(state.error.value).toBe('keyUnavailable'); expect(discoverModels).not.toHaveBeenCalled()
  })
  it('counts a skipped-only plan and preserves unrelated results', async () => {
    const state = setup(); await state.open(1)
    await state.start(state.plan(['gpt-6'], 'auto', {}, false, false))
    await state.start(state.plan(['alias'], 'auto', {}, false, false))
    expect(state.counts.value).toMatchObject({ total: 1, completed: 1, skipped: 1 })
    expect(state.results.value['gpt-6'].status).toBe('success')
  })
  it('rejects oversized plans without refreshing or executing', async () => {
    const state = setup(); await state.open(1)
    await state.start({ selections: Array(51).fill({ modelId: 'gpt-6', profile: 'responses', stream: false }), skipped: [], imageCount: 0 })
    expect(state.error.value).toBe('batchLimit'); expect(executeTest).not.toHaveBeenCalled()
  })
})
