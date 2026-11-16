import { createApp, h } from 'vue'
import CoreConfirmDialog from '@/components/CoreConfirmDialog.vue'
// user:“确保视觉、功能和交互不退化”+(按 Ping 独立小窗口尺寸检查共享确认框)。
const host = document.createElement('div')
const result = document.createElement('div')
result.id = 'ping-confirm-result'
document.body.append(host, result)
createApp({ render: () => h(CoreConfirmDialog, { open: true, title: '撤回此消息及后续对话？', onConfirm: () => { result.textContent = '已确认' } }) }).mount(host)
