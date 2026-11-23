// user:“分屏是为了便于交互…第一性原则”+(几何只在一个地方算：computeWorkspace 是矩形唯一来源，
// 组件不再测量 DOM。树只存 ratio，像素在这里算；空间不足按固定顺序降级，绝不靠“藏屏”凑合)。

import { SPLIT_TAB_BAR_HEIGHT, WORKSPACE_HEADER_HEIGHT } from './constants'
import {
  DEFAULT_FLOAT_RECT,
  type Area,
  type AreaId,
  type Rect,
  type SplitNode,
  type SurfaceId,
  type WorkspaceModel,
} from './model'

export interface SizeLimits { main: { width: number; height: number }; aux: { width: number; height: number } }
export interface ChromeSpec { tabbar: number; header: number }

// user:“insufficient 时给出实数字据而不是空白”+(need/have 都是实数，界面可以直接说“需要 Npx / 当前 Mpx”)。
export type Issue =
  | { code: 'insufficient'; areaId: AreaId; need: { width: number; height: number }; have: { width: number; height: number } }


export interface AreaGeometry {
  rect: Rect
  contentRect: Rect
  // 标签条密度与页眉高度：webview 矩形只能由 contentRect 得到，组件不再自己量。
  // Agent 主区的标签入口在侧栏，辅助分屏始终保留顶部操作条。
  chrome: { tabbar: 'full' | 'compact' | 'hidden'; header: number }
}
export interface WorkspaceGeometry {
  areas: Record<AreaId, AreaGeometry>
  floats: Record<SurfaceId, Rect>
  issues: Issue[]
}

// user:“最小宽高”+(主区 420/320、辅助 320/240；紧凑模式只降横向下限——窄窗口的问题只出在宽度)。
export const DEFAULT_LIMITS: SizeLimits = { main: { width: 420, height: 320 }, aux: { width: 320, height: 240 } }
export const DEFAULT_CHROME: ChromeSpec = { tabbar: SPLIT_TAB_BAR_HEIGHT, header: WORKSPACE_HEADER_HEIGHT }
export const DEFAULT_GAP = 0

export function compactLimits(base: SizeLimits = DEFAULT_LIMITS): SizeLimits {
  return {
    main: { width: Math.max(1, Math.round(base.main.width * 0.86)), height: base.main.height },
    aux: { width: Math.max(1, Math.round(base.aux.width * 0.86)), height: base.aux.height },
  }
}

function limitOf(area: Area, limits: SizeLimits): { width: number; height: number } {
  return area.role === 'main' ? limits.main : limits.aux
}

/** 整棵树的最小尺寸：横向切分宽相加、高取大；纵向反过来。 */
export function minimumSizeOf(tree: SplitNode, limits: SizeLimits = DEFAULT_LIMITS, gap = DEFAULT_GAP): { width: number; height: number } {
  if (tree.kind === 'leaf') return limitOf(tree.area, limits)
  const a = minimumSizeOf(tree.a, limits, gap)
  const b = minimumSizeOf(tree.b, limits, gap)
  return tree.direction === 'row'
    ? { width: a.width + gap + b.width, height: Math.max(a.height, b.height) }
    : { width: Math.max(a.width, b.width), height: a.height + gap + b.height }
}


/**
 * user:“任意随机树 × 任意视口 → 铺满、两两不重叠、每区 ≥ 下限 或 insufficient”+
 * (ratio 只在“两侧都放得下最小值”时被夹到合法区间；放不下就按比例尽力，同时记 insufficient，
//  但绝不产生重叠或负尺寸——这是几何层唯一不可让步的东西)。
 */
