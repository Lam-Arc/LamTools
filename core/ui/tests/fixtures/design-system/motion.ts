import { createApp, h } from 'vue'
import PingRing from '@/pet/ui/PingRing.vue'
import appStyles from '@/styles/app-page.css?inline'
import pluginDetails from '@/styles/plugin-editor-details.css?inline'
import pluginStates from '@/styles/plugin-editor-states.css?inline'
// user:“梳理所有可见的组件、样式、布局、动效及交互”+(用实际状态样式和 Ping 环验证减少动态效果)。
const style = document.createElement('style')
style.textContent = appStyles + pluginDetails + pluginStates
document.head.append(style)
const host = document.createElement('div')
host.id = 'motion-fixture'
document.body.append(host)
const tier = { visible: true, radius: 140, width: 40, sectors: [{ id: 'child', icon: '', label: '示例' }], slots: [1], span: 1, start: 0, hovered: '' }
const ping = { overlay: { x: 0, y: 0, width: innerWidth }, ring: { visible: true, x: 400, y: 300, hovered: '', sectors: [{ id: 'a', kind: 'chat', icon: '', label: '示例' }] }, config: { ping: { radius: 100, ringWidth: 30 } }, tiers: { l2: tier, l3: { ...tier, visible: false }, expanded: '' } }
createApp({ render: () => h('div', [h('span', { class: 'core-remote-badge is-lost' }, '离线'), h('span', { class: 'plugin-status-row is-pending' }, [h('span', { class: 'plugin-status-dot' })]), h(PingRing, { ping: ping as any })]) }).mount(host)
