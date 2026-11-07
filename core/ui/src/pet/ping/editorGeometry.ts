/**
 * Ping 工作台环预览的纯几何。
 *
 * user:“一级为完整同心环；二级、三级均是父扇区径向外侧的局部同心弧形环带”+
 * “每项文字整体按自己的扇区中心径向角旋转”+
 * “长文本截断 …，悬停可显示全文”+
 * (设置页沙盒与生产环共用同一套角度语义：0° 在正上方、顺时针增长，
 *  标签旋转角 = 扇区中心角。这里只产出 SVG 路径与文本锚点，方便单测。)
 */
import type { PingSectorConfig } from '../config.ts'
import { childGroupOf } from './editorTree.ts'

export interface RingArc {
  id: string
  label: string
  fullLabel: string
  icon: string
  color: string
  enabled: boolean
  /** 扇区起止角（标准数学角：-π/2 = 正上方，顺时针增长）。 */
  start: number
  end: number
  path: string
  labelX: number
  labelY: number
  rotation: number
}

export interface RingBand {
  inner: number
  outer: number
  arcs: RingArc[]
}

export interface RingEditorGeometry {
  size: number
  cx: number
  cy: number
  radius: number
  bandWidth: number
  root: RingBand
  /** 兼容旧调用：第二层；没有则为 null。 */
  child: RingBand | null
  childParentId: string
  /** 从一级到当前选中项的所有同心环带（最多 3 层）。 */
  bands: RingBand[]
}

export const EDITOR_GAP_RATIO = 0.03
export const EDITOR_MAX_CHILD_SPAN = 2.1
export const EDITOR_MIN_CHILD_SPAN = 0.7

export function polar(cx: number, cy: number, radius: number, angle: number): { x: number; y: number } {
  // 与生产 PingRing/ringModel 使用同一套标准数学角，避免工作台预览与真实
  // 环的扇区中心、标签旋转角出现偏移。
  return {
    x: cx + Math.cos(angle) * radius,
    y: cy + Math.sin(angle) * radius,
  }
}

/** 环形扇区路径（外弧顺时针、内弧逆时针）。 */
export function annulusPath(
  cx: number,
  cy: number,
  inner: number,
  outer: number,
  start: number,
  end: number,
): string {
  const large = end - start > Math.PI ? 1 : 0
  const outerStart = polar(cx, cy, outer, start)
  const outerEnd = polar(cx, cy, outer, end)
  const innerEnd = polar(cx, cy, inner, end)
  const innerStart = polar(cx, cy, inner, start)
  return [
    `M${round(outerStart.x)} ${round(outerStart.y)}`,
    `A${round(outer)} ${round(outer)} 0 ${large} 1 ${round(outerEnd.x)} ${round(outerEnd.y)}`,
    `L${round(innerEnd.x)} ${round(innerEnd.y)}`,
    `A${round(inner)} ${round(inner)} 0 ${large} 0 ${round(innerStart.x)} ${round(innerStart.y)}`,
    'Z',
  ].join(' ')
}

function round(value: number): number {
  return Math.round(value * 100) / 100
}

/** 长标签截断；完整文本保留在 fullLabel 供 title/悬停显示。 */
export function truncateLabel(text: string, maxChars = 8): string {
  const value = String(text || '').trim()
  if (value.length <= maxChars) return value
  return `${value.slice(0, Math.max(1, maxChars - 1))}…`
}

function arcsFor(
  sectors: PingSectorConfig[],
  cx: number,
  cy: number,
  inner: number,
  outer: number,
  startAngle: number,
  span: number,
  maxChars: number,
): RingArc[] {
  if (sectors.length === 0 || outer <= inner) return []
  const slot = span / sectors.length
  const gap = Math.min(slot * EDITOR_GAP_RATIO, 0.018)
  return sectors.map((sector, index) => {
    const start = startAngle + index * slot + gap / 2
    const end = startAngle + (index + 1) * slot - gap / 2
    const mid = (start + end) / 2
    const labelRadius = (inner + outer) / 2
    const label = polar(cx, cy, labelRadius, mid)
    return {
      id: sector.id,
      label: truncateLabel(sector.label, maxChars),
      fullLabel: sector.label,
      icon: sector.icon,
      color: sector.color,
      enabled: sector.enabled,
      start,
      end,
      path: annulusPath(cx, cy, inner, outer, start, end),
      labelX: round(label.x),
      labelY: round(label.y),
      rotation: round((mid * 180) / Math.PI),
    }
  })
}

function enabledRoots(sectors: PingSectorConfig[]): PingSectorConfig[] {
  return sectors.filter(sector => !sector.group && sector.enabled)
}

