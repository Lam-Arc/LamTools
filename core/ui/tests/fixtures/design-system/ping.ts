import { createApp, h } from 'vue'
import CorePingEditor from '@/components/CorePingEditor.vue'
// user:“确保视觉、功能和交互不退化”+(使用本地桌面接口替身验证真实 Ping 下拉与浮层)。
;(globalThis as any).__TAURI_INTERNALS__ = { invoke: async () => null, transformCallback: () => 1 }
const host = document.createElement('div')
host.id = 'ping-fixture'
host.style.cssText = 'position:fixed; inset:0; z-index:300; overflow:auto; background:var(--theme-main-background)'
document.body.append(host)
createApp({ render: () => h(CorePingEditor) }).mount(host)
