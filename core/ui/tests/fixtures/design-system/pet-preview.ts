import { createApp, h } from 'vue'
import PetPreview from '@/pet/ui/PetPreview.vue'
// user:“确保视觉、功能和交互不退化”+(本地运行桌宠预览，检查菜单在覆盖层上可点击)。
const host = document.createElement('div')
host.id = 'pet-preview-fixture'
host.style.cssText = 'position:fixed; inset:0; z-index:300'
document.body.append(host)
const runtime = { importer: { analysis: null, spriteWidth: 128, spriteHeight: 128, scale: 1 }, cancelImport() {}, confirmImport: async () => {} }
createApp({ render: () => h(PetPreview, { runtime: runtime as any }) }).mount(host)