export function childrenOf(sectors: PingSectorConfig[], parent: PingSectorConfig | null): PingSectorConfig[] {
  if (!parent) return enabledRoots(sectors)
  const group = parent.subring || parent.id
  return sectors.filter(sector => sector.enabled && sector.group === group)
}

/**
 * 生成工作台预览：一级完整环 + 选中项父链上的局部子环（最多到第三级）。
 * `selectedId` 为空时默认选第一个一级项。
 */
export function buildRingEditorGeometry(
  sectors: PingSectorConfig[],
  options: {
    radius: number
    ringWidth: number
    selectedId?: string
    maxLabelChars?: number
  },
): RingEditorGeometry {
  const roots = enabledRoots(sectors)
  const radius = Math.max(40, options.radius)
  const bandWidth = Math.max(8, options.ringWidth)
  const outerRadius = radius + bandWidth / 2
  const childWidth = Math.max(46, Math.min(96, bandWidth * 2.2))
  const pad = Math.max(18, bandWidth * 1.3)
  const maxChars = options.maxLabelChars ?? 8
  const maxChildOuter = outerRadius + (8 + childWidth) * 2
  const size = Math.max(240, (maxChildOuter + pad) * 2)
  const cx = size / 2
  const cy = size / 2
  const rootBand: RingBand = {
    inner: radius - bandWidth / 2,
    outer: outerRadius,
    arcs: arcsFor(roots, cx, cy, radius - bandWidth / 2, outerRadius, -Math.PI / 2, Math.PI * 2, maxChars),
  }
  if (roots.length === 0) {
    return { size, cx, cy, radius, bandWidth, root: rootBand, child: null, childParentId: '', bands: [rootBand] }
  }

  const byId = new Map(sectors.map(sector => [sector.id, sector]))
  const parentOf = (sector: PingSectorConfig): PingSectorConfig | null => {
    if (!sector.group) return null
    return sectors.find(candidate => childGroupOf(candidate) === sector.group) || null
  }
  const chain: PingSectorConfig[] = []
  let cursor = byId.get(options.selectedId || '') || roots[0]
  while (cursor && chain.length < 3) {
    chain.unshift(cursor)
    cursor = parentOf(cursor) || roots[0]
    if (chain[0] === cursor) break
  }
  // 选中的可能是第三级，也可能在会话环里；父链只保留能从根到达的部分。
  const rootInChain = chain.find(sector => !sector.group) || roots[0]
  const rootIndex = roots.findIndex(sector => sector.id === rootInChain.id)
  const selectedRoot = roots[rootIndex >= 0 ? rootIndex : 0]
  const bands: RingBand[] = [rootBand]
  const step = (Math.PI * 2) / roots.length
  let parentArc: RingArc | null = rootBand.arcs.find(arc => arc.id === selectedRoot.id) || rootBand.arcs[0] || null
  let parent: PingSectorConfig | null = selectedRoot
  let inner = outerRadius + 8
  for (let depth = 2; depth <= 3 && parent; depth += 1) {
    const children = childrenOf(sectors, parent)
    if (children.length === 0) break
    const span = Math.min(EDITOR_MAX_CHILD_SPAN, Math.max(EDITOR_MIN_CHILD_SPAN, children.length * 0.3))
    const parentMid = parentArc ? (parentArc.start + parentArc.end) / 2 : -Math.PI / 2 + rootIndex * step + step / 2
    // 只有父链上的项才继续向外展开；否则显示当前父项的一层子环即可。
    const nextInChain = chain[depth - 1]
    const chainChild = nextInChain ? children.find(child => child.id === nextInChain.id) : undefined
    const band: RingBand = {
      inner,
      outer: inner + childWidth,
      arcs: arcsFor(children, cx, cy, inner, inner + childWidth, parentMid - span / 2, span, maxChars),
    }
    bands.push(band)
    if (!chainChild) break
    parent = chainChild
    parentArc = band.arcs.find(arc => arc.id === chainChild.id) || null
    inner = band.outer + 8
  }

  return {
    size,
    cx,
    cy,
    radius,
    bandWidth,
    root: rootBand,
    child: bands[1] || null,
    childParentId: parent?.id || selectedRoot.id,
    bands,
  }
}

/** 某个环带里光标落在哪个扇区（沙盒点击/悬停用）。 */
export function arcAtPoint(
  band: RingBand,
  cx: number,
  cy: number,
  x: number,
  y: number,
): RingArc | null {
  const dx = x - cx
  const dy = y - cy
  const distance = Math.hypot(dx, dy)
  if (distance < band.inner || distance > band.outer) return null
  const angle = Math.atan2(dy, dx)
  const normalize = (value: number): number => {
    const full = Math.PI * 2
    return ((value % full) + full) % full
  }
  return band.arcs.find(arc => {
    const span = normalize(arc.end - arc.start)
    const relative = normalize(angle - arc.start)
    return relative <= span
  }) || null
}
