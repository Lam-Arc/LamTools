// user:“角柄 > 交叉点 > 边缘热区 > 标签栏 > 内容区；拖标签时改为标签栏优先”+
// (命中只吃 compute 出来的几何，不碰 DOM：这样“拖到角上到底是分屏还是调比例”只有一个答案)。

import type { WorkspaceGeometry } from './compute'
import { areasOf, type AreaId, type Rect, type SplitNode, type WorkspaceModel } from './model'

export type HitZone =
  | { kind: 'divider'; path: number[]; direction: 'row' | 'column' }
  | { kind: 'corner'; areaId: AreaId; corner: 'nw' | 'ne' | 'sw' | 'se' }
  | { kind: 'edge'; areaId: AreaId; edge: 'left' | 'right' | 'top' | 'bottom' }
  | { kind: 'tabbar'; areaId: AreaId }
  | { kind: 'content'; areaId: AreaId }
  | { kind: 'none' }

const CORNER_SIZE = 18
const DEFAULT_DIVIDER_HIT = 6
const DEFAULT_EDGE_BAND = 40
const TABBAR_BAND = 36

interface Point { x: number; y: number }

function inside(rect: Rect, point: Point): boolean {
  return point.x >= rect.x && point.y >= rect.y && point.x < rect.x + rect.width && point.y < rect.y + rect.height
}

function subtreeRect(node: SplitNode, rects: Record<AreaId, Rect>): Rect | null {
  if (node.kind === 'leaf') return rects[node.area.id] ?? null
  const a = subtreeRect(node.a, rects)
  const b = subtreeRect(node.b, rects)
  if (!a) return b
  if (!b) return a
  const x = Math.min(a.x, b.x)
  const y = Math.min(a.y, b.y)
  const right = Math.max(a.x + a.width, b.x + b.width)
  const bottom = Math.max(a.y + a.height, b.y + b.height)
  return { x, y, width: right - x, height: bottom - y }
}

/** 深层优先：T 形布局里贴近指针的那条短分隔线先命中，不会被外层整条线吃掉。 */
function findDivider(node: SplitNode, path: number[], rects: Record<AreaId, Rect>, point: Point, hit: number): HitZone | null {
  if (node.kind !== 'split') return null
  const deeper = findDivider(node.a, [...path, 0], rects, point, hit)
    ?? findDivider(node.b, [...path, 1], rects, point, hit)
  if (deeper) return deeper
  const a = subtreeRect(node.a, rects)
  const b = subtreeRect(node.b, rects)
  if (!a || !b) return null
  if (node.direction === 'row') {
    const line = a.x + a.width
    const top = Math.min(a.y, b.y)
    const bottom = Math.max(a.y + a.height, b.y + b.height)
    if (point.y >= top && point.y <= bottom && point.x >= line - hit && point.x <= b.x + hit) {
      return { kind: 'divider', path, direction: 'row' }
    }
  } else {
    const line = a.y + a.height
    const left = Math.min(a.x, b.x)
    const right = Math.max(a.x + a.width, b.x + b.width)
    if (point.x >= left && point.x <= right && point.y >= line - hit && point.y <= b.y + hit) {
      return { kind: 'divider', path, direction: 'column' }
    }
  }
  return null
}

function findEdge(geometry: WorkspaceGeometry, model: WorkspaceModel, point: Point, band: number): HitZone | null {
  let best: { areaId: AreaId; edge: 'left' | 'right' | 'top' | 'bottom'; distance: number } | null = null
  for (const area of areasOf(model)) {
    const value = geometry.areas[area.id]
    if (!value || !inside(value.rect, point)) continue
    const rect = value.rect
    const bandX = Math.min(band, rect.width * .25)
    const bandY = Math.min(band, rect.height * .25)
    const candidates: Array<{ edge: 'left' | 'right' | 'top' | 'bottom'; distance: number; limit: number }> = [
      { edge: 'left', distance: point.x - rect.x, limit: bandX },
      { edge: 'right', distance: rect.x + rect.width - point.x, limit: bandX },
      { edge: 'top', distance: point.y - rect.y, limit: bandY },
      { edge: 'bottom', distance: rect.y + rect.height - point.y, limit: bandY },
    ]
    for (const candidate of candidates) {
      if (candidate.distance > candidate.limit) continue
      if (!best || candidate.distance < best.distance) best = { areaId: area.id, edge: candidate.edge, distance: candidate.distance }
    }
  }
  return best ? { kind: 'edge', areaId: best.areaId, edge: best.edge } : null
}

