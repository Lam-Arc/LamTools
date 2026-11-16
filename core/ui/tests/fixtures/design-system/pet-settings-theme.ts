import { createApp } from 'vue'
// user:“确保视觉、功能和交互不退化”+(本地桌面接口示例不读写用户配置)。
;(globalThis as any).__TAURI_INTERNALS__ = { invoke: async () => null, transformCallback: () => 1, unregisterCallback: () => {} }
const { default: CorePetEditor } = await import('@/components/CorePetEditor.vue')
const host = document.createElement('div')
host.id = 'pet-settings-theme-fixture'
host.style.width = '800px'
document.body.append(host)
createApp(CorePetEditor).mount(host)
