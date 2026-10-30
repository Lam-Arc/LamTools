import { ref } from 'vue'
// user:“设置中把它标记为实验性功能”+(分屏文件预览默认开启并标为实验性；用户可在通用设置里关掉)。
const STORAGE_KEY = 'lamtools:split-preview-experimental'
function readPreference(): boolean {
  try { return localStorage.getItem(STORAGE_KEY) !== 'off' } catch { return true }
}
const enabled = ref(readPreference())
export function splitPreviewEnabled(): boolean {
  return enabled.value
}
export function useSplitPreviewPreference() {
  return {
    enabled,
    setEnabled(value: boolean) {
      enabled.value = value
      try { localStorage.setItem(STORAGE_KEY, value ? 'on' : 'off') } catch { /* The switch still applies to this session. */ }
    },
  }
}
