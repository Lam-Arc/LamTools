// user:“审查分屏代码，并优化”+(只有真正盖住网页宿主的浮层才隐藏原生网页；常驻在设置页里的 listbox 不能让浏览器永久空白)。
export const HOST_OBSCURERS = '[aria-modal="true"], .right-sidebar-card, [role="listbox"]'

/** Native webviews always paint above HTML: hide one only when a rendered overlay actually covers it. */
export function hostBlockedByOverlay(host: HTMLElement | null, root: ParentNode = document): boolean {
  if (!host) return false
  const hostRect = host.getBoundingClientRect()
  if (!hostRect.width || !hostRect.height) return false
  for (const element of root.querySelectorAll<HTMLElement>(HOST_OBSCURERS)) {
    if (!element.getClientRects().length) continue
    // A modal brings a full-window backdrop, so it blocks even when its dialog is smaller than the host.
    if (element.matches('[aria-modal="true"]')) return true
    const rect = element.getBoundingClientRect()
    if (!rect.width || !rect.height) continue
    if (rect.right > hostRect.left && rect.left < hostRect.right && rect.bottom > hostRect.top && rect.top < hostRect.bottom) return true
  }
  return false
}

export function obscuresHostNode(node: Node): boolean {
  if (node.nodeType !== 1) return false
  const element = node as Element
  return element.matches(HOST_OBSCURERS) || Boolean(element.querySelector(HOST_OBSCURERS))
}
