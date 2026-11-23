// user:“有分屏时菜单/右栏/浮窗不被网页盖住；浮层拖动不隐藏网页”+
// (网页可见性收敛成一个纯函数：矩形 + 区域可见 + 浮层计数 + 交互相位 + 置底。
//  让位只由“会重排布局的手势”触发，浮层自己的拖动/缩放不算——那正是“网页原地不动”的旧病根)。
//
// 归属（避免两份判定漂移）：
// - 本文件只作**几何侧派生**用：布局/预览/壳层判断“这一块此刻有没有可画的网页长方形”。
// - **原生网页的唯一判定**是 `core/ui/src/split/browserVisibility.ts`（V2-B，含 overlay 登记、
//   可见性时序与 bounds 下发）；两边冲突时以那边为准。
// - 改这里前先确认 browserVisibility.ts 是否需要同步，不要各写一套各自演化。

import type { AreaGeometry } from './compute'
import type { Rect } from './model'

export interface BrowserVisibilityInput {
  rect: Rect | null
  areaVisible: boolean
  overlayCount: number
  phase: 'idle' | 'draggingTab' | 'resizingDivider' | 'movingArea' | 'floating'
  floatBehind: boolean
}

export function browserVisible(input: BrowserVisibilityInput): boolean {
  const { rect, areaVisible, overlayCount, phase, floatBehind } = input
  if (!rect) return false
  if (!(rect.width > 0) || !(rect.height > 0)) return false
  if (!areaVisible) return false
  if (overlayCount > 0) return false
  if (floatBehind) return false
  // 只有会重排布局的手势让位；floating（浮层拖动/缩放）保持可见，网页才能跟手。
  if (phase === 'draggingTab' || phase === 'resizingDivider' || phase === 'movingArea') return false
  return true
}

/**
 * user:“矩形唯一来源：compute 的 area rect 减去 chrome 就是 webview rect”+
 * (contentRect 已经扣掉页眉与标签条；这里只做整数化与 >=1 保护。tabbarHeight 保留参数与调用方对齐，
//  真正的标签条高度已经体现在 contentRect 里)。
 */
export function webviewRectFor(area: AreaGeometry, tabbarHeight: number): Rect {
  void tabbarHeight
  const rect = area.contentRect
  return {
    x: Math.round(rect.x),
    y: Math.round(rect.y),
    width: Math.max(1, Math.round(rect.width)),
    height: Math.max(1, Math.round(rect.height)),
  }
}
