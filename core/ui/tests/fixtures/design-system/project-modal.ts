import { createApp, h, ref } from 'vue'
import CoreProjectCreate from '@/components/CoreProjectCreate.vue'
import CoreProjectPicker from '@/components/CoreProjectPicker.vue'
// user:“确保视觉、功能和交互不退化”+(使用本地示例检查项目弹窗的键盘交互，不访问实际项目)。
const transport = { request: async () => ({ status: 200, headers: {}, body: new TextEncoder().encode(JSON.stringify({ entries: [] })) }) }
const host = document.createElement('div'); host.id = 'project-modal-fixture'; document.body.append(host)
createApp({ setup() {
  const view = ref('')
  return () => h('div', [
    h('button', { id: 'open-project-picker', onClick: () => { view.value = 'picker' } }, '选择示例项目'),
    h('button', { id: 'open-project-create', onClick: () => { view.value = 'create' } }, '创建示例项目'),
    view.value === 'picker' ? h(CoreProjectPicker, { projects: [{ id: 'p', name: '示例项目', workRoot: 'E:/example', iconKey: 'folder', colorKey: 'gray' }], onCancel: () => { view.value = '' } }) : null,
    view.value === 'create' ? h(CoreProjectCreate, { transport: transport as any, onCancel: () => { view.value = '' } }) : null,
  ])
} }).mount(host)
