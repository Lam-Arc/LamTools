/**
 * 托盘面板入口：只挂载那张小卡片，不加载主界面。
 *
 * user:“托盘样式重做”“只做自绘面板”+(点托盘图标弹的是自家窗口，
 * 所以这里和覆盖层一样：独立文档、独立挂载，窗口标题写出挂载进度方便排查。)
 */
document.title = 'Sunday 托盘面板 · loading'
window.addEventListener('error', event => {
  document.title = `Sunday 托盘面板 · error: ${event.message || 'unknown'}`
})

import './frontendConsoleLog'
import { createApp } from 'vue'
// 与主界面、覆盖层同一套设计令牌：主题变量由 TrayPanel 的 useOverlayTheme 注入。
import '@/styles/variables.css'
import '@/styles/base.css'
// 开关用的是主界面同一套 SundaySwitch，缺这份样式表就会退化成系统复选框。
import '@/styles/sunday-controls.css'
import TrayPanel from '@/tray/TrayPanel.vue'

const host = document.getElementById('tray-app')
if (host) {
  document.title = 'Sunday 托盘面板 · mounting'
  try {
    createApp(TrayPanel).mount(host)
    document.title = 'Sunday 托盘面板 · mounted'
  } catch (error) {
    document.title = `Sunday 托盘面板 · mount failed: ${
      error instanceof Error ? error.message : String(error)
    }`
    throw error
  }
} else {
  document.title = 'Sunday 托盘面板 · no host element'
}
