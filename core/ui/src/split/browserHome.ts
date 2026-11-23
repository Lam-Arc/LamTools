// user:“browser 首页 UI参考，核心仅为中间的输入栏，上方的网址栏和标签页，其余均为可选自定义组件或不实现”+
// (首页什么时候出现、问候语说哪一句、偏好记在哪、哪些快捷入口是真能落地的 —— 全是纯函数，
//  组件只负责画和触发；地址解析仍然只有 browserAddress.resolveAddress 一份，这里不另写判断)。

/**
 * 首页可见性输入。
 * user:“当浏览器标签没有地址（tab.resource 为空、尚未创建 webview）时，在 pane 内渲染一张首页而不是空白”+
 * (原生 webview 永远盖在 DOM 之上，所以判据只有一条硬约束：这个标签没有活着的网页。
 *  “地址为空”或“上次没建起来”是它的两个来源，不是第二套规则)。
 */
export interface BrowserHomeState {
  /** 标签记录上的地址（用户输入的，或页面推送回来的）。 */
  resource: string
  /** 原生 webview 是否已经建起来。 */
  created: boolean
  /** 上一次创建 / 导航失败过：回到首页并说明原因，而不是留一张白屏。 */
  failed?: boolean
}

export function browserHomeVisible(state: BrowserHomeState): boolean {
  // 有网页就一定不画首页：否则 DOM 首页会被原生网页整个盖住，看着像点了没反应。
  if (state.created) return false
  return state.failed === true || !state.resource.trim()
}

export type GreetingSlot = 'morning' | 'afternoon' | 'evening'

/** 24 小时制 → 时段。边界写死在一处，组件与测试读同一份。 */
export function greetingSlot(hour: number): GreetingSlot {
  const value = Number.isFinite(hour) ? Math.floor(hour) : 0
  if (value >= 5 && value < 12) return 'morning'
  if (value >= 12 && value < 18) return 'afternoon'
  return 'evening'
}

/** 问候语源键：i18n 只认中文源键，组件拿它去 t()。 */
export function greetingText(hour: number): string {
  const slot = greetingSlot(hour)
  return slot === 'morning' ? '早上好' : slot === 'afternoon' ? '下午好' : '晚上好'
}

/**
 * user:“问候语…可关闭并记住偏好”+
 * (关掉是跨会话的：切标签、重开应用都不该再冒出来。存储不可用时退回“显示”，
 *  但本次会话里用户点过一次关，组件内部的 ref 一样生效)。
 */
// user:“可选组件做成可关闭并记住偏好：问候语（按时段）+ 四个快捷入口”+
// (两块的开关共用一个存储形状：'off' 才算关，其余（含没有记录）都算开；
//  关掉后还能从首页的「设置」再打开，不是单向不可逆的消失)。
export type HomeOptionalId = 'greeting' | 'actions'

const OPTIONAL_KEYS: Record<HomeOptionalId, string> = {
  greeting: 'lamtools:browser-home-greeting',
  actions: 'lamtools:browser-home-actions',
}

export function optionalStoredVisible(raw: string | null | undefined): boolean {
  return raw !== 'off'
}
export function readOptionalVisible(id: HomeOptionalId): boolean {
  try { return optionalStoredVisible(localStorage.getItem(OPTIONAL_KEYS[id])) } catch { return true }
}
export function writeOptionalVisible(id: HomeOptionalId, visible: boolean): void {
  try { localStorage.setItem(OPTIONAL_KEYS[id], visible ? 'on' : 'off') } catch { /* 存不下只影响下次启动 */ }
}

/** 兼容旧调用名（问候语）与既有测试。 */
export const greetingStoredVisible = optionalStoredVisible
export function readGreetingVisible(): boolean { return readOptionalVisible('greeting') }
export function writeGreetingVisible(visible: boolean): void { writeOptionalVisible('greeting', visible) }

/** 有真实去处的可选快捷入口。 */
export type BrowserHomeActionId = 'web' | 'media'

/**
 * user:“四个方形快捷入口做成可选：Web（聚焦输入栏）、Workspace（打开分屏文件树）、
 * Media（打开资料库）、Saved（打开资料库收藏或最近项）——能对上的真实入口就接，接不上就不要放假的”+
 * (Web 不需要任何外部能力；Workspace / Media 都得先能在这块分屏里开标签，拿不到控制器就不出现。
 *  Saved 暂时不放：资料库的「收藏 / 最近」筛选是 MaterialsView 内部状态，页面入口只能整版打开，
 *  没有可深链的地址，硬接一个按钮点下去只会打开同一张资料库首页 —— 那就是假的)。
 */
export function homeQuickActionIds(input: { hasController: boolean; hasPane: boolean }): BrowserHomeActionId[] {
  const ids: BrowserHomeActionId[] = ['web']
  // user:“把库和easy file统合到一起”+(文件与资料只保留一个首页入口)。
  if (input.hasController && input.hasPane) ids.push('media')
  return ids
}