export function computeWorkspace(
  model: WorkspaceModel,
  viewport: Rect,
  opts: { limits?: SizeLimits; chrome?: ChromeSpec; gap?: number } = {},
): WorkspaceGeometry {
  const gap = Math.max(0, Math.round(opts.gap ?? DEFAULT_GAP))
  const chrome = opts.chrome ?? DEFAULT_CHROME
  const base = opts.limits ?? DEFAULT_LIMITS
  // user:“降级顺序：标签条 full→compact；换成 prefs.compact 的 limits；仍不足才 insufficient”+
  // (prefs.compact 是用户的显式选择：它决定这一份 limits 用哪套；标签条密度只影响内容区高度)。
  const limits = model.prefs.compact ? compactLimits(base) : base
  const x = Math.round(viewport.x)
  const y = Math.round(viewport.y)
  const width = Math.max(0, Math.round(viewport.width))
  const height = Math.max(0, Math.round(viewport.height))
  const root: Rect = { x, y, width, height }

  const tree = model.tree
  const issues: Issue[] = []

  const need = tree ? minimumSizeOf(tree, limits, gap) : { width: 0, height: 0 }
  const fits = need.width <= width && need.height <= height
  // ① 放得下就是完整标签条；放不下时先降成紧凑标签条，把高度尽量让给内容。
  const tabbarMode: 'full' | 'compact' = fits ? 'full' : 'compact'

  const laidOut: Array<{ area: Area; rect: Rect }> = []
  if (tree) {
    const walk = (node: SplitNode, rect: Rect): void => {
      if (node.kind === 'leaf') { laidOut.push({ area: node.area, rect }); return }
      const horizontal = node.direction === 'row'
      const extent = Math.max(0, (horizontal ? rect.width : rect.height) - gap)
      const aMin = minimumSizeOf(node.a, limits, gap)[horizontal ? 'width' : 'height']
      const bMin = minimumSizeOf(node.b, limits, gap)[horizontal ? 'width' : 'height']
      let ratio = Number.isFinite(node.ratio) ? Math.min(1, Math.max(0, node.ratio)) : .5
      if (extent > 0 && aMin + bMin <= extent) {
        ratio = Math.min(1 - bMin / extent, Math.max(aMin / extent, ratio))
      }
      const sizeA = Math.max(0, Math.min(extent, Math.round(extent * ratio)))
      const sizeB = Math.max(0, extent - sizeA)
      const aRect: Rect = horizontal
        ? { x: rect.x, y: rect.y, width: sizeA, height: rect.height }
        : { x: rect.x, y: rect.y, width: rect.width, height: sizeA }
      const bRect: Rect = horizontal
        ? { x: rect.x + sizeA + gap, y: rect.y, width: sizeB, height: rect.height }
        : { x: rect.x, y: rect.y + sizeA + gap, width: rect.width, height: sizeB }
      walk(node.a, aRect)
      walk(node.b, bRect)
    }
    walk(tree, root)
  }

  const header = Math.max(0, Math.round(chrome.header))
  const tabbarHeight = tabbarMode === 'full' ? Math.max(0, Math.round(chrome.tabbar)) : Math.max(0, Math.round(chrome.tabbar * 0.67))
  const areas: Record<AreaId, AreaGeometry> = {}
  for (const { area, rect } of laidOut) {
    const hasTabbar = area.role === 'aux' || area.axis === 'horizontal'
    const top = header + (hasTabbar ? tabbarHeight : 0)
    const contentRect: Rect = {
      x: rect.x,
      y: rect.y + Math.min(top, rect.height),
      width: Math.max(1, Math.round(rect.width)),
      height: Math.max(1, Math.round(rect.height) - top),
    }
    areas[area.id] = {
      rect,
      contentRect,
      chrome: { tabbar: hasTabbar ? tabbarMode : 'hidden', header },
    }
    const limit = limitOf(area, limits)
    if (rect.width < limit.width || rect.height < limit.height) {
      issues.push({
        code: 'insufficient',
        areaId: area.id,
        need: { width: limit.width, height: limit.height },
        have: { width: rect.width, height: rect.height },
      })
    }
  }

  // user:“浮层矩形夹进视口（允许贴边），宽高不小于 1”+(只收进可视区，不改用户摆过的尺寸语义)。
  const floats: Record<SurfaceId, Rect> = {}
  for (const box of model.floats) {
    const w = Math.max(1, Math.min(Math.round(box.rect.width || DEFAULT_FLOAT_RECT.width), Math.max(1, width)))
    const h = Math.max(1, Math.min(Math.round(box.rect.height || DEFAULT_FLOAT_RECT.height), Math.max(1, height)))
    const maxX = Math.max(x, x + width - w)
    const maxY = Math.max(y, y + height - h)
    floats[box.id] = {
      x: Math.min(Math.max(x, Math.round(box.rect.x)), maxX),
      y: Math.min(Math.max(y, Math.round(box.rect.y)), maxY),
      width: w,
      height: h,
    }
  }

  return { areas, floats, issues }
}

export interface YieldInsets {
  left: number
  right: number
  top: number
  bottom: number
}

/**
 * 自由让位（Free Yield）：根据开启让位的浮层与主区交集，计算主区应主动让出的安全边距。
 *
 * user:“依旧不可见，你来完成新布局系统的开发工作：# Sunday UI 与统一工作区布局系统”+
 * (当某个浮层开启自由让位且主区避让后仍保留 >= minUsable 空间时，按遮挡面积最小的一侧避让；
 *  若任何方向避让都会把主区压到不可读，则自动回退为 0 边距的普通浮层覆盖)。
 */
export function computeYieldInsets(
  mainRect: Rect,
  floatRects: readonly Rect[],
  minUsable: { width: number; height: number } = { width: 360, height: 240 },
): YieldInsets {
  const zero: YieldInsets = { left: 0, right: 0, top: 0, bottom: 0 }
  if (!floatRects.length || mainRect.width <= 0 || mainRect.height <= 0) return zero

  let left = 0
  let right = 0
  let top = 0
  let bottom = 0
  const mainRight = mainRect.x + mainRect.width
  const mainBottom = mainRect.y + mainRect.height

  for (const box of floatRects) {
    const ix1 = Math.max(mainRect.x, box.x)
    const iy1 = Math.max(mainRect.y, box.y)
    const ix2 = Math.min(mainRight, box.x + box.width)
    const iy2 = Math.min(mainBottom, box.y + box.height)
    if (ix2 <= ix1 || iy2 <= iy1) continue

    const candidates: Array<{ side: keyof YieldInsets; inset: number }> = [
      { side: 'right', inset: Math.max(0, mainRight - ix1) },
      { side: 'left', inset: Math.max(0, ix2 - mainRect.x) },
      { side: 'bottom', inset: Math.max(0, mainBottom - iy1) },
      { side: 'top', inset: Math.max(0, iy2 - mainRect.y) },
    ]
    const valid = candidates.filter(c => {
      if (c.side === 'left' || c.side === 'right') return mainRect.width - c.inset >= minUsable.width
      return mainRect.height - c.inset >= minUsable.height
    })
    if (!valid.length) continue
    valid.sort((a, b) => a.inset - b.inset)
    const chosen = valid[0]
    if (chosen.side === 'left') left = Math.max(left, chosen.inset)
    else if (chosen.side === 'right') right = Math.max(right, chosen.inset)
    else if (chosen.side === 'top') top = Math.max(top, chosen.inset)
    else bottom = Math.max(bottom, chosen.inset)
  }

  if (mainRect.width - left - right < minUsable.width || mainRect.height - top - bottom < minUsable.height) {
    return zero
  }
  return { left, right, top, bottom }
}
