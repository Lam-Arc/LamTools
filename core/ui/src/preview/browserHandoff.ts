/**
 * 「用浏览器打开」的唯一注入点。
 *
 * user:“预览器负责查看内容，浏览器负责访问和操作网站…两者互通：预览器里的网页链接可交浏览器”+
 * (预览器不实现网页浏览。这里只留一个注册位：将来的浏览器模块启动时把真正的
 * "打开这个网址"接进来；没有注册方时界面不显示这个出口，也不假装能用。)
 */
export type PreviewBrowserHandoff = (url: string) => void | Promise<void>

let handoff: PreviewBrowserHandoff | null = null

/** 浏览器模块启动时调用；传 null 可撤销注册（例如模块被卸载）。 */
export function registerPreviewBrowserHandoff(next: PreviewBrowserHandoff | null): void {
  handoff = next
}

/** 当前是否有浏览器接手方。灯箱据此决定是否显示「用浏览器打开」。 */
export function canHandOffToBrowser(): boolean {
  return handoff !== null
}

/**
 * 把网址交给浏览器模块。
 * 返回 false 表示没有接手方——调用方应当隐藏出口，而不是退化成应用内浏览。
 */
export async function handOffToBrowser(url: string): Promise<boolean> {
  if (!handoff) return false
  await handoff(url)
  return true
}

/** 只把 http(s) 当作可以交给浏览器的链接；本机与内部源不算。 */
export function isBrowserHandoffUrl(url: string): boolean {
  return /^https?:\/\//i.test(url || '') && !/^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:|\/|$)/i.test(url)
}
