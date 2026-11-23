// user:“切布局 = 改 Placement；内容实例不重建”+(ops 里每个函数都是纯函数：失败返回原因码，
// 成功返回新 model。布局操作从不删除 surfaces 注册表里的内容——那属于内容层，不属于布局)。
//
// 说明：布局操作不会“销毁内容”。关区域/关标签只是把内容从位置上摘掉，SurfaceRef 仍留在注册表里。

import { computeWorkspace, type SizeLimits } from './compute'
import {
  areasOf,
  axisForKind,
  cloneModel,
  DEFAULT_FLOAT_RECT,
  normalizeWorkspace,
  type Area,
  type AreaId,
  type Rect,
  type SplitNode,
  type SurfaceId,
  type WorkspaceModel,
} from './model'

export type OpResult = { ok: true; model: WorkspaceModel } | { ok: false; reason: string }
export type SplitEdge = 'left' | 'right' | 'top' | 'bottom'

function fail(reason: string): OpResult { return { ok: false, reason } }

/** 确定性的区域 id：不引入 Date/random，引擎保持可重放。 */
function nextAreaId(model: WorkspaceModel): AreaId {
  const ids = new Set(areasOf(model).map(area => area.id))
  let index = 1
  while (ids.has(`aux-${index}`)) index += 1
  return `aux-${index}`
}

function replaceLeaf(node: SplitNode, areaId: AreaId, replacement: SplitNode): SplitNode {
  if (node.kind === 'leaf') return node.area.id === areaId ? replacement : node
  return { ...node, a: replaceLeaf(node.a, areaId, replacement), b: replaceLeaf(node.b, areaId, replacement) }
}

function removeLeaf(node: SplitNode, areaId: AreaId): SplitNode | null {
  if (node.kind === 'leaf') return node.area.id === areaId ? null : node
  const a = removeLeaf(node.a, areaId)
  const b = removeLeaf(node.b, areaId)
  if (!a) return b
  if (!b) return a
  return { ...node, a, b }
}

function directionOf(edge: SplitEdge): 'row' | 'column' {
  return edge === 'left' || edge === 'right' ? 'row' : 'column'
}

/** 把 surface 从所有区域里摘掉（除 keepAreaId 外），active 就近修正。 */
function detachFromAreas(model: WorkspaceModel, surfaceId: SurfaceId, keepAreaId?: AreaId): void {
  for (const area of areasOf(model)) {
    if (area.id === keepAreaId) continue
    const index = area.tabs.indexOf(surfaceId)
    if (index < 0) continue
    area.tabs.splice(index, 1)
    if (area.active === surfaceId) area.active = area.tabs[Math.min(index, area.tabs.length - 1)] ?? null
  }
}

function dropFloat(model: WorkspaceModel, surfaceId: SurfaceId): void {
  model.floats = model.floats.filter(box => box.id !== surfaceId)
  if (model.floatFocus === surfaceId) model.floatFocus = null
}

/**
 * 内部切分：返回新 model 与新建区域 id（不做 normalize，调用方需要精确的创建结果）。
 * share = 新区域占父区域的比例（0..1）。
 */
function splitInto(
  model: WorkspaceModel,
  areaId: AreaId,
  edge: SplitEdge,
  surfaceId: SurfaceId | null,
  share = .5,
): { model: WorkspaceModel; areaId: AreaId } | null {
  const source = areasOf(model).find(area => area.id === areaId)
  if (!source) return null
  if (surfaceId) {
    detachFromAreas(model, surfaceId)
    dropFloat(model, surfaceId)
  }
  const created: Area = {
    id: nextAreaId(model),
    tabs: surfaceId ? [surfaceId] : [],
    active: surfaceId ?? null,
    role: 'aux',
    axis: surfaceId && model.surfaces[surfaceId] ? axisForKind(model.surfaces[surfaceId].kind) : 'vertical',
  }
  const clampedShare = Math.min(.9, Math.max(.1, Number.isFinite(share) ? share : .5))
  const ratio = edge === 'left' || edge === 'top' ? clampedShare : 1 - clampedShare
  const original: SplitNode = { kind: 'leaf', area: { ...source } }
  const createdNode: SplitNode = { kind: 'leaf', area: created }
  const before = edge === 'left' || edge === 'top'
  const node: SplitNode = {
    kind: 'split',
    direction: directionOf(edge),
    ratio,
    a: before ? createdNode : original,
    b: before ? original : createdNode,
  }
  model.tree = replaceLeaf(model.tree, areaId, node)
  return { model, areaId: created.id }
}

