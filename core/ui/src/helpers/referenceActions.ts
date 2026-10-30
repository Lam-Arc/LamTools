import { inject } from 'vue'
import { Copy, ExternalLink, FolderOpen } from 'lucide-vue-next'
import { openContextMenu } from '@/components/context-menu/context-menu'
import { copyText } from '@/helpers/clipboard'
import { openExternalUrl } from '@/helpers/openUrl'
import { normalizeWebLink } from './webLinks'
import type { LamToolsTransport, TransportHttpResponse } from '@/transport'
import { useOptionalSplitWorkspace } from '@/split/useSplitWorkspace'
import { openFileInSplit } from '@/split/openFile'

export function absoluteReference(path: string, root = ''): string {
  const value = path.replace(/\\/g, '/')
  if (/^[A-Za-z]:\//.test(value) || value.startsWith('/')) return value
  return root ? root.replace(/\\/g, '/').replace(/\/$/, '') + '/' + value.replace(/^workspace:\/\//, '') : value
}

export function useReferenceActions(explicitTransport?: LamToolsTransport, explicitRoot?: () => string) {
  const splitWorkspace = useOptionalSplitWorkspace()
  const transport = explicitTransport || inject<LamToolsTransport | undefined>('lamtools-reference-transport', undefined)
  const injectedRoot = inject<() => string>('lamtools-reference-root', () => '')
  const workRoot = () => explicitRoot?.() || injectedRoot()
  const notice = inject<(message: string) => void>('lamtools-reference-notice', () => {})
  const pending = new Map<string, Promise<string>>()
  function query(path: string) { return new URLSearchParams({ path, ...(workRoot() ? { work_root: workRoot() } : {}) }).toString() }
  async function resolve(path: string): Promise<string> {
    if (path.startsWith('attachment://')) return resolveLegacy(path)
    if (!transport || normalizeWebLink(path)) return absoluteReference(path, workRoot())
    const key = query(path)
    const previous = pending.get(key)
    if (previous) return previous
    const task = (async () => {
      const response = await transport.request<TransportHttpResponse>({ kind: 'http', method: 'GET', path: `/files/resolve-reference?${key}` })
      const result = JSON.parse(new TextDecoder().decode(response.body))
      if (response.status !== 200 || typeof result.path !== 'string' || !result.path) throw new Error(result.detail || '原文件不存在')
      return result.path as string
    })()
    pending.set(key, task)
    try { return await task } finally { pending.delete(key) }
  }
  async function read(path: string): Promise<TransportHttpResponse> {
    if (!transport) throw new Error('当前无法读取本地文件')
    const response = await transport.request<TransportHttpResponse>({ kind: 'http', method: 'GET', path: `/files/read-reference?${query(path)}` })
    if (response.status < 200 || response.status >= 300) {
      let message = '原文件不存在'
      try { message = JSON.parse(new TextDecoder().decode(response.body)).detail || message } catch { /* Non-JSON errors retain the readable fallback. */ }
      throw new Error(message)
    }
    return response
  }
  async function canonicalize(scope: HTMLElement) {
    if (!transport) return
    // user:“引用的地址可能不对”+(显示和菜单都使用后台核实的地址，不把错误路径藏在正确文件名后面)。
    await Promise.all(Array.from(scope.querySelectorAll<HTMLAnchorElement>('a[data-file-path]')).map(async anchor => {
      const raw = anchor.dataset.filePath || ''
      try {
        const actual = await resolve(raw)
        anchor.dataset.filePath = actual; anchor.title = actual
        delete anchor.dataset.referenceError
      } catch (error) {
        anchor.dataset.referenceError = 'true'
        anchor.title = `${raw}\n${error instanceof Error ? error.message : '原文件不存在'}`
      }
    }))
  }
  async function resolveLegacy(path: string): Promise<string> {
    if (!path.startsWith('attachment://') || !transport) return path
    const response = await transport.request<TransportHttpResponse>({ kind: 'http', method: 'GET', path: `/attachments/${encodeURIComponent(path.slice('attachment://'.length))}/preview` })
    if (response.status !== 200) throw new Error('附件原文件无法读取')
    const result = JSON.parse(new TextDecoder().decode(response.body))
    if (!result.path) throw new Error('附件缺少原文件路径')
    return String(result.path)
  }
  async function open(path: string, reveal = false) {
    if (path.startsWith('attachment://')) {
      try { path = await resolveLegacy(path) } catch { notice('附件原文件无法读取'); return }
    }
    const url = normalizeWebLink(path)
    if (url) { await openExternalUrl(url); return }
    if (!transport) { notice('当前无法打开本地文件'); return }
    try {
      path = await resolve(path)
      const response = await transport.request<TransportHttpResponse>({ kind: 'http', method: 'POST', path: '/files/open-reference', headers: { 'Content-Type': 'application/json' }, body: new TextEncoder().encode(JSON.stringify({ path, work_root: workRoot(), reveal })) })
      if (response.status < 200 || response.status >= 300) {
        let message = '原文件不存在或无法打开'
        try { message = JSON.parse(new TextDecoder().decode(response.body)).detail || message } catch { /* Keep the fallback for older backends. */ }
        throw new Error(message)
      }
    } catch (error) { notice(error instanceof Error ? error.message : '打开失败') }
  }
  function menu(event: MouseEvent, raw: string) {
    if (raw.startsWith('attachment://')) {
      event.preventDefault(); event.stopPropagation()
      void resolveLegacy(raw).then(path => menu(event, path)).catch(() => notice('附件原文件无法读取'))
      return
    }
    const url = normalizeWebLink(raw), path = url || absoluteReference(raw, workRoot())
    // user:“右键弹窗与右键成果一致”+(正文和成果共用同一套文件与链接操作)。
    openContextMenu({ event, ownerId: 'file-reference', ariaLabel: url ? '链接操作' : '文件操作', items: [
      ...(splitWorkspace ? [{ id: 'open-split', label: '在分屏中打开', icon: ExternalLink, action: async () => { try { const actual = url || await resolve(path); if (url) splitWorkspace.add('browser', actual, new URL(url).hostname, undefined, undefined, workRoot()); else openFileInSplit(splitWorkspace, actual, { workRoot: workRoot(), force: true }) } catch (error) { notice(error instanceof Error ? error.message : '原文件不存在') } } }] : []),
      { id: 'open-default', label: url ? '使用默认浏览器打开' : '使用默认应用打开文件', icon: ExternalLink, action: () => open(path) },
      ...(!url ? [{ id: 'open-folder', label: '打开文件夹', icon: FolderOpen, action: () => open(path, true) }] : []),
      { id: 'copy-path', label: url ? '复制链接' : '复制路径', icon: Copy, action: async () => { try { await copyText(url || await resolve(path)) } catch (error) { notice(error instanceof Error ? error.message : '复制失败') } } },
    ] })
  }
  return { open, menu, resolve, read, canonicalize, absolute: (path: string) => absoluteReference(path, workRoot()) }
}
