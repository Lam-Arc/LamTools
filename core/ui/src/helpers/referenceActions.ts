import { inject } from 'vue'
import { Copy, ExternalLink, FolderOpen } from 'lucide-vue-next'
import { openContextMenu } from '@/components/context-menu/context-menu'
import { copyText } from '@/helpers/clipboard'
import { openExternalUrl } from '@/helpers/openUrl'
import { normalizeWebLink } from './webLinks'
import type { LamToolsTransport, TransportHttpResponse } from '@/transport'
import { useOptionalSplitWorkspace } from '@/split/useSplitWorkspace'

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
      const response = await transport.request<TransportHttpResponse>({ kind: 'http', method: 'POST', path: '/files/open-reference', headers: { 'Content-Type': 'application/json' }, body: new TextEncoder().encode(JSON.stringify({ path: absoluteReference(path, workRoot()), reveal })) })
      if (response.status < 200 || response.status >= 300) throw new Error('原文件不存在或无法打开')
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
      ...(splitWorkspace ? [{ id: 'open-split', label: '在分屏中打开', icon: ExternalLink, action: () => { splitWorkspace.add(url ? 'browser' : 'editor', path, url ? new URL(url).hostname : path.split(/[\\/]/).pop() || path, undefined, undefined, workRoot()) } }] : []),
      { id: 'open-default', label: url ? '使用默认浏览器打开' : '使用默认应用打开文件', icon: ExternalLink, action: () => open(path) },
      ...(!url ? [{ id: 'open-folder', label: '打开文件夹', icon: FolderOpen, action: () => open(path, true) }] : []),
      { id: 'copy-path', label: url ? '复制链接' : '复制路径', icon: Copy, action: () => copyText(path).catch(() => notice('复制失败')) },
    ] })
  }
  return { open, menu, absolute: (path: string) => absoluteReference(path, workRoot()) }
}
