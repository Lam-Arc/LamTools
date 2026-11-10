/**
 * 手绘风格路径：把直线、方框、椭圆画成带抖动的笔迹。
 *
 * user:“箭头和圈选更像手绘风格和手绘出现”+(同一份标记每次重画要长得一样，
 * 所以抖动由标记 id 派生的种子决定，不用 Math.random；线段切成短段后按
 * 法线方向加减微小偏移，看起来像手画的，又不会歪出标记范围)。
 */

export interface RoughRect {
  x: number
  y: number
  width: number
  height: number
}

/** 32 位字符串散列：同一个标记 id 每次得到同一个种子。 */
export function hashSeed(text: string): number {
  let hash = 2166136261
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

/** 可复现的伪随机序列。 */
export function seededRandom(seed: number): () => number {
  let state = seed >>> 0 || 1
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let value = state
    value = Math.imul(value ^ (value >>> 15), value | 1)
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61)
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296
  }
}

function round(value: number): number {
  return Math.round(value * 100) / 100
}

function pointOnSegment(
  start: [number, number],
  end: [number, number],
  ratio: number,
): [number, number] {
  return [start[0] + (end[0] - start[0]) * ratio, start[1] + (end[1] - start[1]) * ratio]
}

/** 一段抖动折线的控制点；首尾保持原位，中间点沿法线偏移。 */
function jitterSegment(
  start: [number, number],
  end: [number, number],
  random: () => number,
  amplitude: number,
): [number, number][] {
  const dx = end[0] - start[0]
  const dy = end[1] - start[1]
  const length = Math.hypot(dx, dy)
  if (length < 1) return [start, end]
  const normal: [number, number] = [-dy / length, dx / length]
  const steps = Math.max(2, Math.min(9, Math.round(length / 26)))
  const points: [number, number][] = [start]
  for (let index = 1; index < steps; index += 1) {
    const ratio = index / steps
    const base = pointOnSegment(start, end, ratio)
    // 两端偏移收敛到 0，接缝处才不会出现折角。
    const taper = Math.sin(ratio * Math.PI)
    const offset = (random() * 2 - 1) * amplitude * taper
    points.push([base[0] + normal[0] * offset, base[1] + normal[1] * offset])
  }
  points.push(end)
  return points
}

/** 抖动点串 → 用二次曲线穿过中点的平滑路径。 */
function smoothPath(points: [number, number][], close: boolean): string {
  if (points.length === 0) return ''
  if (points.length === 1) return `M ${round(points[0][0])} ${round(points[0][1])}`
  const head = `M ${round(points[0][0])} ${round(points[0][1])}`
  if (points.length === 2) {
    return `${head} L ${round(points[1][0])} ${round(points[1][1])}${close ? ' Z' : ''}`
  }
  const parts: string[] = [head]
  for (let index = 1; index < points.length - 1; index += 1) {
    const current = points[index]
    const next = points[index + 1]
    const midX = (current[0] + next[0]) / 2
    const midY = (current[1] + next[1]) / 2
    parts.push(`Q ${round(current[0])} ${round(current[1])} ${round(midX)} ${round(midY)}`)
  }
  const last = points[points.length - 1]
  parts.push(`L ${round(last[0])} ${round(last[1])}`)
  if (close) parts.push('Z')
  return parts.join(' ')
}

/** 手绘线条：按种子抖动，保留首尾端点。 */
export function roughLinePath(
  points: [number, number][],
  seed: number,
  amplitude = 2.4,
): string {
  if (points.length < 2) return ''
  const random = seededRandom(seed)
  const collected: [number, number][] = [points[0]]
  for (let index = 1; index < points.length; index += 1) {
    const segment = jitterSegment(points[index - 1], points[index], random, amplitude)
    collected.push(...segment.slice(1))
  }
  return smoothPath(collected, false)
}

