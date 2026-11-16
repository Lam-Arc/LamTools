import { mountQuick } from '../../../../src/lamtools_core/plugins/bundled/network-exploration/ui/page.mjs'
import variables from '@/styles/variables.css?inline'
const style = document.createElement('style'); style.textContent = variables; document.head.append(style)
const host = document.createElement('div'); host.id = 'network-disabled-fixture'; document.body.append(host)
const snapshot = { revision: 4, settings: { mode: 'local', sample_seconds: 5 }, proxy: { running: true, config_saved: true }, downloads: [], transactions: [], rules: [], automations: [], history: [], reports: [], events: [] }
mountQuick(host, {
  visible: true, signal: new AbortController().signal, onVisibilityChange: () => () => {},
  rpc: async (method: string) => {
    if (method.endsWith('.status')) return snapshot
    if (method.endsWith('.proxy.inspect')) return { proxies: { Auto: { type: 'Selector', now: 'Tokyo', all: ['Tokyo', 'Singapore'] } } }
    if (method.endsWith('.proxy.stop')) return new Promise(() => {})
    return {}
  },
})
