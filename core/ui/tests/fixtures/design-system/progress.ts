import { createApp, h } from 'vue'
import PluginRegionBlocks from '@/components/PluginRegionBlocks.vue'
import RightSidebarWidgetRenderer from '@/components/RightSidebarWidgetRenderer.vue'
// user:“确保视觉、功能和交互不退化”+(用本地示例核对插件和侧栏进度的真实样式)。
const host = document.createElement('div'); host.id = 'progress-fixture'; host.style.cssText = 'width:600px; position:relative'; document.body.append(host)
createApp({ render: () => h('div', [
  h(PluginRegionBlocks, { regions: [{ plugin: 'demo', region: 'main', order: 0, actions: [], blocks: [{ type: 'progress', label: '插件进度', value: 50, max: 100 }] }] as any, requestRpc: async () => ({}) }),
  h(RightSidebarWidgetRenderer, { entry: { pluginId: 'demo', id: 'widget', title: '示例', renderer: 'blocks' } as any, snapshot: { blocks: [{ type: 'progress', label: '侧栏进度', value: 50, max: 100 }] } as any }),
]) }).mount(host)
