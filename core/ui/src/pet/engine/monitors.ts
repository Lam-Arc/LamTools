/**
 * 多显示器可视区域约束（纯函数）。
 *
 * user:“多显示器之间的非显示区域处理”+
 * (覆盖层是横跨虚拟桌面的一个矩形，但显示器并不一定拼成完整矩形。角色
 *  走到显示器之间的空隙时，要拉回最近的显示器可视范围，而不是停在看不见
 *  的桌面区域。)
 */
import type { Rect } from './math.ts'

export interface MonitorClampResult {
  x: number
  y: number
  changed: boolean
  clampedX: boolean
  clampedY: boolean
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), Math.max(min, max))
}

function contains(monitor: Rect, x: number, y: number): boolean {
  return x >= monitor.x
    && x <= monitor.x + monitor.width
    && y >= monitor.y
    && y <= monitor.y + monitor.height
}

/**
 * 把脚底中心点拉回最近的显示器。`bodyHeight` 用于保证角色身体不会伸出
 * 显示器上边缘（脚下是锚点，身体向上生长）。
 */
export function clampToMonitors(
  monitors: Rect[],
  x: number,
  y: number,
  bodyHeight: number,
): MonitorClampResult {
  const usable = monitors.filter(monitor => monitor.width > 0 && monitor.height > 0)
  if (usable.length === 0 || usable.some(monitor => contains(monitor, x, y))) {
    return { x, y, changed: false, clampedX: false, clampedY: false }
  }
  let best: MonitorClampResult | null = null
  let bestDistance = Number.POSITIVE_INFINITY
  for (const monitor of usable) {
    const minY = monitor.y + Math.min(Math.max(0, bodyHeight), monitor.height)
    const nextX = clamp(x, monitor.x, monitor.x + monitor.width)
    const nextY = clamp(y, minY, monitor.y + monitor.height)
    const distance = Math.hypot(nextX - x, nextY - y)
    if (distance < bestDistance) {
      bestDistance = distance
      best = {
        x: nextX,
        y: nextY,
        changed: true,
        clampedX: Math.abs(nextX - x) > 0.01,
        clampedY: Math.abs(nextY - y) > 0.01,
      }
    }
  }
  return best || { x, y, changed: false, clampedX: false, clampedY: false }
}
