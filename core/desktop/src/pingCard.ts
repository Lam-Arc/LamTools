/**
 * Ping 会话卡片窗口入口（卡片即窗口）。
 *
 * user:“卡片即窗口，把 ping 和桌宠拆分开”+(卡片不再画在桌宠覆盖层里：
 * 每张卡片一个独立窗口，自带会话通道，原生 Acrylic 磨砂直接作用在窗口上。)
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
// 与主界面/覆盖层同一套设计令牌与全局样式：卡片要复刻本体的聊天面板，
// 输入栏/消息区依赖这些全局样式（layout.css 等），单独引 tokens 会样式残缺。
import '@/styles/variables.css'
import '@/styles/base.css'
import '@/styles/layout.css'
import '@/styles/sunday-controls.css'
import PingCardWindow from '@/pet/ui/PingCardWindow.vue'

const host = document.getElementById('card-app')
if (host) {
  document.title = 'Sunday Ping · mounting'
  try {
    createApp(PingCardWindow).mount(host)
    document.title = 'Sunday Ping · mounted'
  } catch (error) {
    document.title = `Sunday Ping · mount failed: ${error instanceof Error ? error.message : String(error)}`
    throw error
  }
} else {
  document.title = 'Sunday Ping · no host element'
}
