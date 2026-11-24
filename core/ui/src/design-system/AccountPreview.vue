<script setup lang="ts">
import { ref } from 'vue'
import AccountShell from '@/components/AccountShell.vue'
import type { ThemeData } from '@/helpers/theme'
import type { RemoteConnectionServices } from '@/components/remoteConnectionServices'

// user:“交互测试”+(配对、状态和复制只在展厅内存模拟，不连接真实设备)。
defineProps<{ theme: ThemeData }>()
const failed = ref(false), copied = ref('')
// user:“三项全做”+(模拟换码和二维码失败，开机选项独立保存)。
const qrFailed = ref(false)
let codeNumber = 0
let expiresAt = 0
// user:“针对远程连接/设备配对 去查修目前用户体验最差的一点，并列出接下来的候选”+(展厅可模拟扫码后的桌面确认步骤)。
const simulateScan = ref(false)
const exampleDevice = { id: 'example-phone', name: '示例手机' }
let pending = false
let trusted = false
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
    if (command === 'p2p_ticket') {
      if (failed.value) throw new Error('示例服务失败')
      serving = true
      pending = simulateScan.value && !trusted
      codeNumber++
      expiresAt = Math.floor(Date.now() / 1000) + 300
      return { ticket: `sunday2:example-${codeNumber}`, expiresAt }
    }
    if (command === 'p2p_status') return { running: serving, serving, autoConnect, pending: pending ? [exampleDevice] : [], ticket: serving ? `sunday2:example-${codeNumber}` : '', expiresAt: serving ? expiresAt : 0 }
    if (command === 'p2p_qr') {
      if (qrFailed.value) throw new Error('示例二维码生成失败')
      return { svg: '<svg viewBox="0 0 100 100" role="img"><rect width="100" height="100" fill="white"/><rect x="20" y="20" width="60" height="60" fill="black"/></svg>' }
    }
    if (command === 'p2p_serve_stop') { serving = false; pending = false; return {} }
    if (command === 'p2p_confirm_device' || command === 'p2p_reject_device') {
      trusted = command === 'p2p_confirm_device'
      pending = false
    }
    if (command === 'p2p_revoke') trusted = false
    return { devices: trusted ? [exampleDevice] : [], revoked: [] }
  },
  async copy(value) { copied.value = value },
}
</script>

<template>
  <div class="account-preview">
    <label><input v-model="failed" type="checkbox" class="sunday-checkbox" />模拟传输服务启动失败</label>
    <label><input v-model="qrFailed" type="checkbox" class="sunday-checkbox" />模拟二维码图片生成失败</label>
    <label><input v-model="simulateScan" type="checkbox" class="sunday-checkbox" />生成二维码后模拟设备扫码</label>
    <div class="account-preview__surface"><AccountShell :theme="theme" :app-runtime="{ platform: 'desktop' }" :remote-services="services" /></div>
    <span v-if="copied">本地复制：{{ copied }}</span>
  </div>
</template>

<style scoped>
.account-preview { display: grid; gap: var(--space-3); width: 100%; }
.account-preview__surface { height: 500px; overflow: auto; }
</style>
