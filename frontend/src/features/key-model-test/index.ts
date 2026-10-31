import { defineAsyncComponent } from 'vue'
export { KEY_MODEL_TEST_ENABLED } from './config'
export const KeyModelTestModal = defineAsyncComponent(() => import('./components/KeyModelTestModal.vue'))
