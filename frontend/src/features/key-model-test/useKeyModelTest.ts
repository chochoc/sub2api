import { computed, onScopeDispose, ref, shallowRef } from 'vue'
import { keysAPI } from '@/api/keys'
import type { ApiKey } from '@/types'
import { maskApiKey } from '@/utils/maskApiKey'
import { discoverModels, executeTest } from './gatewayClient'
import { createPreviewStore } from './imagePreview'
import { limits } from './config'
import { isImageProfile, resolveProfile } from './testProfiles'
import { sanitize, TestError } from './resultSanitizer'
import type { CatalogModel, ModelTestResult, ProfileChoice, TestPlan } from './types'

function identity(key: ApiKey): string {
  // Private comparison only; never returned, displayed, logged, or persisted.
  // updated_at also changes when the gateway records use/charges quota. It is not
  // a configuration version: comparing it would invalidate our own discovery.
  return JSON.stringify([key.id, key.user_id, key.key, key.name, key.group_id,
    key.group?.updated_at, key.group?.platform, key.status, key.expires_at,
    key.ip_whitelist, key.ip_blacklist, key.quota,
    key.rate_limit_5h, key.rate_limit_1d, key.rate_limit_7d])
}

function validateKey(key: ApiKey, expectedId: number): void {
  if (!key || key.id !== expectedId || typeof key.key !== 'string' || !key.key || typeof key.status !== 'string') throw new TestError('keyUnavailable')
}