/** 标签栏：横向轴在页眉之下、内容之上；纵向轴是左侧侧栏（宽度用 36 兜底）。 */
function findTabbar(geometry: WorkspaceGeometry, model: WorkspaceModel, point: Point): HitZone | null {
  for (const area of areasOf(model)) {
    const value = geometry.areas[area.id]
    if (!value || !inside(value.rect, point)) continue
    if (value.chrome.tabbar !== 'hidden') {
      const top = value.rect.y + value.chrome.header
      const bottom = value.contentRect.y
      if (bottom > top && point.y >= top && point.y < bottom) return { kind: 'tabbar', areaId: area.id }
      if (bottom <= top && point.y - value.rect.y < TABBAR_BAND) return { kind: 'tabbar', areaId: area.id }
    } else if (point.x - value.rect.x < TABBAR_BAND) {
      return { kind: 'tabbar', areaId: area.id }
    }
  }
  return null
}

/**
 * user:“拖拽的判定，应该只有中间区域是拖拽判定，偏靠角的那一块应该留给创建分屏的判定”+
 * (priority='tabbar-first' 给“拖标签”用：落在别人的标签栏上是要“挪进去”，不是再开一块屏)。
 */
export function hitWorkspace(
  geometry: WorkspaceGeometry,
  model: WorkspaceModel,
  point: Point,
  opts: { dividerHit?: number; edgeBand?: number; priority?: 'default' | 'tabbar-first' } = {},
): HitZone {
  const dividerHit = Math.max(1, opts.dividerHit ?? DEFAULT_DIVIDER_HIT)
  const edgeBand = Math.max(1, opts.edgeBand ?? DEFAULT_EDGE_BAND)
  const priority = opts.priority ?? 'default'

  for (const area of areasOf(model)) {
    const value = geometry.areas[area.id]
    if (!value || !inside(value.rect, point)) continue
    const rect = value.rect
    const left = point.x - rect.x
    const right = rect.x + rect.width - point.x
    const top = point.y - rect.y
    const bottom = rect.y + rect.height - point.y
    if (left <= CORNER_SIZE && top <= CORNER_SIZE) return { kind: 'corner', areaId: area.id, corner: 'nw' }
    if (right <= CORNER_SIZE && top <= CORNER_SIZE) return { kind: 'corner', areaId: area.id, corner: 'ne' }
    if (left <= CORNER_SIZE && bottom <= CORNER_SIZE) return { kind: 'corner', areaId: area.id, corner: 'sw' }
    if (right <= CORNER_SIZE && bottom <= CORNER_SIZE) return { kind: 'corner', areaId: area.id, corner: 'se' }
  }

  const rects: Record<AreaId, Rect> = {}
  for (const [id, value] of Object.entries(geometry.areas)) rects[id] = value.rect

  if (priority === 'tabbar-first') {
    const tabbar = findTabbar(geometry, model, point)
    if (tabbar) return tabbar
  }
  const divider = findDivider(model.tree, [], rects, point, dividerHit)
  if (divider) return divider
  const edge = findEdge(geometry, model, point, edgeBand)
  if (edge) return edge
  if (priority !== 'tabbar-first') {
    const tabbar = findTabbar(geometry, model, point)
    if (tabbar) return tabbar
  }
  for (const area of areasOf(model)) {
    const value = geometry.areas[area.id]
    if (value && inside(value.rect, point)) return { kind: 'content', areaId: area.id }
  }
  return { kind: 'none' }
}

// user:“吸附 25/50/75（Alt 关闭）”+(只把指针值就近归位，不改变比率模型；关掉就完全跟手)。
export function snapRatio(ratio: number, opts: { stops?: number[]; tolerance?: number; snap?: boolean } = {}): number {
  const value = Number.isFinite(ratio) ? Math.min(1, Math.max(0, ratio)) : .5
  if (opts.snap === false) return value
  const stops = opts.stops ?? [.25, .5, .75]
  const tolerance = opts.tolerance ?? .04
  for (const stop of stops) if (Math.abs(value - stop) <= tolerance) return stop
  return value
}

/** 拖标签/拖区域的落点：边缘带内取最近的一条边，否则算“挪进去”。band 是比例（0–0.45）。 */
export function dropEdgeFor(point: Point, rect: Rect, band = .2): 'left' | 'right' | 'top' | 'bottom' | 'center' {
  if (!(rect.width > 0) || !(rect.height > 0)) return 'center'
  if (!inside(rect, point)) return 'center'
  const ratio = Math.min(.45, Math.max(0, band))
  const left = point.x - rect.x
  const right = rect.x + rect.width - point.x
  const top = point.y - rect.y
  const bottom = rect.y + rect.height - point.y
  const candidates: Array<{ edge: 'left' | 'right' | 'top' | 'bottom'; distance: number }> = []
  if (left <= rect.width * ratio) candidates.push({ edge: 'left', distance: left })
  if (right <= rect.width * ratio) candidates.push({ edge: 'right', distance: right })
  if (top <= rect.height * ratio) candidates.push({ edge: 'top', distance: top })
  if (bottom <= rect.height * ratio) candidates.push({ edge: 'bottom', distance: bottom })
  candidates.sort((a, b) => a.distance - b.distance)
  return candidates[0]?.edge ?? 'center'
}
