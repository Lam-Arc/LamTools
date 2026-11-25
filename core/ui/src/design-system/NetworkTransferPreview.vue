<script setup lang="ts">
import { reactive, ref } from 'vue'
import TransferView from '../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/TransferView.vue'

// user:“交互测试”+(模拟下载任务与操作，不访问网络、文件或系统下载器)。
const result = ref('')
const failLimit = ref(false)
const session = reactive({
  busy: '', error: '', notice: '',
  state: {
    proxy: { running: false },
    downloads: [],
    download_default: 'C:\示例\Downloads',
    settings: { download: { concurrency: 3, max_tries: 5, bytes_per_second: 0, directory: '' } },
  },
  async pickDirectory() { return 'C:\示例\Downloads' },
  openFile() {},
  async refresh() {},
  tasks: [
    { gid: 'sample-active', filename: '示例文件.zip', status: 'active', completedLength: 512, totalLength: 1024, downloadSpeed: 128 },
    { gid: 'sample-complete', filename: '已完成.pdf', status: 'complete', completedLength: 1024, totalLength: 1024, downloadSpeed: 0 },
  ],
  async loadTasks() {},
  async run(method: string, payload: Record<string, unknown> = {}) {
    result.value = `${method} ${JSON.stringify(payload)}`
    if (method === 'transfer.action' && payload.action === 'limit' && failLimit.value) return null
    if (method === 'transfer.action') {
      const task = session.tasks.find(item => item.gid === payload.gid)
      if (task && payload.action === 'pause') task.status = 'paused'
      if (task && payload.action === 'resume') task.status = 'active'
      if (task && payload.action === 'cancel') task.status = 'removed'
    }
    if (method === 'transfer.add') session.tasks.push({ gid: `sample-${session.tasks.length}`, filename: '新示例下载', status: 'waiting', completedLength: 0, totalLength: 1024, downloadSpeed: 0 })
    return { verified: true }
  },
})
</script>

<template>
  <div class="network-transfer-preview">
    <label><input v-model="failLimit" type="checkbox" class="sunday-checkbox" />模拟限速失败</label>
    <div class="nx-app network-transfer-preview__surface"><TransferView :session="session" /></div>
    <span v-if="result" data-local-network-action>本地操作：{{ result }}</span>
  </div>
</template>

<style scoped>
.network-transfer-preview { display: grid; gap: var(--space-3); width: 100%; }
.network-transfer-preview__surface { display: block; width: 100%; min-height: 0; height: auto; padding: var(--space-3); }
</style>
