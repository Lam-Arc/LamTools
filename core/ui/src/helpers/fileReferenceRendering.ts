import { absoluteReference } from './referenceActions'
import { normalizeWebLink } from './webLinks'

const FILE_END = /\.(?:md|txt|pdf|png|jpe?g|webp|gif|svg|xlsx?|csv|pptx?|docx?|zip|jsonc?|ya?ml|toml|py|rs|ts|tsx|js|jsx|vue|html?|css|log|mp[34]|wav|webm)(?::\d+(?::\d+)?)?$/i
export function isLocalFileReference(path: string): boolean {
  return FILE_END.test(path) && !normalizeWebLink(path) && (!/^[a-z][\w+.-]*:/i.test(path) || /^(?:[A-Za-z]:[\\/]|workspace:\/\/|file:\/\/)/i.test(path))
}
export function renderFileReferenceNodes(root: HTMLElement, workRoot: string): void {
  function decorate(anchor: HTMLAnchorElement, raw: string) {
    const path = absoluteReference(raw.replace(/:\d+(?::\d+)?$/, ''), workRoot)
    anchor.dataset.filePath = path; anchor.href = '#'; anchor.title = path
    anchor.classList.add('file-reference-link'); anchor.textContent = '@' + (path.split('/').pop() || path)
    anchor.removeAttribute('target')
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
