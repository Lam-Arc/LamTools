/**
 * 三级地形。
 *
 * - L1：屏幕边界，最稳的基础约束。
 * - L2：OS 窗口边框、Sunday 自己的 UI 几何、用户手绘线；可靠事件更新，
 *   宠物稳定站在上面时可以跟随窗口移动。
 * - L3：截图里的视觉边缘；一次识别、可刷新可删除，**不跟随位置移动**。
 *
 * 几何只有三种：水平平台、斜坡、垂直边。倒挂不是新的地形类型，是同一块
 * 水平平台的"下方接触"，由物理的接触方向判断。
 */
import { clamp, closestPointOnSegment, type Rect } from './math.ts'

export type SegmentKind = 'platform' | 'ramp' | 'vertical'
export type TerrainLayer = 'L1' | 'L2' | 'L3' | 'user'

export interface TerrainSegment {
  id: string
  kind: SegmentKind
  layer: TerrainLayer
  x1: number
  y1: number
  x2: number
  y2: number
  /** L2 段的来源窗口标识，用于"稳定附着时跟随窗口移动"。 */
  sourceId?: string
  /** 该段所属窗口在上一帧的位置，用于跟随位移。 */
  sourceBounds?: Rect
  /** 单向平台（泰拉瑞亚式）：可站、从下往上可穿过、提交下落意图可穿下。 */
  oneWay?: boolean
  /**
   * 绳梯（泰拉瑞亚绳子 / MC 梯子语义）：
   * user:"竖边就像泰拉瑞亚里的绳子一样，或者说是MC里的梯子一样，它不是必须爬，但是它可以爬"+
   * (无碰撞：走过时不挡路、不吸附；有攀爬意图且身体与绳梯重叠时才抓附上下。
   *  窗口竖边属于这一类——它们不是墙。)
   */
  ladder?: boolean
}

export type TerrainQuality = 'low' | 'balanced' | 'high'

export interface FitOptions {
  quality: TerrainQuality
  /** 只保留长度超过该值的线段。 */
  minLength: number
  /** 拟合容差：同一条边上的点允许的最大纵向偏差。 */
  tolerance: number
  /** 梯度阈值，越低越敏感。 */
  threshold: number
  /** 采样步长（像素），决定识别分辨率。 */
  stride: number
  /** 参与扫描的边缘方向（度）：0 水平、90 垂直、其余为斜边。 */
  angles: number[]
}

export const QUALITY_PRESETS: Record<TerrainQuality, FitOptions> = {
  // 数量自适应：不写死"必须 8/12/16 段"，由误差与最短边界决定。
  // 精度越高，扫描的方向越多：低档只找水平/垂直，高档连斜边一起找。
  low: { quality: 'low', minLength: 96, tolerance: 6, threshold: 34, stride: 8, angles: [0, 90] },
  balanced: { quality: 'balanced', minLength: 64, tolerance: 3, threshold: 24, stride: 4, angles: [0, 90, 45, -45] },
  high: { quality: 'high', minLength: 40, tolerance: 2, threshold: 16, stride: 2, angles: [0, 90, 45, -45, 26.565, -26.565] },
}

export function classifySegment(x1: number, y1: number, x2: number, y2: number): SegmentKind {
  const dx = Math.abs(x2 - x1)
  const dy = Math.abs(y2 - y1)
  if (dx < 1e-6) return 'vertical'
  // 水平平台要求"几乎水平"：桌面上的窗口上边缘、任务栏都属于这一类。
  if (dy / dx <= 0.12) return 'platform'
  if (dy / dx >= 4) return 'vertical'
  return 'ramp'
}

export class TerrainField {
  private segments = new Map<string, TerrainSegment>()
  private bounds: Rect = { x: 0, y: 0, width: 1920, height: 1080 }

