// user:“内置浏览器出现：这个浏览器标签已经关闭 导致无法点击操作网页”+
// (这句只说明「前端记着的原生标签已经不在了」——应用重载、宿主关掉了它、或映射失效，
//  不是用户做错了什么。判定与重建节流收敛成纯函数：组件只负责丢映射、清错误、重建一次；
//  绝不再把它当成一条常驻错误，更不能让它挡住网页的鼠标事件)。
import { errorCode, errorText } from './browserErrorText'

/** native.ts 里 `browserTab` 找不到本地映射时的原话（前端自己抛的，不是 Rust 的错误码）。 */
export const LOCAL_TAB_MISSING = '网页还没打开'

/**
 * 这次失败是不是「标签丢了、该重建」。
 *
 * 两个来源必须都认：
 *  - Rust 的 `tab_not_found`（注册表里没有这个标签）；
 *  - 前端本地映射缺失（`browserTab` 抛出的「网页还没打开」）。
 * 其余错误（busy / tab_inactive / 网络失败等）都不是重建能解决的，交回调用方如实显示。
 */
export function nativeTabLost(cause: unknown): boolean {
  if (errorCode(cause) === 'tab_not_found') return true
  return errorText(cause, '').includes(LOCAL_TAB_MISSING)
}

/**
 * 重建节流：同一个标签在一个窗口内只重建一次。
 *
 * 没有这道闸，原生侧连续失败时会出现「重建 → 又失败 → 再重建」的空转；
 * 用它把空转变成「一秒几次」的可控重试，页面至少不会看起来一直在闪。
 */
export function canRebuildLostTab(now: number, lastAttemptAt: number, windowMs = 2000): boolean {
  if (!Number.isFinite(now)) return true
  if (!Number.isFinite(lastAttemptAt) || lastAttemptAt <= 0) return true
  if (!Number.isFinite(windowMs) || windowMs <= 0) return true
  return now - lastAttemptAt >= windowMs
}
