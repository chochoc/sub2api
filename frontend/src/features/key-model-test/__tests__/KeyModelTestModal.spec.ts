import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import KeyModelTestModal from '../components/KeyModelTestModal.vue'
import ModelTestTable from '../components/ModelTestTable.vue'
import ModelTestResult from '../components/ModelTestResult.vue'
import BaseDialog from '@/components/common/BaseDialog.vue'
import { keysAPI } from '@/api/keys'
import { json, png, responsesOK } from './fixtures'
import messages from '@/i18n/locales/en/keyModelTest'

vi.mock('vue-i18n', async () => {
  const actual = await vi.importActual<typeof import('vue-i18n')>('vue-i18n')
  return { ...actual, useI18n: () => ({ t: (key: string, params: Record<string, unknown> = {}) => {
    const value = key.split('.').slice(1).reduce<unknown>((node, part) => node && typeof node === 'object' ? (node as Record<string, unknown>)[part] : undefined, messages)
    return typeof value === 'string' ? value.replace(/\{(\w+)\}/g, (_match, name) => String(params[name] ?? '')) : key
  } }) }
})

vi.mock('@/api/keys', () => ({ keysAPI: { getById: vi.fn() } }))
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copyToClipboard: vi.fn() }) }))
const wrappers: VueWrapper[] = []
const key = { id: 1, key: 'sk-test-only', name: 'Test key', status: 'active', updated_at: 'v1', group: { name: 'Test group', platform: 'openai' } }
let fetchMock: ReturnType<typeof vi.fn>
const mountModal = async (realDialog = false) => {
  const wrapper = mount(KeyModelTestModal, {
    ...(realDialog ? { attachTo: document.body } : {}),
    props: { show: true, keyId: 1 },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'en', messages: { en: { keyModelTest: messages } } })],
      stubs: {
        transition: true,
        ...(realDialog ? { Icon: true } : { BaseDialog: { props: ['show', 'title'], emits: ['close'], template: '<div v-if="show" role="dialog"><h2>{{ title }}</h2><slot/><slot name="footer"/></div>' } }),
        Pagination: { props: ['page', 'total'], emits: ['update:page'], template: '<button data-test="next-page" @click="$emit(\'update:page\', 2)">Next</button>' },
        RouterLink: { template: '<a><slot/></a>' },
        DataTable: { props: ['data', 'columns'], template: '<div><div v-for="row in data" :key="row.id"><slot v-for="col in columns" :name="\'cell-\' + col.key" :row="row"/></div><slot v-if="!data.length" name="empty"/></div>' }
      }
    }
  })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(keysAPI.getById).mockResolvedValue(key as never)
  fetchMock = vi.fn(async (_url: string, init: RequestInit) => init.method === 'GET' ? json({ data: [{ id: 'gpt-6' }, { id: 'gpt-image-2' }, { id: 'alias' }] }) : json(responsesOK))
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.unstubAllGlobals(); document.body.innerHTML = '' })

const detailsDialog = (wrapper: VueWrapper) => wrapper.findAllComponents(BaseDialog).find(dialog => dialog.props('title') === 'Test result details')!
const testRow = async (wrapper: VueWrapper, id = 'gpt-6') => {
  wrapper.getComponent(ModelTestTable).vm.$emit('test', id); await flushPromises()
}
const viewResult = async (wrapper: VueWrapper, id = 'gpt-6') => {
  wrapper.getComponent(ModelTestTable).vm.$emit('details', id); await flushPromises()
}
const closeResult = async (wrapper: VueWrapper) => {
  await detailsDialog(wrapper).findAll('button').find(button => button.text() === 'Close details')!.trigger('click')
}
const confirmPlan = async (wrapper: VueWrapper) => {
  wrapper.findAllComponents({ name: 'ConfirmDialog' })[0].vm.$emit('confirm'); await flushPromises()
}

