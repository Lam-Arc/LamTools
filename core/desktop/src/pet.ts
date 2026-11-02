/**
 * 桌宠覆盖层入口。
 *
 * 与主界面是两个文档、两个窗口：桌宠能够脱离主窗口独立运行，
 * 关掉主界面后仍然可以 Ping、看审批、完成真实工作交互。
 */
// user:“从你启动开始就一直是黑屏未响应状态”+(覆盖层页面必须能被外部看见进度：
// 窗口标题直接写加载到哪一步，出问题时不用打开 devtools 也知道卡在哪。)
document.title = 'Sunday Pet · loading'
window.addEventListener('error', event => {
  document.title = `Sunday Pet · error: ${event.message || 'unknown'}`
})
window.addEventListener('unhandledrejection', event => {
  const reason = event.reason instanceof Error ? event.reason.message : String(event.reason)
  document.title = `Sunday Pet · reject: ${reason}`
})

import './frontendConsoleLog'
import { createApp } from 'vue'
// user:“把样式也对齐，这是第一步”+(覆盖层文档加载主界面同一套设计令牌：
//  variables.css 令牌 / base.css 基础与滚动条 / optical-glass.css 玻璃原语；
//  主题变量由 PetSurface 的 useOverlayTheme 注入。)
import '@/styles/variables.css'
import '@/styles/base.css'
import '@/styles/optical-glass.css'
import PetSurface from '@/pet/ui/PetSurface.vue'
import '@/pet/ui/pet-surface.css'

const host = document.getElementById('pet-app')
if (host) {
  // 覆盖层每次都是全新加载：不保留上一次的滚动/焦点状态。
  // user:"内置默认就是方块人"+(入口模块不做 HMR 热替换；配置/默认角色的
  // 变更需要整页重载，boot 才会重新执行预设安装。)
  host.setAttribute('aria-label', 'Sunday 桌宠覆盖层')
  document.title = 'Sunday Pet · mounting'
  try {
    createApp(PetSurface).mount(host)
    document.title = 'Sunday Pet · mounted'
  } catch (error) {
    document.title = `Sunday Pet · mount failed: ${error instanceof Error ? error.message : String(error)}`
    throw error
  }
} else {
  document.title = 'Sunday Pet · no host element'
}
