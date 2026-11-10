/**
 * Computer Use 覆盖层入口：只做显示和停止入口，业务状态全部来自后端。
 */
import { createApp } from 'vue'
import ComputerUseOverlay from '@/computerUse/ComputerUseOverlay.vue'

const host = document.getElementById('computer-use-app')
if (host) {
  document.title = 'Sunday Computer Use · mounting'
  try {
    createApp(ComputerUseOverlay).mount(host)
    document.title = 'Sunday Computer Use · mounted'
  } catch (error) {
    document.title = `Sunday Computer Use · mount failed: ${
      error instanceof Error ? error.message : String(error)
    }`
  }
}