/**
 * user:“拖到 Area 边缘 = 切分；右键「向右/向下分屏」”+
 * (切分只改树与位置；带 withSurface 时把这份内容搬进新区域，同一 Surface 仍只有一处)。
 */
export function splitArea(model: WorkspaceModel, areaId: AreaId, edge: SplitEdge, withSurface?: SurfaceId): OpResult {
  if (!areasOf(model).some(area => area.id === areaId)) return fail('area-not-found')
  if (withSurface && !model.surfaces[withSurface]) return fail('surface-not-found')
  const clone = cloneModel(model)
  const split = splitInto(clone, areaId, edge, withSurface ?? null)
  if (!split) return fail('area-not-found')
  return { ok: true, model: normalizeWorkspace(split.model) }
}

/** user:“关闭区域”+(main 不可关；关掉的只是位置，内容注册表不因此删除)。 */
export function closeArea(model: WorkspaceModel, areaId: AreaId): OpResult {
  const area = areasOf(model).find(item => item.id === areaId)
  if (!area) return fail('area-not-found')
  if (area.role === 'main') return fail('main-area')
  const clone = cloneModel(model)
  const tree = removeLeaf(clone.tree, areaId)
  if (!tree) return fail('last-area')
  clone.tree = tree
  return { ok: true, model: normalizeWorkspace(clone) }
}

/** path 从根开始：0 = a（左/上），1 = b（右/下）。路径无效时原样返回。 */
export function resizeSplit(model: WorkspaceModel, path: number[], ratio: number): WorkspaceModel {
  const clone = cloneModel(model)
  let node: SplitNode = clone.tree
  for (const step of path) {
    if (node.kind !== 'split') return model
    node = step === 0 ? node.a : step === 1 ? node.b : node
  }
  if (node.kind !== 'split') return model
  const next = Number.isFinite(ratio) ? ratio : node.ratio
  node.ratio = Math.min(.98, Math.max(.02, next))
  return clone
}



/** user:“主辅互换：交换两个区域的内容集合，surface 实例不变”+(角色跟着位置，内容跟着互换)。 */
export function swapAreas(model: WorkspaceModel, a: AreaId, b: AreaId): OpResult {
  if (a === b) return fail('same-area')
  const clone = cloneModel(model)
  const first = areasOf(clone).find(area => area.id === a)
  const second = areasOf(clone).find(area => area.id === b)
  if (!first || !second) return fail('area-not-found')
  const tabs = first.tabs; first.tabs = second.tabs; second.tabs = tabs
  const active = first.active; first.active = second.active; second.active = active
  for (const area of [first, second]) {
    const surface = area.active ? clone.surfaces[area.active] : undefined
    if (surface) area.axis = axisForKind(surface.kind)
  }
  return { ok: true, model: normalizeWorkspace(clone) }
}

/**
 * user:“区域重停靠：拖 Area 角柄到另一 Area 边缘，先撤源再切目标，净变化为零”+
 * (先把源叶子从树上摘掉、再用同一块 Area 对象挂到目标边缘：标签对象不复制，内容不重建)。
 */
