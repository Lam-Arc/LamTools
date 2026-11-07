/**
 * 气泡二维布局：围绕桌宠找空闲矩形，而不是把气泡排成一列。
 *
 * user:“不要再把‘支持多个气泡’简单理解成 flex-direction: column”+
 * “多个气泡围绕桌宠在二维空间自然排布，互相避让”+
 * “尽可能不要遮住桌宠本体”“不允许气泡溢出当前显示器边界”+
 * “布局应稳定，避免桌宠轻微移动时全部气泡反复交换位置”+
 * (没有 DOM 依赖：真实宽高、桌宠矩形、其他桌宠矩形和上一帧位置都作为输入，
 *  输出每个气泡的左上角。候选位置打分 = 距离 + 碰撞面积 + 越界 + 稳定性。)
 */

export interface LayoutRect {
  x: number
  y: number
  width: number
  height: number
}

export interface BubbleLayoutItem {
  id: string
  width: number
  height: number
  /** 桌宠头顶中点的 CSS 坐标。 */
  anchorX: number
  anchorY: number
  /** 桌宠精灵框高度（CSS），用于生成下方候选位。 */
  petHeight: number
  /** 越大越先摆位（最新的请求优先拿到好位置）。 */
  priority: number
  /** 上一帧的位置：用于稳定性惩罚，避免轻微移动就换边。 */
  previous?: { left: number; top: number }
}

export interface BubbleLayoutOptions {
  viewport: { width: number; height: number }
  /** 其他宠物/窗口等不该被遮住的矩形（CSS 坐标）。 */
  obstacles?: LayoutRect[]
  /** 拖拽宠物时简化布局：减少候选、弱化稳定性，保持跟手。 */
  simplify?: boolean
  gap?: number
  padding?: number
}

export interface BubblePlacement {
  left: number
  top: number
  width: number
  height: number
}

interface Candidate {
  left: number
  top: number
  bias: number
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), Math.max(min, max))
}

function overlapArea(a: LayoutRect, b: LayoutRect): number {
  const width = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x)
  const height = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y)
  return width > 0 && height > 0 ? width * height : 0
}

function candidatesFor(item: BubbleLayoutItem, gap: number, simplify: boolean): Candidate[] {
  const { width: w, height: h, anchorX: ax, anchorY: ay, petHeight } = item
  const upper = ay - h - gap
  const left = ax - w - gap
  const right = ax + gap
  const midY = ay + petHeight * 0.32 - h / 2
  const lower = ay + petHeight * 0.75 - h * 0.35
  const below = ay + petHeight + gap
  // 偏好：左上、右上、左侧、右侧；下方与正上方是空间不足时的退路。
  const list: Candidate[] = [
    { left, top: upper, bias: 0 },
    { left: right, top: upper, bias: 1 },
    { left, top: midY, bias: 2 },
    { left: right, top: midY, bias: 3 },
    { left, top: lower, bias: 4 },
    { left: right, top: lower, bias: 5 },
    { left: ax - w / 2, top: upper, bias: 6 },
    { left: ax - w / 2, top: below, bias: 7 },
    { left, top: below, bias: 8 },
    { left: right, top: below, bias: 9 },
  ]
  if (simplify) {
    // 拖拽期间不做大范围换位：只保留四个贴身候选。
    return item.previous
      ? [{ left: item.previous.left, top: item.previous.top, bias: -20 }, ...list.slice(0, 4)]
      : list.slice(0, 4)
  }
  // 上一帧位置永远参与候选：桌宠轻微移动时优先保持原位。
  if (item.previous) {
    list.unshift({ left: item.previous.left, top: item.previous.top, bias: -20 })
  }
  // 多圈候选：手动展开很多条时，逐圈向外找空位，而不是全挤成一列。
  for (const ring of [1, 2, 3]) {
    for (const sx of [-1, 1]) {
      for (const sy of [-1, 0, 1]) {
        list.push({
          left: ax + sx * ring * (w + gap) - w / 2,
          top: ay + sy * ring * (h + gap) - h / 2,
          bias: 10 + ring * 3 + (sy + 1),
        })
      }
    }
  }
  return list
}

/**
 * 计算每个气泡的位置。返回值始终在可视区域内；宁可与其它气泡部分重叠，
 * 也不把气泡缩到不可阅读的尺寸。
 */
