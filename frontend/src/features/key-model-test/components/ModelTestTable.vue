<template>
  <div>
    <label class="mb-2 flex min-h-11 items-center gap-2 text-sm">
      <input type="checkbox" :checked="allSelected" :disabled="disabled || !models.length" @change="selectPage(($event.target as HTMLInputElement).checked)" />
      {{ t('keyModelTest.selectPage') }}
    </label>
    <DataTable :columns="columns" :data="models" row-key="id">
      <template #cell-select="{ row }">
        <label class="inline-flex min-h-11 min-w-11 items-center justify-center">
          <input type="checkbox" :checked="selected.includes(row.id)" :disabled="disabled" :aria-label="t('keyModelTest.selectModel', { model: row.id })" @change="select(row.id, ($event.target as HTMLInputElement).checked)" />
        </label>
      </template>
      <template #cell-id="{ row }">
        <div class="max-w-[18rem] break-all font-mono text-sm">{{ row.id }}</div>
        <div v-if="row.displayName !== row.id" class="max-w-[18rem] break-words text-xs text-gray-500 dark:text-gray-400">{{ row.displayName }}</div>
      </template>
      <template #cell-profile="{ row }">
        <select class="input min-h-11 max-w-[13rem] text-sm" :value="overrides[row.id] || 'auto'" :disabled="disabled" :aria-label="t('keyModelTest.profileFor', { model: row.id })" @change="emit('override', row.id, ($event.target as HTMLSelectElement).value as ProfileChoice)">
          <option value="auto">{{ t('keyModelTest.inherit') }}</option>
          <option v-for="profile in profiles" :key="profile" :value="profile">{{ t(`keyModelTest.profiles.${profile}`) }}</option>
        </select>
        <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">{{ profileLabel(row) }}</p>
      </template>
      <template #cell-status="{ row }">
        <span class="text-sm font-medium" :class="statusClass(results[row.id]?.status)">{{ t(`keyModelTest.status.${results[row.id]?.status || 'untested'}`) }}</span>
      </template>
      <template #cell-result="{ row }">
        <div v-if="results[row.id]" class="max-w-[16rem] break-words text-sm">
          {{ t(`keyModelTest.messages.${results[row.id].summary}`) }}
          <span v-if="results[row.id].durationMs"> · {{ results[row.id].durationMs }} ms</span>
        </div>
        <span v-else>—</span>
      </template>
      <template #cell-actions="{ row }">
        <div class="flex flex-wrap gap-2">
          <button type="button" class="btn btn-primary min-h-11" :disabled="disabled || !resolveProfile(row, globalProfile, overrides[row.id]).profile" @click="emit('test', row.id)">{{ t('keyModelTest.test') }}</button>
          <button v-if="results[row.id]" type="button" class="btn btn-secondary min-h-11" @click="emit('details', row.id)">{{ t('keyModelTest.details') }}</button>
        </div>
      </template>
      <template #empty><p class="p-6 text-center text-sm">{{ t('keyModelTest.noModels') }}</p></template>
    </DataTable>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import DataTable from '@/components/common/DataTable.vue'
import { profiles, type CatalogModel, type ModelTestResult, type ProfileChoice } from '../types'
import { resolveProfile } from '../testProfiles'

const props = defineProps<{ models: CatalogModel[]; results: Record<string, ModelTestResult>; selected: string[]; overrides: Record<string, ProfileChoice>; globalProfile: ProfileChoice; disabled: boolean }>()
const emit = defineEmits<{ 'update:selected': [ids: string[]]; override: [id: string, profile: ProfileChoice]; test: [id: string]; details: [id: string] }>()
const { t } = useI18n()
const columns = computed(() => ['select', 'id', 'profile', 'status', 'result', 'actions'].map(key => ({ key, label: t(`keyModelTest.columns.${key}`), sortable: false })))
const allSelected = computed(() => props.models.length > 0 && props.models.every(m => props.selected.includes(m.id)))
function select(id: string, checked: boolean) {
  emit('update:selected', checked ? [...new Set([...props.selected, id])] : props.selected.filter(value => value !== id))
}
function selectPage(checked: boolean) {
  const page = new Set(props.models.map(m => m.id))
  emit('update:selected', checked ? [...new Set([...props.selected, ...page])] : props.selected.filter(id => !page.has(id)))
}
function profileLabel(model: CatalogModel) {
  const resolved = resolveProfile(model, props.globalProfile, props.overrides[model.id])
  return resolved.profile ? t(`keyModelTest.profiles.${resolved.profile}`) : t(`keyModelTest.messages.${resolved.reason}`)
}
function statusClass(status?: string) {
  if (status === 'success') return 'text-green-700 dark:text-green-400'
  if (['failed', 'timeout'].includes(status || '')) return 'text-red-700 dark:text-red-400'
  return 'text-gray-700 dark:text-gray-300'
}
</script>
