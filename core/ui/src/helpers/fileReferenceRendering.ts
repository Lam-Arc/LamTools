import { absoluteReference } from './referenceActions'
import { fileTypeBadge } from './fileTypeBadge'
import { fileTypeIconMarkup } from './fileTypeIcon'
import { normalizeWebLink } from './webLinks'

const FILE_END = /\.(?:md|txt|pdf|png|jpe?g|webp|gif|svg|xlsx?|csv|pptx?|docx?|zip|jsonc?|ya?ml|toml|py|rs|ts|tsx|js|jsx|vue|html?|css|log|mp[34]|wav|webm)(?::\d+(?::\d+)?)?$/i
export function isLocalFileReference(path: string): boolean {
  return FILE_END.test(path) && !normalizeWebLink(path) && (!/^[a-z][\w+.-]*:/i.test(path) || /^(?:[A-Za-z]:[\\/]|workspace:\/\/|file:\/\/)/i.test(path))
}

/**
 * Auto-linkification is intentionally strict: only a drive-letter absolute
 * path or a project-root-relative path (which needs a known work root) is a
 * candidate. Bare model output like `report.md` is too ambiguous to resolve.
 */
export function isAutoFileReferenceCandidate(raw: string, workRoot = ''): boolean {
  let value = String(raw || '').trim()
  if (value.startsWith('@')) value = value.slice(1)
  if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
    value = value.slice(1, -1)
  }
  if (!value || normalizeWebLink(value)) return false

  const path = value.replace(/:\d+(?::\d+)?$/, '')
  if (!FILE_END.test(path)) return false
  const normalized = path.replace(/\\/g, '/')
  if (/^[A-Za-z]:\//.test(normalized)) return true
  if (normalized.startsWith('/') || normalized.startsWith('~') || /^[A-Za-z][\w+.-]*:/.test(normalized)) return false
  if (normalized === '..' || normalized.startsWith('../')) return false
  const relative = normalized.replace(/^\.\//, '')
  if (!Boolean(workRoot) || !relative.includes('/')) return false
  // A project-relative path must stay inside the project root.
  let depth = 0
  for (const segment of relative.split('/')) {
    if (!segment || segment === '.') continue
    if (segment === '..') {
      depth -= 1
      if (depth < 0) return false
    } else {
      depth += 1
    }
  }
  return depth > 0
}

export function renderFileReferenceNodes(root: HTMLElement, workRoot: string): void {
  function decorate(anchor: HTMLAnchorElement, raw: string, originalText = '') {
    const path = absoluteReference(raw.replace(/:\d+(?::\d+)?$/, ''), workRoot)
    anchor.dataset.filePath = path
    anchor.dataset.fileReferenceAuto = 'true'
    if (originalText) anchor.dataset.fileReferenceRaw = originalText
    anchor.href = '#'; anchor.title = path
    anchor.classList.add('file-reference-link'); anchor.removeAttribute('target')
    // user:“把那个@的符号去掉 换成对应的文件图标”+(引用只保留文件类型徽标 + 文件名，
    // 徽标按扩展名取色、30% 圆角；完整路径仍在 title 里)。
    const name = path.split('/').pop() || path
    const badgeData = fileTypeBadge(name)
    const icon: HTMLSpanElement = document.createElement('span')
    icon.className = 'file-reference-icon'
    const badge = document.createElement('span')
    badge.className = 'file-reference-badge'
    badge.dataset.label = badgeData.label
    badge.style.background = badgeData.background
    badge.style.color = badgeData.color
    badge.innerHTML = fileTypeIconMarkup(name, 11)
    icon.appendChild(badge)
    anchor.replaceChildren(icon, document.createTextNode(name))
  }
  for (const anchor of root.querySelectorAll<HTMLAnchorElement>('a[href]')) {
    const raw = (anchor.getAttribute('href') || '').replace(/%20/g, ' ')
    if (isAutoFileReferenceCandidate(raw, workRoot)) decorate(anchor, raw, anchor.textContent || '')
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
      if (!isAutoFileReferenceCandidate(raw, workRoot)) continue
      if (from > 0 && /[\w/@]/.test(text[from - 1]!)) continue
      const originalText = (match[1] ? `@"${match[1]}"` : match[0]).replace(/[.,;，。；)\]]+$/, '')
      fragment.append(text.slice(end, from))
      const anchor = document.createElement('a'); decorate(anchor, raw, originalText); fragment.append(anchor)
      end = from + match[0].length
    }
    if (end) { fragment.append(text.slice(end)); node.replaceWith(fragment) }
  }
}