export function useKeyModelTest() {
  let snapshot: ApiKey | undefined
  let session = 0, run = 0
  let controller: AbortController | undefined
  const keyInfo = shallowRef<{ name: string; group: string; masked: string; active: boolean }>()
  const models = shallowRef<CatalogModel[]>([])
  const results = shallowRef<Record<string, ModelTestResult>>(Object.create(null))
  const batchIds = ref<string[]>([])
  const loading = ref(false), running = ref(false)
  const notice = ref(''), error = ref(''), errorDetail = ref(''), invalidCount = ref(0)
  const previewStore = createPreviewStore()
  const counts = computed(() => {
    const values = batchIds.value.map(id => results.value[id]).filter(Boolean)
    return { total: values.length, completed: values.filter(r => !['queued', 'running', 'untested'].includes(r.status)).length,
      success: values.filter(r => r.status === 'success').length,
      failed: values.filter(r => ['failed', 'timeout', 'cancelled'].includes(r.status)).length,
      incomplete: values.filter(r => r.status === 'incomplete').length,
      skipped: values.filter(r => r.status === 'skipped').length }
  })
  const put = (result: ModelTestResult) => { results.value = Object.assign(Object.create(null), results.value, { [result.modelId]: result }) }
  const stub = (modelId: string, status: ModelTestResult['status'], summary: string): ModelTestResult => ({ modelId, status, summary, stream: false, startedAt: '', durationMs: 0, partialOutput: false })

  function stop() {
    run++
    controller?.abort()
    controller = undefined
    for (const result of Object.values(results.value)) {
      if (result.status === 'queued') put({ ...result, status: 'skipped', summary: 'stopped' })
      if (result.status === 'running') put({ ...result, status: 'cancelled', summary: 'cancelled', partialOutput: !!result.textPreview,
        durationMs: Math.max(0, Date.now() - new Date(result.startedAt).getTime()) })
    }
    running.value = false
    notice.value = 'stopped'
  }
  function close() {
    session++; stop(); snapshot = undefined; keyInfo.value = undefined
    loading.value = false; models.value = []; results.value = Object.create(null); batchIds.value = []; error.value = ''; errorDetail.value = ''; notice.value = ''; invalidCount.value = 0
    previewStore.clear()
  }
  async function open(keyId: number) {
    close()
    const current = session
    loading.value = true
    const requestController = new AbortController()
    controller = requestController
    try {
      const key = await keysAPI.getById(keyId)
      if (current !== session) return
      validateKey(key, keyId)
      snapshot = key
      const active = key.status === 'active' && (!key.expires_at || new Date(key.expires_at).getTime() > Date.now())
      keyInfo.value = { name: key.name, group: key.group?.name || '', masked: maskApiKey(key.key), active }
      if (!active) { notice.value = 'inactiveKey'; return }
      const catalog = await discoverModels(key.key, requestController.signal, key.group?.platform)
      if (current !== session) return
      models.value = catalog.models; invalidCount.value = catalog.invalidCount
    } catch (cause) {
      if (current === session) {
        error.value = cause instanceof TestError ? cause.reason : 'keyUnavailable'
        errorDetail.value = cause instanceof TestError ? sanitize([cause.code, cause.detail].filter(Boolean).join(': '), snapshot?.key) : ''
      }
    } finally {
      if (current === session) { loading.value = false; controller = undefined }
    }
  }

  function plan(ids: string[], global: ProfileChoice, overrides: Record<string, ProfileChoice>, stream: boolean, includeImages: boolean, single = false): TestPlan {
    const output: TestPlan = { selections: [], skipped: [], imageCount: 0 }
    const byId = new Map(models.value.map(m => [m.id, m]))
    for (const id of new Set(ids)) {
      const model = byId.get(id)
      if (!model) continue
      const resolved = resolveProfile(model, global, Object.prototype.hasOwnProperty.call(overrides, id) ? overrides[id] : undefined)
      if (!resolved.profile) { output.skipped.push({ modelId: id, reason: resolved.reason || 'manualRequired' }); continue }
      const image = isImageProfile(resolved.profile)
      if (image && !includeImages && !single) { output.skipped.push({ modelId: id, reason: 'imageExcluded' }); continue }
      output.selections.push({ modelId: id, profile: resolved.profile, stream: image ? false : stream })
      if (image) output.imageCount++
    }
    return output
  }

  async function start(plan: TestPlan) {
    if (running.value || loading.value || !snapshot || !keyInfo.value?.active) return
    error.value = ''; notice.value = ''
    if (plan.selections.length > limits.batchSize) { error.value = 'batchLimit'; return }
    if (!plan.selections.length) {
      batchIds.value = plan.skipped.map(item => item.modelId)
      for (const id of batchIds.value) previewStore.remove(results.value[id]?.previewId)
      for (const item of plan.skipped) put(stub(item.modelId, 'skipped', item.reason))
      notice.value = 'nothingToTest'; return
    }
    // Capture a plan snapshot before the asynchronous authorization refresh.
    const frozen = { selections: plan.selections.map(s => ({ ...s })), skipped: plan.skipped.map(s => ({ ...s })) }
    const currentSession = session, currentRun = ++run
    const original = snapshot
    const requestController = new AbortController()
    controller = requestController; running.value = true
    try {
      const fresh = await keysAPI.getById(original.id)
      if (currentSession !== session || currentRun !== run) return
      validateKey(fresh, original.id)
      if (identity(fresh) !== identity(original)) { await open(original.id); if (currentSession + 1 === session) notice.value = 'keyChanged'; return }
      snapshot = fresh
      if (fresh.status !== 'active' || (fresh.expires_at && new Date(fresh.expires_at).getTime() <= Date.now())) { notice.value = 'inactiveKey'; return }
      const modelIds = new Set(models.value.map(m => m.id))
      if (frozen.selections.some(s => !modelIds.has(s.modelId))) { error.value = 'keyChanged'; return }
      batchIds.value = [...frozen.selections.map(s => s.modelId), ...frozen.skipped.map(s => s.modelId)]
      for (const id of batchIds.value) previewStore.remove(results.value[id]?.previewId)
      for (const item of frozen.skipped) put(stub(item.modelId, 'skipped', item.reason))
      for (const selection of frozen.selections) put({ ...stub(selection.modelId, 'queued', 'queued'), ...selection })
      for (const selection of frozen.selections) {
        if (currentRun !== run || currentSession !== session) return
        put({ ...stub(selection.modelId, 'running', 'running'), ...selection, startedAt: new Date().toISOString() })
        const execution = await executeTest(fresh.key, selection, requestController.signal, text => {
          if (currentRun === run && currentSession === session) put({ ...results.value[selection.modelId], textPreview: text })
        })
        if (currentRun !== run || currentSession !== session) return
        if (execution.images[0]) execution.result.previewId = previewStore.add(execution.images[0])
        put(execution.result)
        if (execution.stopQueue) {
          for (const pending of Object.values(results.value)) if (pending.status === 'queued') put({ ...pending, status: 'skipped', summary: 'queueStopped' })
          notice.value = 'queueStopped'; break
        }
      }
    } catch {
      if (currentRun === run && currentSession === session) error.value = 'keyUnavailable'
    } finally {
      if (currentRun === run && currentSession === session) { running.value = false; controller = undefined }
    }
  }
  onScopeDispose(close)
  return { keyInfo, models, results, loading, running, notice, error, errorDetail, invalidCount, counts, previews: previewStore.previews, open, close, stop, plan, start }
}