  setScreenBounds(bounds: Rect): void {
    this.bounds = { ...bounds }
    this.clearLayer('L1')
    const { x, y, width, height } = bounds
    // 屏幕边界：上下各一条水平平台，左右各一条垂直边。
    // user:"L1顶部那一条是可以悬挂的"+
    // (顶边是单向板：下沿可悬挂；上升时可穿过，不会把角色顶死在屏幕外。)
    this.add({ id: 'L1:top', kind: 'platform', layer: 'L1', x1: x, y1: y, x2: x + width, y2: y, oneWay: true })
    this.add({ id: 'L1:bottom', kind: 'platform', layer: 'L1', x1: x, y1: y + height, x2: x + width, y2: y + height })
    // user:"L1墙可沿边缘攀爬，就像梯子"+
    // (屏幕左右边缘当绳梯：无碰撞、可沿边缘上下爬，和窗口竖边同一套语义。)
    this.add({ id: 'L1:left', kind: 'vertical', layer: 'L1', x1: x, y1: y, x2: x, y2: y + height, ladder: true })
    this.add({ id: 'L1:right', kind: 'vertical', layer: 'L1', x1: x + width, y1: y, x2: x + width, y2: y + height, ladder: true })
  }

  get screenBounds(): Rect {
    return this.bounds
  }

  add(segment: TerrainSegment): void {
    this.segments.set(segment.id, segment)
  }

  get(id: string): TerrainSegment | undefined {
    return this.segments.get(id)
  }

  all(): TerrainSegment[] {
    return [...this.segments.values()]
  }

  layer(layer: TerrainLayer): TerrainSegment[] {
    return this.all().filter(segment => segment.layer === layer)
  }

  removeLayer(layer: TerrainLayer): void {
    for (const [id, segment] of this.segments) {
      if (segment.layer === layer) this.segments.delete(id)
    }
  }

  /** 只清局部：窗口几何变化时不必重建整张图。 */
  removeBySource(sourceId: string): void {
    for (const [id, segment] of this.segments) {
      if (segment.sourceId === sourceId) this.segments.delete(id)
    }
  }

  clearLayer(layer: TerrainLayer): void {
    this.removeLayer(layer)
  }

  /** 查询与矩形相交的地形段，物理每步只碰这些。 */
  query(rect: Rect, padding = 0): TerrainSegment[] {
    const left = rect.x - padding
    const right = rect.x + rect.width + padding
    const top = rect.y - padding
    const bottom = rect.y + rect.height + padding
    const result: TerrainSegment[] = []
    for (const segment of this.segments.values()) {
      const minX = Math.min(segment.x1, segment.x2)
      const maxX = Math.max(segment.x1, segment.x2)
      const minY = Math.min(segment.y1, segment.y2)
      const maxY = Math.max(segment.y1, segment.y2)
      if (maxX < left || minX > right || maxY < top || minY > bottom) continue
      result.push(segment)
    }
    return result
  }

