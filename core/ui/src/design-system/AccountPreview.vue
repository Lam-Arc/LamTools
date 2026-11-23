<script setup lang="ts">
import { ref } from 'vue'
import AccountShell from '@/components/AccountShell.vue'
import type { ThemeData } from '@/helpers/theme'
import type { RemoteConnectionServices } from '@/components/remoteConnectionServices'

// user:“交互测试”+(配对、状态和复制只在展厅内存模拟，不连接真实设备)。
defineProps<{ theme: ThemeData }>()
const failed = ref(false), copied = ref('')
let serving = false
let autoConnect = false
const services: RemoteConnectionServices = {
  async invoke(command, args) {
    // user:“交互测试”+(自动访问的选择只在本预览内记住)。
    if (command === 'p2p_config_set') {
      autoConnect = args?.autoConnect === true
      return { autoConnect }
    }
    if (command === 'get_api_base') return 'http://127.0.0.1:1234'
    if (command === 'p2p_ticket') { if (failed.value) throw new Error('示例服务失败'); serving = true; return { ticket: 'sunday1:example' } }
    if (command === 'p2p_status') return { running: serving, serving, autoConnect, expiresAt: serving ? Math.floor(Date.now() / 1000) + 180 : 0 }
    if (command === 'p2p_qr') return { svg: '<svg viewBox="0 0 100 100" role="img"><rect width="100" height="100" fill="white"/><rect x="20" y="20" width="60" height="60" fill="black"/></svg>' }
    if (command === 'p2p_serve_stop') { serving = false; return {} }
    return { devices: [], revoked: [] }
  },
  async copy(value) { copied.value = value },
}
</script>

<template>
  <div class="account-preview">
    <label><input v-model="failed" type="checkbox" class="sunday-checkbox" />模拟生成失败</label>
    <div class="account-preview__surface"><AccountShell :theme="theme" :app-runtime="{ platform: 'desktop' }" :remote-services="services" /></div>
    <span v-if="copied">本地复制：{{ copied }}</span>
  </div>
</template>

<style scoped>
.account-preview { display: grid; gap: var(--space-3); width: 100%; }
.account-preview__surface { height: 500px; overflow: auto; }
</style>
