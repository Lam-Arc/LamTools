/**
 * Desktop Overlay 入口：只挂载标注层，不加载主界面。
 */
import { createApp } from 'vue'
import OverlaySurface from '@/overlay/OverlaySurface.vue'

const host = document.getElementById('overlay-app')
if (host) {
  document.title = 'Sunday Overlay · mounting'
  try {
    createApp(OverlaySurface).mount(host)
    document.title = 'Sunday Overlay · mounted'
  } catch (error) {
    document.title = `Sunday Overlay · mount failed: ${
      error instanceof Error ? error.message : String(error)
    }`
  }
}