export function moveArea(model: WorkspaceModel, areaId: AreaId, targetAreaId: AreaId, edge: SplitEdge): OpResult {
  if (areaId === targetAreaId) return fail('same-area')
  const source = areasOf(model).find(area => area.id === areaId)
  if (!source) return fail('area-not-found')
  if (source.role === 'main') return fail('main-area')
  if (!areasOf(model).some(area => area.id === targetAreaId)) return fail('target-not-found')
  const clone = cloneModel(model)
  const moving = areasOf(clone).find(area => area.id === areaId)!
  const target = areasOf(clone).find(area => area.id === targetAreaId)!
  const pruned = removeLeaf(clone.tree, areaId)
  if (!pruned) return fail('last-area')
  const before = edge === 'left' || edge === 'top'
  const node: SplitNode = {
    kind: 'split',
    direction: directionOf(edge),
    ratio: .5,
    a: before ? { kind: 'leaf', area: moving } : { kind: 'leaf', area: target },
    b: before ? { kind: 'leaf', area: target } : { kind: 'leaf', area: moving },
  }
  clone.tree = replaceLeaf(pruned, targetAreaId, node)
  return { ok: true, model: normalizeWorkspace(clone) }
}

function overlapArea(a: Rect, b: Rect): number {
  const width = Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x))
  const height = Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y))
  return width * height
}

function centerGap(a: Rect, b: Rect): number {
  return Math.hypot(a.x + a.width / 2 - (b.x + b.width / 2), a.y + a.height / 2 - (b.y + b.height / 2))
}

/** 与 compute 的浮层夹取同一口径：夹进视口、宽高 ≥1，让 ops 返回的模型可以直接渲染。 */
function clampRectInto(rect: Rect, viewport: Rect): Rect {
  const originX = Math.round(viewport.x)
  const originY = Math.round(viewport.y)
  const width = Math.max(1, Math.min(Math.round(rect.width), Math.max(1, Math.round(viewport.width))))
  const height = Math.max(1, Math.min(Math.round(rect.height), Math.max(1, Math.round(viewport.height))))
  const maxX = originX + Math.max(0, Math.round(viewport.width) - width)
  const maxY = originY + Math.max(0, Math.round(viewport.height) - height)
  return {
    x: Math.min(Math.max(originX, Math.round(rect.x)), maxX),
    y: Math.min(Math.max(originY, Math.round(rect.y)), maxY),
    width,
    height,
  }
}

function pinEdgeFor(rect: Rect, floatRect: Rect): SplitEdge {
  const dx = (floatRect.x + floatRect.width / 2) - (rect.x + rect.width / 2)
  const dy = (floatRect.y + floatRect.height / 2) - (rect.y + rect.height / 2)
  if (Math.abs(dx) >= Math.abs(dy)) return dx >= 0 ? 'right' : 'left'
  return dy >= 0 ? 'bottom' : 'top'
}

/** 新区域占父区域的比例：取浮层外沿在目标区域里的真实位置，再夹到一个安全区间。 */
function pinShareFor(rect: Rect, floatRect: Rect, edge: SplitEdge): number {
  const horizontal = edge === 'left' || edge === 'right'
  const extent = horizontal ? rect.width : rect.height
  if (!(extent > 0)) return .5
  const raw = edge === 'left' ? (floatRect.x + floatRect.width - rect.x) / extent
    : edge === 'right' ? 1 - (floatRect.x - rect.x) / extent
    : edge === 'top' ? (floatRect.y + floatRect.height - rect.y) / extent
    : 1 - (floatRect.y - rect.y) / extent
  return Math.min(.9, Math.max(.1, Number.isFinite(raw) ? raw : .5))
}

function attemptPin(
  model: WorkspaceModel,
  surfaceId: SurfaceId,
  floatRect: Rect,
  areaId: AreaId,
  edge: SplitEdge,
  share: number,
  viewport: Rect,
  useCompact: boolean,
  limits?: SizeLimits,
  requireFit = true,
): { ok: true; model: WorkspaceModel; preview: Rect } | null {
  const clone = cloneModel(model)
  if (useCompact) clone.prefs.compact = true
  // user:“pin 时保留上一次浮层尺寸”+(此刻的浮层矩形就是“最新一次浮动”，先记下来再摘掉浮层；
  //  之后 unpin 才能恢复原尺寸。纯置顶/焦点不会走到这里，所以不会把记录改乱)。
  clone.lastFloatRect[surfaceId] = { ...floatRect }
  dropFloat(clone, surfaceId)
  const split = splitInto(clone, areaId, edge, surfaceId, share)
  if (!split) return null
  const next = normalizeWorkspace(split.model)
  const after = computeWorkspace(next, viewport, { limits })
  const preview = after.areas[split.areaId]?.rect
  if (!preview || preview.width < 1 || preview.height < 1) return null
  if (requireFit && after.issues.some(issue => issue.code === 'insufficient')) return null
  return { ok: true, model: next, preview }
}

