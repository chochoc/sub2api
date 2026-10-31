<template>
  <BaseDialog :show="show" :title="t('keyModelTest.title', { name: state.keyInfo.value?.name || '' })" width="extra-wide" @close="requestClose">
    <div class="space-y-4 text-gray-900 dark:text-gray-100">
      <p v-if="state.keyInfo.value" class="flex flex-wrap gap-4 text-sm"><span>{{ t('keyModelTest.group') }}: {{ state.keyInfo.value.group || '—' }}</span><span>{{ state.keyInfo.value.masked }}</span></p>
      <p class="rounded-lg bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-900/20 dark:text-amber-200">{{ t('keyModelTest.costNotice') }}</p>
      <p v-if="state.loading.value" role="status">{{ t('keyModelTest.loading') }}</p>
      <p v-if="state.error.value" role="alert" class="text-sm text-red-700 dark:text-red-400">{{ t(`keyModelTest.messages.${state.error.value}`) }}</p>
      <p v-if="state.errorDetail.value" class="break-words text-sm text-red-700 dark:text-red-400">{{ state.errorDetail.value }}</p>
      <p v-if="state.notice.value" role="status" class="text-sm">{{ t(`keyModelTest.messages.${state.notice.value}`) }}</p>
      <p v-if="state.invalidCount.value" class="text-sm">{{ t('keyModelTest.invalidItems', { count: state.invalidCount.value }) }}</p>
      <div class="grid items-end gap-4 sm:grid-cols-2">
        <label class="space-y-1 text-sm"><span>{{ t('keyModelTest.profile') }}</span>
          <select v-model="globalProfile" class="input min-h-11 w-full" :disabled="busy">
            <option value="auto">{{ t('keyModelTest.auto') }}</option>
            <option v-for="profile in profiles" :key="profile" :value="profile">{{ t(`keyModelTest.profiles.${profile}`) }}</option>
          </select>
        </label>
        <label class="flex min-h-11 items-center gap-2 text-sm"><input v-model="stream" type="checkbox" :disabled="busy" />{{ t('keyModelTest.streaming') }}</label>
      </div>
      <p class="text-xs text-gray-500 dark:text-gray-400">{{ t('keyModelTest.autoHint') }}</p>
      <div class="flex flex-wrap gap-2">
        <label class="min-w-0 flex-1"><span class="sr-only">{{ t('keyModelTest.search') }}</span><input v-model="search" type="search" class="input min-h-11 w-full" :placeholder="t('keyModelTest.search')" :disabled="busy" /></label>
        <button type="button" class="btn btn-secondary min-h-11" :disabled="busy" @click="refresh">{{ t('keyModelTest.refresh') }}</button>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <button type="button" class="btn btn-primary min-h-11" :disabled="!canTest || !selected.length" @click="prepare(selected)">{{ t('keyModelTest.testSelected', { count: selected.length }) }}</button>
        <button type="button" class="btn btn-secondary min-h-11" :disabled="!canTest || !filtered.length" @click="prepare(filtered.map(m => m.id))">{{ t('keyModelTest.testFiltered', { count: filtered.length }) }}</button>
        <button type="button" class="btn btn-secondary min-h-11" :disabled="!state.running.value" @click="state.stop">{{ t('keyModelTest.stop') }}</button>
        <label class="flex min-h-11 items-center gap-2 text-sm"><input v-model="includeImages" type="checkbox" :disabled="busy" />{{ t('keyModelTest.includeImages') }}</label>
      </div>
      <ModelTestTable :models="pageModels" :results="state.results.value" :selected="selected" :overrides="overrides" :global-profile="globalProfile" :disabled="!canTest" @update:selected="selected = $event" @override="setOverride" @test="prepare([$event], true)" @details="detailId = $event" />
      <p v-if="state.counts.value.total" role="status" aria-live="polite" class="text-sm">{{ t('keyModelTest.progress', state.counts.value) }}</p>
      <Pagination v-if="filtered.length" :page="page" :page-size="limits.pageSize" :total="filtered.length" :show-page-size-selector="false" @update:page="page = $event" />
      <ModelTestResult v-if="detail" :result="detail" :preview-url="detail.previewId ? state.previews.value[detail.previewId] : undefined" />
    </div>
    <template #footer><button type="button" class="btn btn-secondary min-h-11" @click="requestClose">{{ t('keyModelTest.close') }}</button></template>
  </BaseDialog>
  <ConfirmDialog :show="!!pendingPlan" :title="t('keyModelTest.confirmTitle')" :message="t('keyModelTest.confirmPlan', { count: pendingPlan?.selections.length || 0, images: pendingPlan?.imageCount || 0, skipped: pendingPlan?.skipped.length || 0 })" :confirm-text="t('keyModelTest.confirmRun')" @confirm="confirmRun" @cancel="pendingPlan = null" />
  <ConfirmDialog :show="confirmClose" :title="t('keyModelTest.closeTitle')" :message="t('keyModelTest.messages.stopped')" :confirm-text="t('keyModelTest.stopAndClose')" :cancel-text="t('keyModelTest.keepTesting')" @confirm="close" @cancel="confirmClose = false" />
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseDialog from '@/components/common/BaseDialog.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import Pagination from '@/components/common/Pagination.vue'
import ModelTestTable from './ModelTestTable.vue'
import ModelTestResult from './ModelTestResult.vue'
import { limits } from '../config'
import { useKeyModelTest } from '../useKeyModelTest'
import { profiles, type ProfileChoice, type TestPlan } from '../types'

