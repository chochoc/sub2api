<template>
  <section class="space-y-4 rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-dark-600 dark:bg-dark-900" :aria-label="t('keyModelTest.details')">
    <div class="flex items-center justify-between gap-2">
      <h4 class="break-all font-semibold">{{ result.modelId }}</h4>
      <button type="button" class="btn btn-secondary min-h-11" @click="copyToClipboard(diagnosticSummary(result))">{{ t('keyModelTest.copyDiagnostics') }}</button>
    </div>
    <dl class="grid gap-2 text-sm sm:grid-cols-2">
      <div v-for="item in fields" :key="item.label" class="min-w-0"><dt class="text-gray-500 dark:text-gray-400">{{ item.label }}</dt><dd class="break-all">{{ item.value }}</dd></div>
    </dl>
    <p role="status">{{ t(`keyModelTest.messages.${result.summary}`) }}</p>
    <p v-if="result.errorMessage" class="break-words text-sm text-red-700 dark:text-red-400">{{ result.errorMessage }}</p>
    <pre v-if="result.textPreview" class="max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-white p-3 text-sm dark:bg-dark-800">{{ result.textPreview }}</pre>
    <div v-if="previewUrl">
      <img v-if="!previewFailed" :src="previewUrl" :alt="t('keyModelTest.generatedImage')" referrerpolicy="no-referrer" class="max-h-80 max-w-full rounded-lg object-contain" @error="previewFailed = true" />
      <p v-else>{{ t('keyModelTest.previewFailed') }}</p>
    </div>
    <p v-else-if="result.imageCount">{{ t('keyModelTest.previewReleased') }}</p>
    <p class="text-sm text-gray-500 dark:text-gray-400">{{ t('keyModelTest.usageNotice') }} <RouterLink to="/usage" class="text-primary-600 underline dark:text-primary-400">{{ t('keyModelTest.usageLink') }}</RouterLink></p>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useClipboard } from '@/composables/useClipboard'
import { formatDateTime } from '@/utils/format'
import { diagnosticSummary } from '../resultSanitizer'
import type { ModelTestResult } from '../types'

const props = defineProps<{ result: ModelTestResult; previewUrl?: string }>()
const { t } = useI18n()
const { copyToClipboard } = useClipboard()
const previewFailed = ref(false)
watch(() => props.previewUrl, () => { previewFailed.value = false })
const fields = computed(() => {
  const r = props.result
  const missing = t('keyModelTest.notReported')
  const values: Record<string, string | number> = {
    status: t(`keyModelTest.status.${r.status}`), profile: r.profile ? t(`keyModelTest.profiles.${r.profile}`) : '—',
    endpoint: r.profile ? ({ responses: '/v1/responses', chat_completions: '/v1/chat/completions', messages: '/v1/messages', images: '/v1/images/generations', gemini_text: r.stream ? '/v1beta/models/{model}:streamGenerateContent?alt=sse' : '/v1beta/models/{model}:generateContent', gemini_image: '/v1beta/models/{model}:generateContent' }[r.profile]) : '—',
    stream: t(r.stream ? 'keyModelTest.enabled' : 'keyModelTest.disabled'), startedAt: r.startedAt ? formatDateTime(r.startedAt) : '—',
    duration: `${r.durationMs} ms`, firstContent: r.firstContentMs === undefined ? missing : `${r.firstContentMs} ms`,
    httpStatus: r.httpStatus ?? missing, requestId: r.gatewayRequestId || missing, responseModel: r.responseModel || missing,
    inputTokens: r.usage?.inputTokens ?? missing, outputTokens: r.usage?.outputTokens ?? missing,
    totalTokens: r.usage?.totalTokens ?? missing, cachedTokens: r.usage?.cachedInputTokens ?? missing,
    images: r.imageCount ?? missing, errorCode: r.errorCode || '—'
  }
  return Object.entries(values).map(([key, value]) => ({ label: t(`keyModelTest.fields.${key}`), value }))
})
</script>