/**
 * user:“固定（pin）：按中心落位选目标 Area，克隆布局算出结果，预览条 = 落地结果；失败给出原因”+
 * (候选按“重叠面积降序 → 中心距升序”逐个尝试；每一步都在克隆上算，所以 preview 就是落地矩形。
//  失败原因码：not-a-float / insufficient)。
 */
// user:“重写判定，满足随时固定的需求”+(第一级优先无 insufficient 的舒适落位；若窗口较窄/较矮或已有多分屏，
// 第二级按主方向与紧凑配比直接落位，仅在视口本身极端过小时才拒绝对等拆分)。
// user:“浮层转为固定分屏之后 会使其他分屏的内容消失”+(固定只改变布局树和落点，所有已打开的区域都继续显示)。
export const MIN_SPLIT_VIEWPORT = 160

export function pinFloat(
  model: WorkspaceModel,
  surfaceId: SurfaceId,
  viewport: Rect,
  limits?: SizeLimits,
): { ok: true; model: WorkspaceModel; preview: Rect } | { ok: false; reason: string } {
  const box = model.floats.find(item => item.id === surfaceId)
  if (!box) return { ok: false, reason: 'not-a-float' }
  if (viewport.width < MIN_SPLIT_VIEWPORT || viewport.height < MIN_SPLIT_VIEWPORT) return { ok: false, reason: 'insufficient' }

  const geometry = computeWorkspace(model, viewport, { limits })
  const candidates = Object.entries(geometry.areas)
    .map(([areaId, value]) => ({ areaId, rect: value.rect, overlap: overlapArea(value.rect, box.rect), gap: centerGap(value.rect, box.rect) }))
    .sort((a, b) => b.overlap - a.overlap || a.gap - b.gap)
  if (!candidates.length) return { ok: false, reason: 'insufficient' }

  // 若存在空闲的辅助分屏区域，优先直接把浮层放入该空区，避免反复新建空白分屏。
  const modelAreas = areasOf(model)
  for (const candidate of candidates) {
    const area = modelAreas.find(item => item.id === candidate.areaId)
    if (!area || area.role === 'main' || area.tabs.length > 0) continue
    const clone = cloneModel(model)
    clone.lastFloatRect[surfaceId] = { ...box.rect }
    dropFloat(clone, surfaceId)
    const target = areasOf(clone).find(item => item.id === area.id)!
    target.tabs = [surfaceId]
    target.active = surfaceId
    const surface = clone.surfaces[surfaceId]
    if (surface) target.axis = axisForKind(surface.kind)
    const next = normalizeWorkspace(clone)
    const after = computeWorkspace(next, viewport, { limits })
    const preview = after.areas[target.id]?.rect
    if (preview) {
      return { ok: true, model: next, preview }
    }
  }

  const compactAttempts = model.prefs.compact ? [true] : [false, true]
  for (const useCompact of compactAttempts) {
    for (const candidate of candidates) {
      const primary = pinEdgeFor(candidate.rect, box.rect)
      const fallbackOrder: SplitEdge[] = primary === 'top' || primary === 'bottom'
        ? [primary, 'right', 'left', primary === 'top' ? 'bottom' : 'top']
        : [primary, primary === 'right' ? 'left' : 'right', 'bottom', 'top']
      for (const edge of fallbackOrder) {
        const preferredShare = pinShareFor(candidate.rect, box.rect, edge)
        const shares = [preferredShare, .5, .44]
        for (const share of shares) {
          const hit = attemptPin(model, surfaceId, box.rect, candidate.areaId, edge, share, viewport, useCompact, limits, true)
          if (hit) return hit
        }
      }
    }
  }

  // 保底放行：允许在不隐藏任何区域的前提下按 0.3..0.7 合理比例直接固定进首选区域。
  const best = candidates[0]
  let edge = pinEdgeFor(best.rect, box.rect)
  const horizontal = edge === 'left' || edge === 'right'
  if (horizontal && best.rect.width < 160 && best.rect.height > best.rect.width) {
    const dy = (box.rect.y + box.rect.height / 2) - (best.rect.y + best.rect.height / 2)
    edge = dy >= 0 ? 'bottom' : 'top'
  } else if (!horizontal && best.rect.height < 160 && best.rect.width >= best.rect.height) {
    const dx = (box.rect.x + box.rect.width / 2) - (best.rect.x + best.rect.width / 2)
    edge = dx >= 0 ? 'right' : 'left'
  }
  const rawShare = pinShareFor(best.rect, box.rect, edge)
  const safeShare = Math.min(.7, Math.max(.3, Number.isFinite(rawShare) ? rawShare : .5))
  const fallbackHit = attemptPin(model, surfaceId, box.rect, best.areaId, edge, safeShare, viewport, !limits, limits, false)
    ?? attemptPin(model, surfaceId, box.rect, best.areaId, edge, .5, viewport, false, limits, false)
  return fallbackHit ?? { ok: false, reason: 'insufficient' }
}

