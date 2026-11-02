/**
 * Ping 轮盘的纯逻辑：哪些项出现在哪一层、指针落在哪个扇区。
 *
 * 抽成纯函数是为了能单测：轮盘的分层与命中角度算错，用户会觉得"按了没反应"，
 * 而这种问题在真实桌面上很难复现。
 *
 * user:"ping 环跟桌宠应当是解耦的，它们是两个独立的功能，我只是在这一次设计方案中把它写在一起了"+
 * (本文件只依赖几何与配置类型，不依赖桌宠引擎（engine/*）与任何宠物实例，
 *  零宠物时轮盘分层与扇区命中照常工作。)
 */
import type { PingSectorConfig } from '../config.ts'

/** 主轮盘 = 没有 group 的启用项；子轮盘 = group 等于父项 subring 的启用项。 */
export function ringSectors(
  sectors: readonly PingSectorConfig[],
  parent: PingSectorConfig | null,
): PingSectorConfig[] {
  if (!parent) return sectors.filter(sector => sector.enabled && !sector.group)
  const group = parent.subring || parent.id
  return sectors.filter(sector => sector.enabled && sector.group === group)
}

/** 从圆心出发的向量落在第几个扇区；返回 -1 表示在中心死区或环外。 */
export function sectorIndexAt(
  dx: number,
  dy: number,
  count: number,
  radius: number,
  ringWidth: number,
  deadZoneRatio = 0.35,
): number {
  if (count <= 0) return -1
  const distance = Math.hypot(dx, dy)
  if (distance > radius + ringWidth * 2) return -1
  if (distance < radius * deadZoneRatio) return -1
  let angle = Math.atan2(dy, dx) + Math.PI / 2
  if (angle < 0) angle += Math.PI * 2
  const step = (Math.PI * 2) / count
  return Math.floor(angle / step) % count
}

/** 扇区数量多时给操作精度提示（不截断、不静默丢弃）。 */
export function ringCrowdingWarning(count: number): string | null {
  if (count <= 8) return null
  if (count <= 12) return `扇区有 ${count} 个，方向选择会比较细，建议调大环半径`
  return `扇区有 ${count} 个，已经很密；建议拆成子轮盘或调大环半径`
}
