export const KEY_MODEL_TEST_ENABLED = import.meta.env.VITE_KEY_MODEL_TEST_ENABLED === 'true'

export const limits = Object.freeze({
  catalogTimeoutMs: 30_000,
  textTimeoutMs: 90_000,
  imageTimeoutMs: 180_000,
  batchSize: 50,
  pageSize: 30,
  catalogBytes: 2 * 1024 * 1024,
  catalogItems: 5000,
  textBytes: 2 * 1024 * 1024,
  eventBytes: 1024 * 1024,
  imageResponseBytes: 32 * 1024 * 1024,
  previewChars: 4000,
  errorChars: 512,
  imageBytes: 16 * 1024 * 1024,
  previewBytes: 48 * 1024 * 1024,
  previewCount: 3
})

export const TEXT_PROMPT = 'Reply with exactly OK.'
export const IMAGE_PROMPT = 'Generate one simple blue circle on a plain white background.'
