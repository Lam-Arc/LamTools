<script setup lang="ts">
import { reactive, ref } from 'vue'
import NetworkSettings from '../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/NetworkSettings.vue'
import SecurityView from '../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/SecurityView.vue'
import AdvancedView from '../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/AdvancedView.vue'

// user:“交互测试”+(所有系统设置、恢复、计划和设备数据均在内存中模拟)。
defineProps<{ view: 'settings' | 'security' | 'advanced' }>()
const action = ref('')
const session = reactive({
  busy: '', error: '', notice: '',
  interfaces: [{ index: 1, name: '示例网络', ipv4: ['192.0.2.5'], dns: ['192.0.2.1'], gateway: [] as string[] }],
  state: {
    revision: 1, settings: { sample_seconds: 5 }, rules: [] as Array<unknown>,
    automations: [] as Array<unknown>, events: [],
    transactions: [{ id: 'sample', request: { kind: 'dns' }, status: 'applied', time: '2026-01-01T00:00:00Z' }],
  },
  async read(method: string) {
    if (method === 'interfaces') return { interfaces: session.interfaces }
    if (method === 'lan') return { devices: [{ IPAddress: '192.0.2.10', LinkLayerAddress: '00:00:00:00:00:00', state: '示例' }] }
    return { connections: [{ process: '示例应用', path: 'C:\\example.exe' }] }
  },
  async run(method: string, params: Record<string, any> = {}) {
    action.value = method
    if (method === 'dns.query') return { domain: params.domain, addresses: ['192.0.2.1'], ms: 12 }
    if (method === 'system.restore') { const item = session.state.transactions.find(row => row.id === params.id); if (item) item.status = 'restored' }
    if (method === 'automation.save') session.state.automations = structuredClone(params.automations)
    if (method === 'settings.update') session.state.settings.sample_seconds = params.settings.sample_seconds
    if (method === 'rules.save') session.state.rules = structuredClone(params.rules)
    if (method === 'rules.test') return { matched: null, outbound: 'DIRECT' }
    if (method === 'automation.run') return { would_execute: { target: '示例网站' } }
    if (method === 'export') return null
    return {}
  },
})
</script>

<template>
  <div class="network-settings-preview">
    <div class="nx-app network-settings-preview__surface"><NetworkSettings v-if="view === 'settings'" :session="session" /><SecurityView v-else-if="view === 'security'" :session="session" /><AdvancedView v-else :session="session" /></div>
    <span v-if="action">本地操作：{{ action }}</span>
  </div>
</template>

<style scoped>
.network-settings-preview { display: grid; gap: var(--space-3); width: 100%; }
.network-settings-preview__surface { display: block; width: 100%; min-height: 0; height: auto; padding: var(--space-3); }
</style>
