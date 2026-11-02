/**
 * 桌宠引擎的基础数学与随机数。
 *
 * 坐标系约定：全部使用**物理像素屏幕坐标**，原点在虚拟桌面左上角，y 向下。
 * 覆盖层窗口横跨整个虚拟桌面，画布按同一套坐标绘制，因此引擎里的数字和
 * Rust 侧上报的光标/命中矩形可以直接比较，不需要来回换算。
 */

export interface Vec2 {
  x: number
  y: number
}

export function vec(x = 0, y = 0): Vec2 {
  return { x, y }
}

export function clone(value: Vec2): Vec2 {
  return { x: value.x, y: value.y }
}

export function add(a: Vec2, b: Vec2): Vec2 {
  return { x: a.x + b.x, y: a.y + b.y }
}

export function sub(a: Vec2, b: Vec2): Vec2 {
  return { x: a.x - b.x, y: a.y - b.y }
}

export function scale(value: Vec2, factor: number): Vec2 {
  return { x: value.x * factor, y: value.y * factor }
}

export function length(value: Vec2): number {
  return Math.hypot(value.x, value.y)
}

export function distance(a: Vec2, b: Vec2): number {
  return Math.hypot(a.x - b.x, a.y - b.y)
}

export function normalize(value: Vec2): Vec2 {
  const len = length(value)
  return len < 1e-6 ? { x: 0, y: 0 } : { x: value.x / len, y: value.y / len }
}

export function clamp(value: number, min: number, max: number): number {
  return value < min ? min : value > max ? max : value
}

export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

export function sign(value: number): number {
  return value < 0 ? -1 : value > 0 ? 1 : 0
}

/** 确定性随机：同一条边在一次规划里拿到同一个补偿值。 */
export function hash32(text: string): number {
  let hash = 2166136261
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

export function seededRandom(seed: string): number {
  return (hash32(seed) % 100000) / 100000
}

export function makeRandom(seed: number): () => number {
  let state = seed >>> 0 || 1
  return () => {
    state ^= state << 13
    state >>>= 0
    state ^= state >> 17
    state ^= state << 5
    state >>>= 0
    return state / 4294967296
  }
}

export interface Rect {
  x: number
  y: number
  width: number
  height: number
}

export function rectContains(rect: Rect, x: number, y: number): boolean {
  return x >= rect.x && x <= rect.x + rect.width && y >= rect.y && y <= rect.y + rect.height
}

export function rectsOverlap(a: Rect, b: Rect): boolean {
  return a.x <= b.x + b.width && b.x <= a.x + a.width && a.y <= b.y + b.height && b.y <= a.y + a.height
}

/** 点到线段的最近点，用于圆形碰撞体与地形线段的接触判定。 */
export function closestPointOnSegment(px: number, py: number, x1: number, y1: number, x2: number, y2: number): Vec2 {
  const dx = x2 - x1
  const dy = y2 - y1
  const lengthSquared = dx * dx + dy * dy
  if (lengthSquared < 1e-9) return { x: x1, y: y1 }
  const t = clamp(((px - x1) * dx + (py - y1) * dy) / lengthSquared, 0, 1)
  return { x: x1 + dx * t, y: y1 + dy * t }
}
