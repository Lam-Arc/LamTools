/**
 * 拖拽与吸附的纯计算。
 *
 * user:“磁吸、对齐、间距调整”+
 * (拖动只计算偏移量；吸附比较元素左中右与上中下六条边到候选线的距离，
 *  超过阈值不吸。结果交给调用方做变换预览，松手才提交。)
 */

export interface OffsetBox {
  left: number
  top: number
  width: number
  height: number
}

export interface Offset {
  x: number
  y: number
}

export interface SnapTargets {
  x: number[]
  y: number[]
}

export interface SnapOutcome extends Offset {
  guideX: number | null
  guideY: number | null
}

export const SNAP_THRESHOLD = 6
export const OFFSET_LIMIT = 4000

function clamp(value: number): number {
  return Math.max(-OFFSET_LIMIT, Math.min(OFFSET_LIMIT, value))
}

function nearest(edges: number[], targets: number[], threshold: number): { delta: number; target: number } | null {
  let best: { delta: number; target: number } | null = null
  for (const target of targets) {
    for (const edge of edges) {
      const delta = target - edge
      if (Math.abs(delta) > threshold) continue
      if (!best || Math.abs(delta) < Math.abs(best.delta)) best = { delta, target }
    }
  }
  return best
}

/** 在给定偏移上做吸附，返回修正后的偏移与需要画出的参考线位置。 */
export function snapOffset(
  box: OffsetBox,
  offset: Offset,
  targets: SnapTargets,
  threshold = SNAP_THRESHOLD,
): SnapOutcome {
  const left = box.left + offset.x
  const centerX = left + box.width / 2
  const right = left + box.width
  const top = box.top + offset.y
  const centerY = top + box.height / 2
  const bottom = top + box.height

  const xSnap = nearest([left, centerX, right], targets.x, threshold)
  const ySnap = nearest([top, centerY, bottom], targets.y, threshold)

  return {
    x: clamp(offset.x + (xSnap?.delta ?? 0)),
    y: clamp(offset.y + (ySnap?.delta ?? 0)),
    guideX: xSnap ? xSnap.target : null,
    guideY: ySnap ? ySnap.target : null,
  }
}
