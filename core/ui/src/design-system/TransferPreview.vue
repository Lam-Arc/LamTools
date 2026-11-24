<script setup lang="ts">
import { ref } from 'vue'
import SendToDeviceMenu from '@/components/SendToDeviceMenu.vue'
import TransferPanel from '@/components/TransferPanel.vue'

defineProps<{ mode: 'panel' | 'menu' }>()
const result = ref('')
const online = { id: 'sample-online', name: '示例笔记本', ticket: 'sample-only' }
const offline = { id: 'sample-offline', name: '示例平板', ticket: 'sample-only' }
const file = { path: 'C:/example/报告.pdf', name: '示例报告.pdf', size: 4096 }
let cancelled = false
const resumed = ref(false)

// user:“交互测试”+(示例状态保存在内存，操作不访问真实设备、文件或配对信息)。
async function invoke(command: string): Promise<unknown> {
  switch (command) {
    case 'p2p_devices':
      return { devices: [online, offline].map(({ id, name }) => ({ id, name })) }
    case 'p2p_status':
      return {
        devices: [{ id: online.id, name: online.name, path: 'direct' }],
        transfers: [{
          id: 'sample-transfer',
          direction: 'send',
          name: file.name,
          total: file.size,
          transferred: file.size / 2,
          percent: 50,
          source: file.path,
          state: cancelled ? 'cancelled' : 'transferring',
        }, {
          id: 'sample-resume',
          direction: 'send',
          name: '示例大文件.zip',
          total: 8192,
          transferred: 4096,
          percent: 50,
          source: 'C:/example/示例大文件.zip',
          state: resumed.value ? 'transferring' : 'failed',
        }],
        received: [{ transferId: 'sample-received', path: 'C:/example/说明.md', name: '说明.md', at: 2000 }],
      }
    case 'p2p_cancel_transfer':
      cancelled = true
      return {}
    case 'p2p_reveal_path':
      result.value = '定位文件'
      return {}
    case 'p2p_send_file':
      return { started: true, transferId: 'sample-transfer' }
    default:
      throw new Error('此操作没有本地示例')
  }
}

const previewPanel = { open: () => { result.value = '预览文件' } }
const previewMenu = { devices: () => [online, offline], sent: () => ({}) }
</script>

<template>
  <div class="transfer-preview">
    <TransferPanel
      v-if="mode === 'panel'"
      :invoke="invoke"
      :preview-services="previewPanel"
      @retry="resumed = true; result = '从已接收的 50% 继续传输'"
    />
    <SendToDeviceMenu
      v-else
      v-bind="file"
      :invoke="invoke"
      :preview-services="previewMenu"
      @sent="result = '开始传输'"
      @close="result = '关闭菜单'"
    />
    <span v-if="result">示例操作：{{ result }}</span>
  </div>
</template>

<style scoped>
.transfer-preview { width: 100%; }
</style>
