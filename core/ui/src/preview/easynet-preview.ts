// user:“整个 easynet 与其相关界面，浏览器打开我随时看”+(独立预览页：用真实组件 + 本地示例数据，不连后端)。
import { createApp, reactive } from 'vue'
import NetworkApp from '../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/NetworkApp.vue'
import pluginCss from '../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/style.css?inline'
import redesignCss from '../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/redesign.css?inline'
import buttonCss from '../styles/sunday-button.css?inline'
import switchCss from '../styles/sunday-switch.css?inline'
import selectCss from '../styles/ui-select.css?inline'

const now = () => new Date().toISOString()
// 预览数据形状故意宽松：示例行之间字段不完全一致。
const state: any = reactive({
  revision: 3,
  settings: {
    mode: 'local',
    sample_seconds: 5,
    download: { concurrency: 3, max_tries: 5, bytes_per_second: 0, directory: '' },
  },
  proxy: { running: true, config_saved: true },
  accelerator: { running: true, port: 49231 },
  traffic: { download: 3560000, upload: 220000, received: 14_300_000_000, sent: 1_200_000_000 },
  history: Array.from({ length: 40 }, (_, i) => ({ download: 900_000 + Math.round(Math.sin(i / 3) * 600_000) + i * 30_000, upload: 120_000 })),
  downloads: [
    { gid: 'a1', filename: 'ubuntu-24.04-desktop-amd64.iso', status: 'active', totalLength: '5900000000', completedLength: '2300000000', downloadSpeed: '3200000', directory: 'C:\\Users\\Administrator\\Downloads', source: 'browser', route: 'auto' },
    { gid: 'a2', filename: 'Sunday-Setup-0.3.43.exe', status: 'paused', totalLength: '82000000', completedLength: '41000000', downloadSpeed: '0', directory: 'C:\\Users\\Administrator\\Downloads', source: 'tool', route: 'auto' },
    { gid: 'a3', filename: 'zhihu-weekly-notes.pdf', status: 'complete', totalLength: '2400000', completedLength: '2400000', downloadSpeed: '0', directory: 'C:\\Users\\Administrator\\Downloads', source: 'page', route: 'auto' },
    { gid: 'a4', filename: 'broken-asset.zip', status: 'error', errorCode: '3', errorText: '源站返回 404，文件不存在或链接已失效', totalLength: '0', completedLength: '0', directory: 'C:\\Users\\Administrator\\Downloads' },
  ],
  download_default: 'C:\\Users\\Administrator\\Downloads',
  subscriptions: [
    { id: 'sub-1', host: 'sub.example.com', saved_at: now(), active: true },
    { id: 'sub-2', host: 'backup.example.net', saved_at: now(), active: false },
  ],
  rules: [],
  transactions: [],
  automations: [],
  events: [
    { time: now(), kind: 'transfer', message: '新增下载任务：ubuntu-24.04-desktop-amd64.iso' },
    { time: now(), kind: 'diagnose', message: '完成网络检查' },
    { time: now(), kind: 'recovery', message: '已恢复上次未完成的任务' },
  ],
  reports: [
    {
      id: 'r1', kind: 'network', time: now(), target: 'network', failures: 0,
      checks: [
        { stage: '本机网络', ok: true, evidence: 'WLAN 192.168.1.5' },
        { stage: '网关', ok: true, evidence: '192.168.1.1 有响应；邻居缓存里有 7 台设备' },
        { stage: 'DNS', ok: true, evidence: '系统解析成功：140.82.113.4' },
        { stage: '外网连接', ok: true, evidence: '1.1.1.1:443 可达；223.5.5.5:443 可达' },
        { stage: '代理', ok: true, evidence: '系统代理 127.0.0.1:49231 可以连接' },
      ],
      conclusion: { code: 'ok', text: '网络正常', suggestion: '本机、网关、域名解析、外网和代理检查都通过' },
    },
  ],
})

const interfaces = {
  interfaces: [
    { index: 4, name: 'WLAN', ipv4: ['192.168.1.5'], ipv6: ['fe80::1'], gateway: ['192.168.1.1'], dns: ['192.168.1.1', '223.5.5.5'] },
  ],
  routes: [{ InterfaceIndex: 4, NextHop: '192.168.1.1', RouteMetric: 0 }],
}

