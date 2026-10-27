/** user:“支持一下”+(每个分屏页面独占 DOM、项目上下文和可中止的生命周期)。 */
import type { PluginRpc } from './types'
import { consentRpc } from './consent'
import { pluginAssetUrl } from './assets'
import { attachPluginStyle } from './styles'

export interface PluginPageEntry {
  plugin: string
  id: string
  title: string
  entry_url: string
  version?: string
  order?: number
  navigation?: boolean
  file_extensions?: readonly string[]
}
export interface PluginPageScope {
  instanceId: string
  workRoot: string
  projectId?: string | null
  sessionId?: string | null
  filePath?: string
}
export interface PluginPageContext extends PluginPageScope {
  signal: AbortSignal
  readonly visible: boolean
  rpc: PluginRpc
  onVisibilityChange: (listener: (visible: boolean) => void) => () => void
  openPage: (pageId: string) => void
  openFile: (path: string) => void
  addStyle: (css: string) => () => void
}
type Cleanup = () => void | Promise<void>
export interface PluginPageModule {
  mount: (root: HTMLElement, context: PluginPageContext) => void | Cleanup | Promise<void | Cleanup>
}

// user:“该修就修，不用停下”+(插件文件页面绑定文件身份，最长后缀优先，多个相同处理器不擅自选择)。
export const pluginPageKey = (plugin: string, page: string, filePath?: string): string => JSON.stringify(filePath ? [plugin, page, filePath] : [plugin, page])
export function parsePluginPageKey(resource: string): [string, string] | [string, string, string] | null {
  try {
    const value = JSON.parse(resource)
    return Array.isArray(value) && (value.length === 2 || value.length === 3) && value.every(item => typeof item === 'string' && item.trim()) ? value as [string, string] | [string, string, string] : null
  } catch { return null }
}
export function findPluginFilePage(pages: readonly PluginPageEntry[], path: string): PluginPageEntry | null {
  const name = path.split(/[\\/]/).pop()?.toLowerCase() || ''
  const hits = pages.flatMap(page => (Array.isArray(page.file_extensions) ? page.file_extensions : [])
    .filter(ext => typeof ext === 'string' && /^\.[a-z0-9][a-z0-9._+-]{0,63}$/i.test(ext) && name.endsWith(ext.toLowerCase()))
    .map(ext => ({page, length:ext.length})))
  if (!hits.length) return null
  const longest = Math.max(...hits.map(hit => hit.length))
  const matches = hits.filter(hit => hit.length === longest)
  return matches.length === 1 ? matches[0].page : null
}
export async function loadPluginPageModule(page: PluginPageEntry): Promise<PluginPageModule> {
  const url = new URL(pluginAssetUrl(page.entry_url), window.location.href)
  if (page.version) url.searchParams.set('plugin-version', page.version)
  return import(/* @vite-ignore */ url.href)
}

export function createPluginPageInstance(host: HTMLElement, page: PluginPageEntry, scope: PluginPageScope, rpc: PluginRpc,
  options: { loadModule?: typeof loadPluginPageModule; visible?: boolean; openPage?: (id: string) => void; openFile?: (path: string) => void } = {}) {
  const bound = { ...scope }
  const controller = new AbortController(), listeners = new Set<(visible: boolean) => void>()
  const styles = new Set<() => void>()
  const approvedRpc = consentRpc(rpc, controller.signal)
  const root = document.createElement('div')
  root.className = 'plugin-page-instance'
  root.dataset.pluginPage = page.id
  root.dataset.plugin = page.plugin
  host.append(root)
  let visible = options.visible ?? true, disposed = false, cleanup: Cleanup | undefined
  let cleanupResult: Promise<void> | undefined
  const runCleanup = () => {
    if (cleanup && !cleanupResult) {
      const callback = cleanup; cleanup = undefined
      cleanupResult = Promise.resolve().then(callback)
    }
    return cleanupResult || Promise.resolve()
  }
  const context: PluginPageContext = Object.freeze({ ...bound, signal: controller.signal,
    get visible() { return visible },
    async rpc(method: string, params: Record<string, unknown> = {}) {
      if (disposed) throw new Error('插件页面已关闭')
      const payload = { ...params, work_root: bound.workRoot, workRoot: bound.workRoot,
        project_id: bound.projectId ?? null, projectId: bound.projectId ?? null,
        ...(bound.sessionId ? { session_id: bound.sessionId, sessionId: bound.sessionId } : {}) }
      const result = await approvedRpc(method, payload)
      if (disposed) throw new Error('插件页面已关闭')
      return result
    },
    onVisibilityChange(listener: (value: boolean) => void) { if (disposed) return () => {}; listeners.add(listener); return () => { listeners.delete(listener) } },
    openPage(id: string) { if (!disposed) options.openPage?.(id) },
    // user:“该修就修，不用停下”+(插件页面可在其项目上下文中打开链接文件)。
    openFile(path: string) { if (!disposed && typeof path === 'string' && path.trim()) options.openFile?.(path) },
    // user:“它自己的样式好像全部都丢了”+(由宿主统一授权样式并归当前页面实例清理)。
    addStyle(css: string) {
      if (disposed) return () => {}
      const remove = attachPluginStyle(root, css, page.plugin)
      const cleanup = () => { remove(); styles.delete(cleanup) }
      styles.add(cleanup)
      return cleanup
    },
  })
  const dispose = async () => {
    if (!disposed) { disposed = true; controller.abort(); listeners.clear(); for (const cleanup of styles) cleanup(); root.remove() }
    await runCleanup()
  }
  const ready = (async () => {
    try {
      const module = await (options.loadModule || loadPluginPageModule)(page)
      if (disposed) return
      if (typeof module.mount !== 'function') throw new Error('插件页面必须导出 mount(root, context)')
      const result = await module.mount(root, context)
      if (typeof result === 'function') cleanup = result
      if (disposed) await runCleanup()
    } catch (error) { await dispose(); throw error }
  })()
  return { ready, dispose, setVisible(value: boolean) {
    if (disposed || visible === value) return
    visible = value
    for (const listener of listeners) {
      try { listener(value) } catch (error) { console.error('Plugin page visibility listener failed', error) }
    }
  } }
}
