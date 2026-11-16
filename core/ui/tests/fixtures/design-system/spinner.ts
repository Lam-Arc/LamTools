import { createApp, h } from 'vue'
import RightSidebarRuntimeStatus from '../../../src/components/RightSidebarRuntimeStatus.vue'
import ArtifactPanel from '../../../src/components/ArtifactPanel.vue'
import PluginMarket from '../../../src/components/PluginMarket.vue'
import RightSidebarRag from '../../../src/components/RightSidebarRag.vue'
import RightSidebarWebSearch from '../../../src/components/RightSidebarWebSearch.vue'
// Load the host's plugin styles too: the market lives inside that page.
import '../../../src/styles/plugin-editor-states.css'

const target = document.createElement('div')
target.id = 'spinner-fixture'
document.body.append(target)
const pending = () => new Promise<Record<string, unknown>>(() => {})
createApp({ render: () => h('div', [
  h(RightSidebarRuntimeStatus, { status: 'running' }),
  h(ArtifactPanel, { projectId: 'sample', requestRpc: pending }),
  h(PluginMarket, { requestRpc: pending }),
  h(RightSidebarRag, { requestRpc: pending }),
  h(RightSidebarWebSearch, { requestRpc: pending, snapshot: { state: 'ok', blocks: [] } }),
]) }).mount(target)
