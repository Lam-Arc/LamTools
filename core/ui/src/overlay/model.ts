/**
 * 交互层的纯几何与状态判定。
 *
 * user:“标记可跟随窗口和对象，用户能直接点击、圈选、批注，与 Agent 实时互动。”
 * +(标记按创建时的窗口原矩形存屏幕坐标；窗口移动或缩放后，渲染前按差值换算。
 * 这部分必须能脱离窗口和 DOM 单测，覆盖层组件只负责把结果画出来。)
 */

export type MarkKind = 'arrow' | 'rect' | 'ellipse' | 'pen' | 'text' | 'svg' | 'danmaku' | 'sticker'

export interface OverlayWindowTarget {
  id: number
  title: string
  /** 创建标记时的窗口矩形，[x, y, width, height]，物理像素。 */
  bounds: [number, number, number, number]
}

export interface MarkMotion {
  type: 'fade' | 'pop' | 'float' | 'drift' | 'danmaku'
  duration: number
  fade: number
  easing: 'linear' | 'ease-out' | 'ease-in-out'
  from: 'right' | 'left' | 'center' | 'top' | 'bottom'
}

export interface MarkDraw {
  mode: 'stroke' | 'reveal' | 'none'
  duration: number
}

export interface MarkImage {
  asset: string
  width?: number
  height?: number
}

/** 受控 SVG 图形，坐标在 viewBox 里，到达时间决定它什么时候开始画。 */
export interface SvgShape {
  type: string
  added_at?: number
  [key: string]: unknown
}

export interface OverlayMark {
  id: string
  kind: MarkKind
  points: [number, number][]
  color: string
  width: number
  text: string
  ttl: number
  motion?: MarkMotion
  draw?: MarkDraw
  image?: MarkImage
  viewBox?: [number, number, number, number]
  shapes?: SvgShape[]
  window: OverlayWindowTarget | null
  window_missing: boolean
  label: string
  created_at: number
  expires_at: number
  source: string
}

/** 桌面窗口的当前几何，来自 pet_desktop_windows。 */
export interface ScreenWindow {
  id: string
  title: string
  bounds: { x: number; y: number; width: number; height: number }
  z: number
}

export interface Rect {
  x: number
  y: number
  width: number
  height: number
}

export interface ArrowGeometry {
  x1: number
  y1: number
  x2: number
  y2: number
  angle: number
  length: number
  /** 三角箭头的 SVG path；零长度时为空串。 */
  head: string
}

export function isExpired(mark: OverlayMark, now: number): boolean {
  return now >= mark.expires_at
}

export function visibleMarks(marks: OverlayMark[], now: number): OverlayMark[] {
  return marks.filter(mark => !isExpired(mark, now))
}

function findWindow(mark: OverlayMark, windows: ScreenWindow[]): ScreenWindow | null {
  const target = mark.window
  if (!target) return null
  const wanted = String(target.id)
  return windows.find(item => String(item.id) === wanted) ?? null
}

function scaleAxis(current: number, original: number): number {
  if (!Number.isFinite(original) || original === 0) return 1
  if (!Number.isFinite(current) || current <= 0) return 1
  return current / original
}

/**
 * 把标记的点换算到窗口的当前位置。
 * 窗口找不到、矩形非法时退回创建时的坐标，标记不会凭空消失。
 */
export function resolveMarkPoints(mark: OverlayMark, windows: ScreenWindow[]): [number, number][] {
  const target = mark.window
  if (!target) return mark.points.map(point => [point[0], point[1]] as [number, number])
  const current = findWindow(mark, windows)
  if (!current) return mark.points.map(point => [point[0], point[1]] as [number, number])
  const [originX, originY, originalWidth, originalHeight] = target.bounds
  const scaleX = scaleAxis(current.bounds.width, originalWidth)
  const scaleY = scaleAxis(current.bounds.height, originalHeight)
  return mark.points.map(point => [
    current.bounds.x + (point[0] - originX) * scaleX,
    current.bounds.y + (point[1] - originY) * scaleY,
  ] as [number, number])
}

export function resolveMark(mark: OverlayMark, windows: ScreenWindow[]): OverlayMark {
  return { ...mark, points: resolveMarkPoints(mark, windows) }
}

export function rectFromPoints(points: [number, number][]): Rect {
  const xs = points.map(point => point[0])
  const ys = points.map(point => point[1])
  const minX = Math.min(...xs)
  const minY = Math.min(...ys)
  return {
    x: minX,
    y: minY,
    width: Math.max(...xs) - minX,
    height: Math.max(...ys) - minY,
  }
}

export function ellipseFromPoints(points: [number, number][]): {
  cx: number
  cy: number
  rx: number
  ry: number
} {
  const rect = rectFromPoints(points)
  return {
    cx: rect.x + rect.width / 2,
    cy: rect.y + rect.height / 2,
    rx: rect.width / 2,
    ry: rect.height / 2,
  }
}

export function penPath(points: [number, number][]): string {
  if (points.length === 0) return ''
  const [first, ...rest] = points
  return [`M ${first[0]} ${first[1]}`, ...rest.map(point => `L ${point[0]} ${point[1]}`)].join(' ')
}