const props = defineProps<{ show: boolean; keyId: number }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
const state = useKeyModelTest()
const search = ref(''), stream = ref(false), includeImages = ref(false), page = ref(1)
const selected = ref<string[]>([]), overrides = ref<Record<string, ProfileChoice>>(Object.create(null))
const globalProfile = ref<ProfileChoice>('auto'), detailId = ref('')
const pendingPlan = ref<TestPlan | null>(null), confirmClose = ref(false)
const busy = computed(() => state.loading.value || state.running.value || !!pendingPlan.value)
const canTest = computed(() => !busy.value && !!state.keyInfo.value?.active && !state.error.value)
const filtered = computed(() => state.models.value.filter(m => `${m.id} ${m.displayName}`.toLowerCase().includes(search.value.toLowerCase())))
const pageModels = computed(() => filtered.value.slice((page.value - 1) * limits.pageSize, page.value * limits.pageSize))
const detail = computed(() => state.results.value[detailId.value])
watch(search, () => { selected.value = []; page.value = 1 })
watch(() => state.models.value, () => { selected.value = []; overrides.value = Object.create(null); detailId.value = ''; page.value = 1 })
watch(() => [props.show, props.keyId] as const, ([show, id]) => {
  pendingPlan.value = null; confirmClose.value = false; search.value = ''; globalProfile.value = 'auto'; stream.value = false; includeImages.value = false
  if (show) void state.open(id)
  else state.close()
}, { immediate: true })
function setOverride(id: string, profile: ProfileChoice) { overrides.value = Object.assign(Object.create(null), overrides.value, { [id]: profile }) }
function refresh() { pendingPlan.value = null; void state.open(props.keyId) }
function prepare(ids: string[], single = false) {
  if (!canTest.value) return
  state.error.value = ''
  const plan = state.plan(ids, globalProfile.value, overrides.value, stream.value, includeImages.value, single)
  if (plan.selections.length > limits.batchSize) { state.notice.value = 'batchLimit'; return }
  detailId.value = single ? ids[0] : ''
  if (plan.selections.length && (!single || plan.imageCount > 0)) pendingPlan.value = plan
  else void state.start(plan)
}
function confirmRun() {
  const plan = pendingPlan.value; pendingPlan.value = null
  if (plan) void state.start(plan)
}
function requestClose() { if (state.running.value) confirmClose.value = true; else close() }
function close() { confirmClose.value = false; pendingPlan.value = null; state.close(); emit('close') }
</script>
