import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import KeyModelTestModal from '../components/KeyModelTestModal.vue'
import ModelTestTable from '../components/ModelTestTable.vue'
import { keysAPI } from '@/api/keys'
import { json, responsesOK } from './fixtures'
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
const mountModal = async () => {
  const wrapper = mount(KeyModelTestModal, {
    props: { show: true, keyId: 1 },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'en', messages: { en: { keyModelTest: messages } } })],
      stubs: {
        BaseDialog: { props: ['show', 'title'], emits: ['close'], template: '<div v-if="show" role="dialog"><h2>{{ title }}</h2><slot/><slot name="footer"/></div>' },
        Pagination: { props: ['page', 'total'], emits: ['update:page'], template: '<button data-test="next-page" @click="$emit(\'update:page\', 2)">Next</button>' },
        RouterLink: { template: '<a><slot/></a>' },
        DataTable: { props: ['data', 'columns'], template: '<div><div v-for="row in data" :key="row.id"><slot v-for="col in columns" :name="\'cell-\' + col.key" :row="row"/></div><slot v-if="!data.length" name="empty"/></div>' }
      }
    }
  })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}
beforeEach(() => {
  vi.mocked(keysAPI.getById).mockResolvedValue(key as never)
  fetchMock = vi.fn(async (_url: string, init: RequestInit) => init.method === 'GET' ? json({ data: [{ id: 'gpt-6' }, { id: 'gpt-image-2' }, { id: 'alias' }] }) : json(responsesOK))
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.unstubAllGlobals() })

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
  it('runs a text row without a second confirmation, shows result and no credential', async () => {
    const wrapper = await mountModal()
    wrapper.getComponent(ModelTestTable).vm.$emit('test', 'gpt-6'); await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('Received a complete text response')
    expect(wrapper.text()).not.toContain(key.key)
    expect(wrapper.text()).toContain('request-123')
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
