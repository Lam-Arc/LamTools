import { createDomFilePicker, type RuntimeFileCapabilities } from '@lamtools/ui/app/runtime'

/**
 * Capacitor's WebView delegates an input click to the platform document
 * picker. Keeping that implementation here makes the shared app unaware of
 * DOM inputs while leaving room for a native file-picker plugin later.
 */
export function createMobileFilePicker(): RuntimeFileCapabilities {
  return createDomFilePicker()
}
