import { createApp, h, reactive } from 'vue'
import NetworkSettings from '../../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/NetworkSettings.vue'
import pluginStyles from '../../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/style.css?inline'
import selectStyles from '@/styles/ui-select.css?inline'
// user:“确保视觉、功能和交互不退化”+(隔离插件样式，验证真实网络表单和本地示例请求)。
const style = document.createElement('style')
style.textContent = pluginStyles + selectStyles
document.head.append(style)
const host = document.createElement('div')
host.id = 'network-settings-fixture'
host.className = 'nx-app'
host.style.cssText = 'position:fixed; inset:0; z-index:300; overflow:auto'
document.body.append(host)
const result = document.createElement('pre')
result.id = 'network-settings-result'
host.append(result)
const mount = document.createElement('div')
host.append(mount)
const session = reactive({ state: { revision: 2, rules: [] }, interfaces: [{ index: 4, name: '以太网' }], busy: '', run: async (_method: string, payload: unknown) => { result.textContent = JSON.stringify(payload); return null }, read: async () => ({ interfaces: [] }) })
createApp({ render: () => h(NetworkSettings, { session }) }).mount(mount)
