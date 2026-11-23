<script setup lang="ts">
import { reactive, ref } from 'vue'
import ConnectionsView from '../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/ConnectionsView.vue'
import DiagnoseView from '../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/DiagnoseView.vue'

// user:“交互测试”+(连接列表和网站检测仅使用示例数据，不读取系统连接或访问网络)。
defineProps<{ view: 'connections' | 'diagnose' }>()
const kind = ref('')
const examples = [
  { process: '示例浏览器', pid: 10, local_port: 1234, remote_address: '192.0.2.1', remote_port: 443, protocol: 'TCP', state: 'Established' },
  { process: '示例工具', pid: 11, local_port: 4567, remote_address: '192.0.2.2', remote_port: 80, protocol: 'TCP', state: 'Listen' },
]
const session = reactive({
  busy: '', state: { reports: [] },
  async read(_method: string, params: { filter?: string }) {
    const connections = examples.filter(row => JSON.stringify(row).includes(params.filter || ''))
    return { connections, total: connections.length }
  },
  async diagnose(target: string, selectedKind: string) {
    kind.value = selectedKind
    return { report: { target, failures: 0, time: '2026-01-01T00:00:00Z', checks: [{ stage: 'DNS', ok: true, evidence: '示例地址', ms: 12 }] } }
  },
})
</script>

<template>
  <div class="network-inspection-preview">
    <div class="nx-app network-inspection-preview__surface"><ConnectionsView v-if="view === 'connections'" :session="session" /><DiagnoseView v-else :session="session" /></div>
    <span v-if="kind">本地检查方式：{{ kind }}</span>
  </div>
</template>

<style scoped>
.network-inspection-preview { display: grid; gap: var(--space-3); width: 100%; }
.network-inspection-preview__surface { display: block; width: 100%; min-height: 0; height: auto; padding: var(--space-3); }
</style>
