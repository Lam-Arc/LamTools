import { createApp, h } from 'vue'
import CoreModelCatalog from '../../../src/components/CoreModelCatalog.vue'
import CorePluginSystemEditor from '../../../src/components/CorePluginSystemEditor.vue'
import DirectCallView from '../../../src/components/DirectCallView.vue'

const pending = () => new Promise<Record<string, unknown>>(() => {})
const modelRpc = (method: string) => method === 'config.providers.status' ? Promise.resolve({ providers: {} }) : pending()
const target = document.createElement('div')
target.id = 'spinner-page-fixture'
document.body.append(target)
createApp({ render: () => h('div', [
  h(CoreModelCatalog, { models: [], providers: [], requestRpc: modelRpc }),
  h(CorePluginSystemEditor, { requestRpc: pending }),
  h(DirectCallView, { requestRpc: pending }),
]) }).mount(target)