  /**
   * 窗口几何 → L2 地形。
   *
   * user:"L2 应该是类似泰拉瑞亚的平台，可下落，竖着的也可穿透 它不是真的墙"+
   * user:"为什么窗口下沿不作为平台？我的设计文档里应该写得很明确吧"+
   * (窗口的上边缘和下边缘都是单向板平台：能站、从下往上可穿过、可下落穿过、
   *  檐下可挂；之前只建上边缘是实现漏项，不是设计。)
   * user:"L2 只见看得见的那些 不要建被遮在后面的"+
   * (按 z 序做可见性裁剪：平台线被更靠前窗口盖住的区间不算地形，露出多少
   *  建多少；上下边缘都看不见的窗口不出任何地形。)
   */
  setWindows(windows: DesktopWindow[]): void {
    this.removeLayer('L2')
    // z 升序 = EnumWindows 自顶向下：排在前面的窗口离用户更近、会遮住后面的。
    const ordered = [...windows].sort((a, b) => a.z - b.z)
    const visiblePieces = (window: DesktopWindow, index: number, lineY: number): Array<{ left: number; right: number }> => {
      let intervals: Array<{ left: number; right: number }> = [{ left: window.bounds.x, right: window.bounds.x + window.bounds.width }]
      for (const above of ordered.slice(0, index)) {
        const a = above.bounds
        // 不压住这条水平线的窗口不参与遮挡。
        if (a.y > lineY || a.y + a.height <= lineY) continue
        intervals = subtractIntervals(intervals, a.x, a.x + a.width)
      }
      return intervals.filter(interval => interval.right - interval.left >= 160)
    }
    for (let index = 0; index < ordered.length; index += 1) {
      const window = ordered[index]
      const { x, y, width, height } = window.bounds
      if (width < 160 || height < 90) continue
      const addPlatforms = (lineY: number, edge: 'top' | 'bottom'): number => {
        let piece = 0
        for (const interval of visiblePieces(window, index, lineY)) {
          this.add({
            id: `L2:${window.id}:${edge}:${piece++}`,
            kind: 'platform',
            layer: 'L2',
            x1: interval.left,
            y1: lineY,
            x2: interval.right,
            y2: lineY,
            oneWay: true,
            sourceId: window.id,
            sourceBounds: { ...window.bounds },
          })
        }
        return piece
      }
      const topPiece = addPlatforms(y, 'top')
      const bottomPiece = addPlatforms(y + height, 'bottom')
      // 上下边缘都完全被遮（露不出任何一段）的窗口：整窗不出地形——绳梯也看不见。
      // user:"L2 只见看得见的那些 不要建被遮在后面的"
      if (topPiece === 0 && bottomPiece === 0) continue
      // 窗口竖边 = 绳梯：无碰撞、可穿过，攀爬意图时抓附上下（不是墙）。
      // user:"平台可上也可下，也可站也可挂"+（竖边给了桌宠登上窗口顶的路。)
      this.add({
        id: `L2:${window.id}:left`,
        kind: 'vertical',
        layer: 'L2',
        x1: x,
        y1: y,
        x2: x,
        y2: y + height,
        ladder: true,
        sourceId: window.id,
        sourceBounds: { ...window.bounds },
      })
      this.add({
        id: `L2:${window.id}:right`,
        kind: 'vertical',
        layer: 'L2',
        x1: x + width,
        y1: y,
        x2: x + width,
        y2: y + height,
        ladder: true,
        sourceId: window.id,
        sourceBounds: { ...window.bounds },
      })
    }
  }

  /**
   * 窗口移动：只平移该窗口的段。用户拖动窗口时宠物仍站在上面，
   * 除非位移超过容差（那时物理自然脱离，见 physics 的支撑失效判断）。
   */
  moveWindowSource(sourceId: string, bounds: Rect): void {
    for (const segment of this.segments.values()) {
      if (segment.sourceId !== sourceId || !segment.sourceBounds) continue
      const dx = bounds.x - segment.sourceBounds.x
      const dy = bounds.y - segment.sourceBounds.y
      segment.x1 += dx
      segment.y1 += dy
      segment.x2 += dx
      segment.y2 += dy
      segment.sourceBounds = { ...bounds }
    }
  }

  boundsOf(segment: TerrainSegment): Rect {
    return {
      x: Math.min(segment.x1, segment.x2),
      y: Math.min(segment.y1, segment.y2),
      width: Math.abs(segment.x2 - segment.x1),
      height: Math.abs(segment.y2 - segment.y1),
    }
  }

  stats(): { total: number; byLayer: Record<string, number> } {
    const byLayer: Record<string, number> = {}
    for (const segment of this.segments.values()) {
      byLayer[segment.layer] = (byLayer[segment.layer] || 0) + 1
    }
    return { total: this.segments.size, byLayer }
  }
}

export interface DesktopWindow {
  id: string
  title: string
  className: string
  bounds: Rect
  z: number
}

/** 从一组水平区间里挖掉 [cutLeft, cutRight]，返回剩余区间（L2 可见性裁剪用）。 */
function subtractIntervals(
  list: Array<{ left: number; right: number }>,
  cutLeft: number,
  cutRight: number,
): Array<{ left: number; right: number }> {
  const result: Array<{ left: number; right: number }> = []
  for (const interval of list) {
    if (cutRight <= interval.left || cutLeft >= interval.right) {
      result.push(interval)
      continue
    }
    if (cutLeft > interval.left) result.push({ left: interval.left, right: Math.min(interval.right, cutLeft) })
    if (cutRight < interval.right) result.push({ left: Math.max(interval.left, cutRight), right: interval.right })
  }
  return result
}

