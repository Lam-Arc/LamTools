<script setup lang="ts">
import { ref } from 'vue'
import TrayPanel from '@/tray/TrayPanel.vue'
import type * as TrayBridge from '@/tray/bridge'
// user:“交互测试”+(托盘示例只更改内存状态，不控制真实窗口或退出应用)。
const result = ref('')
const state = { pet_open: false, overlay_open: false, panel_open: true }
const services: typeof TrayBridge = {
  async panelState() { return { ...state } },
  async toggleTarget(target) { if (target === 'pet') state.pet_open = !state.pet_open; else state.overlay_open = !state.overlay_open },
  async panelMaterial() { return 'solid' },
  async fitPanel() {},
  async closePanel() { result.value = '关闭' },
  async revealMain() { result.value = '打开界面' },
  async quitApp() { result.value = '退出' },
}
</script>
<template><div><TrayPanel :services="services" /><span v-if="result">示例操作：{{ result }}</span></div></template>
