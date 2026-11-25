<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import HomeView from '../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/HomeView.vue'
import DashboardView from '../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/DashboardView.vue'

// user:“交互测试”+(首页与加速页共用本地示例，所有操作只修改展厅内存)。
withDefaults(defineProps<{ view?: 'home' | 'dashboard' }>(), { view: 'home' })
const navigation = ref('')
const diagnostic = ref('')
const failDownload = ref(false)
const session = reactive({
  accelerated: false,
  busy: '',
  systemProxyReady: true,
  state: {
    traffic: { download: 4096, upload: 1024, received: 409600, sent: 102400 },
    proxy: { config_saved: false, running: false },
    history: [{ download: 4096, upload: 1024 }],
    events: [{ message: '示例加速已准备', time: '2026-01-01T00:00:00Z' }],
    download_default: 'C:\示例\Downloads',
    settings: { download: { concurrency: 3, max_tries: 5, bytes_per_second: 0, directory: '' } },
  },
  async pickDirectory() { return 'C:\示例\Downloads' },
  openFile() {},
  async refresh() {},
  proxy: null,
  tasks: [] as Array<{ status: string; downloadSpeed: number }>,
  async toggleAcceleration() { session.accelerated = !session.accelerated },
  async toggleProxy() { session.state.proxy.running = !session.state.proxy.running },
  async run(_method: string, _params: unknown, _notice: string) { if (failDownload.value) return false; session.tasks.push({ status: 'active', downloadSpeed: 4096 }); return true },
  async loadTasks() {},
  async diagnose(target: string) { return { report: { target } } },
})
const busy = computed({ get: () => Boolean(session.busy), set: (value: boolean) => { session.busy = value ? 'sample' : '' } })
</script>

<template>
  <div class="network-home-preview">
    <label v-if="view === 'home'"><input v-model="session.state.proxy.config_saved" type="checkbox" class="sunday-checkbox" />模拟已有订阅</label>
    <label v-if="view === 'home'"><input v-model="failDownload" type="checkbox" class="sunday-checkbox" />模拟下载失败</label>
    <label><input v-model="busy" type="checkbox" class="sunday-checkbox" />模拟处理中</label>
    <div class="nx-app network-home-preview__surface"><HomeView v-if="view === 'home'" :session="session" @navigate="navigation = $event" /><DashboardView v-else :session="session" @navigate="navigation = $event" @diagnostic="diagnostic = $event.target" /></div>
    <span v-if="navigation">本地导航：{{ navigation }}</span>
    <span v-if="diagnostic">本地检查：{{ diagnostic }}</span>
  </div>
</template>

<style scoped>
.network-home-preview { display: grid; gap: var(--space-3); width: 100%; }
.network-home-preview__surface { display: block; width: 100%; min-height: 0; height: auto; padding: var(--space-3); }
</style>
