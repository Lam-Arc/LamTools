// user:“入口藏得深…会话里的链接可直接打开内置浏览器”+
// (入口本身散在竖栏、右键菜单、命令面板与链接点击四处，但「能不能开、开到哪」只有这里一份实现：
//  宿主启动时注册一个 opener，其余调用方只问 entry 能否用、失败原因是什么)。
import { classifyLink, type LinkDecision } from './linkRouting'

export interface BrowserEntryResult {
  ok: boolean
  /** 失败原因；成功时是空串。入口不能点了没反应，所以失败必须带一句话。 */
  reason: string
}

export interface BrowserEntryAvailability {
  available: boolean
  reason: string
}

/** 宿主提供的真正开标签的实现（LamToolsApp 注册）。 */
export type BrowserEntryOpener = (target: { url: string; title?: string; reuse?: boolean }) => BrowserEntryResult

let opener: BrowserEntryOpener | null = null

/**
 * user:“入口都要能在「浏览器不可用」时给出明确原因”+
 * (注册者退出时要注销，避免入口还亮着但已经没人能开)。
 * user:“清掉死导出 browserEntryOwner——零引用”+
 * (它只把注册者名字存起来给谁读？没有任何调用方。注册这件事只需要「有一个 opener」，
 *  所以 owner 参数和那份状态一起删掉，少一处没人读的历史字段)。
 */
export function registerBrowserEntry(fn: BrowserEntryOpener): () => void {
  opener = fn
  return () => {
    if (opener === fn) opener = null
  }
}

export function hasDesktopHost(): boolean {
  return typeof window !== 'undefined' && Boolean((window as unknown as Record<string, unknown>).__TAURI_INTERNALS__)
}

/**
 * 入口是否可用。不可用时一定给原因：手机端、非桌面宿主、宿主还没注册 opener
 * 是三种完全不同的「为什么点了没反应」。
 */
export function browserEntryAvailability(): BrowserEntryAvailability {
  if (!hasDesktopHost()) {
    return { available: false, reason: '内置浏览器需要在桌面应用里使用' }
  }
  if (!opener) {
    return { available: false, reason: '内置浏览器还没就绪（宿主尚未注册浏览器入口）' }
  }
  return { available: true, reason: '' }
}

/**
 * user:“右键菜单加「在内置浏览器中打开」（与现有「在系统浏览器打开」并存）”+
 * (分类规则与纯函数一致：非 http(s) 不开内置，直接返回理由而不是静默失败)。
 */
export function openInBrowser(raw: string, title = ''): BrowserEntryResult {
  const decision: LinkDecision = classifyLink(raw)
  if (decision.route !== 'internal') return { ok: false, reason: decision.reason }
  const state = browserEntryAvailability()
  if (!state.available) return { ok: false, reason: state.reason }
  try {
    const result = opener?.({ url: decision.url, title }) ?? { ok: false, reason: '内置浏览器还没就绪' }
    return result
  } catch (error) {
    return { ok: false, reason: error instanceof Error ? error.message : String(error) }
  }
}

/** 打开（或聚焦）一块浏览器分屏，不指定网址——竖栏与命令面板的「打开浏览器」用它。 */
export function openBrowserPane(): BrowserEntryResult {
  const state = browserEntryAvailability()
  if (!state.available) return { ok: false, reason: state.reason }
  try {
    return opener?.({ url: '', reuse: true }) ?? { ok: false, reason: '内置浏览器还没就绪' }
  } catch (error) {
    return { ok: false, reason: error instanceof Error ? error.message : String(error) }
  }
}

/**
 * user:“命令面板：在当前页打开链接”+
 * (从一段文本里挑出第一个 http(s) 地址：命令面板不弹输入框，用户把链接复制到剪贴板后
 *  这条命令就能落在「当前这块浏览器屏」上，而不是又开一个标签)。
 */
export function firstHttpLink(text: string): string {
  const match = String(text ?? '').match(/https?:\/\/[^\s<>"'）)】]+/i)
  if (!match) return ''
  const decision = classifyLink(match[0])
  return decision.route === 'internal' ? decision.url : ''
}

/** 「在当前页打开」：有现成浏览器屏就复用，没有就新开一块。 */
export function openLinkInCurrentPage(text: string): BrowserEntryResult {
  const url = firstHttpLink(text)
  if (!url) return { ok: false, reason: '没有找到 http(s) 链接' }
  const state = browserEntryAvailability()
  if (!state.available) return { ok: false, reason: state.reason }
  try {
    return opener?.({ url, reuse: true }) ?? { ok: false, reason: '内置浏览器还没就绪' }
  } catch (error) {
    return { ok: false, reason: error instanceof Error ? error.message : String(error) }
  }
}
