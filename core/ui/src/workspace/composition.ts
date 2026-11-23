import type { Rect } from './model'

// user:“层级应为红>绿>黄”+(由同一份浮窗顺序决定哪些底层表面要给原生网页让出区域)。
export function workspaceFloatCutouts(
  order: readonly string[],
  live: ReadonlyMap<string, Rect>,
  surfaceId?: string,
): Rect[] {
  return order.slice(surfaceId === undefined ? 0 : order.indexOf(surfaceId) + 1)
    .flatMap(id => {
      const rect = live.get(id)
      return rect ? [rect] : []
    })
}

function without(rect: Rect, covered: Rect): Rect[] {
  const right = rect.x + rect.width
  const bottom = rect.y + rect.height
  const x1 = Math.max(rect.x, covered.x)
  const y1 = Math.max(rect.y, covered.y)
  const x2 = Math.min(right, covered.x + covered.width)
  const y2 = Math.min(bottom, covered.y + covered.height)
  if (x1 >= x2 || y1 >= y2) return [rect]
  return [
    { x: rect.x, y: rect.y, width: rect.width, height: y1 - rect.y },
    { x: rect.x, y: y2, width: rect.width, height: bottom - y2 },
    { x: rect.x, y: y1, width: x1 - rect.x, height: y2 - y1 },
    { x: x2, y: y1, width: right - x2, height: y2 - y1 },
  ].filter(piece => piece.width > 0 && piece.height > 0)
}

// Even-odd clipping requires disjoint holes. Overlaps would otherwise become opaque again.
export function disjointCutouts(rects: readonly Rect[]): Rect[] {
  const result: Rect[] = []
  for (const rect of rects) {
    const uncovered = result.reduce<Rect[]>((pieces, covered) => pieces.flatMap(piece => without(piece, covered)), [rect])
    result.push(...uncovered)
  }
  return result
}

// user:“中间消失了”+(工作区、区域和浮窗共用裁切计算，子组件无需回头加载工作区组件)。
export function buildCutoutClipPath(origin: { x: number; y: number; width?: number; height?: number }, holes: readonly Rect[]): string | undefined {
  if (!holes.length) return undefined
  // user:“网页遇见分屏会出现细线”+(以原生网页的亚像素边界裁切底层，只在被盖住的范围让位)。
  const localHoles = holes.map(hole => {
    const x = Math.max(0, hole.x - origin.x)
    const y = Math.max(0, hole.y - origin.y)
    const right = Math.min(origin.width ?? Infinity, hole.x + hole.width - origin.x)
    const bottom = Math.min(origin.height ?? Infinity, hole.y + hole.height - origin.y)
    return { x, y, width: right - x, height: bottom - y }
  }).filter(hole => hole.width > 0 && hole.height > 0)
  const pts: string[] = ['0 0', '100% 0', '100% 100%', '0 100%', '0 0']
  for (const hole of disjointCutouts(localHoles)) {
    const { x: x1, y: y1 } = hole
    const x2 = x1 + hole.width
    const y2 = y1 + hole.height
    pts.push(`${x1}px ${y1}px`, `${x2}px ${y1}px`, `${x2}px ${y2}px`, `${x1}px ${y2}px`, `${x1}px ${y1}px`, '0 0')
  }
  return pts.length > 5 ? `polygon(evenodd, ${pts.join(', ')})` : undefined
}
