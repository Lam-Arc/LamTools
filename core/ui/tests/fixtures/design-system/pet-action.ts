import { createApp, h } from 'vue'
import PetActionPanel from '@/components/PetActionPanel.vue'
// user:“确保视觉、功能和交互不退化”+(用真实组件和本地示例验证桌宠行为滑条的主题与尺寸)。
const host = document.createElement('div')
host.id = 'pet-action-fixture'
host.style.cssText = 'width: 650px; position: fixed; bottom: 0; left: 0; z-index: 10000;'
document.body.append(host)
const record = { id: 'sample', actions: {}, hitboxes: [], behavior: { enabled: true, activity: .5, restChance: .2, mouseBias: .3, exploreRadius: 400 } }
createApp({ render: () => h(PetActionPanel, { record: record as any }) }).mount(host)
