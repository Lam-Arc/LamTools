import { createApp, h, ref } from 'vue'
import CoreUpdateCard from '@/components/CoreUpdateCard.vue'
// user:“确保视觉、功能和交互不退化”+(更新窗口使用本地示例，不执行真实更新)。
const host = document.createElement('div'); host.id = 'update-card-fixture'; document.body.append(host)
createApp({ setup() {
  const open = ref(false), origin = ref<HTMLElement | null>(null)
  return () => h('div', [
    h('button', { id: 'open-update-preview', ref: origin, onClick: () => { open.value = true } }, '打开示例更新'),
    open.value ? h(CoreUpdateCard, { origin: origin.value, currentVersion: '1.0', latestVersion: '2.0', notes: '本地示例', onClosed: () => { open.value = false } }) : null,
  ])
} }).mount(host)
