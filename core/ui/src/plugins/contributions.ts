import { reactive, readonly } from 'vue'

import type { PluginRpc } from '@/plugins/types.ts'

export type { PluginRpc }

/**
 * user:“九个区域统一挂载”+插件 UI 声明全进程一份：样式/脚本注入、区域
 * 块渲染、replace 判定都读这里；宿主容器用它决定默认内容是否让位。
 */

export interface PluginStyleEntry {
  plugin: string
  url: string
}

export interface PluginScriptEntry {
  plugin: string
  url: string
}

export interface PluginBlock {
  type: string
  label: string
  value: unknown
  text: string
  state: string
  items: unknown[]
  detail: string
  max?: number
}

export interface PluginAction {
  id: string
  title: string
  operation: string
  input_schema?: Record<string, unknown>
  dangerous?: boolean
  mutates?: boolean
}

export interface PluginRegionContribution {
  plugin: string
  region: string
  order: number
  mode: string
  replace: boolean
  entry_url?: string
  blocks: PluginBlock[]
  actions: PluginAction[]
}

export interface PluginContributionState {
  loaded: boolean
  styles: PluginStyleEntry[]
  scripts: PluginScriptEntry[]
  regions: PluginRegionContribution[]
  enabledPlugins: Set<string>
}

const state = reactive<PluginContributionState>({
  loaded: false,
  styles: [],
  scripts: [],
  regions: [],
  enabledPlugins: new Set<string>(),
})

let inflight: Promise<void> | null = null

// 宿主启动时注册的全局 RPC：message 区域等没有 prop 通道的挂点用它。
let globalRpc: PluginRpc | null = null

export function setContributionsRpc(rpc: PluginRpc | null): void {
  globalRpc = rpc
}

export function contributionsRpc(): PluginRpc | null {
  return globalRpc
}

// 样式与脚本是页面级资源：每个地址只注入一次，重复挂载不叠加；
// 禁用插件后已注入的不撤除，需要整页重载（作者约定）。
const injectedStyles = new Set<string>()
const injectedScripts = new Set<string>()

function injectStyle(url: string): void {
  if (!url || injectedStyles.has(url)) return
  const link = document.createElement('link')
  link.rel = 'stylesheet'
  link.href = url
  link.dataset.pluginSystemStyle = 'true'
  document.head.appendChild(link)
  injectedStyles.add(url)
}

function injectScript(url: string): void {
  if (!url || injectedScripts.has(url)) return
  if (document.querySelector(`script[data-plugin-system-script="${url}"]`)) {
    injectedScripts.add(url)
    return
  }
  const script = document.createElement('script')
  script.type = 'module'
  script.src = url
  script.dataset.pluginSystemScript = url
  document.head.appendChild(script)
  injectedScripts.add(url)
}

export { injectScript }

async function refreshOnce(requestRpc: PluginRpc): Promise<void> {
  if (inflight) return inflight
  inflight = (async () => {
    try {
      const payload = await requestRpc('plugin.system.ui', {})
      const styles = Array.isArray(payload.styles) ? (payload.styles as PluginStyleEntry[]) : []
      for (const style of styles) injectStyle(String(style.url || ''))
      const scripts = Array.isArray(payload.scripts) ? (payload.scripts as PluginScriptEntry[]) : []
      for (const script of scripts) injectScript(String(script.url || ''))
      state.regions = Array.isArray(payload.regions)
        ? (payload.regions as PluginRegionContribution[])
        : []
      const listing = await requestRpc('plugin.system.list', {})
      const plugins = Array.isArray(listing.plugins)
        ? (listing.plugins as Array<{ name: string; enabled: boolean }>)
        : []
      state.enabledPlugins = new Set(
        plugins.filter((plugin) => plugin.enabled).map((plugin) => plugin.name),
      )
      state.loaded = true
    } catch {
      // 插件声明加载失败不阻断界面；下一次挂载会重试。
      state.regions = []
      state.enabledPlugins = new Set()
    } finally {
      inflight = null
    }
  })()
  return inflight
}

export async function ensureContributions(requestRpc: PluginRpc): Promise<void> {
  await refreshOnce(requestRpc)
}

export function contributionsFor(region: string): PluginRegionContribution[] {
  return state.regions
    .filter((item) => item.region === region)
    .sort((a, b) => a.order - b.order || a.plugin.localeCompare(b.plugin))
}

/** user:“replace 语义”+同区域有接管者时宿主隐藏默认内容，只留插件的。 */
export function isRegionReplaced(region: string): boolean {
  return state.regions.some((item) => item.region === region && item.replace)
}

export function pluginEnabled(name: string): boolean {
  return state.enabledPlugins.has(name)
}

export function contributionState() {
  return readonly(state)
}