/**
 * L3 识别：沿若干候选方向做 1D 扫描，找连续的强亮度阶跃。
 *
 * user:“完善 L3 地形识别，不应长期只有水平边缘”+
 * (桌面上的可靠几何不只有窗口横边：侧边栏竖线、斜着摆的卡片、圆形图表的切线
 *  都是可站立或可攀爬的接触面。这里按方向逐条扫描，再用同一套三类几何归类。)
 *
 * 为什么不用 OCR / 模板：任何软件界面都无法预设模板，唯一稳定的通用信号是
 * "沿某个方向连续存在的亮度阶跃"。方向扫描比全局 Hough 便宜，也更容易被
 * 精度档位控制（低档只看水平/垂直）。
 */
export function fitEdges(
  image: { width: number; height: number; data: Uint8ClampedArray },
  offsetX: number,
  offsetY: number,
  options: FitOptions,
): TerrainSegment[] {
  const { width, height, data } = image
  const stride = Math.max(1, Math.round(options.stride))
  // 采样网格：所有方向共用，避免每条扫描线重复读像素。
  const columns = Math.max(2, Math.floor(width / stride))
  const rows = Math.max(2, Math.floor(height / stride))
  const luminance = new Float32Array(columns * rows)
  for (let row = 0; row < rows; row += 1) {
    const py = Math.min(height - 1, row * stride)
    for (let column = 0; column < columns; column += 1) {
      const px = Math.min(width - 1, column * stride)
      const index = (py * width + px) * 4
      luminance[row * columns + column] = 0.299 * data[index] + 0.587 * data[index + 1] + 0.114 * data[index + 2]
    }
  }
  const sample = (x: number, y: number): number => {
    const column = Math.min(columns - 1, Math.max(0, Math.round(x / stride)))
    const row = Math.min(rows - 1, Math.max(0, Math.round(y / stride)))
    return luminance[row * columns + column]
  }
  // 扫描预算：方向多、图大时不能无限跑，超了就直接停（低精度优先）。
  const budget = 6_000_000
  let consumed = 0
  const collected: TerrainSegment[] = []
  let counter = 0
  for (const angleDeg of options.angles) {
    const angle = (angleDeg * Math.PI) / 180
    const dir = { x: Math.cos(angle), y: Math.sin(angle) }
    const normal = { x: -Math.sin(angle), y: Math.cos(angle) }
    // 投影范围：四个角在法线/方向轴上的极值。
    const corners = [
      { x: 0, y: 0 },
      { x: width, y: 0 },
      { x: 0, y: height },
      { x: width, y: height },
    ]
    let minS = Infinity
    let maxS = -Infinity
    let minT = Infinity
    let maxT = -Infinity
    for (const corner of corners) {
      const s = corner.x * normal.x + corner.y * normal.y
      const t = corner.x * dir.x + corner.y * dir.y
      minS = Math.min(minS, s)
      maxS = Math.max(maxS, s)
      minT = Math.min(minT, t)
      maxT = Math.max(maxT, t)
    }
    const lineCount = Math.floor((maxS - minS) / stride)
    const samplesPerLine = Math.floor((maxT - minT) / stride)
    if (lineCount <= 0 || samplesPerLine <= 0) continue
    if (consumed + lineCount * samplesPerLine > budget) break
    consumed += lineCount * samplesPerLine
    for (let lineIndex = 0; lineIndex < lineCount; lineIndex += 1) {
      const s = minS + lineIndex * stride
      let runStart = -1
      let runSign = 0
      const flush = (endIndex: number) => {
        if (runStart < 0) return
        const length = (endIndex - runStart) * stride
        if (length >= options.minLength) {
          const t0 = minT + runStart * stride
          const t1 = minT + endIndex * stride
          const x1 = normal.x * s + dir.x * t0
          const y1 = normal.y * s + dir.y * t0
          const x2 = normal.x * s + dir.x * t1
          const y2 = normal.y * s + dir.y * t1
          collected.push({
            id: `L3:${counter++}`,
            kind: classifySegment(x1, y1, x2, y2),
            layer: 'L3',
            x1: offsetX + x1,
            y1: offsetY + y1,
            x2: offsetX + x2,
            y2: offsetY + y2,
          })
        }
        runStart = -1
        runSign = 0
      }
      for (let sampleIndex = 0; sampleIndex <= samplesPerLine; sampleIndex += 1) {
        const t = minT + sampleIndex * stride
        const px = normal.x * s + dir.x * t
        const py = normal.y * s + dir.y * t
        if (px < 0 || py < 0 || px >= width || py >= height) {
          flush(sampleIndex)
          continue
        }
        const before = sample(px - normal.x * stride, py - normal.y * stride)
        const after = sample(px + normal.x * stride, py + normal.y * stride)
        const delta = after - before
        const strong = Math.abs(delta) >= options.threshold
        const sameSign = runSign === 0 || Math.sign(delta) === runSign
        if (strong && sameSign) {
          if (runStart < 0) {
            runStart = sampleIndex
            runSign = Math.sign(delta)
          }
        } else if (runStart >= 0) {
          flush(sampleIndex)
        }
      }
      flush(samplesPerLine)
    }
  }
  return dedupeSegments(collected, options.tolerance, stride)
}

