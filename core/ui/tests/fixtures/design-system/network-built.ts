import { mount, mountQuick } from '../../../../src/lamtools_core/plugins/bundled/network-exploration/ui/page.mjs'
import variables from '@/styles/variables.css?inline'
// user:“确保视觉、功能和交互不退化”+(直接加载随应用分发的插件产物，检查自己的样式和节点请求)。
const style = document.createElement('style')
style.textContent = variables
document.head.append(style)
const host = document.createElement('div')
host.id = 'network-built-fixture'
document.body.replaceChildren(host)
const result = document.createElement('pre')
result.id = 'network-built-result'
document.body.append(result)
const snapshot = { revision: 4, settings: { mode: 'local', sample_seconds: 5 }, proxy: { running: true, config_saved: true }, downloads: [], transactions: [], rules: [], automations: [], history: [], reports: [], events: [] }
const context = {
  visible: true,
  signal: new AbortController().signal,
  onVisibilityChange: () => () => {},
  rpc: async (method: string, params: unknown) => {
    if (method.endsWith('.status')) return snapshot
    if (method.endsWith('.proxy.inspect')) return { proxies: { Auto: { type: 'Selector', now: 'Tokyo', all: ['Tokyo', 'Singapore'] } } }
    if (method.endsWith('.proxy.select')) { result.textContent = JSON.stringify(params); return {} }
    if (method.endsWith('.interfaces')) return { interfaces: [] }
    return {}
  },
}
mountQuick(host, context)
const main = document.createElement('div')
main.id = 'network-built-main'
document.body.append(main)
mount(main, context)