/**
 * 手绘矩形：四边分别抖动，收笔处稍微出头。
 *
 * user:“箭头和圈选更像手绘风格”+(真拿笔勾一个框，四条边不会正好在角上停住，
 * 总会多划出去一点；出头量控制在抖动幅度以内，不会撑出标记范围)。
 */
export function roughRectPath(rect: RoughRect, seed: number, amplitude = 2.4): string {
  const random = seededRandom(seed)
  const { x, y, width, height } = rect
  const corners: [number, number][] = [
    [x, y],
    [x + width, y],
    [x + width, y + height],
    [x, y + height],
  ]
  const overshoot = Math.min(3.2, amplitude)
  const parts: string[] = []
  for (let index = 0; index < 4; index += 1) {
    const start = corners[index]
    const end = corners[(index + 1) % 4]
    const dx = end[0] - start[0]
    const dy = end[1] - start[1]
    const length = Math.hypot(dx, dy)
    if (length < 0.5) continue
    const ux = dx / length
    const uy = dy / length
    const head: [number, number] = [start[0] - ux * overshoot, start[1] - uy * overshoot]
    const tail: [number, number] = [end[0] + ux * overshoot, end[1] + uy * overshoot]
    parts.push(smoothPath(jitterSegment(head, tail, random, amplitude), false))
  }
  return parts.join(' ')
}

/**
 * 手绘椭圆：沿圆周取点后做径向抖动，闭合。
 *
 * user:“箭头和圈选更像手绘风格”+(抖动按像素算，大圈也能看出手写的起伏；
 * 早先按半径比例算，圈一大就抖成一条完美的椭圆)。
 */
export function roughEllipsePath(rect: RoughRect, seed: number, amplitude = 3): string {
  const random = seededRandom(seed)
  const cx = rect.x + rect.width / 2
  const cy = rect.y + rect.height / 2
  const rx = Math.max(1, rect.width / 2)
  const ry = Math.max(1, rect.height / 2)
  const steps = 44
  const points: [number, number][] = []
  for (let index = 0; index < steps; index += 1) {
    const angle = (index / steps) * Math.PI * 2
    const wobble = (random() * 2 - 1) * amplitude
    const radiusX = Math.max(1, rx + wobble)
    const radiusY = Math.max(1, ry + wobble)
    points.push([cx + Math.cos(angle) * radiusX, cy + Math.sin(angle) * radiusY])
  }
  points.push(points[0])
  return smoothPath(points, true)
}

/** 手绘箭头：杆和头都抖动，头的两条边从顶点回勾。 */
export function roughArrow(
  points: [number, number][],
  seed: number,
  headSize: number,
  amplitude = 2.2,
): { shaft: string; head: string } {
  // 空点集不能让后面按 last[0] 取坐标时崩掉。
  if (!points.length) return { shaft: '', head: '' }
  const first = points[0]
  const last = points[points.length - 1] ?? first
  const random = seededRandom(seed)
  const dx = last[0] - first[0]
  const dy = last[1] - first[1]
  const length = Math.hypot(dx, dy)
  const shaft = roughLinePath(points, seed, amplitude)
  if (length < 0.5) return { shaft, head: '' }
  const angle = Math.atan2(dy, dx)
  // 箭羽张开一点才像手画的箭头，窄了看着像个小钩子。
  const spread = headSize * 0.66
  const baseX = last[0] - Math.cos(angle) * headSize
  const baseY = last[1] - Math.sin(angle) * headSize
  const left: [number, number] = [
    baseX + Math.cos(angle + Math.PI / 2) * spread,
    baseY + Math.sin(angle + Math.PI / 2) * spread,
  ]
  const right: [number, number] = [
    baseX + Math.cos(angle - Math.PI / 2) * spread,
    baseY + Math.sin(angle - Math.PI / 2) * spread,
  ]
  const head = [
    smoothPath(jitterSegment(left, last, random, amplitude * 0.8), false),
    smoothPath(jitterSegment(last, right, random, amplitude * 0.8), false),
  ].join(' ')
  return { shaft, head }
}