export function arrowGeometry(points: [number, number][], width: number): ArrowGeometry {
  const first = points[0] ?? [0, 0]
  const last = points[points.length - 1] ?? first
  const dx = last[0] - first[0]
  const dy = last[1] - first[1]
  const length = Math.hypot(dx, dy)
  const angle = Math.atan2(dy, dx)
  const headSize = Math.max(10, Math.min(28, width * 4.5))
  const head = length < 0.5
    ? ''
    : (() => {
        const baseX = last[0] - Math.cos(angle) * headSize
        const baseY = last[1] - Math.sin(angle) * headSize
        const spread = headSize * 0.55
        const leftX = baseX + Math.cos(angle + Math.PI / 2) * spread
        const leftY = baseY + Math.sin(angle + Math.PI / 2) * spread
        const rightX = baseX + Math.cos(angle - Math.PI / 2) * spread
        const rightY = baseY + Math.sin(angle - Math.PI / 2) * spread
        return `M ${last[0]} ${last[1]} L ${leftX} ${leftY} L ${rightX} ${rightY} Z`
      })()
  return { x1: first[0], y1: first[1], x2: last[0], y2: last[1], angle, length, head }
}

function distanceToSegment(
  point: [number, number],
  start: [number, number],
  end: [number, number],
): number {
  const dx = end[0] - start[0]
  const dy = end[1] - start[1]
  if (dx === 0 && dy === 0) return Math.hypot(point[0] - start[0], point[1] - start[1])
  const t = Math.max(
    0,
    Math.min(1, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (dx * dx + dy * dy)),
  )
  return Math.hypot(point[0] - (start[0] + t * dx), point[1] - (start[1] + t * dy))
}

function pointInRect(point: [number, number], rect: Rect, padding: number): boolean {
  return (
    point[0] >= rect.x - padding
    && point[0] <= rect.x + rect.width + padding
    && point[1] >= rect.y - padding
    && point[1] <= rect.y + rect.height + padding
  )
}

/**
 * 找光标下最上面的标记。数组顺序就是绘制顺序，后面的盖在前面上，
 * 所以从后往前找。容差按标记线宽放宽，方便点到细箭头。
 */
export function hitTestMarks(
  marks: OverlayMark[],
  point: [number, number],
  tolerance = 6,
): OverlayMark | null {
  for (let index = marks.length - 1; index >= 0; index -= 1) {
    const mark = marks[index]
    const padding = tolerance + Math.max(0, mark.width) / 2
    if (mark.kind === 'text') {
      const anchor = mark.points[0]
      if (anchor && Math.hypot(point[0] - anchor[0], point[1] - anchor[1]) <= Math.max(24, padding * 3)) {
        return mark
      }
      continue
    }
    if (mark.kind === 'rect' || mark.kind === 'ellipse' || mark.kind === 'svg') {
      if (pointInRect(point, rectFromPoints(mark.points), padding)) return mark
      continue
    }
    if (mark.kind === 'danmaku') {
      // 弹幕在轨道上快速扫过，点中整条轨道就算命中，方便用户追问。
      const anchor = mark.points[0]
      if (anchor && Math.abs(point[1] - anchor[1]) <= 40) return mark
      continue
    }
    if (mark.kind === 'sticker') {
      const anchor = mark.points[0]
      if (anchor && Math.hypot(point[0] - anchor[0], point[1] - anchor[1]) <= 90) return mark
      continue
    }
    for (let i = 1; i < mark.points.length; i += 1) {
      if (distanceToSegment(point, mark.points[i - 1], mark.points[i]) <= padding) return mark
    }
  }
  return null
}

/** 屏幕绝对坐标换算成覆盖层页面里的 CSS 像素。 */
export function toPagePoint(
  point: [number, number],
  overlay: { x: number; y: number; width: number; height: number },
  viewport: { width: number; height: number },
): [number, number] {
  // user:“对代码进行审查，不要出错或者低级漏洞或问题”+(几何没取到时 overlay.width
  // 是 0，比例变成 0 就会算出 Infinity/NaN，整层静默画不出来；这里退成 1)。
  const ratioX = overlay.width > 0 && viewport.width > 0 ? overlay.width / viewport.width : 1
  const ratioY = overlay.height > 0 && viewport.height > 0 ? overlay.height / viewport.height : 1
  return [(point[0] - overlay.x) / ratioX, (point[1] - overlay.y) / ratioY]
}

/** 页面里的拖拽像素换算回屏幕物理坐标，用于用户圈选。 */
export function toScreenRect(
  start: [number, number],
  end: [number, number],
  overlay: { x: number; y: number; width: number; height: number },
  viewport: { width: number; height: number },
): [number, number, number, number] {
  const ratioX = viewport.width > 0 ? overlay.width / viewport.width : 1
  const ratioY = viewport.height > 0 ? overlay.height / viewport.height : 1
  const x1 = overlay.x + start[0] * ratioX
  const y1 = overlay.y + start[1] * ratioY
  const x2 = overlay.x + end[0] * ratioX
  const y2 = overlay.y + end[1] * ratioY
  const rect = rectFromPoints([[x1, y1], [x2, y2]])
  return [Math.round(rect.x), Math.round(rect.y), Math.round(rect.width), Math.round(rect.height)]
}
