import { h, render } from 'vue'
import {
  File,
  FileArchive,
  FileCode2,
  FileJson2,
  FileText,
  Image as ImageIcon,
  Presentation,
  Sheet,
  type LucideIcon,
} from 'lucide-vue-next'
import { absoluteReference } from './referenceActions'
import { normalizeWebLink } from './webLinks'

const FILE_END = /\.(?:md|txt|pdf|png|jpe?g|webp|gif|svg|xlsx?|csv|pptx?|docx?|zip|jsonc?|ya?ml|toml|py|rs|ts|tsx|js|jsx|vue|html?|css|log|mp[34]|wav|webm)(?::\d+(?::\d+)?)?$/i
export function isLocalFileReference(path: string): boolean {
  return FILE_END.test(path) && !normalizeWebLink(path) && (!/^[a-z][\w+.-]*:/i.test(path) || /^(?:[A-Za-z]:[\\/]|workspace:\/\/|file:\/\/)/i.test(path))
}

const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'avif', 'svg'])
const SHEET_EXTENSIONS = new Set(['xls', 'xlsx', 'ods', 'csv'])
const PRESENTATION_EXTENSIONS = new Set(['ppt', 'pptx', 'odp'])
const ARCHIVE_EXTENSIONS = new Set(['zip', 'rar', '7z', 'tar', 'gz', 'bz2'])
const CODE_EXTENSIONS = new Set(['ts', 'tsx', 'js', 'jsx', 'vue', 'py', 'rs', 'go', 'java', 'c', 'cc', 'cpp', 'h', 'hpp', 'cs', 'php', 'rb', 'sh', 'ps1', 'sql', 'html', 'css', 'scss', 'less'])
const DATA_EXTENSIONS = new Set(['json', 'jsonc', 'yaml', 'yml', 'toml', 'xml'])
const TEXT_EXTENSIONS = new Set(['md', 'mdx', 'txt', 'log', 'ini', 'cfg', 'conf', 'env'])

function fileIcon(name: string): LucideIcon {
  const ext = name.includes('.') ? name.split('.').pop()!.toLowerCase() : ''
  if (IMAGE_EXTENSIONS.has(ext)) return ImageIcon
  if (ext === 'pdf') return FileText
  if (SHEET_EXTENSIONS.has(ext)) return Sheet
  if (PRESENTATION_EXTENSIONS.has(ext)) return Presentation
  if (ARCHIVE_EXTENSIONS.has(ext)) return FileArchive
  if (CODE_EXTENSIONS.has(ext)) return FileCode2
  if (DATA_EXTENSIONS.has(ext)) return FileJson2
  if (TEXT_EXTENSIONS.has(ext)) return FileText
  return File
}

export function renderFileReferenceNodes(root: HTMLElement, workRoot: string): void {
  function decorate(anchor: HTMLAnchorElement, raw: string) {
    const path = absoluteReference(raw.replace(/:\d+(?::\d+)?$/, ''), workRoot)
    anchor.dataset.filePath = path; anchor.href = '#'; anchor.title = path
    anchor.classList.add('file-reference-link'); anchor.removeAttribute('target')
    // user:“渲染的@改为对应文件图标”+(引用开头的 @ 字符换成按扩展名选择的文件图标，文件名保留)。
    const name = path.split('/').pop() || path
    const icon: HTMLSpanElement = document.createElement('span')
    icon.className = 'file-reference-icon'
    // 这里只借 Vue 生成静态 SVG：渲染后立刻卸载，避免把组件实例留在脱离
    // 文档的临时容器里（有 effect/watch 的图标会泄漏）。
    const mount = document.createElement('span')
    render(h(fileIcon(name), { size: 13, 'stroke-width': 1.8, 'aria-hidden': 'true' }), mount)
    icon.innerHTML = mount.innerHTML
    render(null, mount)
    anchor.replaceChildren(icon, document.createTextNode(name))
  }
  for (const anchor of root.querySelectorAll<HTMLAnchorElement>('a[href]')) {
    const raw = (anchor.getAttribute('href') || '').replace(/%20/g, ' ')
    if (!normalizeWebLink(raw) && FILE_END.test(raw) && !/^[a-z]+:(?![\\/])/i.test(raw)) decorate(anchor, raw)
  }
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), nodes: Text[] = []
  while (walker.nextNode()) {
    const node = walker.currentNode as Text
    // user:“不要出错”+(隐藏原稿和交互源码必须逐字保留，不能被文件引用转换改写)。
    if (!node.parentElement?.closest('a,pre,script,style,svg,math,.katex,[hidden],[data-no-linkify]')) nodes.push(node)
  }
  for (const node of nodes) {
    const text = node.data, fragment = document.createDocumentFragment()
    const regex = /@"([^"\n]+)"|(?:[A-Za-z]:[\\/]|\/)[^\s<>"'，。；]+|(?:[\w\u0080-\uffff.-]+[\\/])*[\w\u0080-\uffff.-]+\.[a-zA-Z0-9]+(?::\d+(?::\d+)?)?/g
    let end = 0
    const matches = node.parentElement?.tagName === 'CODE' && FILE_END.test(text.trim())
      ? [{ 0: text, 1: '', index: 0 }]
      : [...text.matchAll(regex)]
    for (const match of matches) {
      const from = match.index!, raw = (match[1] || match[0]).replace(/[.,;，。；)\]]+$/, '')
      if (!FILE_END.test(raw) || normalizeWebLink(raw) || (!workRoot && !/^(?:[A-Za-z]:[\\/]|\/)/.test(raw))) continue
      if (from > 0 && /[\w/@]/.test(text[from - 1]!)) continue
      fragment.append(text.slice(end, from))
      const anchor = document.createElement('a'); decorate(anchor, raw); fragment.append(anchor)
      end = from + match[0].length
    }
    if (end) { fragment.append(text.slice(end)); node.replaceWith(fragment) }
  }
}