const proxies = {
  mode: 'rule',
  proxies: {
    'Auto': { type: 'Selector', now: 'Tokyo-01', all: ['Tokyo-01', 'Osaka-02', 'DIRECT'] },
    'Tokyo-01': { type: 'Shadowsocks', history: [{ delay: 86 }] },
    'Osaka-02': { type: 'Shadowsocks', history: [{ delay: 142 }] },
  },
}

const lan = {
  devices: [
    { IPAddress: '192.168.1.1', LinkLayerAddress: 'AA-BB-CC-00-11-22', InterfaceIndex: 4, state: 'Reachable' },
    { IPAddress: '192.168.1.9', LinkLayerAddress: 'AA-BB-CC-33-44-55', InterfaceIndex: 4, state: 'Stale' },
    { IPAddress: '192.168.1.12', LinkLayerAddress: 'AA-BB-CC-66-77-88', InterfaceIndex: 4, state: 'Reachable' },
  ],
  source: 'neighbor_cache',
}

async function rpc(method: string, params: Record<string, unknown> = {}) {
  const name = String(method).replace(/^easynet\./, '')
  switch (name) {
    case 'status':
      return JSON.parse(JSON.stringify(state))
    case 'interfaces':
      return interfaces
    case 'lan':
      return lan
    case 'connections':
      return { connections: [], total: 0, traffic_source: 'system_connections' }
    case 'proxy.inspect':
      return proxies
    case 'system.inspect':
      return { enabled: 1, server: '127.0.0.1:49231', bypass: '<local>' }
    case 'diagnose':
      return { report: state.reports[0] }
    case 'transfer.add': {
      const gid = `p${state.downloads.length + 1}`
      const row = {
        gid,
        filename: String((params.url as string) || 'download.bin').split('/').pop() || 'download.bin',
        status: 'active',
        totalLength: '180000000',
        completedLength: '12000000',
        downloadSpeed: '2100000',
        directory: String(params.directory || state.download_default),
        source: String(params.source || 'page'),
      }
      state.downloads.unshift(row)
      return row
    }
    case 'transfer.action':
      return { result: { ok: true } }
    case 'transfer.verify':
      return { gid: params.gid, sha256: '9f2c…', verified: null }
    case 'settings.update':
      Object.assign(state.settings, (params.settings as Record<string, unknown>) || {})
      return { revision: ++state.revision, settings: state.settings }
    case 'proxy.subscriptions':
      return { subscriptions: state.subscriptions }
    case 'proxy.start':
      state.proxy.running = true
      return { running: true }
    case 'proxy.stop':
      state.proxy.running = false
      return { running: false }
    case 'accelerator.start':
      state.accelerator = { running: true, port: 49231 }
      return state.accelerator
    case 'accelerator.stop':
      state.accelerator = { running: false, port: 0 }
      return state.accelerator
    default:
      return {}
  }
}

const root = document.getElementById('preview-root')!
const style = document.createElement('style')
style.textContent = `${buttonCss}\n${switchCss}\n${selectCss}\n${pluginCss}\n${redesignCss}`
document.head.append(style)

// 预览直接带页签：?page=transfer / devices / diagnose / settings
const requested = new URLSearchParams(location.search).get('page')
if (requested) {
  try { sessionStorage.setItem('easynet:page', requested) } catch { /* 忽略 */ }
}

// user:“把所有文字都去掉，还能不能猜到怎么做”+(?notext=1 只隐藏文字，图标、开关、进度条保持可见)。
if (new URLSearchParams(location.search).get('notext') === '1') {
  const noText = document.createElement('style')
  noText.textContent = `
    .nx-app, .nx-app * { color: transparent !important; }
    .nx-app svg, .nx-app svg * { color: var(--nx-text) !important; stroke: currentColor !important; }
    .nx-app .nx2-station-icon.is-on svg, .nx-app .nx2-accent svg { color: var(--nx-accent) !important; }
    .nx-app input::placeholder { color: transparent !important; }
  `
  document.head.append(noText)
}

createApp(NetworkApp, {
  context: {
    rpc,
    visible: true,
    signal: new AbortController().signal,
    onVisibilityChange: () => () => {},
    openFile: (path: string) => window.alert(`用系统程序打开：${path}`),
    pickDirectory: async () => 'D:\\EasyNetDownloads',
  },
}).mount(root)