/** 同一个边缘会被多个方向扫到：按"位置+角度+长度"去重，只留最干净的一条。 */
export function dedupeSegments(segments: TerrainSegment[], tolerance: number, stride: number): TerrainSegment[] {
  const result: TerrainSegment[] = []
  for (const segment of segments) {
    const angle = Math.atan2(segment.y2 - segment.y1, segment.x2 - segment.x1)
    const midX = (segment.x1 + segment.x2) / 2
    const midY = (segment.y1 + segment.y2) / 2
    const length = Math.hypot(segment.x2 - segment.x1, segment.y2 - segment.y1)
    const duplicate = result.some(existing => {
      const existingAngle = Math.atan2(existing.y2 - existing.y1, existing.x2 - existing.x1)
      const existingMidX = (existing.x1 + existing.x2) / 2
      const existingMidY = (existing.y1 + existing.y2) / 2
      const existingLength = Math.hypot(existing.x2 - existing.x1, existing.y2 - existing.y1)
      const angleClose = Math.abs(normalizeAngle(angle - existingAngle)) < 0.12
      const positionClose = Math.hypot(midX - existingMidX, midY - existingMidY) < Math.max(stride * 2, tolerance * 2)
      const lengthClose = Math.abs(length - existingLength) < Math.max(stride * 2, tolerance * 2)
      return angleClose && positionClose && lengthClose
    })
    if (!duplicate) result.push(segment)
  }
  return result
}

function normalizeAngle(angle: number): number {
  let value = angle
  while (value > Math.PI) value -= Math.PI * 2
  while (value < -Math.PI) value += Math.PI * 2
  return value
}

/**
 * 兼容入口：只扫水平边的旧行为。
 */
export function fitHorizonEdges(
  image: { width: number; height: number; data: Uint8ClampedArray },
  offsetX: number,
  offsetY: number,
  options: FitOptions,
): TerrainSegment[] {
  // 旧入口 = 只扫水平方向；真正的识别统一走 fitEdges。
  return mergeCollinear(
    fitEdges(image, offsetX, offsetY, { ...options, angles: [0] }),
    options.tolerance,
  )
}

/** 共线合并：同一高度、间隔很小的碎片并成一条，避免文字边缘碎成上百段。 */
export function mergeCollinear(segments: TerrainSegment[], tolerance: number): TerrainSegment[] {
  const sorted = [...segments].sort((a, b) => a.y1 - b.y1 || a.x1 - b.x1)
  const merged: TerrainSegment[] = []
  for (const segment of sorted) {
    const last = merged[merged.length - 1]
    if (last
      && Math.abs(last.y1 - segment.y1) <= tolerance
      && segment.x1 <= last.x2 + tolerance * 2
      && segment.x1 >= last.x1 - tolerance * 2) {
      last.x2 = Math.max(last.x2, segment.x2)
      continue
    }
    merged.push({ ...segment })
  }
  return merged
}

/**
 * 斜坡/曲线的线段拟合：把一串采样点按 Douglas–Peucker 化简成直线段。
 * 半圆用这个函数拟合后，仍然可以站立、爬行、悬挂。
 */
