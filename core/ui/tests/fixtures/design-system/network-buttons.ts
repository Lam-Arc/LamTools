import { createApp, h, nextTick, reactive } from 'vue'
import TransferView from '../../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/TransferView.vue'
import SecurityView from '../../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/SecurityView.vue'
import buttonStyles from '@/styles/sunday-button.css?inline'
import pluginStyles from '../../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/style.css?inline'
// user:“确保视觉、功能和交互不退化”+(实际网络页面按钮在浅暗主题下使用可读的共享配色)。
const style = document.createElement('style'); style.textContent = buttonStyles + pluginStyles; document.head.append(style)
const host = document.createElement('div'); host.id = 'network-buttons-fixture'; host.className = 'nx-app'; document.body.append(host)
const session = reactive({ state: { proxy: { running: false }, downloads: [], transactions: [] }, tasks: [], busy: '', run: async () => null, read: async () => ({ connections: [] }), loadTasks: async () => {} })
createApp({ render: () => h('main', [h(TransferView, { session }), h(SecurityView, { session })]) }).mount(host)
await nextTick()
host.querySelector('.nx-download-composer button')?.setAttribute('data-network-primary', '')
host.querySelector('.nx-section-heading .nx-button')?.setAttribute('data-network-secondary', '')
