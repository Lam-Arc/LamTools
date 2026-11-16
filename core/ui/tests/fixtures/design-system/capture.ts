import { createApp, h } from 'vue'
import CaptureEditor from '@/pet/ui/CaptureEditor.vue'
// user:“确保视觉、功能和交互不退化”+(独立截图窗口仍填满视口，与嵌入沙盒分开验证)。
const host = document.createElement('div')
host.id = 'capture-fixture'
document.body.append(host)
const width = 600, height = 400
const frame = { x: 0, y: 0, width, height, scale: 1, data: new Uint8Array(width * height * 4) }
createApp({ render: () => h(CaptureEditor, { frame: frame as any, busy: false, error: '' }) }).mount(host)