export function fitPolyline(points: { x: number; y: number }[], tolerance: number): TerrainSegment[] {
  if (points.length < 2) return []
  const simplified = douglasPeucker(points, tolerance)
  const segments: TerrainSegment[] = []
  for (let index = 0; index + 1 < simplified.length; index += 1) {
    const a = simplified[index]
    const b = simplified[index + 1]
    segments.push({
      id: `fit:${index}`,
      kind: classifySegment(a.x, a.y, b.x, b.y),
      layer: 'user',
      x1: a.x,
      y1: a.y,
      x2: b.x,
      y2: b.y,
    })
  }
  return segments
}

function douglasPeucker(points: { x: number; y: number }[], tolerance: number): { x: number; y: number }[] {
  if (points.length < 3) return points.slice()
  let maxDistance = 0
  let index = 0
  const first = points[0]
  const last = points[points.length - 1]
  for (let cursor = 1; cursor < points.length - 1; cursor += 1) {
    const point = points[cursor]
    const closest = closestPointOnSegment(point.x, point.y, first.x, first.y, last.x, last.y)
    const delta = Math.hypot(point.x - closest.x, point.y - closest.y)
    if (delta > maxDistance) {
      maxDistance = delta
      index = cursor
    }
  }
  if (maxDistance <= tolerance) return [first, last]
  const head = douglasPeucker(points.slice(0, index + 1), tolerance)
  const tail = douglasPeucker(points.slice(index), tolerance)
  return [...head.slice(0, -1), ...tail]
}

/** 内置回形半圆测试图：外侧回字框、内侧左竖边接地、内侧右边半圆、外框顶部小断口。 */
export function buildTestArena(width: number, height: number, petSize: number): TerrainSegment[] {
  const margin = Math.max(24, Math.round(petSize * 0.6))
  const left = margin
  const top = margin
  const right = width - margin
  const bottom = height - margin
  const innerLeft = left + Math.max(140, petSize * 3)
  const innerRight = right - Math.max(140, petSize * 3)
  const innerTop = top + Math.max(120, petSize * 2.4)
  const segments: TerrainSegment[] = []
  let counter = 0
  const push = (kind: SegmentKind, x1: number, y1: number, x2: number, y2: number) => {
    segments.push({ id: `arena:${counter++}`, kind, layer: 'user', x1, y1, x2, y2 })
  }
  // 外框底边贯通，作为地面。
  push('platform', left, bottom, right, bottom)
  push('vertical', left, top, left, bottom)
  push('vertical', right, top, right, bottom)
  // 外框顶部留一个"小断口"：跳到对面需要越过缺口。
  const gap = Math.max(24, petSize * 0.9)
  const gapCenter = (left + right) / 2
  push('platform', left, top, gapCenter - gap / 2, top)
  push('platform', gapCenter + gap / 2, top, right, top)
  // 内侧左竖边直接接地。
  push('vertical', innerLeft, innerTop, innerLeft, bottom)
  // 内侧右边：标准半圆（右半圆，弦在竖直方向上），用线段拟合。
  const radius = (bottom - innerTop) / 2
  const centerY = (bottom + innerTop) / 2
  const samples: { x: number; y: number }[] = []
  const steps = 24
  for (let index = 0; index <= steps; index += 1) {
    const angle = -Math.PI / 2 + (Math.PI * index) / steps
    samples.push({
      x: innerRight + Math.sin(angle) * radius * 0.5,
      y: centerY - Math.cos(angle) * radius,
    })
  }
  for (const segment of fitPolyline(samples, Math.max(2, petSize * 0.04))) {
    push(segment.kind, segment.x1, segment.y1, segment.x2, segment.y2)
  }
  // 内侧右半圆与地面之间的短平台，保证能走过去绕路。
  push('platform', innerLeft, innerTop, innerLeft + Math.max(80, petSize * 1.4), innerTop)
  return segments
}

export function drawingBounds(segments: TerrainSegment[]): Rect {
  const xs: number[] = []
  const ys: number[] = []
  for (const segment of segments) {
    xs.push(segment.x1, segment.x2)
    ys.push(segment.y1, segment.y2)
  }
  if (xs.length === 0) return { x: 0, y: 0, width: 0, height: 0 }
  const minX = Math.min(...xs)
  const minY = Math.min(...ys)
  return {
    x: minX,
    y: minY,
    width: clamp(Math.max(...xs) - minX, 1, 1e6),
    height: clamp(Math.max(...ys) - minY, 1, 1e6),
  }
}