/**
 * user:“解除固定（unpin）：恢复该内容上一次浮层尺寸，位置贴近原 Area，置顶并聚焦”+
 * (优先用 lastFloatRect：尺寸照搬；位置若仍落在目标区域内就沿用用户摆过的地方，
//  否则拉回区域左上角 +24 保持视觉联系；最后整体夹进视口——窗口变小也一定看得见。
//  没有记录（旧档/从未浮动过）才退回区域 46%/52% 兜底。取走后区域空掉就收拢)。
 */
// user:“分屏化为浮层时 给它安排合适的大小”+(根据原区域与视口按比例取舒适的浮窗宽高，既不缩成细条也不铺满整屏)
export function defaultFloatSize(areaRect: Rect, viewport: Rect): { width: number; height: number } {
  const maxW = Math.max(240, Math.round(viewport.width * 0.65))
  const maxH = Math.max(180, Math.round(viewport.height * 0.78))
  const width = Math.min(maxW, Math.max(460, Math.round(areaRect.width * 0.9)))
  const height = Math.min(maxH, Math.max(360, Math.round(areaRect.height * 0.72)))
  return { width: Math.max(1, width), height: Math.max(1, height) }
}

export function unpinArea(model: WorkspaceModel, areaId: AreaId, viewport: Rect): OpResult {
  const area = areasOf(model).find(item => item.id === areaId)
  if (!area) return fail('area-not-found')

  const surfaceId = area.active ?? area.tabs[0] ?? null
  if (!surfaceId) return fail('empty-area')
  const geometry = computeWorkspace(model, viewport)
  const rect = geometry.areas[areaId]?.rect
  if (!rect) return fail('no-rect')

  const remembered = model.lastFloatRect[surfaceId]
  const fallback = defaultFloatSize(rect, viewport)
  const width = Math.max(1, Math.round(remembered?.width ?? fallback.width))
  const height = Math.max(1, Math.round(remembered?.height ?? fallback.height))
  // 位置仍与目标区域相交 → 沿用记录位置；否则贴回区域左上角（视觉联系优先于“原地复原”）。
  const keepPosition = remembered ? overlapArea(remembered, rect) > 0 : false
  const floatRect = clampRectInto({
    x: keepPosition ? remembered!.x : rect.x + 24,
    y: keepPosition ? remembered!.y : rect.y + 24,
    width,
    height,
  }, viewport)

  const clone = cloneModel(model)
  const target = areasOf(clone).find(item => item.id === areaId)!
  const index = target.tabs.indexOf(surfaceId)
  if (index >= 0) target.tabs.splice(index, 1)
  if (target.active === surfaceId) target.active = target.tabs[Math.min(Math.max(index, 0), target.tabs.length - 1)] ?? null
  if (target.tabs.length === 0 && areasOf(clone).length > 1) {
    const pruned = removeLeaf(clone.tree, areaId)
    if (pruned) clone.tree = pruned
  }
  clone.floats = [...clone.floats, { id: surfaceId, rect: floatRect, yieldEnabled: false }]
  clone.floatFocus = surfaceId
  clone.lastFloatRect[surfaceId] = { ...floatRect }
  return { ok: true, model: normalizeWorkspace(clone) }
}

