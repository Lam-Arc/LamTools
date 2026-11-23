<script setup lang="ts">
import { reactive, ref } from 'vue'
import ProxyView from '../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/ProxyView.vue'

// user:“交互测试”+(订阅、节点和测速均为本地示例，不读取或发送真实订阅)。
const cancelSave = ref(false)
const session = reactive({
  busy: '', notice: '', error: '', accelerated: false,
  state: { proxy: { config_saved: false, running: false } },
  proxy: { mode: 'rule', proxies: {} as Record<string, { type?: string; all?: string[]; now?: string; history?: Array<{ delay: number }> }> },
  async run(method: string) {
    if (method === 'proxy.config') {
      if (cancelSave.value) return { cancelled: true }
      session.state.proxy.config_saved = true
    }
    if (method === 'proxy.delay') return { delay: 48 }
    return {}
  },
  async toggleProxy() {
    session.state.proxy.running = !session.state.proxy.running
    session.proxy.proxies = session.state.proxy.running ? {
      示例分组: { type: 'Selector', all: ['示例线路 A', '示例线路 B'], now: '示例线路 A' },
      '示例线路 A': { history: [{ delay: 65 }] }, '示例线路 B': { history: [] },
    } : {}
  },
  async selectNode(group: string, name: string) { const entry = session.proxy.proxies[group]; if (entry) entry.now = name },
  async loadProxy() {},
  async optimizeNode(group: string) { await session.selectNode(group, '示例线路 B'); return { candidates: [{ name: '示例线路 B', delay: 48 }] } },
  async toggleAcceleration() { session.accelerated = !session.accelerated },
})
</script>

<template>
  <div class="network-proxy-preview">
    <label><input v-model="cancelSave" type="checkbox" class="sunday-checkbox" />模拟取消保存</label>
    <div class="nx-app network-proxy-preview__surface"><ProxyView :session="session" /></div>
  </div>
</template>

<style scoped>
.network-proxy-preview { display: grid; gap: var(--space-3); width: 100%; }
.network-proxy-preview__surface { display: block; width: 100%; min-height: 0; height: auto; padding: var(--space-3); }
</style>