export function layoutBubbles(
  items: BubbleLayoutItem[],
  options: BubbleLayoutOptions,
): Map<string, BubblePlacement> {
  const gap = options.gap ?? 8
  const padding = options.padding ?? 8
  const viewportWidth = Math.max(1, options.viewport.width)
  const viewportHeight = Math.max(1, options.viewport.height)
  const obstacles = (options.obstacles || []).filter(rect => rect.width > 0 && rect.height > 0)
  /** 已摆位矩形（统一用 x/y，BubblePlacement 用的是 left/top）。 */
  const placed: LayoutRect[] = []
  const result = new Map<string, BubblePlacement>()
  const ordered = [...items].sort((a, b) => {
    if (b.priority !== a.priority) return b.priority - a.priority
    return a.id.localeCompare(b.id)
  })

  for (const item of ordered) {
    const width = Math.min(Math.max(40, item.width), Math.max(40, viewportWidth - padding * 2))
    const height = Math.min(Math.max(32, item.height), Math.max(32, viewportHeight - padding * 2))
    let best: { left: number; top: number; score: number; overlap: number; obstacleOverlap: number } | null = null
    const seen = new Set<string>()
    for (const candidate of candidatesFor(item, gap, Boolean(options.simplify))) {
      const left = clamp(candidate.left, padding, viewportWidth - width - padding)
      const top = clamp(candidate.top, padding, viewportHeight - height - padding)
      const key = `${Math.round(left)}:${Math.round(top)}`
      if (seen.has(key)) continue
      seen.add(key)
      const rect: LayoutRect = { x: left, y: top, width, height }
      let score = candidate.bias * 1.5
      let overlap = 0
      let obstacleOverlap = 0
      // 越界惩罚：夹取之前的原始位置已经出界，说明这个方向空间不足。
      const rawLeft = candidate.left
      const rawTop = candidate.top
      const overflowX = Math.max(0, padding - rawLeft) + Math.max(0, rawLeft + width - (viewportWidth - padding))
      const overflowY = Math.max(0, padding - rawTop) + Math.max(0, rawTop + height - (viewportHeight - padding))
      score += (overflowX + overflowY) * 8
      for (const other of placed) {
        const area = overlapArea(rect, other)
        overlap += area
        score += area * 0.9
      }
      for (const obstacle of obstacles) {
        const area = overlapArea(rect, obstacle)
        obstacleOverlap += area
        score += area * 1.4
      }
      // 离桌宠越近越优先（以气泡中心到锚点的距离计）。
      const centerX = left + width / 2
      const centerY = top + height / 2
      score += Math.hypot(centerX - item.anchorX, centerY - item.anchorY) * 0.08
      if (item.previous && !options.simplify) {
        const drift = Math.hypot(left - item.previous.left, top - item.previous.top)
        // 稳定性：轻微移动不换边；但新位置明显更空时仍然让位。
        score += Math.max(0, drift - 24) * 0.35
        if (drift <= 24) score -= 12
      }
      if (!best || score < best.score) best = { left, top, score, overlap, obstacleOverlap }
    }
    // 候选位置都被占用或压到桌宠时，用较粗的网格找第一个完全不和已展开气泡
    // 重叠的位置。这只在空间紧张时发生；宁可在屏幕上多找几圈，也不让卡片互相盖住。
    if (best && (best.overlap > 0 || best.obstacleOverlap > 0) && !options.simplify) {
      const step = 32
      let fallback: { left: number; top: number; score: number } | null = null
      for (let top = padding; top <= viewportHeight - height - padding; top += step) {
        for (let left = padding; left <= viewportWidth - width - padding; left += step) {
          const rect: LayoutRect = { x: left, y: top, width, height }
          if (placed.some(other => overlapArea(rect, other) > 0)) continue
          let score = Math.hypot(left + width / 2 - item.anchorX, top + height / 2 - item.anchorY) * 0.08
          for (const obstacle of obstacles) score += overlapArea(rect, obstacle) * 1.4
          if (!fallback || score < fallback.score) fallback = { left, top, score }
        }
      }
      if (fallback) best = { ...fallback, overlap: 0, obstacleOverlap: 0 }
    }
    const placement: BubblePlacement = best
      ? { left: Math.round(best.left), top: Math.round(best.top), width, height }
      : { left: padding, top: padding, width, height }
    result.set(item.id, placement)
    placed.push({ x: placement.left, y: placement.top, width, height })
  }
  return result
}
