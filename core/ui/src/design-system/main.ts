import { createApp } from 'vue'
import Gallery from './Gallery.vue'
import { DEFAULT_THEME, themeToCSSVars } from '@/helpers/theme'
import '@/styles/variables.css'
import '@/styles/base.css'
// user:“直接渲染项目真实组件”+(设置预览加载主应用真实的卡片与布局样式)。
import '@/styles/layout.css'
import '@/styles/app-page.css'
// user:“直接渲染项目真实组件”+(学习侧栏预览加载主窗口的导航样式)。
import '@/styles/workspace-shell.css'
// user:“直接渲染项目真实组件”+(主题区域预览使用应用中的主题编辑器样式)。
import '@/styles/theme-editor.css'
import '@/styles/sunday-controls.css'
// user:“直接渲染项目真实组件”+(网速图表使用网络工具原有样式与主题映射)。
import '../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/style.css'
// user:“直接渲染项目真实组件”+(消息示例使用会话区生产样式)。
import '@/styles/chat-thread-shell.css'
import '@/styles/chat-thread-tools.css'
import '@/styles/chat-thread-cards.css'
import '@/styles/chat-thread-process.css'
import '@/styles/chat-thread-reasoning.css'
import '@/styles/chat-thread-editing.css'
// user:“直接渲染项目真实组件”+(资料库确认预览使用实际页面共享样式)。
import '@/styles/library-surface.css'
// user:“直接渲染项目真实组件”+(状态胶囊使用与应用相同的玻璃材质)。
import '@/styles/optical-glass.css'

// user:“直接渲染项目真实组件”+(展厅使用应用的默认主题，包括传送到 body 的浮层)
for (const [name, value] of Object.entries(themeToCSSVars(DEFAULT_THEME))) {
  document.documentElement.style.setProperty(name, value)
}
document.body.style.background = 'var(--theme-main-background)'
createApp(Gallery).mount('#app')