export function floatToFront(model: WorkspaceModel, surfaceId: SurfaceId): WorkspaceModel {
  const box = model.floats.find(item => item.id === surfaceId)
  if (!box) return model
  const clone = cloneModel(model)
  const rest = clone.floats.filter(item => item.id !== surfaceId)
  clone.floats = [...rest, clone.floats.find(item => item.id === surfaceId)!]
  clone.floatFocus = surfaceId
  return clone
}

export function floatToBack(model: WorkspaceModel, surfaceId: SurfaceId): WorkspaceModel {
  const box = model.floats.find(item => item.id === surfaceId)
  if (!box) return model
  const clone = cloneModel(model)
  const moving = clone.floats.find(item => item.id === surfaceId)!
  clone.floats = [moving, ...clone.floats.filter(item => item.id !== surfaceId)]
  if (clone.floatFocus === surfaceId) clone.floatFocus = clone.floats[clone.floats.length - 1]?.id ?? null
  return clone
}

/** user:“Alt+` 循环焦点”+(焦点永远在最上面：轮转顺序只改 z 序，不改内容)。 */
export function cycleFloatFocus(model: WorkspaceModel, direction: 1 | -1): WorkspaceModel {
  if (!model.floats.length) return model
  const clone = cloneModel(model)
  const order = clone.floats.map(item => item.id)
  const current = clone.floatFocus ? order.indexOf(clone.floatFocus) : -1
  const next = current < 0
    ? (direction === 1 ? 0 : order.length - 1)
    : (current + direction + order.length) % order.length
  const id = order[next]
  clone.floatFocus = id
  clone.floats = [...clone.floats.filter(item => item.id !== id), clone.floats.find(item => item.id === id)!]
  return clone
}

export function setFloatRect(model: WorkspaceModel, surfaceId: SurfaceId, rect: Rect): WorkspaceModel {
  const current = model.floats.find(item => item.id === surfaceId)?.rect
  if (!current) return model
  const next: Rect = {
    x: Number.isFinite(rect.x) ? rect.x : current.x,
    y: Number.isFinite(rect.y) ? rect.y : current.y,
    width: Math.max(1, Number.isFinite(rect.width) ? rect.width : current.width),
    height: Math.max(1, Number.isFinite(rect.height) ? rect.height : current.height),
  }
  // user:“只在矩形真的变化时更新上一次浮层尺寸”+(同一帧里重复写同一个矩形、或只是置顶/切焦点，
  //  都不该动这条记录——否则“上一次合理的浮层尺寸”会被中间值污染)。
  if (next.x === current.x && next.y === current.y && next.width === current.width && next.height === current.height) return model
  const clone = cloneModel(model)
  const box = clone.floats.find(item => item.id === surfaceId)!
  box.rect = next
  clone.lastFloatRect[surfaceId] = { ...next }
  return clone
}

export function setFloatYield(model: WorkspaceModel, surfaceId: SurfaceId, enabled: boolean): WorkspaceModel {
  if (!model.floats.some(item => item.id === surfaceId)) return model
  const clone = cloneModel(model)
  const box = clone.floats.find(item => item.id === surfaceId)!
  box.yieldEnabled = enabled === true
  return clone
}