describe('key test modal interactions', () => {
  it('loads discovery only and requires confirmation before images', async () => {
    const wrapper = await mountModal()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    wrapper.getComponent(ModelTestTable).vm.$emit('test', 'gpt-image-2'); await flushPromises()
    expect(wrapper.text()).toContain('Confirm test plan')
    expect(wrapper.text()).toContain('including 1 image tests')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    wrapper.findAllComponents({ name: 'ConfirmDialog' })[0].vm.$emit('cancel'); await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
  it('only opens the separate result dialog on demand without another API call', async () => {
    const wrapper = await mountModal()
    await testRow(wrapper)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('Received a complete text response')
    expect(wrapper.findComponent(ModelTestResult).exists()).toBe(false)
    expect(detailsDialog(wrapper).props('show')).toBe(false)
    const keyReads = vi.mocked(keysAPI.getById).mock.calls.length
    await viewResult(wrapper)
    expect(detailsDialog(wrapper).props('show')).toBe(true)
    expect(detailsDialog(wrapper).getComponent(ModelTestResult).props('result').modelId).toBe('gpt-6')
    expect(wrapper.findAllComponents(BaseDialog)[0].findComponent(ModelTestResult).exists()).toBe(false)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(keysAPI.getById).toHaveBeenCalledTimes(keyReads)
    expect(wrapper.text()).not.toContain(key.key)
    expect(wrapper.text()).toContain('request-123')
    expect(detailsDialog(wrapper).get('pre').text()).toBe('OK')
    expect(detailsDialog(wrapper).text()).toContain('Copy diagnostic summary')
    expect(detailsDialog(wrapper).text()).toContain('usage records')
  })
  it('ignores result selection when the row has no result', async () => {
    const wrapper = await mountModal()
    await viewResult(wrapper)
    expect(detailsDialog(wrapper).props('show')).toBe(false)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
  it('preserves the filter, page, selection and results when details close', async () => {
    fetchMock.mockResolvedValueOnce(json({ data: Array.from({ length: 31 }, (_, i) => ({ id: `gpt-${i}` })) }))
    const wrapper = await mountModal()
    await wrapper.get('input[type="search"]').setValue('gpt-')
    await wrapper.get('[data-test="next-page"]').trigger('click')
    wrapper.getComponent(ModelTestTable).vm.$emit('update:selected', ['gpt-30']); await flushPromises()
    await testRow(wrapper, 'gpt-30')
    await viewResult(wrapper, 'gpt-30')
    const calls = fetchMock.mock.calls.length
    await closeResult(wrapper)
    expect(detailsDialog(wrapper).props('show')).toBe(false)
    expect(wrapper.get('input[type="search"]').element).toHaveProperty('value', 'gpt-')
    expect(wrapper.getComponent(ModelTestTable).props('models').map((m: { id: string }) => m.id)).toEqual(['gpt-30'])
    expect(wrapper.getComponent(ModelTestTable).props('selected')).toEqual(['gpt-30'])
    expect(wrapper.getComponent(ModelTestTable).props('results')['gpt-30'].status).toBe('success')
    expect(fetchMock).toHaveBeenCalledTimes(calls)
    expect(wrapper.emitted('close')).toBeUndefined()
    await viewResult(wrapper, 'gpt-30')
    expect(detailsDialog(wrapper).get('pre').text()).toBe('OK')
  })
  it.each(['refresh', 'key', 'hide', 'close'])('discards old details after %s', async action => {
    const wrapper = await mountModal()
    await testRow(wrapper); await viewResult(wrapper)
    if (action === 'refresh') await wrapper.findAll('button').find(b => b.text() === 'Refresh models')!.trigger('click')
    if (action === 'key') {
      vi.mocked(keysAPI.getById).mockResolvedValue({ ...key, id: 2 } as never)
      await wrapper.setProps({ keyId: 2 })
    }
    if (action === 'hide') await wrapper.setProps({ show: false })
    if (action === 'close') wrapper.findAllComponents(BaseDialog)[0].vm.$emit('close')
    await flushPromises()
    expect(detailsDialog(wrapper).props('show')).toBe(false)
    expect(wrapper.findComponent(ModelTestResult).exists()).toBe(false)
    if (action === 'hide') { await wrapper.setProps({ show: true }); await flushPromises() }
    expect(detailsDialog(wrapper).props('show')).toBe(false)
    expect(wrapper.getComponent(ModelTestTable).props('results')).toEqual({})
  })
  it('keeps a live result and continues the serial batch when details close', async () => {
    let finishFirst!: (response: Response) => void, finishSecond!: (response: Response) => void
    const first = new Promise<Response>(resolve => { finishFirst = resolve })
    const second = new Promise<Response>(resolve => { finishSecond = resolve })
    fetchMock.mockResolvedValueOnce(json({ data: [{ id: 'gpt-6' }, { id: 'gpt-5' }] }))
    const wrapper = await mountModal()
    fetchMock.mockReturnValueOnce(first).mockReturnValueOnce(second)
    await wrapper.findAll('button').find(b => b.text() === 'Test 2 filtered')!.trigger('click')
    await confirmPlan(wrapper)
    await viewResult(wrapper)
    expect(detailsDialog(wrapper).getComponent(ModelTestResult).props('result').status).toBe('running')
    finishFirst(json(responsesOK)); await flushPromises()
    expect(detailsDialog(wrapper).getComponent(ModelTestResult).props('result').status).toBe('success')
    const signal = fetchMock.mock.calls[2][1].signal as AbortSignal
    await closeResult(wrapper)
    expect(signal.aborted).toBe(false)
    finishSecond(json(responsesOK)); await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(wrapper.getComponent(ModelTestTable).props('results')['gpt-5'].status).toBe('success')
    expect(detailsDialog(wrapper).props('show')).toBe(false)
    expect(wrapper.emitted('close')).toBeUndefined()
  })
  it('opens the selected failure rather than another model result', async () => {
    const wrapper = await mountModal()
    await testRow(wrapper)
    wrapper.getComponent(ModelTestTable).vm.$emit('override', 'alias', 'responses'); await flushPromises()
    fetchMock.mockResolvedValueOnce(json({ error: { code: 'model_not_found', message: 'The selected model is unavailable' } }, 404))
    await testRow(wrapper, 'alias')
    expect(detailsDialog(wrapper).props('show')).toBe(false)
    await viewResult(wrapper, 'alias')
    expect(detailsDialog(wrapper).text()).toContain('The selected model is unavailable')
    expect(detailsDialog(wrapper).getComponent(ModelTestResult).props('result')).toMatchObject({ modelId: 'alias', status: 'failed', httpStatus: 404 })
    expect(detailsDialog(wrapper).find('pre').exists()).toBe(false)
  })
  it('retains a Blob preview across details close and releases it with the main session', async () => {
    const create = vi.fn(() => 'blob:test-preview'), revoke = vi.fn()
    vi.stubGlobal('URL', class extends URL { static createObjectURL = create; static revokeObjectURL = revoke })
    const wrapper = await mountModal()
    fetchMock.mockResolvedValueOnce(json({ data: [{ b64_json: png }] }))
    await testRow(wrapper, 'gpt-image-2'); await confirmPlan(wrapper)
    expect(detailsDialog(wrapper).props('show')).toBe(false)
    await viewResult(wrapper, 'gpt-image-2')
    expect(detailsDialog(wrapper).get('img').attributes('src')).toBe('blob:test-preview')
    await closeResult(wrapper)
    expect(revoke).not.toHaveBeenCalled()
    await viewResult(wrapper, 'gpt-image-2')
    expect(detailsDialog(wrapper).get('img').attributes('src')).toBe('blob:test-preview')
    expect(create).toHaveBeenCalledTimes(1)
    await wrapper.setProps({ show: false })
    expect(revoke).toHaveBeenCalledWith('blob:test-preview')
  })
  it('shows a released preview and image loading failures without regenerating', async () => {
    fetchMock.mockResolvedValueOnce(json({ data: Array.from({ length: 4 }, (_, i) => ({ id: `gpt-image-${i}` })) }))
    const wrapper = await mountModal()
    for (let i = 0; i < 4; i++) {
      fetchMock.mockResolvedValueOnce(json({ data: [{ url: `https://images.example.test/${i}.png` }] }))
      await testRow(wrapper, `gpt-image-${i}`); await confirmPlan(wrapper)
    }
    await viewResult(wrapper, 'gpt-image-0')
    expect(detailsDialog(wrapper).text()).toContain('Generation succeeded; the preview was released.')
    await viewResult(wrapper, 'gpt-image-3')
    await detailsDialog(wrapper).get('img').trigger('error')
    expect(detailsDialog(wrapper).text()).toContain('An image was returned, but its preview could not load.')
    expect(fetchMock).toHaveBeenCalledTimes(5)
  })
  it('unmounts both dialogs and releases the main session preview', async () => {
    const revoke = vi.fn()
    vi.stubGlobal('URL', class extends URL { static createObjectURL = () => 'blob:unmount'; static revokeObjectURL = revoke })
    const wrapper = await mountModal(true)
    fetchMock.mockResolvedValueOnce(json({ data: [{ b64_json: png }] }))
    await testRow(wrapper, 'gpt-image-2'); await confirmPlan(wrapper); await viewResult(wrapper, 'gpt-image-2')
    expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(2)
    wrappers.splice(wrappers.indexOf(wrapper), 1); wrapper.unmount()
    expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(0)
    expect(document.body.classList.contains('modal-open')).toBe(false)
    expect(revoke).toHaveBeenCalledWith('blob:unmount')
  })
  it('uses real stacked dialogs for Escape, backdrop, focus, scroll and close controls', async () => {
    const wrapper = await mountModal(true)
    await testRow(wrapper)
    const main = document.querySelector<HTMLElement>('[role="dialog"]')!
    const mainBody = main.querySelector<HTMLElement>('.modal-body')!
    mainBody.scrollTop = 360
    const trigger = Array.from(main.querySelectorAll('button')).find(b => b.textContent === 'View result')!
    const open = async () => { trigger.focus(); trigger.click(); await flushPromises() }
    await open()
    let child = document.querySelectorAll<HTMLElement>('[role="dialog"]')[1]
    expect(child.style.zIndex).toBe('60')
    expect(main.contains(child)).toBe(false)
    expect(child.contains(document.activeElement)).toBe(true)
    expect(main.querySelector('section')).toBeNull()
    child.click(); await flushPromises()
    expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(2)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); await flushPromises()
    expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(1)
    expect(wrapper.emitted('close')).toBeUndefined()
    expect(document.activeElement).toBe(trigger)
    expect(mainBody.scrollTop).toBe(360)
    expect(document.body.classList.contains('modal-open')).toBe(true)
    await open()
    child = document.querySelectorAll<HTMLElement>('[role="dialog"]')[1]
    child.querySelector<HTMLButtonElement>('[aria-label="Close modal"]')!.click(); await flushPromises()
    expect(document.activeElement).toBe(trigger)
    await open()
    child = document.querySelectorAll<HTMLElement>('[role="dialog"]')[1]
    child.querySelector<HTMLButtonElement>('.modal-footer button')!.click(); await flushPromises()
    expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(1)
    expect(document.activeElement).toBe(trigger)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); await flushPromises()
    expect(wrapper.emitted('close')).toHaveLength(1)
    await wrapper.setProps({ show: false })
    expect(document.body.classList.contains('modal-open')).toBe(false)
  })
  it('clears selection when the filter changes', async () => {
    const wrapper = await mountModal()
    wrapper.getComponent(ModelTestTable).vm.$emit('update:selected', ['gpt-6']); await flushPromises()
    expect(wrapper.text()).toContain('Test 1 selected')
    await wrapper.get('input[type="search"]').setValue('image')
    expect(wrapper.text()).toContain('Test 0 selected')
  })
  it('uses pagination events and filters across the complete model list', async () => {
    fetchMock.mockResolvedValueOnce(json({ data: Array.from({ length: 31 }, (_, i) => ({ id: `gpt-${i}` })) }))
    const wrapper = await mountModal()
    expect(wrapper.getComponent(ModelTestTable).props('models')).toHaveLength(30)
    await wrapper.get('[data-test="next-page"]').trigger('click')
    expect(wrapper.getComponent(ModelTestTable).props('models')).toHaveLength(1)
    await wrapper.get('input[type="search"]').setValue('gpt-0')
    expect(wrapper.getComponent(ModelTestTable).props('models')[0].id).toBe('gpt-0')
  })
})
