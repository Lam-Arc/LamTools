// user:“无论有没有 HTTP 或前缀，都把这个链接标蓝可跳转”+(域名补全协议，文件名和危险协议不转链接)。
const WEB_TLDS = '[a-z]{2,63}|xn--[a-z0-9-]{2,59}'
const FILE_SUFFIXES = new Set('md txt pdf png jpg jpeg gif svg webp bmp avif heic csv tsv xls xlsx doc docx ppt pptx zip tar gz json jsonc yaml yml toml xml ini cfg log ts tsx js jsx py rs vue css html htm exe dll ps1 bat cmd sh sql'.split(' '))
const HOST = new RegExp(`^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\\.)+(?:${WEB_TLDS})(?::\\d+)?(?:[/#?]|$)`, 'i')
export const BARE_WEB_LINK = new RegExp(`(?:https?:\\/\\/|\\/\\/)?(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\\.)+(?:${WEB_TLDS})(?::\\d+)?(?:[/#?][^\\s<>"'，。；！？]*)?`, 'gi')
export function normalizeWebLink(value: string): string | null {
  const raw = value.trim().replace(/[.,;，。；]+$/, '')
  if (!raw || /[\s\\]/.test(raw)) return null
  const explicit = /^https?:\/\//i.test(raw)
  if (!explicit && !HOST.test(raw.replace(/^\/\//, ''))) return null
  if (!explicit && FILE_SUFFIXES.has(raw.replace(/^\/\//, '').split(/[/:?#]/)[0]!.split('.').pop()!.toLowerCase())) return null
  try {
    const url = new URL(explicit ? raw : 'https://' + raw.replace(/^\/\//, ''))
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) return null
    return url.href
  } catch { return null }
}
export function linkifyTextNodes(root: HTMLElement): void {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const nodes: Text[] = []
  while (walker.nextNode()) {
    const node = walker.currentNode as Text
    if (!node.parentElement?.closest('a, code, pre, script, style, svg, math, .katex, [data-no-linkify]')) nodes.push(node)
  }
  for (const node of nodes) {
    const text = node.data, fragment = document.createDocumentFragment()
    let end = 0
    for (const match of text.matchAll(BARE_WEB_LINK)) {
      const from = match.index!, raw = match[0].replace(/[.,;，。；)\]]+$/, '')
      if (from > 0 && /[\w/@:\\.-]/.test(text[from - 1]!)) continue
      const href = normalizeWebLink(raw)
      if (!href) continue
      fragment.append(text.slice(end, from))
      const anchor = document.createElement('a')
      anchor.href = href; anchor.textContent = raw; anchor.target = '_blank'; anchor.rel = 'noopener noreferrer'
      fragment.append(anchor); end = from + raw.length
    }
    if (end) { fragment.append(text.slice(end)); node.replaceWith(fragment) }
  }
  for (const anchor of root.querySelectorAll<HTMLAnchorElement>('a[href]')) {
    const href = normalizeWebLink(anchor.getAttribute('href') || '')
    if (href) anchor.href = href
  }
}
