/**
 * Ping 独立覆盖层入口。
 *
 * user:“你看看 ping 环 要不也自己做窗口？”+(环/标记/标注/选择器在独立的全屏
 * 透明窗口里，桌宠关掉/禁用不影响 Ping 入口。)
 */
// 与覆盖层一样：页面错误要能从外部看见进度。
document.title = 'Sunday Ping · loading'
window.addEventListener('error', event => {
  document.title = `Sunday Ping · error: ${event.message || 'unknown'}`
})
window.addEventListener('unhandledrejection', event => {
  const reason = event.reason instanceof Error ? event.reason.message : String(event.reason)
  document.title = `Sunday Ping · reject: ${reason}`
})

import './frontendConsoleLog'
import { createApp } from 'vue'
// 设计令牌与主界面同一套（主题变量由 useOverlayTheme 注入）。
import '@/styles/variables.css'
import '@/styles/base.css'
import PingSurface from '@/pet/ui/PingSurface.vue'

const host = document.getElementById('ping-app')
if (host) {
  host.setAttribute('aria-label', 'Sunday Ping 覆盖层')
  document.title = 'Sunday Ping · mounting'
  try {
    createApp(PingSurface).mount(host)
    document.title = 'Sunday Ping · mounted'
  } catch (error) {
    document.title = `Sunday Ping · mount failed: ${error instanceof Error ? error.message : String(error)}`
    throw error
  }
} else {
  document.title = 'Sunday Ping · no host element'
}
