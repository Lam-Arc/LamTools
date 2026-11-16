import { createApp, h } from 'vue'
import ComputerUseCapsule from '@/computerUse/ComputerUseCapsule.vue'
// user:“确保视觉、功能和交互不退化”+(状态条已迁移到独立覆盖窗口，按新入口验证按钮操作)。
const host = document.createElement('div')
host.style.cssText = 'position:fixed;inset:0'
const result = document.createElement('div')
result.id = 'status-result'
document.body.replaceChildren(host, result)
createApp({ render: () => h(ComputerUseCapsule, { onStop: () => { result.textContent = '已请求结束' } }) }).mount(host)
